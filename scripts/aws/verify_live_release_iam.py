#!/usr/bin/env python3
"""Fail closed on live IAM state that Terraform planning cannot safely prove.

The protected release role can pass only a reserved set of workload roles. IAM
does not support applying a permissions-boundary condition to ``PassRole``, so
an account administrator must not be able to leave a colliding role for the
release workflow to pass. This verifier binds every existing reserved role to
the exact boundary and trust policy in the reviewed Terraform plan before any
plan is applied.

AWS Backup managed policies are also outside this repository's control. Their
reviewed default versions and required allow statements are rechecked on every
protected release before Terraform can attach them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote


class LiveIamContractError(ValueError):
    """The live account differs from the reviewed release contract."""


JsonObject = dict[str, Any]


def load_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveIamContractError(f"JSON root must be an object: {path}")
    return value


def normalize_policy(value: Any) -> Any:
    """Return a stable semantic representation of an IAM policy document."""
    if isinstance(value, str):
        decoded = unquote(value)
        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise LiveIamContractError("IAM trust/policy document is not valid JSON") from exc

    return normalize_policy_value(value)


def normalize_policy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_policy_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [normalize_policy_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return value


def iter_modules(module: JsonObject):
    yield module
    for child in module.get("child_modules", []):
        if not isinstance(child, dict):
            raise LiveIamContractError("Terraform child module must be an object")
        yield from iter_modules(child)


def planned_roles(plan: JsonObject) -> dict[str, JsonObject]:
    root = plan.get("planned_values", {}).get("root_module")
    if not isinstance(root, dict):
        raise LiveIamContractError("Terraform plan omits planned_values.root_module")

    result: dict[str, JsonObject] = {}
    for module in iter_modules(root):
        for resource in module.get("resources", []):
            if not isinstance(resource, dict) or resource.get("type") != "aws_iam_role":
                continue
            values = resource.get("values")
            if not isinstance(values, dict):
                raise LiveIamContractError("planned IAM role omits values")
            name = values.get("name")
            boundary = values.get("permissions_boundary")
            trust = values.get("assume_role_policy")
            if not isinstance(name, str) or not name.startswith("jsc-public-beta-"):
                raise LiveIamContractError("planned workload role has a non-reserved or unknown name")
            if not isinstance(boundary, str) or not boundary.startswith("arn:aws:iam::"):
                raise LiveIamContractError(f"planned role {name} has no exact permissions boundary")
            if trust is None:
                raise LiveIamContractError(f"planned role {name} has no exact trust policy")
            if name in result:
                raise LiveIamContractError(f"duplicate planned IAM role name: {name}")
            result[name] = {
                "boundary": boundary,
                "trust": normalize_policy(trust),
            }
    if not result:
        raise LiveIamContractError("Terraform plan contains no reserved workload roles")
    return result


def is_wildcard_passrole_name(name: str) -> bool:
    return (
        name.startswith("jsc-public-beta-")
        and (name.endswith("-task") or name.endswith("-execution"))
    )


def verify_roles(
    plan: JsonObject,
    live: JsonObject,
    role_reader: Callable[[str], JsonObject] | None = None,
) -> None:
    expected = planned_roles(plan)
    if live.get("IsTruncated") is True or live.get("Marker"):
        raise LiveIamContractError("IAM ListRoles response is incomplete")
    roles = live.get("Roles")
    if not isinstance(roles, list):
        raise LiveIamContractError("IAM ListRoles response omits Roles")

    seen: set[str] = set()
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("RoleName"), str):
            raise LiveIamContractError("IAM ListRoles returned a malformed role")
        name = role["RoleName"]
        if is_wildcard_passrole_name(name) and name not in expected:
            raise LiveIamContractError(f"unexpected reserved PassRole collision: {name}")
        if name not in expected:
            continue
        seen.add(name)
        # IAM ListRoles deliberately omits PermissionsBoundary. Resolve the
        # complete role before comparing an existing reserved name; tests may
        # pass an already-complete role object by omitting the reader.
        complete_role = role_reader(name) if role_reader is not None else role
        if not isinstance(complete_role, dict) or complete_role.get("RoleName") != name:
            raise LiveIamContractError(f"IAM GetRole returned a malformed or mismatched role: {name}")
        boundary = complete_role.get("PermissionsBoundary")
        actual_boundary = boundary.get("PermissionsBoundaryArn") if isinstance(boundary, dict) else None
        if actual_boundary != expected[name]["boundary"]:
            raise LiveIamContractError(f"reserved role has the wrong permissions boundary: {name}")
        if normalize_policy(complete_role.get("AssumeRolePolicyDocument")) != expected[name]["trust"]:
            raise LiveIamContractError(f"reserved role has the wrong trust policy: {name}")

    # Planned roles absent from ListRoles are legitimate creates. Existing
    # planned roles have all been checked above; no wildcard collision can be
    # silently ignored.
    _ = seen


def allowed_statements(document: Any) -> list[JsonObject]:
    normalized = normalize_policy(document)
    if not isinstance(normalized, dict):
        raise LiveIamContractError("AWS managed-policy document is not an object")
    statements = normalized.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not all(isinstance(item, dict) for item in statements):
        raise LiveIamContractError("AWS managed-policy Statement is malformed")
    return [statement for statement in statements if statement.get("Effect") == "Allow"]


def action_set(statements: list[JsonObject]) -> set[str]:
    actions: set[str] = set()
    for statement in statements:
        value = statement.get("Action", [])
        if isinstance(value, str):
            actions.add(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            actions.update(value)
        else:
            raise LiveIamContractError("AWS managed-policy Action is malformed")
    return actions


def aws_json(arguments: list[str]) -> JsonObject:
    result = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "AWS CLI returned no diagnostic"
        raise LiveIamContractError(f"AWS IAM read failed: {message}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LiveIamContractError("AWS IAM read returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LiveIamContractError("AWS IAM read returned a non-object")
    return value


def verify_backup_policies(
    contract: JsonObject,
    reader: Callable[[list[str]], JsonObject] = aws_json,
) -> None:
    policies = contract.get("contracts")
    if not isinstance(policies, dict) or len(policies) != 4:
        raise LiveIamContractError("backup managed-policy contract must contain exactly four policies")

    for name, policy_contract in policies.items():
        if not isinstance(policy_contract, dict):
            raise LiveIamContractError(f"backup policy contract is malformed: {name}")
        arn = policy_contract.get("policyArn")
        reviewed_version = policy_contract.get("reviewedDefaultVersion")
        required_sids = policy_contract.get("requiredSids")
        required_actions = policy_contract.get("requiredActions")
        if (
            not isinstance(arn, str)
            or not isinstance(reviewed_version, str)
            or not isinstance(required_sids, list)
            or not all(isinstance(item, str) for item in required_sids)
            or not isinstance(required_actions, list)
            or not all(isinstance(item, str) for item in required_actions)
        ):
            raise LiveIamContractError(f"backup policy contract fields are invalid: {name}")

        metadata = reader(["iam", "get-policy", "--policy-arn", arn])
        actual_version = metadata.get("Policy", {}).get("DefaultVersionId")
        if actual_version != reviewed_version:
            raise LiveIamContractError(
                f"AWS managed policy default version drifted for {name}: "
                f"reviewed={reviewed_version}, live={actual_version}"
            )
        version = reader([
            "iam", "get-policy-version", "--policy-arn", arn,
            "--version-id", reviewed_version,
        ])
        statements = allowed_statements(version.get("PolicyVersion", {}).get("Document"))
        actual_sids = {statement.get("Sid") for statement in statements if isinstance(statement.get("Sid"), str)}
        missing_sids = sorted(set(required_sids) - actual_sids)
        missing_actions = sorted(set(required_actions) - action_set(statements))
        if missing_sids or missing_actions:
            raise LiveIamContractError(
                f"AWS managed policy document drifted for {name}: "
                f"missingSids={missing_sids}, missingActions={missing_actions}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--backup-contract", type=Path, required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    try:
        plan = load_json(args.plan_json)
        roles = aws_json(["iam", "list-roles", "--region", args.region])

        def read_role(name: str) -> JsonObject:
            result = aws_json(["iam", "get-role", "--role-name", name, "--region", args.region])
            role = result.get("Role")
            if not isinstance(role, dict):
                raise LiveIamContractError(f"IAM GetRole response omits Role: {name}")
            return role

        verify_roles(plan, roles, read_role)
        verify_backup_policies(load_json(args.backup_contract))
    except (OSError, json.JSONDecodeError, LiveIamContractError) as exc:
        print(f"Live release IAM verification failed: {exc}", file=sys.stderr)
        return 3
    print("Verified reserved IAM roles and four reviewed AWS Backup managed policies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
