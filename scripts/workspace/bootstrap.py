#!/usr/bin/env python3
"""Safely clone missing Job Seeker Copilot repositories into this workspace."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.workspace.catalog import DEFAULT_CATALOG, ROOT, load_catalog


def remote_url(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def expected_remote(owner: str, repository: str) -> tuple[str, str]:
    return (
        f"https://github.com/{owner}/{repository}.git",
        f"git@github.com:{owner}/{repository}.git",
    )


def plan(root: Path, owner: str, repositories: tuple[str, ...]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    conflicts: list[str] = []
    for repository in repositories:
        path = root / repository
        if not path.exists():
            missing.append(repository)
            continue
        current_remote = remote_url(path)
        if current_remote not in expected_remote(owner, repository):
            conflicts.append(
                f"{repository}: existing path is not the expected Git checkout "
                f"(origin={current_remote or 'missing'})"
            )
    return missing, conflicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="clone missing repositories; without this flag the command is read-only",
    )
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    missing, conflicts = plan(ROOT, catalog.owner, catalog.repositories)

    for message in conflicts:
        print(f"CONFLICT {message}")
    for repository in missing:
        print(f"MISSING {catalog.owner}/{repository}")

    if conflicts:
        print("Refusing to clone while workspace conflicts exist.")
        return 2
    if not args.apply:
        print(f"Dry run: {len(missing)} repository/repositories would be cloned.")
        return 0

    for repository in missing:
        subprocess.run(
            [
                "gh",
                "repo",
                "clone",
                f"{catalog.owner}/{repository}",
                str(ROOT / repository),
                "--",
                "--branch",
                catalog.default_ref,
                "--single-branch",
            ],
            check=True,
        )
    print(f"Cloned {len(missing)} repository/repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
