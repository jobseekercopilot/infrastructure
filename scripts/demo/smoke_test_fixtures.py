#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.http_client import get_json, post_json

ADZUNA_GATEWAY_URL = os.environ.get("ADZUNA_GATEWAY_URL", "http://localhost:9108")
JSEARCH_GATEWAY_URL = os.environ.get("JSEARCH_GATEWAY_URL", "http://localhost:9109")
REED_GATEWAY_URL = os.environ.get("REED_GATEWAY_URL", "http://localhost:9107")
POSTCODE_IO_GATEWAY_URL = os.environ.get("POSTCODE_IO_GATEWAY_URL", "http://localhost:9102")
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://localhost:9113")
STRIPE_GATEWAY_URL = os.environ.get("STRIPE_GATEWAY_URL", "http://localhost:9122")


def job_count(payload, keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def main():
    argparse.ArgumentParser(description="Smoke test fixture-mode gateway responses.").parse_args()
    failures = []
    checks = [
        ("adzuna", lambda: post_json(f"{ADZUNA_GATEWAY_URL}/api/v1/adzuna/jobs/search", {
            "targetRole": "Software Developer",
            "location": "Reading",
            "page": 1,
            "resultsPerPage": 5,
        }), ["jobs"]),
        ("jsearch", lambda: post_json(f"{JSEARCH_GATEWAY_URL}/api/v1/jsearch/jobs/search", {
            "targetRole": "Software Developer",
            "location": "Reading",
            "remoteOnly": False,
        }), ["jobs"]),
        ("reed", lambda: get_json(f"{REED_GATEWAY_URL}/api/reed/search?query=Software%20Developer&location=Reading&limit=5"), ["results"]),
    ]
    for name, call, keys in checks:
        try:
            first = call()
            second = call()
            count = job_count(first, keys)
            print(f"{name}: resultCount={count}")
            if count <= 0:
                failures.append(f"{name}: no fixture jobs returned")
            if first != second:
                failures.append(f"{name}: response changed across repeated fixture calls")
        except Exception as error:
            failures.append(f"{name}: {error}")

    try:
        postcode = get_json(f"{POSTCODE_IO_GATEWAY_URL}/api/postcodes/RG1%201AA")
        print(f"postcode: postcode={postcode.get('postcode')} region={postcode.get('region')}")
        if postcode.get("postcode") != "RG1 1AA":
            failures.append("postcode: unexpected fixture postcode response")
    except Exception as error:
        failures.append(f"postcode: {error}")

    try:
        llm = post_json(f"{LLM_GATEWAY_URL}/api/v1/generate", {
            "taskType": "CV_GENERATION",
            "prompt": "Write a concise demo CV summary for Alex Taylor.",
            "temperature": 0.2,
            "maxTokens": 500,
        })
        print(f"llm: provider={llm.get('provider')} model={llm.get('model')}")
        if llm.get("provider") != "FIXTURE":
            failures.append("llm: expected provider=FIXTURE")
    except Exception as error:
        failures.append(f"llm: {error}")

    try:
        stripe = post_json(f"{STRIPE_GATEWAY_URL}/api/v1/stripe/checkout-sessions", {
            "userId": "alex-taylor-demo",
            "pricingPlanId": "starter",
            "tokenAmount": 100000,
            "priceGbpPence": 499,
        })
        print(f"stripe: sessionId={stripe.get('sessionId')}")
        if not str(stripe.get("sessionId", "")).startswith("cs_test_demo_"):
            failures.append("stripe: expected fixture checkout session id")
    except Exception as error:
        failures.append(f"stripe: {error}")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
