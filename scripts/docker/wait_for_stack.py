#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.docker.stack_config import STACKS, stack_for


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status < 500
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for stack HTTP readiness checks.")
    parser.add_argument("stack", choices=sorted(STACKS))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    stack = stack_for(args.stack)
    checks = [
        ("frontend", stack.frontend_url),
        ("system-data-service", f"{stack.system_data_url}/actuator/health"),
    ]
    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        failures = [name for name, url in checks if not healthy(url)]
        if not failures:
            print(f"{stack.name} stack is ready")
            return 0
        print(f"Waiting for {', '.join(failures)}...")
        time.sleep(5)
    print(f"Timed out waiting for {stack.name} stack", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
