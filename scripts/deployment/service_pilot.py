#!/usr/bin/env python3
"""Replace one allowlisted fixture service with an immutable local image.

This is deliberately a local Docker Compose proving tool. It has no AWS,
Terraform or production deployment path.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.workspace.catalog import (  # noqa: E402
    INFRASTRUCTURE_ROOT,
    WORKSPACE_ROOT,
    Catalog,
    Profile,
    load_catalog,
)
from scripts.workspace.lifecycle import (  # noqa: E402
    ensure_environment,
    parse_compose_status,
    selected_repositories,
)
from scripts.workspace.runtime_env import controlled_environment  # noqa: E402


POLICY_PATH = INFRASTRUCTURE_ROOT / "config/non-production-service-pilot.json"
RECORD_ROOT = WORKSPACE_ROOT / ".cache/service-deployments"
EXPECTED_ENVIRONMENT = "NON_PRODUCTION_COMPOSE_PILOT"
EXPECTED_PROFILE = "full-fixture"
EXPECTED_PROJECT = "job-seeker-copilot-full"
EXPECTED_COMPOSE_FILES = ("docker-compose.yml",)
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_ENVIRONMENT_NAME = re.compile(r"^JSC_PILOT_[A-Z0-9_]+_IMAGE$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REFERENCE_PREFIX = re.compile(r"^[a-z0-9][a-z0-9._:/-]*$")


class PilotError(RuntimeError):
    """A fail-closed pilot validation or operation error."""


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Run one command and return stdout, or raise PilotError."""


