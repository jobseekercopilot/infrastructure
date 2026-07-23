"""Small stdlib HTTP client helpers for system-data environment scripts."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(method: str, service_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = service_url.rstrip("/") + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach system-data-service at {url}: {error.reason}") from error


def print_operation(response: dict[str, Any]) -> None:
    print(f"Operation: {response.get('operationId')}")
    print(f"Scenario: {response.get('scenario')}")
    print(f"Status: {response.get('status')}")
    print("Services:")
    for service in response.get("services", []):
        print(
            f"  {service.get('service')}: {service.get('operation')} "
            f"{service.get('status')} records={service.get('recordsAffected')}"
        )
        for warning in service.get("warnings", []):
            print(f"    warning: {warning}")
        details = service.get("details") or {}
        if details:
            print(f"    details: {details}")
    summary = response.get("summary") or {}
    if summary:
        print("Summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
    for warning in response.get("warnings", []):
        print(f"Warning: {warning}")


def fail_if_unsuccessful(response: dict[str, Any]) -> int:
    return 0 if response.get("status") == "SUCCESS" else 1


def confirm_or_exit(prompt: str, yes: bool) -> None:
    if yes:
        return
    answer = input(f"{prompt} Type 'yes' to continue: ")
    if answer.strip().lower() != "yes":
        raise SystemExit("Aborted.")
