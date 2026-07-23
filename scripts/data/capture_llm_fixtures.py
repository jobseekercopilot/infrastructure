#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture one live CV and cover-letter response through llm-gateway.")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--llm-gateway-url", default="http://localhost:9113")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--yes", action="store_true", help="Confirm live LLM token usage.")
    return parser.parse_args()


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with HTTP {error.code}: {detail}") from error


def prompt(kind: str, job: dict[str, Any]) -> str:
    document = "tailored CV" if kind == "CV_GENERATION" else "tailored cover letter"
    return f"""
You are writing a polished UK job application document for demo user Alex Taylor.

Create exactly one {document}.

Alex Taylor profile:
- Software Developer at BrightTech Solutions, 2021-07 to present.
- Software Engineering Intern at CodeBridge Ltd, 2020-06 to 2020-08.
- BSc Computer Science, University of Birmingham.
- Skills: Java, Spring Boot, Angular, TypeScript, SQL, PostgreSQL, REST APIs, Git, Docker, Microservices.
- Tone: professional, specific, credible, concise.
- Do not invent employers, certifications, degrees, or unverifiable claims.

Target job:
- ID: {job.get('id')}
- Provider: {job.get('sourceProvider')}
- Title: {job.get('title')}
- Company: {job.get('companyName')}
- Location: {job.get('locationName')}
- Salary: {job.get('salaryMinimum')} to {job.get('salaryMaximum')} {job.get('salaryCurrency') or 'GBP'}
- Description: {job.get('description')}

Return the final {document} only, in markdown-friendly plain text with clear section headings.
""".strip()


def fixture_key(operation: str, job_id: str) -> str:
    return f"DEMO_READY:ALEX_TAYLOR:{operation}:{job_id}"


def validate_response(operation: str, response: dict[str, Any]) -> None:
    content = response.get("response") or ""
    if len(content.strip()) < 500:
        raise RuntimeError(f"{operation} response was too short to use as a demo fixture.")
    if "Alex Taylor" not in content:
        raise RuntimeError(f"{operation} response did not mention Alex Taylor.")
    usage = response.get("usage") or {}
    if not usage.get("totalTokens"):
        raise RuntimeError(f"{operation} response did not include total token usage.")


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset_path)
    if not args.yes:
        print("Refusing to make live LLM calls without --yes.", file=sys.stderr)
        return 2

    mode = get_json(f"{args.llm_gateway_url.rstrip('/')}/internal/provider-mode")
    if mode.get("mode") != "LIVE" or mode.get("externalCallsEnabled") is not True:
        print(f"llm-gateway is not in LIVE mode: {mode}", file=sys.stderr)
        return 2
    print(f"llm-gateway live mode confirmed provider metadata endpoint reports mode={mode.get('mode')}")

    jobs = json.loads((dataset_path / "jobs.json").read_text())["jobs"]
    job = next((candidate for candidate in jobs if candidate.get("id") == args.job_id), None)
    if job is None:
        print(f"Job not found in dataset: {args.job_id}", file=sys.stderr)
        return 2

    fixtures: dict[str, Any] = {}
    total_tokens = 0
    for operation in ("CV_GENERATION", "COVER_LETTER_GENERATION"):
        payload = {
            "taskType": operation,
            "prompt": prompt(operation, job),
            "temperature": 0.3,
            "maxTokens": 2500,
        }
        response = post_json(f"{args.llm_gateway_url.rstrip('/')}/api/v1/generate", payload)
        validate_response(operation, response)
        usage = response.get("usage") or {}
        key = fixture_key(operation, args.job_id)
        total_tokens += int(usage.get("totalTokens") or 0)
        fixtures[key] = {
            "provider": response.get("provider"),
            "model": response.get("model"),
            "response": response.get("response"),
            "inputTokens": usage.get("inputTokens") or 0,
            "outputTokens": usage.get("outputTokens") or 0,
            "totalTokens": usage.get("totalTokens") or 0,
            "finishReason": "stop",
            "createdAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "fixtureKey": key,
            "fixtureMode": True,
            "scenario": "DEMO_READY",
            "userId": "08f6daa3-8f21-38ce-aed6-0e090bad5d77",
            "jobId": args.job_id,
            "operation": operation,
            "sourceMode": "LIVE_CAPTURED_FIXTURE",
        }
        print(f"{operation}: provider={response.get('provider')} model={response.get('model')} totalTokens={usage.get('totalTokens')}")

    fixture_path = dataset_path / "llm-fixtures.json"
    fixture_path.write_text(json.dumps(fixtures, indent=2) + "\n")
    print(f"Fixture file: {fixture_path}")
    print(f"Total live LLM tokens: {total_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
