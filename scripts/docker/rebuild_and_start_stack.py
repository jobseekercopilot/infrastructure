#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.clients.api_client_config import backend_services, load_services
from scripts.lib.project_paths import PROJECT_ROOT

def run(command: list[str], cwd: Path = PROJECT_ROOT) -> None:
    print()
    print(" ".join(command))
    result = subprocess.run(command, cwd=cwd)

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def build_backend_service(service_name: str) -> None:
    service_dir = PROJECT_ROOT / service_name

    if not service_dir.exists():
        print(f"Skipping missing service: {service_name}")
        return

    print()
    print("=" * 80)
    print(f"Building backend service: {service_name}")
    print("=" * 80)

    run(["mvn", "clean", "package", "-DskipTests"], cwd=service_dir)


def docker_compose_up() -> None:
    print()
    print("=" * 80)
    print("Rebuilding and starting Docker Compose stack")
    print("=" * 80)

    run(["docker", "compose", "down"])
    run(["docker", "compose", "up", "--build", "-d"])


def main() -> int:
    argparse.ArgumentParser(description="Install clients, build backend services, and rebuild/start Docker Compose.").parse_args()
    try:
        services = load_services()
        run([sys.executable, "-m", "scripts.clients.install_backend_clients"])
        for service in backend_services(services):
            build_backend_service(service)

        # The frontend is built by its Dockerfile with the project's pinned
        # Node version. This avoids host Node-version drift and duplicate work.
        docker_compose_up()

        print()
        print("=" * 80)
        print("Stack rebuilt and started")
        print("=" * 80)
        print("Check containers:")
        print("docker ps")
        print()
        print("View logs:")
        print("docker compose logs -f")
        return 0

    except Exception as error:
        print()
        print("FAILED")
        print(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
