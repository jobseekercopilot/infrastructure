#!/usr/bin/env python3
"""Validate the locked sibling workspace and portable Compose topology."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.security.generate_profile_env import render
from scripts.workspace.bootstrap import report_payload
from scripts.workspace.catalog import (
    INFRASTRUCTURE_ROOT,
    WORKSPACE_ROOT,
    Catalog,
    load_catalog,
    load_workspace_lock,
)

INTERPOLATION = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
STAGED_RUNTIME_CONTEXTS = {
    "document-generation-gateway",
    "jsearch-gateway",
    "reed-gateway",
}


@dataclass(frozen=True)
class Finding:
    check: str
    ok: bool
    detail: str


def compose_model(
    catalog: Catalog, profile_name: str, environment_file: Path
) -> dict:
    profile = catalog.profile(profile_name)
    command = [
        "docker",
        "compose",
        "-p",
        profile.compose_project,
        "--env-file",
        str(environment_file),
    ]
    for compose_file in profile.compose_files:
        command.extend(("-f", compose_file))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(
        command,
        cwd=INFRASTRUCTURE_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Docker Compose model failed")
    return json.loads(result.stdout)


def validate_configuration_schema(catalog: Catalog) -> list[Finding]:
    schema = json.loads(catalog.environment_schema_path.read_text(encoding="utf-8"))
    schema_names = {
        variable["name"] for variable in schema.get("variables", []) if "name" in variable
    }
    referenced: set[str] = set()
    template_names: set[str] = set()
    for path in INFRASTRUCTURE_ROOT.glob("docker-compose*.yml"):
        referenced.update(INTERPOLATION.findall(path.read_text(encoding="utf-8")))
    for path in INFRASTRUCTURE_ROOT.glob(".env*.example"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                template_names.add(line.split("=", 1)[0])
    missing = sorted((referenced | template_names) - schema_names)
    return [
        Finding(
            "runtime-environment-schema",
            not missing,
            "covers every Compose/template variable"
            if not missing
            else "missing variables: " + ", ".join(missing),
        )
    ]


def validate_model(
    catalog: Catalog, profile_name: str, model: dict, workspace: Path
) -> list[Finding]:
    findings: list[Finding] = []
    services = model.get("services", {})
    owned_services = {
        service: repository.name
        for repository in catalog.repositories
        for service in repository.compose_services
    }
    missing_owned = sorted(set(owned_services) - set(services))
    findings.append(
        Finding(
            f"{profile_name}-catalog-services",
            not missing_owned,
            "all catalogued runtime services are represented"
            if not missing_owned
            else "missing Compose services: " + ", ".join(missing_owned),
        )
    )

    context_failures: list[str] = []
    health_failures: list[str] = []
    for service, repository_name in owned_services.items():
        definition = services.get(service, {})
        build = definition.get("build")
        if repository_name in STAGED_RUNTIME_CONTEXTS:
            expected_context = (
                workspace / ".cache/runtime-images" / repository_name
            ).resolve()
        else:
            expected_context = (workspace / repository_name).resolve()
        if not isinstance(build, dict):
            context_failures.append(f"{service}: no source build")
        else:
            actual_context = Path(build.get("context", "")).resolve()
            if actual_context != expected_context:
                context_failures.append(
                    f"{service}: {actual_context} != {expected_context}"
                )
            dockerfile = (
                expected_context / build.get("dockerfile", "Dockerfile")
            ).resolve()
            if not dockerfile.is_file():
                context_failures.append(f"{service}: missing {dockerfile}")
        if not definition.get("healthcheck"):
            health_failures.append(f"{service}: no container healthcheck")
    findings.append(
        Finding(
            f"{profile_name}-source-contexts",
            not context_failures,
            "all build contexts map to sibling sources or staged current-workspace artifacts"
            if not context_failures
            else "; ".join(context_failures),
        )
    )
    findings.append(
        Finding(
            f"{profile_name}-health-contracts",
            not health_failures,
            "all runtime services define health checks"
            if not health_failures
            else "; ".join(health_failures),
        )
    )

    published_ports: dict[int, str] = {}
    collisions: list[str] = []
    for service_name, definition in services.items():
        for port in definition.get("ports", []):
            published = port.get("published") if isinstance(port, dict) else None
            if not isinstance(published, int):
                continue
            previous = published_ports.setdefault(published, service_name)
            if previous != service_name:
                collisions.append(f"{published}: {previous}, {service_name}")
    findings.append(
        Finding(
            f"{profile_name}-host-ports",
            not collisions,
            "published host ports are unique"
            if not collisions
            else "collisions: " + "; ".join(collisions),
        )
    )
    return findings


def validate_workspace(
    workspace: Path = WORKSPACE_ROOT,
    *,
    exact_lock: bool = True,
    require_infrastructure_name: bool = False,
) -> list[Finding]:
    catalog = load_catalog()
    lock = load_workspace_lock(catalog)
    findings: list[Finding] = []
    if require_infrastructure_name:
        findings.append(
            Finding(
                "infrastructure-directory-name",
                INFRASTRUCTURE_ROOT.name == catalog.infrastructure_path,
                (
                    f"{INFRASTRUCTURE_ROOT.name} == {catalog.infrastructure_path}"
                    if INFRASTRUCTURE_ROOT.name == catalog.infrastructure_path
                    else f"expected Infrastructure checkout named {catalog.infrastructure_path}"
                ),
            )
        )
    report = report_payload(workspace, catalog, lock)
    unsafe = [
        state
        for state in report["repositories"]
        if state["status"] in {"dirty", "conflict", "wrong-branch"}
    ]
    drift = [
        state
        for state in report["repositories"]
        if state["status"] in {"missing", "revision-drift"}
    ]
    findings.append(
        Finding(
            "workspace-checkouts",
            not unsafe and (not exact_lock or not drift),
            (
                f"{len(report['repositories'])} repositories match the lock"
                if not unsafe and not drift
                else json.dumps(report["summary"], sort_keys=True)
            ),
        )
    )
    findings.extend(validate_configuration_schema(catalog))
    if unsafe or (exact_lock and drift):
        return findings

    with tempfile.TemporaryDirectory() as directory:
        environment_file = Path(directory) / ".env"
        render(
            "local",
            INFRASTRUCTURE_ROOT / ".env.example",
            environment_file,
        )
        for profile in catalog.profiles:
            model = compose_model(catalog, profile.name, environment_file)
            findings.extend(validate_model(catalog, profile.name, model, workspace))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--allow-revision-drift", action="store_true")
    parser.add_argument("--require-infrastructure-name", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    findings = validate_workspace(
        args.workspace.resolve(),
        exact_lock=not args.allow_revision_drift,
        require_infrastructure_name=args.require_infrastructure_name,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": all(finding.ok for finding in findings),
                    "findings": [finding.__dict__ for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for finding in findings:
            print(f"{'OK' if finding.ok else 'FAIL'} {finding.check}: {finding.detail}")
    return 0 if all(finding.ok for finding in findings) else 1


if __name__ == "__main__":
    raise SystemExit(main())
