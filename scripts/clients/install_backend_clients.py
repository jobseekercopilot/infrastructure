#!/usr/bin/env python3

import argparse
import subprocess
import sys
import shutil
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.clients.api_client_config import backend_client_targets, backend_consumers, load_services
from scripts.lib.project_paths import BACKEND_CLIENTS_DIR, PROJECT_ROOT


def run(command: list[str], cwd: Path) -> None:
    print()
    print(f"Running in {cwd.relative_to(PROJECT_ROOT)}:")
    print(" ".join(command))

    result = subprocess.run(command, cwd=cwd)

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def find_client_projects(services: dict[str, dict]) -> list[Path]:
    if not BACKEND_CLIENTS_DIR.exists():
        print(f"ERROR: directory not found: {BACKEND_CLIENTS_DIR}")
        return []

    projects = []
    targets = set(backend_client_targets(services))

    for path in sorted(BACKEND_CLIENTS_DIR.iterdir()):
        if path.name in targets and path.is_dir() and (path / "pom.xml").exists():
            projects.append(path)

    missing = targets.difference(path.name for path in projects)
    if missing:
        names = ", ".join(sorted(missing))
        raise FileNotFoundError(f"Missing generated backend clients: {names}")

    return projects


def install_client(client_dir: Path, services: dict[str, dict]) -> None:
    print()
    print("=" * 80)
    print(f"Installing generated backend client: {client_dir.name}")
    print("=" * 80)

    # Consumers use system-scoped jars from their own libs directory, so a
    # package build is sufficient and avoids coupling rebuilds to ~/.m2 writes.
    run(["mvn", "clean", "package", "-DskipTests"], cwd=client_dir)

    jar_name = f"{client_dir.name}-client-1.0.0.jar"
    source_jar = client_dir / "target" / jar_name
    for consumer in backend_consumers(services, client_dir.name):
        libs_dir = PROJECT_ROOT / consumer / "libs"
        libs_dir.mkdir(exist_ok=True)
        destination = libs_dir / jar_name
        shutil.copy2(source_jar, destination)
        print(f"Copied -> {destination.relative_to(PROJECT_ROOT)}")


def main() -> int:
    argparse.ArgumentParser(description="Build and install generated backend client JARs into consumer services.").parse_args()
    services = load_services()
    try:
        projects = find_client_projects(services)
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    if not projects:
        print("No generated backend client projects found.")
        print("Run this first:")
        print("python -m scripts.clients.generate_backend_clients")
        return 1

    failures = []

    for project in projects:
        try:
            install_client(project, services)
        except Exception as error:
            failures.append(project.name)
            print()
            print(f"FAILED: {project.name}")
            print(error)

    print()
    print("=" * 80)

    if failures:
        print("Some generated backend clients failed to install:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("All generated backend clients installed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
