#!/usr/bin/env python3
"""Build, test and operate a locked fixture-backed source workspace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

from scripts.security.generate_profile_env import render
from scripts.workspace.catalog import (
    INFRASTRUCTURE_ROOT,
    WORKSPACE_ROOT,
    Catalog,
    Profile,
    load_catalog,
)
from scripts.workspace.validate import compose_model, validate_workspace

CACHE_ROOT = WORKSPACE_ROOT / ".cache"
MAVEN_REPOSITORY = CACHE_ROOT / "m2"
NPM_CACHE = CACHE_ROOT / "npm"
MAVEN_SETTINGS = CACHE_ROOT / "maven-settings.xml"
GITHUB_PACKAGE_SERVERS = (
    "github-user-profile",
    "github-cv-cover-letter",
    "github-document-export",
)


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
    return INFRASTRUCTURE_ROOT / f".env.{profile.name}"


def ensure_environment(profile: Profile) -> Path:
    output = environment_path(profile)
    if not output.exists():
        render(
            profile.environment_profile,
            INFRASTRUCTURE_ROOT / ".env.example",
            output,
        )
        print(f"Generated safe fixture configuration: {output}")
    return output


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[{cwd.name}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def ensure_maven_settings() -> Path:
    """Create ignored, owner-only Maven credentials from the validated gh login."""
    try:
        username = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        token = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "GitHub Packages authentication requires a working `gh auth login`"
        ) from error
    if not username or not token:
        raise RuntimeError("GitHub CLI returned incomplete package credentials")

    servers = "\n".join(
        "    <server>\n"
        f"      <id>{escape(server_id)}</id>\n"
        f"      <username>{escape(username)}</username>\n"
        f"      <password>{escape(token)}</password>\n"
        "    </server>"
        for server_id in GITHUB_PACKAGE_SERVERS
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0">\n'
        "  <servers>\n"
        f"{servers}\n"
        "  </servers>\n"
        "</settings>\n"
    )
    MAVEN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        MAVEN_SETTINGS,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(document)
    MAVEN_SETTINGS.chmod(0o600)
    return MAVEN_SETTINGS


def maven_command(*goals: str) -> list[str]:
    MAVEN_REPOSITORY.mkdir(parents=True, exist_ok=True)
    settings = ensure_maven_settings()
    return [
        "mvn",
        "-B",
        "--settings",
        str(settings),
        f"-Dmaven.repo.local={MAVEN_REPOSITORY}",
        *goals,
    ]


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
        "-p",
        profile.compose_project,
        "--env-file",
        str(environment_file),
    ]
    for compose_file in profile.compose_files:
        command.extend(("-f", compose_file))
    command.extend(arguments)
    return command


def start(profile: Profile, build: bool) -> None:
    fail_if_invalid()
    environment_file = ensure_environment(profile)
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


def container_status(profile: Profile) -> list[dict]:
    environment_file = ensure_environment(profile)
    result = subprocess.run(
        compose_command(profile, environment_file, "ps", "--format", "json"),
        cwd=INFRASTRUCTURE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    text = result.stdout.strip()
    if not text:
        return []
    parsed = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    raise RuntimeError("unexpected Docker Compose status output")


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
            ok, detail = http_ready(
                f"http://localhost:{repository.port}{repository.health}"
            )
            if not ok:
                failures.append(f"{repository.name}: {detail}")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("build", "test", "start", "stop", "status", "health", "logs"),
    )
    parser.add_argument(
        "--profile",
        choices=("basic-fixture", "full-fixture"),
        default="basic-fixture",
    )
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--delete-volumes", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog()
    profile = catalog.profile(args.profile)
    try:
        if args.command in {"build", "test"}:
            fail_if_invalid()
            operation = build_repository if args.command == "build" else test_repository
            for repository in selected_repositories(catalog, profile):
                operation(repository)
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
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
