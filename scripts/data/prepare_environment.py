#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.environment_client import fail_if_unsuccessful, print_operation, request_json


SCENARIOS = [
    "EMPTY",
    "REGISTRATION_CLEAN",
    "LOGIN_SESSION",
    "PROFILE_LOCATION",
    "DUPLICATE_REGISTRATION",
    "CROSS_USER_SECURITY",
    "REAL_WORLD_PERSONAS",
    "PROVIDER_FAILURE",
    "DEMO_READY",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a governed System Data named state.")
    parser.add_argument("--service-url", default="http://localhost:9103")
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    args = parser.parse_args()

    response = request_json(
        "POST",
        args.service_url,
        "/internal/environments/prepare",
        {"scenario": args.scenario},
    )
    print_operation(response)
    return fail_if_unsuccessful(response)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
