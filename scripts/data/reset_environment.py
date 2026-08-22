#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.environment_client import confirm_or_exit, fail_if_unsuccessful, print_operation, request_json
from scripts.data.prepare_environment import SCENARIOS


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset non-production Job Seeker Copilot environment data.")
    parser.add_argument("--service-url", default="http://localhost:9103")
    parser.add_argument("--scenario", default="EMPTY", choices=SCENARIOS)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    status = request_json("GET", args.service_url, "/internal/environments/status")
    print(f"Target service: {args.service_url}")
    print(f"Environment: {status.get('activeEnvironment')}")
    confirm_or_exit(f"Reset scenario {args.scenario} at {args.service_url}.", args.yes)
    response = request_json("POST", args.service_url, "/internal/environments/reset", {"scenario": args.scenario})
    print_operation(response)
    # `verify` proves the prepared state and therefore must fail after a
    # successful reset of a populated scenario. The reset response itself
    # carries the bounded per-service deletion counts and zeroed summary.
    return fail_if_unsuccessful(response)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
