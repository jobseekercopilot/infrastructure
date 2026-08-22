#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.http_client import get_json, post_json, query


def main():
    parser = argparse.ArgumentParser(description="Validate system-data fixture endpoints and deterministic responses.")
    parser.add_argument("--base-url", default="http://localhost:8103")
    parser.add_argument("--dataset-id", default="uk-software-developer-demo")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--scenario", default="happy-path")
    args = parser.parse_args()
    params = {
        "datasetId": args.dataset_id,
        "datasetVersion": args.dataset_version,
        "scenario": args.scenario,
    }
    failures = []
    try:
        status = get_json(f"{args.base_url}/internal/fixtures/status")
        print(f"status: enabled={status.get('enabled')} datasetId={status.get('datasetId')} scenario={status.get('scenario')}")
        if status.get("enabled") is not True:
            failures.append("fixture status endpoint did not report enabled=true")

        search_url = query(args.base_url, "/internal/fixtures/jobs/search", params | {
            "query": "software developer",
            "location": "Reading",
            "provider": "ADZUNA",
            "page": 0,
            "pageSize": 5,
            "sort": "relevance",
        })
        first = get_json(search_url)
        second = get_json(search_url)
        jobs = first.get("jobs", [])
        print(f"jobs/search: count={len(jobs)} total={first.get('totalResults')}")
        if not jobs:
            failures.append("job fixture search returned no jobs")
        if first != second:
            failures.append("job fixture search was not deterministic across repeated calls")

        if jobs:
            job = get_json(query(args.base_url, f"/internal/fixtures/jobs/{jobs[0]['id']}", params))
            print(f"jobs/{{jobId}}: id={job.get('id')} title={job.get('title')}")

        postcode = get_json(query(args.base_url, "/internal/fixtures/postcodes/RG1%201AA", params))
        print(f"postcodes: postcode={postcode.get('postcode')} region={postcode.get('region')}")
        if postcode.get("postcode") != "RG1 1AA":
            failures.append("postcode fixture did not return expected RG1 1AA response")

        llm = post_json(query(args.base_url, "/internal/fixtures/llm/respond", params), {
            "taskType": "CV_GENERATION",
            "prompt": "Write a concise CV summary for Alex Taylor.",
            "temperature": 0.2,
            "maxTokens": 400,
        })
        print(f"llm/respond: provider={llm.get('provider')} totalTokens={llm.get('totalTokens')}")
        if llm.get("provider") != "FIXTURE":
            failures.append("LLM fixture did not report provider=FIXTURE")

        stripe = post_json(query(args.base_url, "/internal/fixtures/stripe/respond", params), {
            "operation": "create-checkout-session",
            "userId": "alex-taylor-demo",
            "pricingPlanId": "starter",
            "tokenAmount": 100000,
            "priceGbpPence": 499,
        })
        print(f"stripe/respond: sessionId={stripe.get('sessionId')} fixtureMode={stripe.get('fixtureMode')}")
        if stripe.get("fixtureMode") is not True:
            failures.append("Stripe fixture did not report fixtureMode=true")
    except Exception as error:
        failures.append(str(error))

    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
