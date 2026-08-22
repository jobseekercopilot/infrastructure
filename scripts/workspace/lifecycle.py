#!/usr/bin/env python3
"""Build, test and operate a locked fixture-backed source workspace."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

from scripts.contracts.lock import load_contract_lock, verify_checkout
from scripts.security.generate_profile_env import PROFILE_TEMPLATES, render
from scripts.security.provider_secrets import (
    secret_files_inside_repositories,
    validate_store,
)
from scripts.security.validate_compose_runtime import (
    compose_model as compose_security_model,
    validate_model as validate_security_model,
)
from scripts.workspace.catalog import (
    INFRASTRUCTURE_ROOT,
    WORKSPACE_ROOT,
    Catalog,
    Profile,
    load_catalog,
)
from scripts.workspace.runtime_env import controlled_environment
from scripts.workspace.validate import validate_workspace

CACHE_ROOT = WORKSPACE_ROOT / ".cache"
MAVEN_REPOSITORY = CACHE_ROOT / "m2"
NPM_CACHE = CACHE_ROOT / "npm"
CLIENT_SOURCE_CACHE = CACHE_ROOT / "client-sources"
RUNTIME_IMAGE_CACHE = CACHE_ROOT / "runtime-images"


def fail_if_invalid() -> None:
    findings = validate_workspace(WORKSPACE_ROOT)
    failures = [finding for finding in findings if not finding.ok]
    if failures:
        for finding in failures:
            print(f"FAIL {finding.check}: {finding.detail}", file=sys.stderr)
        raise RuntimeError("workspace validation failed")


def selected_repositories(catalog: Catalog, profile: Profile):
    if profile.services == "all-runtime":
        names = {
            repository.name
            for repository in catalog.repositories
            if repository.compose_services
        }
    else:
        selected_services = set(profile.services)
        names = {
            repository.name
            for repository in catalog.repositories
            if selected_services.intersection(repository.compose_services)
        }
    return [
        catalog.repository(name)
        for name in catalog.build_order
        if name in names
    ]


def environment_path(profile: Profile) -> Path:
    return profile.environment_file


def ensure_environment(profile: Profile) -> Path:
    output = environment_path(profile)
    if not output.exists():
        render(
            profile.environment_profile,
            PROFILE_TEMPLATES[profile.environment_profile],
            output,
        )
        print(f"Generated owner-only base runtime configuration: {output}")
    return output


def validate_runtime_boundary(profile: Profile, environment_file: Path) -> None:
    """Fail closed on isolated or live-provider trust boundaries before startup."""
    if profile.name == "e2e":
        expected_files = (
            "docker-compose.yml",
            "docker-compose.e2e.yml",
            "docker-compose.low-memory.yml",
        )
        if profile.compose_files != expected_files:
            raise RuntimeError(
                "e2e Compose order must be base, E2E isolation, then low memory"
            )
        model = compose_security_model(
            environment_file,
            [INFRASTRUCTURE_ROOT / path for path in profile.compose_files[1:]],
            "e2e",
        )
        validate_security_model(model, "e2e")
        print("e2e runtime boundary is valid; external providers remain fixtures.")
        return
    if profile.name == "google-maps-smoke":
        validate_google_maps_boundary(profile, environment_file)
        return
    if profile.name != "real-providers":
        return
    if profile.secret_environment_file is None:
        raise RuntimeError("real-providers requires the catalogued secret store")
    expected_files = (
        "docker-compose.yml",
        "docker-compose.real-job-providers.yml",
        "docker-compose.real-openai.yml",
        "docker-compose.real-google-maps.yml",
        "docker-compose.low-memory.yml",
    )
    if profile.compose_files != expected_files:
        raise RuntimeError(
            "real-providers Compose order must be base, real job providers, "
            "real OpenAI, real Google Maps, then low memory"
        )
    model = compose_security_model(
        environment_file,
        [INFRASTRUCTURE_ROOT / path for path in profile.compose_files[1:]],
        "real-providers",
        secret_env_file=profile.secret_environment_file,
    )
    validate_security_model(model, "real-providers")
    print("real-providers runtime boundary is valid; no values were printed.")


def validate_google_maps_boundary(profile: Profile, environment_file: Path) -> None:
    if profile.secret_environment_file is None:
        raise RuntimeError("google-maps-smoke requires the catalogued secret store")
    expected_files = (
        "docker-compose.yml",
        "docker-compose.real-google-maps.yml",
        "docker-compose.low-memory.yml",
    )
    if profile.compose_files != expected_files:
        raise RuntimeError(
            "google-maps-smoke Compose order must be base, real Google Maps, then low memory"
        )
    model = compose_security_model(
        environment_file,
        [INFRASTRUCTURE_ROOT / path for path in profile.compose_files[1:]],
        "local",
        secret_env_file=profile.secret_environment_file,
    )
    services = model.get("services", {})
    google = services.get("google-maps-gateway", {})
    location = services.get("location-service", {})
    if google.get("environment", {}).get("GOOGLE_MAPS_ENABLED") != "true":
        raise RuntimeError("google-maps-gateway must be explicitly enabled")
    if location.get("environment", {}).get("GOOGLE_MAPS_ENABLED") != "true":
        raise RuntimeError("location-service must be explicitly enabled")
    if google.get("environment", {}).get("GOOGLE_MAPS_API_KEY"):
        raise RuntimeError("Google Maps API key must not be exposed as container environment")
    secret_mounts = google.get("secrets", [])
    if len(secret_mounts) != 1 or secret_mounts[0].get("target") != "GOOGLE_MAPS_API_KEY":
        raise RuntimeError("google-maps-gateway must mount only its API key secret")
    unexpected = [
        name for name, service in services.items()
        if name != "google-maps-gateway"
        and service.get("environment", {}).get("GOOGLE_MAPS_API_KEY")
    ]
    if unexpected:
        raise RuntimeError("Google Maps API key reached an unapproved service")
    validate_security_model(model, "local")
    print("google-maps-smoke runtime boundary is valid; no values were printed.")


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[{cwd.name}] {' '.join(command)}", flush=True)
    subprocess.run(
        command,
        cwd=cwd,
        env=controlled_environment() if env is None else env,
        check=True,
    )


def maven_command(*goals: str) -> list[str]:
    MAVEN_REPOSITORY.mkdir(parents=True, exist_ok=True)
    return [
        "mvn",
        "-B",
        "--no-transfer-progress",
        f"-Dmaven.repo.local={MAVEN_REPOSITORY}",
        *goals,
    ]


def _pom_coordinates(path: Path) -> tuple[str, str, str]:
    root = ElementTree.parse(path).getroot()
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}

    def value(name: str) -> str:
        element = root.find(f"m:{name}", namespace)
        return element.text.strip() if element is not None and element.text else ""

    return value("groupId"), value("artifactId"), value("version")


def _extract_client_source(contract: dict) -> Path:
    package = contract["javaPackage"]
    revision = package["buildRevision"]
    destination = CLIENT_SOURCE_CACHE / contract["service"] / revision
    marker = destination / ".complete"
    if marker.is_file():
        return destination / package["modulePath"]

    if destination.exists():
        if CLIENT_SOURCE_CACHE.resolve() not in destination.resolve().parents:
            raise RuntimeError(f"unsafe client source cache path: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    module_directory = str(Path(package["modulePath"]).parent)
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(WORKSPACE_ROOT / contract["service"]),
            "archive",
            "--format=tar",
            revision,
            module_directory,
            contract["path"],
        ],
        env=controlled_environment(),
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        source.extractall(destination, filter="data")
    marker.write_text(f"{revision}\n", encoding="utf-8")
    return destination / package["modulePath"]


def install_source_clients() -> None:
    """Build pinned producer-owned clients from Git, never from a user Maven cache."""
    for contract in load_contract_lock()["contracts"]:
        package = contract.get("javaPackage")
        if package is None:
            continue
        verify_checkout(contract, WORKSPACE_ROOT)
        pom = _extract_client_source(contract)
        expected = (
            package["groupId"],
            package["artifactId"],
            package["version"],
        )
        actual = _pom_coordinates(pom)
        if actual != expected:
            raise RuntimeError(
                f"{contract['service']}: source client coordinates {actual} "
                f"do not match lock {expected}"
            )
        run(
            [
                *maven_command("-DskipTests", "clean", "install"),
                "-f",
                str(pom),
            ],
            pom.parent,
        )


RUNTIME_IMAGE_ARTIFACTS = {
    "adzuna-gateway": "target/adzuna-gateway-1.0.0.jar",
    "document-generation-gateway": "target/document-generation-gateway-1.0.0.jar",
    "jsearch-gateway": "target/jsearch-gateway-1.0.0.jar",
    "reed-gateway": "target/reed-gateway-1.0.0.jar",
}


def stage_runtime_image_contexts(repository_names: set[str]) -> None:
    """Stage current-workspace artifacts excluded by service build contexts."""
    for repository_name, artifact_path in RUNTIME_IMAGE_ARTIFACTS.items():
        if repository_name not in repository_names:
            continue
        source = WORKSPACE_ROOT / repository_name / artifact_path
        if not source.is_file():
            raise RuntimeError(
                f"{repository_name}: expected built artifact is missing: {source}; "
                "run the workspace build before building images"
            )
        destination = RUNTIME_IMAGE_CACHE / repository_name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / "app.jar")


def build_repository(repository) -> None:
    path = WORKSPACE_ROOT / repository.name
    if repository.build == "maven":
        run(maven_command("-DskipTests", "clean", "package"), path)
    elif repository.build == "npm":
        NPM_CACHE.mkdir(parents=True, exist_ok=True)
        run(["npm", "ci", "--cache", str(NPM_CACHE)], path)
        run(["npm", "run", "build"], path)
    else:
        raise RuntimeError(f"unsupported build strategy: {repository.build}")


def test_repository(repository) -> None:
    path = WORKSPACE_ROOT / repository.name
    if repository.build == "maven":
        run(maven_command("test"), path)
    elif repository.build == "npm":
        NPM_CACHE.mkdir(parents=True, exist_ok=True)
        run(["npm", "ci", "--cache", str(NPM_CACHE)], path)
        run(["npm", "test", "--", "--watch=false"], path)
    else:
        raise RuntimeError(f"unsupported build strategy: {repository.build}")


def compose_command(
    profile: Profile, environment_file: Path, *arguments: str
) -> list[str]:
    command = [
        "docker",
        "compose",
    ]
    if profile.compose_parallel_limit is not None:
        command.extend(("--parallel", str(profile.compose_parallel_limit)))
    command.extend(
        (
            "-p",
            profile.compose_project,
            "--env-file",
            str(environment_file),
        )
    )
    if profile.secret_environment_file is not None:
        command.extend(("--env-file", str(profile.secret_environment_file)))
    for compose_file in profile.compose_files:
        command.extend(("-f", compose_file))
    command.extend(arguments)
    return command


def start(profile: Profile, build: bool) -> None:
    if profile.secret_environment_file is not None:
        repository_secret_files = secret_files_inside_repositories()
        if repository_secret_files:
            paths = ", ".join(
                str(path.relative_to(WORKSPACE_ROOT))
                for path in repository_secret_files
            )
            raise RuntimeError(
                "real provider credentials are forbidden inside Git repositories: "
                + paths
            )
        secret_failures = validate_store(
            profile.secret_providers,
            profile.secret_environment_file,
        )
        if secret_failures:
            raise RuntimeError("; ".join(secret_failures))
    fail_if_invalid()
    if build:
        stage_runtime_image_contexts(
            {repository.name for repository in selected_repositories(load_catalog(), profile)}
        )
    environment_file = ensure_environment(profile)
    validate_runtime_boundary(profile, environment_file)
    command = compose_command(profile, environment_file, "up", "-d")
    if build:
        command.append("--build")
    if profile.services != "all-runtime":
        command.append("--no-deps")
        command.extend(profile.services)
    run(command, INFRASTRUCTURE_ROOT)


def stop(profile: Profile, delete_volumes: bool, confirmed: bool) -> None:
    if delete_volumes and not confirmed:
        raise RuntimeError("volume deletion requires --yes")
    environment_file = ensure_environment(profile)
    command = compose_command(profile, environment_file, "down", "--remove-orphans")
    if delete_volumes:
        command.append("--volumes")
    run(command, INFRASTRUCTURE_ROOT)


def parse_compose_status(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    try:
        parsed_lines = [
            json.loads(line) for line in text.splitlines() if line.strip()
        ]
    except json.JSONDecodeError as error:
        raise RuntimeError("unexpected Docker Compose status output") from error
    if all(isinstance(item, dict) for item in parsed_lines):
        return parsed_lines
    raise RuntimeError("unexpected Docker Compose status output")


def container_status(profile: Profile) -> list[dict]:
    environment_file = ensure_environment(profile)
    result = subprocess.run(
        compose_command(profile, environment_file, "ps", "--format", "json"),
        cwd=INFRASTRUCTURE_ROOT,
        env=controlled_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_compose_status(result.stdout)


def http_ready(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(65536).decode("utf-8", errors="replace")
            if response.status >= 400:
                return False, f"HTTP {response.status}"
            if url.endswith("/actuator/health"):
                payload = json.loads(body)
                if payload.get("status") != "UP":
                    return False, f"health status {payload.get('status')}"
            return True, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return False, str(error)


def container_http_ready(
    profile: Profile, service: str, port: int, path: str
) -> tuple[bool, str]:
    environment_file = ensure_environment(profile)
    result = subprocess.run(
        compose_command(
            profile,
            environment_file,
            "exec",
            "-T",
            service,
            "wget",
            "-qO-",
            f"http://127.0.0.1:{port}{path}",
        ),
        cwd=INFRASTRUCTURE_ROOT,
        env=controlled_environment(),
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or f"wget exit {result.returncode}"
        return False, detail
    if path.endswith("/actuator/health"):
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            return False, str(error)
        if payload.get("status") != "UP":
            return False, f"health status {payload.get('status')}"
    return True, "container HTTP 200"


def health(profile: Profile, timeout_seconds: int) -> None:
    catalog = load_catalog()
    selected = selected_repositories(catalog, profile)
    expected_services = {
        service
        for repository in selected
        for service in repository.compose_services
    }
    deadline = time.monotonic() + timeout_seconds
    last_failures: list[str] = []
    while time.monotonic() < deadline:
        containers = {item.get("Service"): item for item in container_status(profile)}
        failures: list[str] = []
        for service in expected_services:
            item = containers.get(service)
            if not item:
                failures.append(f"{service}: container missing")
                continue
            if item.get("State") != "running":
                failures.append(f"{service}: state={item.get('State')}")
                continue
            health_state = item.get("Health")
            if health_state and health_state != "healthy":
                failures.append(f"{service}: health={health_state}")
        for repository in selected:
            if repository.port is None or repository.health is None:
                continue
            ok, detail = container_http_ready(
                profile,
                repository.compose_services[0],
                repository.port,
                repository.health,
            )
            if not ok:
                failures.append(f"{repository.name}: {detail}")
        frontend_ok, frontend_detail = http_ready(profile.frontend_url)
        if not frontend_ok:
            failures.append(f"frontend access: {frontend_detail}")
        if not failures:
            print(
                f"{profile.name} ready: {len(expected_services)} application services"
            )
            return
        last_failures = failures
        print("Waiting: " + "; ".join(failures[:8]), flush=True)
        time.sleep(5)
    raise RuntimeError("health check timeout: " + "; ".join(last_failures))


def main() -> int:
    catalog = load_catalog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("build", "test", "start", "stop", "status", "health", "logs"),
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.name for profile in catalog.profiles),
        default="basic-fixture",
    )
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--delete-volumes", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    profile = catalog.profile(args.profile)
    try:
        if args.command in {"build", "test"}:
            fail_if_invalid()
            selected = selected_repositories(catalog, profile)
            if any(
                repository.name == "document-generation-gateway"
                for repository in selected
            ):
                install_source_clients()
            operation = build_repository if args.command == "build" else test_repository
            for repository in selected:
                operation(repository)
            if args.command == "build":
                stage_runtime_image_contexts(
                    {repository.name for repository in selected}
                )
        elif args.command == "start":
            start(profile, args.build)
        elif args.command == "stop":
            stop(profile, args.delete_volumes, args.yes)
        elif args.command == "status":
            environment_file = ensure_environment(profile)
            run(
                compose_command(profile, environment_file, "ps"),
                INFRASTRUCTURE_ROOT,
            )
        elif args.command == "health":
            health(profile, args.timeout_seconds)
        elif args.command == "logs":
            environment_file = ensure_environment(profile)
            command = compose_command(profile, environment_file, "logs")
            if args.follow:
                command.append("--follow")
            run(command, INFRASTRUCTURE_ROOT)
        return 0
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
