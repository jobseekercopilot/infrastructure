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

The retained RDS monitoring permissions boundary is bootstrap-owned rather
than Terraform-owned. Its live default policy is therefore compared with the
exact reviewed RDSOSMetrics document before any Terraform plan can be applied.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote


class LiveIamContractError(ValueError):
    """The live account differs from the reviewed release contract."""


JsonObject = dict[str, Any]
RDS_MONITORING_ROLE_NAME = "jsc-public-beta-rds-monitoring"
RDS_MONITORING_BOUNDARY_NAME = "jsc-public-beta-rds-monitoring-boundary"
LEGACY_WORKLOAD_BOUNDARY_NAME = "jsc-public-beta-workload-boundary"
RDS_MONITORING_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"


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


def is_exact_rds_monitoring_migration_state(
    actual_boundary: Any,
    actual_trust: Any,
    expected_role: JsonObject,
) -> bool:
    """Recognise only the one reviewed, one-way RDS role migration state.

    The first foundation reconciliation after introducing the dedicated
    RDSOSMetrics boundary must be able to replace the old common boundary and
    wildcard database trust. The AWS provider updates trust before it updates
    a role boundary, so an interrupted apply may also leave the old boundary
    with the already-narrowed exact trust. Only those two states are accepted,
    and the release script performs the verifier again without this exception
    after Terraform applies the migration.
    """
    expected_boundary = expected_role.get("boundary")
    expected_trust = expected_role.get("trust")
    if not isinstance(expected_boundary, str) or not isinstance(expected_trust, dict):
        return False

    boundary_match = re.fullmatch(
        rf"arn:aws:iam::([0-9]{{12}}):policy/{re.escape(RDS_MONITORING_BOUNDARY_NAME)}",
        expected_boundary,
    )
    if boundary_match is None:
        return False

    statements = expected_trust.get("Statement")
    if not isinstance(statements, list) or len(statements) != 1 or not isinstance(statements[0], dict):
        return False
    statement = statements[0]
    condition = statement.get("Condition")
    if not isinstance(condition, dict):
        return False
    source_account = condition.get("StringEquals", {}).get("aws:SourceAccount")
    source_arn = condition.get("ArnEquals", {}).get("aws:SourceArn")
    if (
        not isinstance(source_account, str)
        or source_account != boundary_match.group(1)
        or not isinstance(source_arn, str)
        or source_arn != f"arn:aws:rds:eu-west-2:{source_account}:db:jsc-public-beta-postgres"
    ):
        return False

    reviewed_trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "monitoring.rds.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": source_account},
                "ArnEquals": {"aws:SourceArn": source_arn},
            },
        }],
    }
    if expected_trust != normalize_policy(reviewed_trust):
        return False

    legacy_boundary = expected_boundary.removesuffix(RDS_MONITORING_BOUNDARY_NAME) + LEGACY_WORKLOAD_BOUNDARY_NAME
    legacy_trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "monitoring.rds.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": source_account},
                "ArnLike": {"aws:SourceArn": f"arn:aws:rds:eu-west-2:{source_account}:db:*"},
            },
        }],
    }
    normalized_actual_trust = normalize_policy(actual_trust)
    return actual_boundary == legacy_boundary and normalized_actual_trust in (
        normalize_policy(legacy_trust),
        normalize_policy(reviewed_trust),
    )


def verify_roles(
    plan: JsonObject,
    live: JsonObject,
    role_reader: Callable[[str], JsonObject] | None = None,
    allow_rds_monitoring_migration: bool = False,
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
        if (
            allow_rds_monitoring_migration
            and name == RDS_MONITORING_ROLE_NAME
            and is_exact_rds_monitoring_migration_state(
                actual_boundary,
                complete_role.get("AssumeRolePolicyDocument"),
                expected[name],
            )
        ):
            continue
        if actual_boundary != expected[name]["boundary"]:
            raise LiveIamContractError(f"reserved role has the wrong permissions boundary: {name}")
        if normalize_policy(complete_role.get("AssumeRolePolicyDocument")) != expected[name]["trust"]:
            raise LiveIamContractError(f"reserved role has the wrong trust policy: {name}")

    # Planned roles absent from ListRoles are legitimate creates. Existing
    # planned roles have all been checked above; no wildcard collision can be
    # silently ignored.
    _ = seen


def verify_rds_monitoring_policies(attached: JsonObject, inline: JsonObject) -> None:
    if attached.get("IsTruncated") is True or attached.get("Marker"):
        raise LiveIamContractError("RDS monitoring attached-policy response is incomplete")
    policies = attached.get("AttachedPolicies")
    if not isinstance(policies, list) or not all(isinstance(item, dict) for item in policies):
        raise LiveIamContractError("RDS monitoring attached-policy response is malformed")
    actual_arns = {item.get("PolicyArn") for item in policies}
    if actual_arns != {RDS_MONITORING_POLICY_ARN}:
        raise LiveIamContractError("RDS monitoring role does not have exactly the reviewed managed policy")

    if inline.get("IsTruncated") is True or inline.get("Marker"):
        raise LiveIamContractError("RDS monitoring inline-policy response is incomplete")
    policy_names = inline.get("PolicyNames")
    if not isinstance(policy_names, list) or not all(isinstance(item, str) for item in policy_names):
        raise LiveIamContractError("RDS monitoring inline-policy response is malformed")
    if policy_names:
        raise LiveIamContractError("RDS monitoring role has an unexpected inline policy")


def expected_rds_monitoring_boundary(account_id: str) -> JsonObject:
    log_group_arn = f"arn:aws:logs:eu-west-2:{account_id}:log-group:RDSOSMetrics"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ManageOnlyRdsOsMetricsLogGroup",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:PutRetentionPolicy",
                ],
                "Resource": log_group_arn,
            },
            {
                "Sid": "WriteOnlyRdsOsMetricsLogStreams",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogStream",
                    "logs:DescribeLogStreams",
                    "logs:GetLogEvents",
                    "logs:PutLogEvents",
                ],
                "Resource": f"{log_group_arn}:log-stream:*",
            },
        ],
    }


