#!/usr/bin/env python3
"""Read-only prerequisites and workspace diagnostics."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.workspace.bootstrap import plan
from scripts.workspace.catalog import ROOT, load_catalog


def command_ok(command: list[str]) -> bool:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def main() -> int:
    checks = {
        "git": shutil.which("git") is not None,
        "gh": shutil.which("gh") is not None,
        "gh-auth": command_ok(["gh", "auth", "status"]),
        "docker": shutil.which("docker") is not None,
        "docker-compose": command_ok(["docker", "compose", "version"]),
        "java": shutil.which("java") is not None,
        "maven": shutil.which("mvn") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "python": shutil.which("python3") is not None,
    }
    catalog = load_catalog()
    missing, conflicts = plan(ROOT, catalog.owner, catalog.repositories)

    for name, ok in checks.items():
        print(f"{'OK' if ok else 'MISSING'} {name}")
    print(f"INFO catalog repositories={len(catalog.repositories)} missing={len(missing)} conflicts={len(conflicts)}")
    for conflict in conflicts:
        print(f"CONFLICT {conflict}")
    return 0 if all(checks.values()) and not conflicts else 1


if __name__ == "__main__":
    raise SystemExit(main())
