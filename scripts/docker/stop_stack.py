#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.docker.stack_config import STACKS, stack_for
from scripts.lib.project_paths import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop an isolated Job Seeker Copilot Docker Compose stack.")
    parser.add_argument("stack", choices=sorted(STACKS), help="Stack to stop.")
    parser.add_argument(
        "--delete-volumes",
        action="store_true",
        help="Permanently delete this exact Compose project's local state.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm permanent volume deletion.",
    )
    args = parser.parse_args()
    if args.delete_volumes and not args.yes:
        parser.error("refusing permanent volume deletion without --yes")

    stack = stack_for(args.stack)
    command = stack.compose_command() + ["down"]
    if args.delete_volumes:
        command.extend(("--volumes", "--remove-orphans"))
    print("Stopping stack")
    print(f"Project: {stack.project}")
    if args.delete_volumes:
        print(f"Permanently deleting volumes owned by {stack.project}")
    print(" ".join(command))
    return subprocess.run(command, cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
