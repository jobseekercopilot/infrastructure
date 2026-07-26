#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.acquisition_policy import (
    authorize,
    create_audit_manifest,
    load_env_file,
    update_audit_manifest,
)
from scripts.docker.stack_config import stack_for
from scripts.lib.project_paths import PROJECT_ROOT


QUARANTINE_ROOT = (
    PROJECT_ROOT / "system-data-service" / "quarantined-acquisitions"
)


def run(command: list[str]) -> int:
    try:
        return subprocess.run(command, cwd=PROJECT_ROOT).returncode
    except OSError:
        print(
            "A required local command could not be executed; no command "
            "arguments or credentials were logged.",
            file=sys.stderr,
        )
        return 127


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one authorized, quarantined live job-provider acquisition. "
            "This can incur external-provider costs."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env.data-acquisition",
    )
    parser.add_argument(
        "--authorize-live-provider-costs",
        action="store_true",
        help="Confirm that the approved live provider calls and costs are intended.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Use existing local images after the guarded preflight.",
    )
    args = parser.parse_args()
    if not args.authorize_live_provider_costs:
        parser.error("refusing live acquisition without explicit cost authorization")

    env_file = args.env_file.resolve()
    try:
        authorization = authorize(load_env_file(env_file))
    except (OSError, ValueError) as error:
        print(f"Acquisition authorization rejected: {error}", file=sys.stderr)
        return 2

    stack = stack_for("data-acquisition")
    validation = stack.validation_command(str(env_file))
    if run(validation) != 0:
        return 2

    try:
        audit_path = create_audit_manifest(QUARANTINE_ROOT, authorization)
    except (FileExistsError, OSError, ValueError) as error:
        print(f"Acquisition audit could not be created: {error}", file=sys.stderr)
        return 2

    command = stack.compose_command(str(env_file))
    for provider in authorization.approved_providers:
        command.extend(("--profile", provider.lower()))
    if authorization.postcode_enabled:
        command.extend(("--profile", "postcode"))

    gateway_start = command + ["up", "-d", "--wait"]
    if not args.no_build:
        gateway_start.append("--build")
    gateway_start.extend(authorization.gateway_services)
    update_audit_manifest(audit_path, "RUNNING")
    status = "FAILED"
    result = 1
    try:
        result = run(gateway_start)
        if result == 0:
            system_data_run = command + ["run", "--rm"]
            if not args.no_build:
                system_data_run.append("--build")
            system_data_run.append("system-data-service")
            result = run(system_data_run)
        status = "COMPLETED" if result == 0 else "FAILED"
    finally:
        teardown = run(command + ["down", "--remove-orphans"])
        if teardown != 0:
            status = "TEARDOWN_FAILED"
            result = result or teardown
        update_audit_manifest(audit_path, status)

    print(f"Acquisition status: {status}")
    print(f"Quarantine audit: {audit_path}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
