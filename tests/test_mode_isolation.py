from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.data.acquisition_policy import (
    CONFIRMATION,
    authorize,
    create_audit_manifest,
)
from scripts.data.capture_llm_fixtures import BACKLOG_URL, main as capture_llm
from scripts.data.purge_acquisition import main as purge_acquisition
from scripts.data.run_acquisition import main as run_acquisition
from scripts.docker.stack_config import stack_for
from scripts.docker.start_stack import main as start_stack
from scripts.docker.stop_stack import main as stop_stack
from scripts.security.generate_profile_env import PROFILE_TEMPLATES, render
from scripts.security.validate_compose_runtime import compose_model, validate_model


class RenderedModeIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary_directory.name)
        cls.models: dict[str, dict] = {}
        for profile, overlays in (
            ("local", []),
            ("e2e", [Path("docker-compose.e2e.yml")]),
        ):
            env_file = directory / f"{profile}.env"
            render(profile, PROFILE_TEMPLATES[profile], env_file)
            cls.models[profile] = compose_model(env_file, overlays, profile)

        live_env = directory / "live.env"
        render("live-provider", PROFILE_TEMPLATES["live-provider"], live_env)
        with patch.dict(
            os.environ,
            {
                "REED_API_KEY": "test-reed-key",
                "ADZUNA_APP_ID": "test-adzuna-id",
                "ADZUNA_APP_KEY": "test-adzuna-key",
                "JSEARCH_API_KEY": "test-jsearch-key",
            },
        ):
            cls.models["live-provider"] = compose_model(
                live_env,
                [Path("docker-compose.live.yml")],
                "live-provider",
            )

        acquisition_env = directory / "acquisition.env"
        render(
            "data-acquisition",
            PROFILE_TEMPLATES["data-acquisition"],
            acquisition_env,
        )
        with patch.dict(
            os.environ,
            {
                "DATA_ACQUISITION_RUN_ID": "audit-20260726-001",
                "DATA_ACQUISITION_CONFIRMATION": CONFIRMATION,
                "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE": "INFRA-11-review",
                "DATA_ACQUISITION_PROVENANCE_REVIEWER": "local-reviewer",
                "DATA_ACQUISITION_APPROVED_PROVIDERS": "ADZUNA",
                "DATA_ACQUISITION_DATASET_VERSION": "2.0.0",
                "DATA_ACQUISITION_ADZUNA_ENABLED": "true",
                "ADZUNA_APP_ID": "test-adzuna-id",
                "ADZUNA_APP_KEY": "test-adzuna-key",
            },
        ):
            cls.models["data-acquisition"] = compose_model(
                acquisition_env,
                [Path("docker-compose.data-acquisition.yml")],
                "data-acquisition",
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def model(self, profile: str) -> dict:
        return copy.deepcopy(self.models[profile])

    def test_all_four_rendered_modes_pass_the_policy(self) -> None:
        for profile, model in self.models.items():
            validate_model(model, profile)

    def test_e2e_rejects_live_mode_before_startup(self) -> None:
        model = self.model("e2e")
        model["services"]["reed-gateway"]["environment"][
            "EXTERNAL_PROVIDER_MODE"
        ] = "LIVE"
        with self.assertRaisesRegex(ValueError, "must be FIXTURE"):
            validate_model(model, "e2e")

    def test_fixture_network_cannot_gain_external_egress(self) -> None:
        for profile in ("local", "e2e"):
            model = self.model(profile)
            model["networks"]["job-seeker-network"]["internal"] = False
            with self.assertRaisesRegex(ValueError, "no external egress"):
                validate_model(model, profile)

    def test_e2e_rejects_live_credentials_and_obsolete_mock_switch(self) -> None:
        for service, variable, value in (
            ("reed-gateway", "REED_API_KEY", "credential"),
            ("llm-gateway", "OPENAI_API_KEY", "credential"),
            ("stripe-gateway", "STRIPE_SECRET_KEY", "credential"),
            ("llm-gateway", "LLM_MOCK_MODE", "false"),
        ):
            with self.subTest(service=service, variable=variable):
                model = self.model("e2e")
                model["services"][service]["environment"][variable] = value
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_e2e_requires_exact_seed_profile_and_allowlist(self) -> None:
        for service, variable in (
            ("application-tracker-service", "ENVIRONMENT_DATA_ENABLED"),
            (
                "application-tracker-service",
                "ENVIRONMENT_DATA_ALLOWED_ENVIRONMENTS",
            ),
            (
                "system-data-service",
                "SYSTEM_DATA_ENVIRONMENT_ALLOWED_PROFILES",
            ),
        ):
            with self.subTest(service=service, variable=variable):
                model = self.model("e2e")
                model["services"][service]["environment"][variable] = "local"
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_app11_producer_consumer_pair_uses_the_internal_target_and_shared_identity(
        self,
    ) -> None:
        model = self.model("e2e")
        model["services"]["system-data-service"]["environment"][
            "APPLICATION_TRACKER_SERVICE_URL"
        ] = "https://application-tracker.example"
        with self.assertRaisesRegex(
            ValueError,
            "APPLICATION_TRACKER_SERVICE_URL must be "
            "http://application-tracker-service:8088",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["system-data-service"]["environment"][
            "SYSTEM_DATA_DOWNSTREAM_ENVIRONMENT_DATA_TOKEN"
        ] = "different-environment-data-identity-value"
        with self.assertRaisesRegex(
            ValueError,
            "ENVIRONMENT_DATA_TOKEN does not match",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["application-tracker-service"]["environment"][
            "SPRING_PROFILES_ACTIVE"
        ] = "local"
        with self.assertRaisesRegex(
            ValueError,
            "application-tracker-service:SPRING_PROFILES_ACTIVE must be e2e",
        ):
            validate_model(model, "e2e")

    def test_application_tracker_uses_isolated_postgres_in_runtime_profiles(
        self,
    ) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                tracker = model["services"]["application-tracker-service"]
                database = model["services"]["application-tracker-postgres"]
                self.assertIn(
                    "application-tracker-postgres:5432",
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_URL"],
                )
                self.assertEqual(
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_PASSWORD"],
                    database["environment"]["POSTGRES_PASSWORD"],
                )
                self.assertEqual(
                    tracker["environment"][
                        "APPLICATION_TRACKER_DATABASE_PRODUCTION_SAFETY_CHECK"
                    ],
                    "false",
                )
                self.assertEqual(
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_SSL_MODE"],
                    "disable",
                )
                self.assertIn(
                    "application-tracker-postgres-data",
                    self.models[profile]["volumes"],
                )

    def test_application_tracker_database_binding_fails_closed(self) -> None:
        mutations = (
            ("APPLICATION_TRACKER_DATABASE_PASSWORD", "different-database-secret"),
            ("APPLICATION_TRACKER_DATABASE_PRODUCTION_SAFETY_CHECK", "true"),
            ("APPLICATION_TRACKER_DATABASE_SSL_MODE", "verify-full"),
            (
                "APPLICATION_TRACKER_DATABASE_URL",
                "jdbc:postgresql://shared-postgres:5432/application_tracker",
            ),
        )
        for variable, value in mutations:
            with self.subTest(variable=variable):
                model = self.model("e2e")
                model["services"]["application-tracker-service"]["environment"][
                    variable
                ] = value
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_local_and_live_profiles_keep_destructive_endpoints_disabled(self) -> None:
        for profile in ("local", "live-provider"):
            model = self.model(profile)
            model["services"]["system-data-service"]["environment"][
                "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED"
            ] = "true"
            with self.assertRaisesRegex(ValueError, "must be false"):
                validate_model(model, profile)

    def test_live_job_provider_profile_cannot_enable_llm_or_stripe(self) -> None:
        for service in ("llm-gateway", "stripe-gateway"):
            model = self.model("live-provider")
            model["services"][service]["environment"][
                "EXTERNAL_PROVIDER_MODE"
            ] = "LIVE"
            with self.assertRaises(ValueError):
                validate_model(model, "live-provider")

    def test_acquisition_contains_no_payment_llm_browser_or_host_port(self) -> None:
        model = self.model("data-acquisition")
        model["services"]["payment-service"] = {"environment": {}}
        with self.assertRaisesRegex(ValueError, "only approved"):
            validate_model(model, "data-acquisition")

        model = self.model("data-acquisition")
        model["services"]["adzuna-gateway"]["ports"] = [{"published": "8101"}]
        with self.assertRaisesRegex(ValueError, "must not publish"):
            validate_model(model, "data-acquisition")

    def test_acquisition_rejects_unapproved_credentials_and_mutable_source(self) -> None:
        model = self.model("data-acquisition")
        model["services"]["reed-gateway"]["environment"][
            "REED_API_KEY"
        ] = "unexpected"
        with self.assertRaisesRegex(ValueError, "must be absent"):
            validate_model(model, "data-acquisition")

        model = self.model("data-acquisition")
        mounts = model["services"]["system-data-service"]["volumes"]
        source_mount = next(
            mount
            for mount in mounts
            if mount["target"] == "/app/dataset-repository"
        )
        source_mount["read_only"] = False
        with self.assertRaisesRegex(ValueError, "read-only"):
            validate_model(model, "data-acquisition")

    def test_acquisition_project_is_separate_and_not_generically_startable(self) -> None:
        local = stack_for("local")
        live = stack_for("live")
        e2e = stack_for("e2e")
        acquisition = stack_for("data-acquisition")
        self.assertEqual(
            len({local.project, live.project, e2e.project, acquisition.project}),
            4,
        )
        self.assertNotEqual(acquisition.project, e2e.project)
        self.assertEqual(
            acquisition.files, ("docker-compose.data-acquisition.yml",)
        )
        self.assertFalse(acquisition.startable)
        self.assertIsNone(acquisition.frontend_url)

    def test_runtime_start_stops_before_compose_up_when_preflight_fails(self) -> None:
        with patch("sys.argv", ["start_stack", "e2e"]), patch(
            "scripts.docker.start_stack.subprocess.run"
        ) as run, redirect_stdout(StringIO()):
            run.return_value.returncode = 1
            self.assertEqual(start_stack(), 1)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertTrue(
            any(value.endswith("validate_compose_runtime.py") for value in command)
        )

    def test_volume_reset_requires_explicit_destructive_confirmation(self) -> None:
        error = StringIO()
        with patch(
            "sys.argv", ["stop_stack", "e2e", "--delete-volumes"]
        ), patch(
            "scripts.docker.stop_stack.subprocess.run"
        ) as run, redirect_stderr(error):
            with self.assertRaises(SystemExit):
                stop_stack()
        run.assert_not_called()
        self.assertIn("without --yes", error.getvalue())


class AcquisitionAuthorizationTests(unittest.TestCase):
    def values(self) -> dict[str, str]:
        return {
            "DATA_ACQUISITION_RUN_ID": "audit-20260726-001",
            "DATA_ACQUISITION_CONFIRMATION": CONFIRMATION,
            "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE": "INFRA-11-review",
            "DATA_ACQUISITION_PROVENANCE_REVIEWER": "local-reviewer",
            "DATA_ACQUISITION_APPROVED_PROVIDERS": "ADZUNA",
            "DATA_ACQUISITION_RETENTION_DAYS": "14",
            "DATA_ACQUISITION_DATASET_ID": "live-provider-acquisition",
            "DATA_ACQUISITION_DATASET_VERSION": "2.0.0",
            "DATA_ACQUISITION_ADZUNA_ENABLED": "true",
            "DATA_ACQUISITION_JSEARCH_ENABLED": "false",
            "DATA_ACQUISITION_REED_ENABLED": "false",
            "DATA_ACQUISITION_POSTCODE_ENABLED": "false",
            "ADZUNA_APP_ID": "test-adzuna-id",
            "ADZUNA_APP_KEY": "test-adzuna-key",
        }

    def test_authorization_creates_redacted_bounded_retention_record(self) -> None:
        authorization = authorize(self.values())
        with tempfile.TemporaryDirectory() as directory:
            path = create_audit_manifest(
                Path(directory),
                authorization,
                now=datetime(2026, 7, 26, tzinfo=UTC),
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "AUTHORIZED")
        self.assertEqual(manifest["approvedProviders"], ["ADZUNA"])
        self.assertEqual(manifest["retainUntil"], "2026-08-09T00:00:00+00:00")
        self.assertNotIn("credential", json.dumps(manifest).lower())
        self.assertFalse(manifest["runtimeEligible"])

    def test_confirmation_flags_credentials_and_retention_fail_closed(self) -> None:
        mutations = (
            ("DATA_ACQUISITION_CONFIRMATION", "yes"),
            ("DATA_ACQUISITION_ADZUNA_ENABLED", "false"),
            ("ADZUNA_APP_KEY", ""),
            ("REED_API_KEY", "unapproved-credential"),
            ("DATA_ACQUISITION_RETENTION_DAYS", "31"),
            ("DATA_ACQUISITION_DATASET_ID", "../escape"),
            ("DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE", "reference with spaces"),
        )
        for variable, value in mutations:
            with self.subTest(variable=variable):
                values = self.values()
                values[variable] = value
                with self.assertRaises(ValueError):
                    authorize(values)

    def test_legacy_live_llm_capture_is_fail_closed_without_network_activity(
        self,
    ) -> None:
        error = StringIO()
        with patch(
            "sys.argv",
            [
                "capture_llm_fixtures",
                "--dataset-path",
                "fixture",
                "--job-id",
                "job",
                "--yes",
            ],
        ), redirect_stderr(error):
            self.assertEqual(capture_llm(), 2)
        self.assertIn("No provider call was made", error.getvalue())
        self.assertIn(BACKLOG_URL, error.getvalue())

    def test_invalid_acquisition_never_reaches_compose(self) -> None:
        values = self.values()
        values["DATA_ACQUISITION_CONFIRMATION"] = "yes"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.data-acquisition"
            env_file.write_text(
                "\n".join(f"{name}={value}" for name, value in values.items())
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "sys.argv",
                [
                    "run_acquisition",
                    "--env-file",
                    str(env_file),
                    "--authorize-live-provider-costs",
                ],
            ), patch("scripts.data.run_acquisition.run") as run, redirect_stderr(
                StringIO()
            ):
                self.assertEqual(run_acquisition(), 2)
        run.assert_not_called()

    def test_rejected_quarantine_is_exactly_deleted_and_audited(self) -> None:
        authorization = authorize(self.values())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "quarantine"
            audit_path = create_audit_manifest(root, authorization)
            run_directory = audit_path.parent
            with patch(
                "scripts.data.purge_acquisition.QUARANTINE_ROOT", root
            ), patch(
                "sys.argv",
                [
                    "purge_acquisition",
                    "--run-id",
                    authorization.run_id,
                    "--reason",
                    "rejected",
                    "--reviewer",
                    "local-reviewer",
                    "--yes",
                ],
            ), redirect_stdout(StringIO()):
                self.assertEqual(purge_acquisition(), 0)
            self.assertFalse(run_directory.exists())
            records = [
                json.loads(line)
                for line in (root / "deletion-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
        self.assertEqual(
            [record["status"] for record in records],
            ["DELETE_REQUESTED", "DELETED"],
        )


if __name__ == "__main__":
    unittest.main()
