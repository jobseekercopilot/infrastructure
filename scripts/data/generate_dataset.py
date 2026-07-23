#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trigger system-data-service dataset generation.")
    parser.add_argument("--service-url", default="http://localhost:8103")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--queries", nargs="+", required=True)
    parser.add_argument("--locations", nargs="+", required=True)
    parser.add_argument("--providers", nargs="+", default=["ADZUNA", "JSEARCH", "REED"])
    parser.add_argument("--maximum-results-per-provider", type=int, default=20)
    parser.add_argument("--description", default="UK software development jobs for demos and automated tests")
    parser.add_argument("--overwrite", action="store_true", help="Intentionally replace an existing dataset version after backing it up.")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="HTTP timeout for the synchronous generation request.")
    return parser.parse_args()


def post_json(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Generation failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach system-data-service: {error.reason}") from error


def main() -> int:
    args = parse_args()
    payload = {
        "datasetId": args.dataset_id,
        "version": args.version,
        "description": args.description,
        "queries": args.queries,
        "locations": args.locations,
        "providers": args.providers,
        "maximumResultsPerProvider": args.maximum_results_per_provider,
        "overwrite": args.overwrite,
    }
    if args.overwrite:
        print("Overwrite requested: an existing dataset version will be backed up before replacement.")
    try:
        response = post_json(f"{args.service_url.rstrip('/')}/internal/datasets/generate", payload, args.timeout_seconds)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    output_directory = Path(response["outputDirectory"])
    print("Dataset generation complete")
    print(f"Dataset: {response['datasetId']} {response['version']}")
    print(f"Overwritten: {response.get('overwritten', False)}")
    backup_directory = response.get("backupDirectory")
    if backup_directory:
        print(f"Backup directory: {backup_directory}")
    print(f"Output directory: {output_directory}")
    print(f"Jobs: {response['jobCount']}")
    print(f"Locations: {response['locationCount']}")
    print(f"Duplicates removed: {response['duplicatesRemoved']}")
    provider_statuses = response.get("providerStatuses", {})
    if provider_statuses:
        print("Providers:")
        for provider, status in provider_statuses.items():
            print(f"  {provider}: {status}")
    warnings = response.get("warnings", [])
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("Warnings: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
