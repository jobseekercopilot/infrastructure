from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.deployment.service_pilot import (
    EXPECTED_ENVIRONMENT,
    POLICY_PATH,
    ComposeBoundary,
    ContainerIdentity,
    DeploymentRecordStore,
    PilotError,
    ServicePilotOperator,
    load_policy,
    replacement_errors,
    validate_policy_against_catalog,
    validate_immutable_version,
)
from scripts.workspace.catalog import load_catalog


OLD_IMAGE = "sha256:" + "a" * 64
NEW_IMAGE = "sha256:" + "b" * 64
NEW_REFERENCE = "registry.example/jsc/reporting-gateway@" + NEW_IMAGE


def identity(
    service: str,
    image_id: str,
    *,
    container_id: str | None = None,
    health: str = "healthy",
    restart_count: int = 0,
    started_at: str = "2026-08-28T10:00:00Z",
) -> ContainerIdentity:
    return ContainerIdentity(
        service=service,
        container_id=container_id or f"container-{service}",
        image_id=image_id,
        image_reference=image_id,
        restart_count=restart_count,
        started_at=started_at,
        state="running",
        health=health,
    )


class FakeRuntimeBoundary:
    """Deterministic command boundary; no Docker process is started."""

    def __init__(self) -> None:
        self.current = {
            "reporting-gateway": identity("reporting-gateway", OLD_IMAGE),
            "reporting-service": identity(
                "reporting-service", "sha256:" + "c" * 64
            ),
            "job-seeker-copilot-client": identity(
                "job-seeker-copilot-client", "sha256:" + "d" * 64
            ),
        }
        self.resolved = {NEW_REFERENCE: NEW_IMAGE}
        self.health_by_version: dict[str, str] = {}
        self.smoke_fail_image_ids: set[str] = set()
        self.smoke_interrupt_image_ids: set[str] = set()
        self.restart_unaffected_on_versions: set[str] = set()
        self.replace_calls: list[tuple[str, str]] = []
        self.smoke_calls: list[str] = []
        self.verified = False

    def verify_non_production(self) -> None:
        self.verified = True

    def resolve_image(self, immutable_version: str) -> str:
        return self.resolved[immutable_version]

    def snapshot(self) -> dict[str, ContainerIdentity]:
        return dict(self.current)

    def replace(self, service, immutable_version: str) -> None:
        self.replace_calls.append((service.name, immutable_version))
        image_id = self.resolved.get(immutable_version, immutable_version)
        health = self.health_by_version.get(immutable_version, "healthy")
        self.current[service.name] = identity(
            service.name,
            image_id,
            container_id=f"replacement-{len(self.replace_calls)}",
            health=health,
        )
        if immutable_version in self.restart_unaffected_on_versions:
            prior = self.current["reporting-service"]
            self.current["reporting-service"] = identity(
                "reporting-service",
                prior.image_id,
                container_id="unexpected-unaffected-restart",
            )

    def smoke(self, service) -> None:
        self.smoke_calls.append(service.name)
        if self.current[service.name].image_id in self.smoke_interrupt_image_ids:
            raise KeyboardInterrupt()
        if self.current[service.name].image_id in self.smoke_fail_image_ids:
            raise PilotError("synthetic caller smoke failure")


class RecordingRunner:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []

    def run(self, command: list[str], *, env=None) -> str:
        self.calls.append((list(command), None if env is None else dict(env)))
        return self.outputs.pop(0) if self.outputs else ""


class ServiceDeploymentPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy()
        self.service = self.policy.services["reporting-gateway"]
        self.required = frozenset(
            {
                "reporting-gateway",
                "reporting-service",
                "job-seeker-copilot-client",
            }
        )

    def operator(
        self,
        boundary: FakeRuntimeBoundary,
        record_root: Path,
    ) -> ServicePilotOperator:
        return ServicePilotOperator(
            self.policy,
            boundary,
            self.required,
            record_store=DeploymentRecordStore(record_root),
            wait_attempts=1,
            sleeper=lambda _: self.fail("one-attempt tests must not sleep"),
            poll_seconds=0,
            now=lambda: datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            identifier=lambda: "deterministic",
        )

    def read_only_record(self, root: Path) -> tuple[Path, dict]:
        records = list(root.glob("*.json"))
        self.assertEqual(len(records), 1)
        return records[0], json.loads(records[0].read_text(encoding="utf-8"))

    def test_policy_is_fixture_only_and_initially_allowlists_one_service(self) -> None:
        self.assertEqual(self.policy.environment, EXPECTED_ENVIRONMENT)
        self.assertEqual(self.policy.profile, "full-fixture")
        self.assertEqual(set(self.policy.services), {"reporting-gateway"})
        self.assertEqual(self.service.smoke_caller, "job-seeker-copilot-client")

    def test_policy_rejects_a_production_profile(self) -> None:
        raw = json.loads(
            POLICY_PATH.read_text(encoding="utf-8")
        )
        raw["profile"] = "production"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(PilotError, "fixture-only"):
                load_policy(path)

    def test_policy_health_metadata_must_match_the_service_catalogue(self) -> None:
        catalog = load_catalog()
        profile = catalog.profile("full-fixture")
        required = validate_policy_against_catalog(
            self.policy, catalog, profile
        )
        self.assertIn("reporting-gateway", required)

        bad_service = replace(self.service, port=65535)
        bad_policy = replace(
            self.policy, services={"reporting-gateway": bad_service}
        )
        with self.assertRaisesRegex(PilotError, "differs from the catalogue"):
            validate_policy_against_catalog(bad_policy, catalog, profile)

    def test_immutable_version_accepts_ids_and_digest_references_only(self) -> None:
        self.assertEqual(validate_immutable_version(OLD_IMAGE), OLD_IMAGE)
        self.assertEqual(validate_immutable_version(NEW_REFERENCE), NEW_REFERENCE)
        for invalid in (
            "reporting-gateway:latest",
            "registry.example/reporting-gateway:1.2.3",
            "https://registry.example/image@" + NEW_IMAGE,
            "registry.example/IMAGE@" + NEW_IMAGE,
            "sha256:" + "A" * 64,
            "sha256:1234",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(PilotError):
                validate_immutable_version(invalid)

    def test_deploy_replaces_only_selected_service_and_records_evidence(self) -> None:
        boundary = FakeRuntimeBoundary()
        unaffected_before = {
            name: value
            for name, value in boundary.current.items()
            if name != "reporting-gateway"
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            path = self.operator(boundary, root).execute(
                "deploy-service", "reporting-gateway", NEW_REFERENCE
            )
            record_path, record = self.read_only_record(root)
            record_mode = record_path.stat().st_mode & 0o777

        self.assertEqual(path, record_path)
        self.assertTrue(boundary.verified)
        self.assertEqual(
            boundary.replace_calls, [("reporting-gateway", NEW_REFERENCE)]
        )
        self.assertEqual(boundary.smoke_calls, ["reporting-gateway"])
        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["unaffectedAssertion"], "PASSED")
        self.assertEqual(
            record["before"]["reporting-gateway"]["image_id"], OLD_IMAGE
        )
        self.assertEqual(
            record["after"]["reporting-gateway"]["image_id"], NEW_IMAGE
        )
        self.assertEqual(
            {
                name: boundary.current[name]
                for name in unaffected_before
            },
            unaffected_before,
        )
        self.assertEqual(record_mode, 0o600)

    def test_unhealthy_replacement_automatically_restores_prior_image(self) -> None:
        boundary = FakeRuntimeBoundary()
        boundary.health_by_version[NEW_REFERENCE] = "unhealthy"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            with self.assertRaisesRegex(PilotError, "FAILED_ROLLED_BACK"):
                self.operator(boundary, root).execute(
                    "deploy-service", "reporting-gateway", NEW_REFERENCE
                )
            _, record = self.read_only_record(root)

        self.assertEqual(
            boundary.replace_calls,
            [
                ("reporting-gateway", NEW_REFERENCE),
                ("reporting-gateway", OLD_IMAGE),
            ],
        )
        self.assertEqual(boundary.current["reporting-gateway"].image_id, OLD_IMAGE)
        self.assertEqual(record["status"], "FAILED_ROLLED_BACK")
        self.assertEqual(
            record["failedAfter"]["reporting-gateway"]["image_id"], NEW_IMAGE
        )
        self.assertEqual(record["rollback"]["status"], "SUCCEEDED")
        self.assertEqual(record["unaffectedAssertion"], "PASSED")

    def test_caller_smoke_failure_automatically_restores_prior_image(self) -> None:
        boundary = FakeRuntimeBoundary()
        boundary.smoke_fail_image_ids.add(NEW_IMAGE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            with self.assertRaisesRegex(PilotError, "FAILED_ROLLED_BACK"):
                self.operator(boundary, root).execute(
                    "deploy-service", "reporting-gateway", NEW_REFERENCE
                )
            _, record = self.read_only_record(root)

        self.assertEqual(boundary.current["reporting-gateway"].image_id, OLD_IMAGE)
        self.assertEqual(boundary.smoke_calls, ["reporting-gateway"] * 2)
        self.assertEqual(record["rollback"]["status"], "SUCCEEDED")

    def test_operator_interrupt_after_replacement_also_restores_prior_image(self) -> None:
        boundary = FakeRuntimeBoundary()
        boundary.smoke_interrupt_image_ids.add(NEW_IMAGE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            with self.assertRaisesRegex(PilotError, "FAILED_ROLLED_BACK"):
                self.operator(boundary, root).execute(
                    "deploy-service", "reporting-gateway", NEW_REFERENCE
                )
            _, record = self.read_only_record(root)

        self.assertEqual(boundary.current["reporting-gateway"].image_id, OLD_IMAGE)
        self.assertEqual(record["status"], "FAILED_ROLLED_BACK")
        self.assertIn("KeyboardInterrupt", record["failure"])

    def test_unaffected_restart_fails_closed_even_after_selected_image_restores(self) -> None:
        boundary = FakeRuntimeBoundary()
        boundary.restart_unaffected_on_versions.add(NEW_REFERENCE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            with self.assertRaisesRegex(PilotError, "FAILED_ROLLBACK_FAILED"):
                self.operator(boundary, root).execute(
                    "deploy-service", "reporting-gateway", NEW_REFERENCE
                )
            _, record = self.read_only_record(root)

        self.assertEqual(boundary.current["reporting-gateway"].image_id, OLD_IMAGE)
        self.assertEqual(record["status"], "FAILED_ROLLBACK_FAILED")
        self.assertEqual(record["unaffectedAssertion"], "FAILED_OR_UNPROVEN")
        self.assertEqual(record["rollback"]["status"], "FAILED")

    def test_rollback_service_uses_the_same_guarded_one_service_path(self) -> None:
        boundary = FakeRuntimeBoundary()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "records"
            self.operator(boundary, root).execute(
                "rollback-service", "reporting-gateway", NEW_REFERENCE
            )
            _, record = self.read_only_record(root)

        self.assertEqual(record["operation"], "rollback-service")
        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(
            boundary.replace_calls, [("reporting-gateway", NEW_REFERENCE)]
        )

    def test_non_allowlisted_service_is_rejected_before_runtime_commands(self) -> None:
        boundary = FakeRuntimeBoundary()
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PilotError, "not allowlisted"
        ):
            self.operator(boundary, Path(directory)).execute(
                "deploy-service", "payment-service", NEW_REFERENCE
            )
        self.assertFalse(boundary.verified)
        self.assertEqual(boundary.replace_calls, [])

    def test_no_op_target_is_rejected_without_replacement(self) -> None:
        boundary = FakeRuntimeBoundary()
        boundary.resolved[NEW_REFERENCE] = OLD_IMAGE
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PilotError, "already running"
        ):
            self.operator(boundary, Path(directory)).execute(
                "deploy-service", "reporting-gateway", NEW_REFERENCE
            )
        self.assertEqual(boundary.replace_calls, [])

    def test_unaffected_identity_change_is_a_failed_replacement(self) -> None:
        before = {
            "reporting-service": identity("reporting-service", OLD_IMAGE),
        }
        after = {
            "reporting-gateway": identity("reporting-gateway", NEW_IMAGE),
            "reporting-service": identity(
                "reporting-service", OLD_IMAGE, container_id="unexpected-restart"
            ),
        }
        errors = replacement_errors(
            after,
            "reporting-gateway",
            NEW_IMAGE,
            before,
            frozenset(after),
        )
        self.assertIn(
            "reporting-service: unaffected container identity changed", errors
        )

    def test_in_place_unaffected_restart_is_a_failed_replacement(self) -> None:
        before = {
            "reporting-service": identity(
                "reporting-service", OLD_IMAGE, container_id="same-container"
            ),
        }
        after = {
            "reporting-gateway": identity("reporting-gateway", NEW_IMAGE),
            "reporting-service": identity(
                "reporting-service",
                OLD_IMAGE,
                container_id="same-container",
                restart_count=1,
                started_at="2026-08-28T10:05:00Z",
            ),
        }
        errors = replacement_errors(
            after,
            "reporting-gateway",
            NEW_IMAGE,
            before,
            frozenset(after),
        )
        self.assertIn(
            "reporting-service: unaffected container identity changed", errors
        )

    def test_compose_replace_command_has_no_dependencies_build_or_pull(self) -> None:
        runner = RecordingRunner()
        profile = load_catalog().profile("full-fixture")
        boundary = ComposeBoundary(
            self.policy, profile, Path("/tmp/non-production-fixture.env"), runner
        )
        boundary.replace(self.service, NEW_REFERENCE)

        command, environment = runner.calls[0]
        self.assertEqual(command[-1], "reporting-gateway")
        self.assertIn("--no-deps", command)
        self.assertIn("--no-build", command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertIn("--force-recreate", command)
        self.assertEqual(
            environment["JSC_PILOT_REPORTING_GATEWAY_IMAGE"], NEW_REFERENCE
        )
        self.assertNotIn("payment-service", command)

    def test_compose_boundary_rejects_remote_docker_selectors(self) -> None:
        runner = RecordingRunner()
        boundary = ComposeBoundary(
            self.policy,
            load_catalog().profile("full-fixture"),
            Path("/tmp/non-production-fixture.env"),
            runner,
        )
        with patch.dict(os.environ, {"DOCKER_HOST": "ssh://production"}), self.assertRaisesRegex(
            PilotError, "remote-Docker"
        ):
            boundary.verify_non_production()
        self.assertEqual(runner.calls, [])

    def test_compose_boundary_accepts_only_a_local_engine_endpoint(self) -> None:
        runner = RecordingRunner(
            ["default\n", '"unix:///var/run/docker.sock"\n']
        )
        boundary = ComposeBoundary(
            self.policy,
            load_catalog().profile("full-fixture"),
            Path("/tmp/non-production-fixture.env"),
            runner,
        )
        with patch.dict(os.environ, {}, clear=True):
            boundary.verify_non_production()
        self.assertEqual(len(runner.calls), 2)

        remote_runner = RecordingRunner(["remote\n", '"ssh://production"\n'])
        remote = ComposeBoundary(
            self.policy,
            load_catalog().profile("full-fixture"),
            Path("/tmp/non-production-fixture.env"),
            remote_runner,
        )
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            PilotError, "non-local"
        ):
            remote.verify_non_production()

    def test_snapshot_records_only_safe_container_identity_fields(self) -> None:
        status = json.dumps(
            [
                {
                    "ID": "short-one",
                    "Image": "reporting:old",
                    "Service": "reporting-gateway",
                    "State": "running",
                    "Health": "healthy",
                },
                {
                    "ID": "short-two",
                    "Image": "client:old",
                    "Service": "job-seeker-copilot-client",
                    "State": "running",
                    "Health": "healthy",
                },
            ]
        )
        inspected = "\n".join(
            (
                f"full-one|{OLD_IMAGE}|0|2026-08-28T10:00:00Z|reporting-gateway",
                f"full-two|{'sha256:' + 'd' * 64}|0|2026-08-28T10:00:00Z|job-seeker-copilot-client",
            )
        )
        runner = RecordingRunner([status, inspected])
        boundary = ComposeBoundary(
            self.policy,
            load_catalog().profile("full-fixture"),
            Path("/tmp/non-production-fixture.env"),
            runner,
        )

        snapshot = boundary.snapshot()

        self.assertEqual(snapshot["reporting-gateway"].container_id, "full-one")
        self.assertEqual(snapshot["reporting-gateway"].image_id, OLD_IMAGE)
        self.assertEqual(snapshot["reporting-gateway"].restart_count, 0)
        self.assertEqual(
            snapshot["reporting-gateway"].started_at,
            "2026-08-28T10:00:00Z",
        )
        self.assertNotIn("Env", json.dumps({k: v.__dict__ for k, v in snapshot.items()}))


if __name__ == "__main__":
    unittest.main()