class SubprocessCommandRunner:
    """The only subprocess boundary used by the production-disabled pilot."""

    def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> str:
        result = subprocess.run(
            command,
            cwd=INFRASTRUCTURE_ROOT,
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # Docker/Compose stderr can contain rendered runtime configuration.
            # Keep the retained deployment record free of that output.
            raise PilotError(
                f"command exited {result.returncode}: {shlex.join(command)}"
            )
        return result.stdout


@dataclass(frozen=True)
class ServicePolicy:
    name: str
    image_environment_variable: str
    port: int
    health_path: str
    smoke_caller: str

    @property
    def smoke_url(self) -> str:
        return f"http://{self.name}:{self.port}{self.health_path}"


@dataclass(frozen=True)
class PilotPolicy:
    environment: str
    profile: str
    compose_override: Path
    services: Mapping[str, ServicePolicy]


@dataclass(frozen=True)
class ContainerIdentity:
    service: str
    container_id: str
    image_id: str
    image_reference: str
    restart_count: int
    started_at: str
    state: str
    health: str

    @property
    def stable_identity(self) -> tuple[str, str, str, int, str]:
        return (
            self.container_id,
            self.image_id,
            self.image_reference,
            self.restart_count,
            self.started_at,
        )


class RuntimeBoundary(Protocol):
    def verify_non_production(self) -> None:
        """Prove that this boundary is a local, fixture-only runtime."""

    def resolve_image(self, immutable_version: str) -> str:
        """Resolve a locally present immutable reference to its image ID."""

    def snapshot(self) -> dict[str, ContainerIdentity]:
        """Return safe identities for every container in the Compose project."""

    def replace(self, service: ServicePolicy, immutable_version: str) -> None:
        """Replace only service, with dependencies explicitly disabled."""

    def smoke(self, service: ServicePolicy) -> None:
        """Probe the selected service from its reviewed caller container."""


def _required_string(raw: Mapping[str, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PilotError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def validate_immutable_version(value: str) -> str:
    """Accept only a local image ID or an OCI repository@sha256 digest."""
    if IMAGE_ID.fullmatch(value):
        return value
    if value.count("@sha256:") != 1:
        raise PilotError(
            "immutable version must be sha256:<64 lowercase hex> or "
            "repository@sha256:<64 lowercase hex>"
        )
    prefix, digest = value.rsplit("@", 1)
    if (
        "://" in prefix
        or not IMAGE_REFERENCE_PREFIX.fullmatch(prefix)
        or not IMAGE_ID.fullmatch(digest)
    ):
        raise PilotError("immutable image reference is not a safe OCI digest reference")
    return value


def load_policy(path: Path = POLICY_PATH) -> PilotPolicy:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotError(f"cannot load service-pilot policy: {error}") from error
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
        raise PilotError("service-pilot policy schemaVersion must be 1")

    environment = _required_string(raw, "environment", "policy")
    profile = _required_string(raw, "profile", "policy")
    if environment != EXPECTED_ENVIRONMENT or profile != EXPECTED_PROFILE:
        raise PilotError("service-pilot policy must remain fixture-only")

    override_value = _required_string(raw, "composeOverride", "policy")
    override = Path(override_value)
    if override.is_absolute() or ".." in override.parts:
        raise PilotError("policy.composeOverride must be repository-relative")
    override = INFRASTRUCTURE_ROOT / override
    if not override.is_file() or override.is_symlink():
        raise PilotError("policy.composeOverride must be a regular repository file")

    raw_services = raw.get("services")
    if not isinstance(raw_services, dict) or not raw_services:
        raise PilotError("policy.services must be a non-empty object")
    services: dict[str, ServicePolicy] = {}
    for name, item in raw_services.items():
        context = f"policy.services.{name}"
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            raise PilotError("policy contains an unsafe service name")
        if not isinstance(item, dict):
            raise PilotError(f"{context} must be an object")
        image_environment_variable = _required_string(
            item, "imageEnvironmentVariable", context
        )
        if not SAFE_ENVIRONMENT_NAME.fullmatch(image_environment_variable):
            raise PilotError(f"{context}.imageEnvironmentVariable is not pilot-scoped")
        port = item.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise PilotError(f"{context}.port must be a valid TCP port")
        health_path = _required_string(item, "healthPath", context)
        if not health_path.startswith("/") or "?" in health_path or "#" in health_path:
            raise PilotError(f"{context}.healthPath must be a simple absolute path")
        smoke_caller = _required_string(item, "smokeCaller", context)
        if not SAFE_NAME.fullmatch(smoke_caller):
            raise PilotError(f"{context}.smokeCaller is not a safe service name")
        services[name] = ServicePolicy(
            name=name,
            image_environment_variable=image_environment_variable,
            port=port,
            health_path=health_path,
            smoke_caller=smoke_caller,
        )

    return PilotPolicy(
        environment=environment,
        profile=profile,
        compose_override=override,
        services=services,
    )


class ComposeBoundary:
    """Local Compose implementation of the runtime command boundary."""

    _SMOKE_PROGRAM = """
const http = require('http');
const url = process.argv[1];
const request = http.get(url, (response) => {
  let body = '';
  response.setEncoding('utf8');
  response.on('data', (chunk) => { body += chunk; });
  response.on('end', () => {
    try {
      const payload = JSON.parse(body);
      process.exit(response.statusCode < 400 && payload.status === 'UP' ? 0 : 1);
    } catch (_) {
      process.exit(1);
    }
  });
});
request.setTimeout(5000, () => request.destroy(new Error('timeout')));
request.on('error', () => process.exit(1));
""".strip()

    def __init__(
        self,
        policy: PilotPolicy,
        profile: Profile,
        environment_file: Path,
        runner: CommandRunner | None = None,
    ) -> None:
        self.policy = policy
        self.profile = profile
        self.environment_file = environment_file
        self.runner = runner or SubprocessCommandRunner()
        self._validate_fixed_boundary()

    def _validate_fixed_boundary(self) -> None:
        if (
            self.profile.name != EXPECTED_PROFILE
            or self.profile.compose_project != EXPECTED_PROJECT
            or self.profile.compose_files != EXPECTED_COMPOSE_FILES
            or self.profile.environment_profile != "local"
            or self.profile.secret_environment_file is not None
            or self.profile.services != "all-runtime"
        ):
            raise PilotError(
                "service pilot is hard-guarded to the complete local fixture stack"
            )

    def _base_compose_command(self, *arguments: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "-p",
            EXPECTED_PROJECT,
            "--env-file",
            str(self.environment_file),
        ]
        for compose_file in self.profile.compose_files:
            command.extend(("-f", compose_file))
        command.extend(arguments)
        return command

    def _replacement_command(self, service: ServicePolicy) -> list[str]:
        return self._base_compose_command(
            "-f",
            str(self.policy.compose_override),
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            service.name,
        )

    def verify_non_production(self) -> None:
        forbidden = [
            name for name in ("DOCKER_HOST", "DOCKER_CONTEXT") if os.environ.get(name)
        ]
        if forbidden:
            raise PilotError(
                "service pilot refuses inherited remote-Docker selectors: "
                + ", ".join(forbidden)
            )
        context = self.runner.run(["docker", "context", "show"]).strip()
        if not context or any(character.isspace() for character in context):
            raise PilotError("Docker returned an unsafe context name")
        raw_endpoint = self.runner.run(
            [
                "docker",
                "context",
                "inspect",
                context,
                "--format",
                "{{json .Endpoints.docker.Host}}",
            ]
        ).strip()
        try:
            endpoint = json.loads(raw_endpoint)
        except json.JSONDecodeError as error:
            raise PilotError("Docker context endpoint was not valid JSON") from error
        if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
            raise PilotError("service pilot refuses a non-local Docker endpoint")

    def resolve_image(self, immutable_version: str) -> str:
        output = self.runner.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", immutable_version]
        ).strip()
        if not IMAGE_ID.fullmatch(output):
            raise PilotError("locally resolved target does not have an immutable image ID")
        return output

    def snapshot(self) -> dict[str, ContainerIdentity]:
        raw_status = self.runner.run(
            self._base_compose_command("ps", "--all", "--format", "json"),
            env=controlled_environment(),
        )
        rows = parse_compose_status(raw_status)
        if not rows:
            raise PilotError("fixture Compose project has no containers")

        ids: list[str] = []
        status_by_service: dict[str, dict] = {}
        for row in rows:
            service = row.get("Service")
            container_id = row.get("ID")
            if not isinstance(service, str) or not SAFE_NAME.fullmatch(service):
                raise PilotError("Compose status contains an unsafe service name")
            if service in status_by_service:
                raise PilotError(f"scaled Compose service is unsupported: {service}")
            if not isinstance(container_id, str) or not container_id:
                raise PilotError(f"Compose returned no container ID for {service}")
            ids.append(container_id)
            status_by_service[service] = row

        inspected = self.runner.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{.Id}}|{{.Image}}|{{.RestartCount}}|{{.State.StartedAt}}|'
                '{{index .Config.Labels "com.docker.compose.service"}}',
                *ids,
            ]
        )
        inspect_by_service: dict[str, tuple[str, str, int, str]] = {}
        for line in inspected.splitlines():
            parts = line.strip().split("|", 4)
            if len(parts) != 5:
                raise PilotError("Docker inspect returned an unexpected identity record")
            container_id, image_id, restart_count_raw, started_at, service = parts
            if service in inspect_by_service or service not in status_by_service:
                raise PilotError("Docker inspect identities do not match the Compose project")
            if not container_id or not IMAGE_ID.fullmatch(image_id):
                raise PilotError("Docker inspect returned an invalid immutable identity")
            try:
                restart_count = int(restart_count_raw)
            except ValueError as exc:
                raise PilotError("Docker inspect returned an invalid restart count") from exc
            if restart_count < 0 or not started_at:
                raise PilotError("Docker inspect returned invalid continuity metadata")
            inspect_by_service[service] = (
                container_id,
                image_id,
                restart_count,
                started_at,
            )
        if inspect_by_service.keys() != status_by_service.keys():
            raise PilotError("Docker inspect omitted a Compose container identity")

        return {
            service: ContainerIdentity(
                service=service,
                container_id=inspect_by_service[service][0],
                image_id=inspect_by_service[service][1],
                image_reference=str(row.get("Image") or ""),
                restart_count=inspect_by_service[service][2],
                started_at=inspect_by_service[service][3],
                state=str(row.get("State") or "").lower(),
                health=str(row.get("Health") or "").lower(),
            )
            for service, row in status_by_service.items()
        }

    def replace(self, service: ServicePolicy, immutable_version: str) -> None:
        environment = controlled_environment()
        environment[service.image_environment_variable] = immutable_version
        self.runner.run(self._replacement_command(service), env=environment)

    def smoke(self, service: ServicePolicy) -> None:
        self.runner.run(
            self._base_compose_command(
                "exec",
                "-T",
                service.smoke_caller,
                "node",
                "-e",
                self._SMOKE_PROGRAM,
                service.smoke_url,
            ),
            env=controlled_environment(),
        )


