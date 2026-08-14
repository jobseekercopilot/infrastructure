#!/usr/bin/env python3
"""One-command safe bootstrap for a new source development workspace."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.workspace.catalog import INFRASTRUCTURE_ROOT, WORKSPACE_ROOT, load_catalog
from scripts.workspace.lifecycle import ensure_environment


def run(command: list[str]) -> None:
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=INFRASTRUCTURE_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("basic-fixture", "full-fixture", "e2e", "full-local-ses"),
        default="basic-fixture",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Clone and validate only; the clean-room proof never uses this option.",
    )
    args = parser.parse_args()
    run(
        [
            sys.executable,
            "-m",
            "scripts.workspace.doctor",
            "--prerequisites-only",
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "scripts.workspace.bootstrap",
            "--workspace",
            str(WORKSPACE_ROOT),
            "--apply",
            "--report",
            str(INFRASTRUCTURE_ROOT / ".workspace-report.json"),
        ]
    )
    catalog = load_catalog()
    ensure_environment(catalog.profile(args.profile))
    run(
        [
            sys.executable,
            "-m",
            "scripts.workspace.validate",
            "--workspace",
            str(WORKSPACE_ROOT),
            "--require-infrastructure-name",
        ]
    )
    if not args.skip_build:
        run(
            [
                sys.executable,
                "-m",
                "scripts.workspace.lifecycle",
                "build",
                "--profile",
                args.profile,
            ]
        )
    print(
        f"Bootstrap complete for {args.profile}. "
        "Use ./scripts/start-local.sh to start it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