def verify_rds_monitoring_boundary(
    plan: JsonObject,
    reader: Callable[[list[str]], JsonObject] | None = None,
) -> None:
    """Prove the bootstrap-owned live boundary is the exact reviewed policy."""
    if reader is None:
        reader = aws_json
    role = planned_roles(plan).get(RDS_MONITORING_ROLE_NAME)
    if not isinstance(role, dict):
        raise LiveIamContractError("Terraform plan omits the RDS monitoring role")
    boundary_arn = role.get("boundary")
    if not isinstance(boundary_arn, str):
        raise LiveIamContractError("planned RDS monitoring role omits its boundary")
    boundary_match = re.fullmatch(
        rf"arn:aws:iam::([0-9]{{12}}):policy/{re.escape(RDS_MONITORING_BOUNDARY_NAME)}",
        boundary_arn,
    )
    if boundary_match is None:
        raise LiveIamContractError("planned RDS monitoring boundary ARN is not exact")

    metadata = reader(["iam", "get-policy", "--policy-arn", boundary_arn])
    policy = metadata.get("Policy")
    if not isinstance(policy, dict):
        raise LiveIamContractError("RDS monitoring boundary metadata omits Policy")
    default_version = policy.get("DefaultVersionId")
    if (
        policy.get("Arn") != boundary_arn
        or policy.get("PolicyName") != RDS_MONITORING_BOUNDARY_NAME
        or policy.get("IsAttachable") is not True
        or not isinstance(default_version, str)
        or re.fullmatch(r"v[1-9][0-9]*", default_version) is None
    ):
        raise LiveIamContractError("RDS monitoring boundary metadata is not exact")

    version = reader([
        "iam", "get-policy-version", "--policy-arn", boundary_arn,
        "--version-id", default_version,
    ])
    policy_version = version.get("PolicyVersion")
    if (
        not isinstance(policy_version, dict)
        or policy_version.get("VersionId") != default_version
        or policy_version.get("IsDefaultVersion") is not True
    ):
        raise LiveIamContractError("RDS monitoring boundary default version is not exact")
    expected_document = expected_rds_monitoring_boundary(boundary_match.group(1))
    if normalize_policy(policy_version.get("Document")) != normalize_policy(expected_document):
        raise LiveIamContractError("RDS monitoring boundary policy document drifted")


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
    parser.add_argument("--allow-rds-monitoring-migration", action="store_true")
    args = parser.parse_args()
    try:
        plan = load_json(args.plan_json)
        verify_rds_monitoring_boundary(plan)
        roles = aws_json(["iam", "list-roles", "--region", args.region])

        def read_role(name: str) -> JsonObject:
            result = aws_json(["iam", "get-role", "--role-name", name, "--region", args.region])
            role = result.get("Role")
            if not isinstance(role, dict):
                raise LiveIamContractError(f"IAM GetRole response omits Role: {name}")
            return role

        verify_roles(
            plan,
            roles,
            read_role,
            allow_rds_monitoring_migration=args.allow_rds_monitoring_migration,
        )
        live_role_names = {
            role.get("RoleName")
            for role in roles.get("Roles", [])
            if isinstance(role, dict)
        }
        if RDS_MONITORING_ROLE_NAME in live_role_names:
            verify_rds_monitoring_policies(
                aws_json([
                    "iam", "list-attached-role-policies",
                    "--role-name", RDS_MONITORING_ROLE_NAME,
                    "--region", args.region,
                ]),
                aws_json([
                    "iam", "list-role-policies",
                    "--role-name", RDS_MONITORING_ROLE_NAME,
                    "--region", args.region,
                ]),
            )
        verify_backup_policies(load_json(args.backup_contract))
    except (OSError, json.JSONDecodeError, LiveIamContractError) as exc:
        print(f"Live release IAM verification failed: {exc}", file=sys.stderr)
        return 3
    print(
        "Verified the RDS monitoring boundary, reserved IAM roles, RDS monitoring "
        "policy scope and four reviewed AWS Backup policies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