def _snapshot_json(snapshot: Mapping[str, ContainerIdentity]) -> dict[str, dict]:
    return {name: asdict(snapshot[name]) for name in sorted(snapshot)}


def _healthy(identity: ContainerIdentity, *, require_healthcheck: bool) -> bool:
    if identity.state != "running":
        return False
    if require_healthcheck:
        return identity.health == "healthy"
    return not identity.health or identity.health == "healthy"


def validate_preflight(
    snapshot: Mapping[str, ContainerIdentity],
    selected_service: str,
    required_services: frozenset[str],
) -> None:
    missing = sorted(required_services.difference(snapshot))
    if missing:
        raise PilotError("fixture stack is incomplete: " + ", ".join(missing))
    if selected_service not in snapshot:
        raise PilotError(f"selected service is not running: {selected_service}")
    failures = [
        name
        for name, identity in snapshot.items()
        if not _healthy(identity, require_healthcheck=name == selected_service)
    ]
    if failures:
        raise PilotError("fixture stack is not healthy: " + ", ".join(sorted(failures)))


def replacement_errors(
    snapshot: Mapping[str, ContainerIdentity],
    selected_service: str,
    expected_image_id: str,
    unaffected_before: Mapping[str, ContainerIdentity],
    required_services: frozenset[str],
) -> list[str]:
    errors: list[str] = []
    missing = sorted(required_services.difference(snapshot))
    if missing:
        errors.append("required services missing: " + ", ".join(missing))
    selected = snapshot.get(selected_service)
    if selected is None:
        errors.append(f"{selected_service}: container missing")
    else:
        if selected.image_id != expected_image_id:
            errors.append(f"{selected_service}: target image is not running")
        if not _healthy(selected, require_healthcheck=True):
            errors.append(
                f"{selected_service}: state={selected.state} health={selected.health or 'none'}"
            )

    if set(snapshot).difference({selected_service}) != set(unaffected_before):
        errors.append("unaffected service set changed")
    for name, before in unaffected_before.items():
        after = snapshot.get(name)
        if after is None:
            errors.append(f"{name}: unaffected container missing")
            continue
        if after.stable_identity != before.stable_identity:
            errors.append(f"{name}: unaffected container identity changed")
        if not _healthy(after, require_healthcheck=False):
            errors.append(f"{name}: unaffected container is not healthy")
    return errors


