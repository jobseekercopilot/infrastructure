#!/usr/bin/env python3
"""Read-only prerequisites and sibling-workspace diagnostics."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

from scripts.workspace.bootstrap import report_payload
from scripts.workspace.catalog import WORKSPACE_ROOT, load_catalog, load_workspace_lock


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
        "java-17+": command_ok(
            ["sh", "-c", "java -version 2>&1 | grep -Eq 'version \"(1[7-9]|[2-9][0-9])'"]
        ),
        "maven": shutil.which("mvn") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "python-3.11+": tuple(map(int, platform.python_version_tuple()[:2]))
        >= (3, 11),
        "openssl": shutil.which("openssl") is not None,
        "curl": shutil.which("curl") is not None,
    }
    catalog = load_catalog()
    lock = load_workspace_lock(catalog)
    report = report_payload(WORKSPACE_ROOT, catalog, lock)

    for name, ok in checks.items():
        print(f"{'OK' if ok else 'MISSING'} {name}")
    print(
        "INFO "
        f"workspace={WORKSPACE_ROOT} "
        f"repositories={len(catalog.repositories)} "
        f"summary={json.dumps(report['summary'], sort_keys=True)}"
    )
    for state in report["repositories"]:
        if state["status"] != "ready":
            print(
                f"{state['status'].upper()} {state['name']}: "
                f"{state.get('detail') or state['path']}"
            )
    return 0 if all(checks.values()) and all(
        state["status"] == "ready" for state in report["repositories"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
