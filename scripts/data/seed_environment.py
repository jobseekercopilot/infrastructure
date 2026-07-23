#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.environment_client import fail_if_unsuccessful, print_operation, request_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed non-production Job Seeker Copilot environment data.")
    parser.add_argument("--service-url", default="http://localhost:8103")
    parser.add_argument("--scenario", default="DEMO_READY", choices=["DEMO_READY"])
    parser.add_argument("--dataset-id", default="uk-software-developer-demo")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--reference-date", default="2026-07-10T09:00:00Z")
    args = parser.parse_args()

    payload = {
        "scenario": args.scenario,
        "datasetId": args.dataset_id,
        "datasetVersion": args.dataset_version,
        "referenceDate": args.reference_date,
    }
    response = request_json("POST", args.service_url, "/internal/environments/seed", payload)
    print_operation(response)
    return fail_if_unsuccessful(response)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
