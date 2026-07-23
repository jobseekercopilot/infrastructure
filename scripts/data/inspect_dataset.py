#!/usr/bin/env python3

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a generated system-data dataset.")
    parser.add_argument("--dataset-path", required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset_path)
    try:
        manifest = read_json(dataset_path / "manifest.json")
        jobs_file = read_json(dataset_path / "jobs.json")
        locations_file = read_json(dataset_path / "locations.json")
        report = read_json(dataset_path / "generation-report.json")
    except FileNotFoundError as error:
        print(f"Missing dataset file: {error.filename}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"Invalid JSON: {error}", file=sys.stderr)
        return 1

    jobs = jobs_file.get("jobs", [])
    providers = Counter(job.get("sourceProvider") for job in jobs if job.get("sourceProvider"))
    companies = {job.get("companyName") for job in jobs if job.get("companyName")}
    locations = {job.get("locationName") for job in jobs if job.get("locationName")}
    salary_count = sum(1 for job in jobs if job.get("salaryMinimum") is not None or job.get("salaryMaximum") is not None)
    remote_counts = Counter(job.get("remoteType") or "UNKNOWN" for job in jobs)
    unsuitable_count = sum(1 for job in jobs if job.get("suitableForDemo") is False)
    invalid_removed = report.get("invalidRecordsRemoved", 0)
    duplicates_removed = report.get("duplicatesRemoved", 0)
    location_records = locations_file.get("locations", [])

    print(f"Dataset ID: {manifest.get('datasetId')}")
    print(f"Version: {manifest.get('version')}")
    print(f"Created at: {manifest.get('createdAt')}")
    print(f"Total jobs: {len(jobs)}")
    print(f"Providers represented: {dict(providers)}")
    print(f"Companies represented: {len(companies)}")
    print(f"Locations represented: {len(locations)}")
    print(f"Jobs with salaries: {salary_count}")
    print(f"Remote types: {dict(remote_counts)}")
    print(f"Location records: {len(location_records)}")
    print(f"Invalid records removed: {invalid_removed}")
    print(f"Unsuitable records retained: {unsuitable_count}")
    print(f"Duplicates removed: {duplicates_removed}")
    warnings = report.get("warnings") or manifest.get("warnings") or []
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("Warnings: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