class DeploymentRecordStore:
    def __init__(self, root: Path = RECORD_ROOT) -> None:
        self.root = root

    def path(self, deployment_id: str, operation: str, service: str) -> Path:
        return self.root / f"{deployment_id}-{operation}-{service}.json"

    def write(self, path: Path, record: Mapping[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise PilotError("deployment-record directory must not be a symlink")
        self.root.chmod(0o700)
        temporary = path.with_suffix(path.suffix + ".tmp")
        open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        open_flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            temporary,
            open_flags,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(record, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


class ServicePilotOperator:
    def __init__(
        self,
        policy: PilotPolicy,
        boundary: RuntimeBoundary,
        required_services: frozenset[str],
        *,
        record_store: DeploymentRecordStore | None = None,
        wait_attempts: int = 90,
        sleeper: Callable[[float], None] = time.sleep,
        poll_seconds: float = 2.0,
        now: Callable[[], datetime] | None = None,
        identifier: Callable[[], str] | None = None,
    ) -> None:
        if wait_attempts < 1 or poll_seconds < 0:
            raise PilotError("wait policy must contain at least one non-negative attempt")
        self.policy = policy
        self.boundary = boundary
        self.required_services = required_services
        self.record_store = record_store or DeploymentRecordStore()
        self.wait_attempts = wait_attempts
        self.sleeper = sleeper
        self.poll_seconds = poll_seconds
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.identifier = identifier or (lambda: uuid.uuid4().hex[:12])

    def _timestamp(self) -> str:
        return self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _wait_for_replacement(
        self,
        service: str,
        expected_image_id: str,
        unaffected_before: Mapping[str, ContainerIdentity],
    ) -> dict[str, ContainerIdentity]:
        last_errors: list[str] = []
        for attempt in range(self.wait_attempts):
            snapshot = self.boundary.snapshot()
            last_errors = replacement_errors(
                snapshot,
                service,
                expected_image_id,
                unaffected_before,
                self.required_services,
            )
            if not last_errors:
                return snapshot
            if attempt + 1 < self.wait_attempts:
                self.sleeper(self.poll_seconds)
        raise PilotError("replacement did not stabilise: " + "; ".join(last_errors))

    def execute(self, operation: str, service_name: str, immutable_version: str) -> Path:
        if operation not in {"deploy-service", "rollback-service"}:
            raise PilotError("unsupported service-pilot operation")
        service = self.policy.services.get(service_name)
        if service is None:
            raise PilotError(f"service is not allowlisted for the pilot: {service_name}")
        immutable_version = validate_immutable_version(immutable_version)

        self.boundary.verify_non_production()
        expected_image_id = self.boundary.resolve_image(immutable_version)
        before = self.boundary.snapshot()
        validate_preflight(before, service_name, self.required_services)
        before_selected = before[service_name]
        if before_selected.image_id == expected_image_id:
            raise PilotError("requested immutable version is already running")
        unaffected_before = {
            name: identity for name, identity in before.items() if name != service_name
        }

        deployment_id = (
            self.now().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + self.identifier()
        )
        path = self.record_store.path(deployment_id, operation, service_name)
        record: dict[str, object] = {
            "schemaVersion": 1,
            "deploymentId": deployment_id,
            "environment": EXPECTED_ENVIRONMENT,
            "operation": operation,
            "service": service_name,
            "requestedVersion": immutable_version,
            "resolvedTargetImageId": expected_image_id,
            "startedAt": self._timestamp(),
            "completedAt": None,
            "status": "PREPARED",
            "before": _snapshot_json(before),
            "after": None,
            "unaffectedAssertion": "PENDING",
            "smoke": {"caller": service.smoke_caller, "url": service.smoke_url, "status": "PENDING"},
            "rollback": {"attempted": False, "targetVersion": before_selected.image_id},
        }
        self.record_store.write(path, record)

        replacement_attempted = False
        deployment_error: BaseException | None = None
        try:
            replacement_attempted = True
            self.boundary.replace(service, immutable_version)
            after = self._wait_for_replacement(
                service_name, expected_image_id, unaffected_before
            )
            self.boundary.smoke(service)
            final_after = self._wait_for_replacement(
                service_name, expected_image_id, unaffected_before
            )
            record.update(
                {
                    "after": _snapshot_json(final_after),
                    "completedAt": self._timestamp(),
                    "status": "SUCCEEDED",
                    "unaffectedAssertion": "PASSED",
                    "smoke": {
                        "caller": service.smoke_caller,
                        "url": service.smoke_url,
                        "status": "PASSED",
                    },
                }
            )
            # Preserve the first stable snapshot as additional audit evidence if
            # it differs from the post-smoke observation.
            if after != final_after:
                record["firstStableAfter"] = _snapshot_json(after)
            self.record_store.write(path, record)
            return path
        except (Exception, KeyboardInterrupt) as error:
            # Ctrl-C after mutation is also a failed deployment: restore the
            # captured image before returning control to the operator.
            deployment_error = error

        record["failure"] = f"{type(deployment_error).__name__}: {deployment_error}"
        record["smoke"] = {
            "caller": service.smoke_caller,
            "url": service.smoke_url,
            "status": "FAILED_OR_NOT_REACHED",
        }
        if replacement_attempted:
            try:
                record["failedAfter"] = _snapshot_json(self.boundary.snapshot())
            except (Exception, KeyboardInterrupt) as snapshot_error:
                record["failedAfter"] = {
                    "status": "UNAVAILABLE",
                    "failure": f"{type(snapshot_error).__name__}: {snapshot_error}",
                }
            rollback_record: dict[str, object] = {
                "attempted": True,
                "targetVersion": before_selected.image_id,
                "status": "IN_PROGRESS",
            }
            record["rollback"] = rollback_record
            try:
                self.boundary.replace(service, before_selected.image_id)
                restored = self._wait_for_replacement(
                    service_name, before_selected.image_id, unaffected_before
                )
                self.boundary.smoke(service)
                restored = self._wait_for_replacement(
                    service_name, before_selected.image_id, unaffected_before
                )
                rollback_record.update(
                    {"status": "SUCCEEDED", "after": _snapshot_json(restored)}
                )
                record["status"] = "FAILED_ROLLED_BACK"
                record["unaffectedAssertion"] = "PASSED"
            except (Exception, KeyboardInterrupt) as rollback_error:
                # Retain both failure causes even if restoration was interrupted.
                rollback_record.update(
                    {
                        "status": "FAILED",
                        "failure": f"{type(rollback_error).__name__}: {rollback_error}",
                    }
                )
                try:
                    rollback_record["after"] = _snapshot_json(
                        self.boundary.snapshot()
                    )
                except (Exception, KeyboardInterrupt):
                    rollback_record["after"] = {"status": "UNAVAILABLE"}
                record["status"] = "FAILED_ROLLBACK_FAILED"
                record["unaffectedAssertion"] = "FAILED_OR_UNPROVEN"
        else:
            record["status"] = "FAILED_BEFORE_REPLACEMENT"
        record["completedAt"] = self._timestamp()
        self.record_store.write(path, record)
        raise PilotError(
            f"{operation} failed; automatic rollback status is "
            f"{record['status']}; record: {path}"
        ) from deployment_error


def validate_policy_against_catalog(
    policy: PilotPolicy, catalog: Catalog, profile: Profile
) -> frozenset[str]:
    required_services = frozenset(
        service
        for repository in selected_repositories(catalog, profile)
        for service in repository.compose_services
    )
    for name, service in policy.services.items():
        if name not in required_services or service.smoke_caller not in required_services:
            raise PilotError(
                f"pilot service/caller is not in the selected fixture runtime: {name}"
            )
        owners = [
            repository
            for repository in catalog.repositories
            if name in repository.compose_services
        ]
        if len(owners) != 1:
            raise PilotError(f"pilot service must have one catalogue owner: {name}")
        owner = owners[0]
        if owner.port != service.port or owner.health != service.health_path:
            raise PilotError(
                f"pilot health metadata differs from the catalogue: {name}"
            )
    return required_services


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("deploy-service", "rollback-service")
    )
    parser.add_argument("service")
    parser.add_argument(
        "immutable_version",
        help="Local sha256 image ID or repository@sha256 OCI digest",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    try:
        if args.timeout_seconds < 1 or args.poll_seconds <= 0:
            raise PilotError("timeouts must be positive")
        policy = load_policy()
        catalog = load_catalog()
        profile = catalog.profile(policy.profile)
        required_services = validate_policy_against_catalog(
            policy, catalog, profile
        )
        environment_file = ensure_environment(profile)
        boundary = ComposeBoundary(policy, profile, environment_file)
        operator = ServicePilotOperator(
            policy,
            boundary,
            required_services,
            wait_attempts=max(1, math.ceil(args.timeout_seconds / args.poll_seconds)),
            poll_seconds=args.poll_seconds,
        )
        record = operator.execute(
            args.operation, args.service, args.immutable_version
        )
        print(f"{args.operation} succeeded; record: {record}")
        return 0
    except (PilotError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
