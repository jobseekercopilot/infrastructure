#!/usr/bin/env python3
"""Reject destructive Cloud Map changes before a protected saved plan is applied."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class SavedReleasePlanError(ValueError):
    """The saved release plan contains an unsafe or malformed change."""


def load_plan(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SavedReleasePlanError("Terraform plan root must be an object")
    return value


def verify_no_cloud_map_service_destruction(plan: dict[str, Any]) -> None:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise SavedReleasePlanError("Terraform plan omits resource_changes")

    destructive: list[str] = []
    for resource in changes:
        if not isinstance(resource, dict):
            raise SavedReleasePlanError("Terraform resource change must be an object")
        address = resource.get("address")
        resource_type = resource.get("type")
        change = resource.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if (
            not isinstance(address, str)
            or not isinstance(resource_type, str)
            or not isinstance(actions, list)
            or not all(isinstance(action, str) for action in actions)
        ):
            raise SavedReleasePlanError("Terraform resource change is malformed")
        if resource_type not in {
            "aws_service_discovery_private_dns_namespace",
            "aws_service_discovery_service",
        }:
            continue
        if "delete" in actions:
            destructive.append(address)

    if destructive:
        joined = ", ".join(sorted(destructive))
        raise SavedReleasePlanError(
            "Cloud Map namespace/service deletion or replacement requires reviewed manual cleanup; "
            f"refusing saved plan: {joined}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify_no_cloud_map_service_destruction(load_plan(args.plan_json))
    except (OSError, json.JSONDecodeError, SavedReleasePlanError) as exc:
        print(f"Saved release plan verification failed: {exc}", file=sys.stderr)
        return 3
    print("Verified saved release plan contains no Cloud Map service destruction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
