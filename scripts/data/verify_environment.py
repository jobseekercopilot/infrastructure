#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.environment_client import fail_if_unsuccessful, print_operation, request_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify non-production Job Seeker Copilot environment data.")
    parser.add_argument("--service-url", default="http://localhost:8103")
    parser.add_argument("--scenario", default="DEMO_READY", choices=["EMPTY", "DEMO_READY"])
    args = parser.parse_args()

    response = request_json("GET", args.service_url, f"/internal/environments/verify?scenario={args.scenario}")
    print_operation(response)
    return fail_if_unsuccessful(response)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
