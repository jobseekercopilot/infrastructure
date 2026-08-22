#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.http_client import get_json


DEFAULT_GATEWAYS = {
    "adzuna-gateway": os.environ.get("ADZUNA_GATEWAY_URL", "http://localhost:9108"),
    "jsearch-gateway": os.environ.get("JSEARCH_GATEWAY_URL", "http://localhost:9109"),
    "nhs-jobs-gateway": os.environ.get("NHS_JOBS_GATEWAY_URL", "http://localhost:9124"),
    "apprenticeships-gateway": os.environ.get("APPRENTICESHIPS_GATEWAY_URL", "http://localhost:9125"),
    "reed-gateway": os.environ.get("REED_GATEWAY_URL", "http://localhost:9107"),
    "postcode-io-gateway": os.environ.get("POSTCODE_IO_GATEWAY_URL", "http://localhost:9102"),
    "llm-gateway": os.environ.get("LLM_GATEWAY_URL", "http://localhost:9113"),
    "stripe-gateway": os.environ.get("STRIPE_GATEWAY_URL", "http://localhost:9122"),
}


def main():
    parser = argparse.ArgumentParser(description="Check external gateways report FIXTURE provider mode.")
    parser.add_argument("--expect", default="FIXTURE", choices=["LIVE", "FIXTURE"])
    args = parser.parse_args()
    failures = []
    for name, base_url in DEFAULT_GATEWAYS.items():
        try:
            payload = get_json(f"{base_url}/internal/provider-mode")
        except Exception as error:
            failures.append(f"{name}: {error}")
            continue
        mode = payload.get("mode")
        external_calls = payload.get("externalCallsEnabled")
        print(f"{name}: mode={mode} externalCallsEnabled={external_calls}")
        if mode != args.expect:
            failures.append(f"{name}: expected {args.expect}, got {mode}")
        if args.expect == "FIXTURE" and external_calls is not False:
            failures.append(f"{name}: expected externalCallsEnabled=false")
    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
