#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.project_paths import PROJECT_ROOT

SCRIPTS = [
    "scripts.clients.export_openapi_contracts",
    "scripts.clients.generate_backend_clients",
    "scripts.clients.install_backend_clients",
    "scripts.clients.generate_frontend_clients",
]


def run_script(module_name: str) -> bool:
    print()
    print("=" * 80)
    print(f"Running {module_name}")
    print("=" * 80)

    result = subprocess.run(
        [sys.executable, "-m", module_name],
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        print()
        print(f"FAILED: {module_name}")
        return False

    print()
    print(f"SUCCESS: {module_name}")
    return True


def main() -> int:
    argparse.ArgumentParser(description="Export contracts and regenerate all backend/frontend API clients.").parse_args()
    print("Generating all API clients")

    failures = []

    for script in SCRIPTS:
        if not run_script(script):
            failures.append(script)
            break

    print()
    print("=" * 80)

    if failures:
        print("API client generation failed")
        print("Failed script:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("All API clients generated successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
