#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.docker.stack_config import stack_for
from scripts.lib.project_paths import INFRASTRUCTURE_ROOT, WORKSPACE_ROOT

DATASET_ID = "uk-software-developer-demo"
DATASET_VERSION = "1.1.0"
SCENARIO = "DEMO_READY"


def run(command: list[str]) -> None:
    print(" ".join(command))
    result = subprocess.run(command, cwd=INFRASTRUCTURE_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def dataset_path() -> Path:
    return (
        WORKSPACE_ROOT
        / "system-data-service"
        / "fixtures"
        / "datasets"
        / DATASET_ID
        / DATASET_VERSION
    )


def dataset_summary() -> dict[str, object]:
    jobs_path = dataset_path() / "jobs.json"
    locations_path = dataset_path() / "locations.json"
    if not jobs_path.exists():
        return {
            "available": False,
            "jobCount": None,
            "locationCount": None,
            "providers": {},
        }
    jobs = json.loads(jobs_path.read_text(encoding="utf-8")).get("jobs", [])
    locations = json.loads(locations_path.read_text(encoding="utf-8")).get("locations", []) if locations_path.exists() else []
    providers = Counter(job.get("sourceProvider") for job in jobs if job.get("sourceProvider"))
    return {
        "available": True,
        "jobCount": len(jobs),
        "locationCount": len(locations),
        "providers": dict(providers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the isolated E2E/demo environment.")
    parser.add_argument("--skip-start", action="store_true", help="Assume the E2E stack is already running.")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip fixture smoke checks.")
    args = parser.parse_args()

    stack = stack_for("e2e")
    if stack.frontend_url.endswith(":3000"):
        raise RuntimeError("Refusing to prepare demo environment against live frontend port 3000")
    if stack.project != "job-seeker-copilot-e2e":
        raise RuntimeError(f"Refusing unexpected compose project: {stack.project}")

    if not args.skip_start:
        run([sys.executable, "-m", "scripts.docker.start_stack", "e2e"])
    run([sys.executable, "-m", "scripts.docker.wait_for_stack", "e2e"])
    run([sys.executable, "-m", "scripts.demo.check_fixture_modes"])

    summary = dataset_summary()
    run([
        sys.executable,
        "-m",
        "scripts.data.reset_and_seed_environment",
        "--service-url",
        stack.system_data_url,
        "--scenario",
        SCENARIO,
        "--dataset-id",
        DATASET_ID,
        "--dataset-version",
        DATASET_VERSION,
        "--yes",
    ])
    if not args.skip_smoke:
        run([sys.executable, "-m", "scripts.demo.smoke_test_fixtures"])

    print()
    print("E2E/demo environment ready")
    print(f"E2E frontend URL: {stack.frontend_url}")
    print(f"System data service URL: {stack.system_data_url}")
    print("Demo user: alex.taylor92@example.com")
    print(f"Dataset: {DATASET_ID} {DATASET_VERSION}")
    if summary["available"]:
        print(f"Provider counts: {summary['providers']}")
        print(f"Job count: {summary['jobCount']}")
        print(f"Location count: {summary['locationCount']}")
    else:
        print(
            "Local dataset summary unavailable; the System Data reset and "
            "verification remain authoritative."
        )
    print(f"Scenario: {SCENARIO}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
