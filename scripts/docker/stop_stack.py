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
    args = parser.parse_args()

    stack = stack_for(args.stack)
    command = stack.compose_command() + ["down"]
    print("Stopping stack")
    print(f"Project: {stack.project}")
    print(" ".join(command))
    return subprocess.run(command, cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
