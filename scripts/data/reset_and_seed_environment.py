#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.environment_client import confirm_or_exit, fail_if_unsuccessful, print_operation, request_json

E2E_SERVICE_URLS = {"http://localhost:9103", "http://127.0.0.1:9103"}
LIVE_SERVICE_URLS = {"http://localhost:8103", "http://127.0.0.1:8103"}
LIVE_FRONTEND_URLS = {"http://localhost:3000", "http://127.0.0.1:3000"}


def enforce_e2e_target(service_url: str, status: dict) -> None:
    normalised_url = service_url.rstrip("/")
    if normalised_url in LIVE_SERVICE_URLS or normalised_url in LIVE_FRONTEND_URLS:
        raise RuntimeError(f"Refusing to reset or seed live-looking URL: {service_url}")
    if normalised_url not in E2E_SERVICE_URLS:
        raise RuntimeError(
            f"Refusing to reset unknown system-data-service URL {service_url}; expected one of {sorted(E2E_SERVICE_URLS)}"
        )
    active_environment = str(status.get("activeEnvironment", "")).lower()
    if "prod" in active_environment or "production" in active_environment:
        raise RuntimeError(f"Refusing production environment: {status.get('activeEnvironment')}")
    if "e2e" not in active_environment:
        raise RuntimeError(f"Refusing non-e2e environment: {status.get('activeEnvironment')}")
    if status.get("environmentManagementEnabled") is not True:
        raise RuntimeError("Refusing because environment management is not enabled")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset and seed the demo-ready Job Seeker Copilot environment.")
    parser.add_argument("--service-url", default="http://localhost:9103")
    parser.add_argument("--scenario", default="DEMO_READY", choices=["DEMO_READY"])
    parser.add_argument("--dataset-id", default="uk-software-developer-demo")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--reference-date", default="2026-07-10T09:00:00Z")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    status = request_json("GET", args.service_url, "/internal/environments/status")
    print(f"Target service: {args.service_url}")
    print(f"Environment: {status.get('activeEnvironment')}")
    enforce_e2e_target(args.service_url, status)
    confirm_or_exit(f"Reset and seed scenario {args.scenario} at {args.service_url}.", args.yes)
    payload = {
        "scenario": args.scenario,
        "datasetId": args.dataset_id,
        "datasetVersion": args.dataset_version,
        "referenceDate": args.reference_date,
    }
    response = request_json("POST", args.service_url, "/internal/environments/reset-and-seed", payload)
    print_operation(response)
    verification = request_json("GET", args.service_url, f"/internal/environments/verify?scenario={args.scenario}")
    print("Verification:")
    print_operation(verification)
    return fail_if_unsuccessful(response) or fail_if_unsuccessful(verification)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
