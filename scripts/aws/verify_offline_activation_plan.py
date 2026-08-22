#!/usr/bin/env python3
"""Verify the rendered account-free public activation plan, not just its exit code."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ActivationPlanError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ActivationPlanError(message)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"{path}: expected a JSON object")
    return value


def flatten_resources(module: dict[str, Any]) -> list[dict[str, Any]]:
    resources = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        resources.extend(flatten_resources(child))
    return resources


def one(resources: list[dict[str, Any]], address: str) -> dict[str, Any]:
    matches = [resource for resource in resources if resource.get("address") == address]
    require(len(matches) == 1, f"activation plan needs exactly one {address}; found {len(matches)}")
    return matches[0]


def one_change(plan: dict[str, Any], address: str) -> dict[str, Any]:
    changes = plan.get("resource_changes", [])
    matches = [change for change in changes if change.get("address") == address]
    require(len(matches) == 1, f"activation plan needs exactly one change for {address}; found {len(matches)}")
    return matches[0]


def indexed_names(resources: list[dict[str, Any]], resource_type: str, name: str) -> set[str]:
    return {
        str(resource["index"])
        for resource in resources
        if resource.get("type") == resource_type and resource.get("name") == name and "index" in resource
    }


def verify_activation_plan(plan: dict[str, Any], runtime: dict[str, Any]) -> None:
    expected_services = set(runtime.get("services", {}))
    require(len(expected_services) == 27, f"runtime contract must contain 27 services; found {len(expected_services)}")
    require("system-data-service" not in expected_services, "System Data must not be a production runtime service")
    require(all("fixture" not in name.lower() for name in expected_services), "fixture service leaked into runtime contract")

    planned = plan.get("planned_values", {}).get("root_module")
    require(isinstance(planned, dict), "Terraform plan has no planned root module")
    resources = flatten_resources(planned)

    service_names = indexed_names(resources, "aws_ecs_service", "service")
    task_names = indexed_names(resources, "aws_ecs_task_definition", "service")
    require(service_names == expected_services, "planned ECS service set differs from the exact 27-service runtime contract")
    require(task_names == expected_services, "planned ECS task-definition set differs from the exact runtime contract")
    for service in expected_services:
        resource = one(resources, f'aws_ecs_service.service["{service}"]')
        require(resource.get("values", {}).get("desired_count") == 1, f"{service}: desired_count is not one")

    clamav_service = one(resources, "aws_ecs_service.clamav")
    require(clamav_service.get("values", {}).get("desired_count") == 1, "ClamAV desired_count is not one")
    one(resources, "aws_ecs_task_definition.clamav")
    for operator_task in ("database_bootstrap", "migration_verification", "release_preflight"):
        one(resources, f"aws_ecs_task_definition.{operator_task}")

    https = one(resources, "aws_lb_listener.https[0]").get("values", {})
    require(https.get("protocol") == "HTTPS" and https.get("port") == 443, "public HTTPS listener is absent")
    actions = https.get("default_action", [])
    require(len(actions) == 1 and actions[0].get("type") == "forward", "HTTPS listener is not forwarding to the frontend")

    webhook = one(resources, "aws_lb_listener_rule.stripe_webhook[0]").get("values", {})
    webhook_actions = webhook.get("action", [])
    require(len(webhook_actions) == 1 and webhook_actions[0].get("type") == "forward",
            "Stripe webhook rule is not an exact forward rule")
    conditions = webhook.get("condition", [])
    paths = {
        value
        for condition in conditions
        for block in condition.get("path_pattern", [])
        for value in block.get("values", [])
    }
    methods = {
        value
        for condition in conditions
        for block in condition.get("http_request_method", [])
        for value in block.get("values", [])
    }
    require(paths == {"/api/v1/stripe/webhook"}, "Stripe webhook path is not exact")
    require(methods == {"POST"}, "Stripe webhook method is not exactly POST")
    one(resources, "aws_route53_record.app[0]")
    one(resources, "aws_wafv2_web_acl_association.app")

    release_contract = one(resources, "terraform_data.release_contract").get("values", {}).get("input", {})
    approvals = release_contract.get("approvals", {})
    require(approvals and all(value is True for value in approvals.values()),
            "synthetic activation approvals are not fully satisfied")
    attestations = one(resources, "terraform_data.runtime_attestations").get("values", {}).get("input", {})
    require(attestations.get("database_bootstrap") == "offline-validation-only",
            "offline DB bootstrap attestation was not isolated")
    require(attestations.get("release_preflight") == "offline-validation-only",
            "offline release preflight attestation was not isolated")

    variables = plan.get("variables", {})
    require(
        variables.get("foundation_data_kms_key_arn", {}).get("value")
        == "arn:aws:kms:eu-west-2:000000000000:key/00000000-0000-0000-0000-000000000000",
        "offline plan did not consume the isolated bootstrap data-key sentinel",
    )
    require(
        variables.get("foundation_operations_topic_arn", {}).get("value")
        == "arn:aws:sns:eu-west-2:000000000000:jsc-public-beta-operations",
        "offline plan did not consume the isolated bootstrap operations-topic sentinel",
    )
    require(
        variables.get("foundation_erasure_journal_kms_key_arn", {}).get("value")
        == "arn:aws:kms:eu-west-2:000000000000:key/11111111-1111-1111-1111-111111111111",
        "offline plan did not consume the isolated erasure-journal key sentinel",
    )
    require(
        variables.get("foundation_erasure_journal_bucket_name", {}).get("value")
        == "jsc-public-beta-erasure-journal-000000000000",
        "offline plan did not consume the isolated erasure-journal bucket sentinel",
    )
    require(
        variables.get("foundation_erasure_journal_retention_days", {}).get("value") == 90,
        "offline plan did not bind the reviewed erasure-journal retention",
    )
    require(
        variables.get("foundation_approved_ecs_ami_id", {}).get("value") == "ami-00000000000000000",
        "offline plan did not bind the bootstrap-approved ECS AMI sentinel",
    )
    require(
        variables.get("foundation_monthly_alert_budget_usd", {}).get("value") == 750
        and variables.get("monthly_budget_usd", {}).get("value") == 750,
        "offline plan did not bind the exact retained USD 750 foundation alert budget",
    )
    require(
        not any(resource.get("type") == "aws_kms_key" for resource in resources),
        "routine Terraform must not create or control foundation KMS keys",
    )
    require(
        not any(
            resource.get("type") == "aws_s3_bucket"
            and "erasure-journal" in str(resource.get("values", {}).get("bucket", ""))
            for resource in resources
        ),
        "routine Terraform must not create or control the retained erasure journal",
    )
    require(
        not any(resource.get("type", "").startswith("aws_appautoscaling_") for resource in resources),
        "opaque-ID ECS scalable targets must not be controlled by the lean beta apply role",
    )
    backup_selection = one(resources, "aws_backup_selection.customer_data").get("values", {})
    require(
        backup_selection.get("plan_id") == "00000000-0000-0000-0000-000000000000",
        "offline plan did not bind its selection to the isolated bootstrap backup-plan sentinel",
    )

    common_boundary = "arn:aws:iam::000000000000:policy/jsc-public-beta-workload-boundary"
    exact_boundaries = {
        "jsc-public-beta-backup": "arn:aws:iam::000000000000:policy/jsc-public-beta-backup-boundary",
        "jsc-public-beta-backup-restore": "arn:aws:iam::000000000000:policy/jsc-public-beta-backup-restore-boundary",
    }
    iam_roles = [resource for resource in resources if resource.get("type") == "aws_iam_role"]
    require(iam_roles, "activation plan contains no IAM workload roles")
    for role in iam_roles:
        values = role.get("values", {})
        name = values.get("name")
        require(isinstance(name, str) and name.startswith("jsc-public-beta-"),
                f"non-public-beta IAM role leaked into plan: {role.get('address')}")
        expected_boundary = exact_boundaries.get(name, common_boundary)
        require(
            values.get("permissions_boundary") == expected_boundary,
            f"{name}: permissions boundary is not the exact reviewed boundary",
        )
    require(
        set(exact_boundaries).issubset({role.get("values", {}).get("name") for role in iam_roles}),
        "one or more specialised backup IAM roles are absent",
    )

    data_key = "arn:aws:kms:eu-west-2:000000000000:key/00000000-0000-0000-0000-000000000000"
    database = one(resources, "aws_db_instance.postgres").get("values", {})
    for field, expected in {
        "storage_encrypted": True,
        "kms_key_id": data_key,
        "manage_master_user_password": True,
        "master_user_secret_kms_key_id": data_key,
        "publicly_accessible": False,
        "deletion_protection": True,
        "skip_final_snapshot": False,
        "performance_insights_kms_key_id": data_key,
    }.items():
        require(database.get(field) == expected, f"rendered RDS protection differs: {field}")

    secrets = [resource for resource in resources if resource.get("type") == "aws_secretsmanager_secret"]
    require(secrets and all(resource.get("values", {}).get("kms_key_id") == data_key for resource in secrets),
            "not every Terraform-owned secret uses the exact foundation data key")
    log_groups = [resource for resource in resources if resource.get("type") == "aws_cloudwatch_log_group"]
    require(log_groups and all(resource.get("values", {}).get("kms_key_id") == data_key for resource in log_groups),
            "not every CloudWatch log group uses the exact foundation data key")

    launch_template = one(resources, "aws_launch_template.ecs").get("values", {})
    block_devices = launch_template.get("block_device_mappings", [])
    require(len(block_devices) == 1 and len(block_devices[0].get("ebs", [])) == 1,
            "ECS launch template does not render one reviewed encrypted root volume")
    root_volume = block_devices[0]["ebs"][0]
    require(
        root_volume.get("encrypted") in (True, "true") and root_volume.get("kms_key_id") == data_key,
        "ECS root volume does not use the exact foundation data key: "
        f"encrypted={root_volume.get('encrypted')!r}, kms_key_id={root_volume.get('kms_key_id')!r}",
    )

    rendered_resources = json.dumps(resources, sort_keys=True)
    for forbidden_state_reference in (
        "jsc-public-beta-terraform-state",
        "public-beta/terraform.tfstate",
        "terraform-state",
    ):
        require(forbidden_state_reference not in rendered_resources,
                f"workload plan references protected Terraform state: {forbidden_state_reference}")

    require(log_groups and all(resource.get("values", {}).get("retention_in_days") == 30 for resource in log_groups),
            "not every rendered CloudWatch log group has the reviewed 30-day retention")
    access_lifecycle = one(resources, "aws_s3_bucket_lifecycle_configuration.access_logs").get("values", {})
    access_rules = access_lifecycle.get("rule", [])
    require(
        len(access_rules) == 1
        and access_rules[0].get("expiration", [{}])[0].get("days") == 30,
        "rendered ALB/S3 access-log retention differs from the reviewed 30 days",
    )
    document_encryption = one(
        resources, "aws_s3_bucket_server_side_encryption_configuration.documents"
    ).get("values", {})
    encryption_rules = document_encryption.get("rule", [])
    require(
        len(encryption_rules) == 1
        and encryption_rules[0].get("apply_server_side_encryption_by_default", [{}])[0].get("sse_algorithm") == "aws:kms"
        and encryption_rules[0].get("apply_server_side_encryption_by_default", [{}])[0].get("kms_master_key_id")
        == data_key,
        "document bucket is not rendered with the exact foundation SSE-KMS key",
    )
    document_policy_value = one(resources, "aws_s3_bucket_policy.documents").get("values", {}).get("policy")
    if isinstance(document_policy_value, str):
        document_policy = json.loads(document_policy_value)
        document_policy_by_sid = {
            statement.get("Sid"): statement for statement in document_policy.get("Statement", [])
        }
        for sid in (
            "DenyMissingObjectEncryption",
            "DenyWrongObjectEncryptionAlgorithm",
            "DenyMissingObjectKmsKey",
            "DenyWrongObjectKmsKey",
        ):
            statement = document_policy_by_sid.get(sid)
            require(
                isinstance(statement, dict)
                and statement.get("Effect") == "Deny"
                and statement.get("Action") == "s3:PutObject",
                f"rendered document bucket policy lacks {sid}",
            )
    else:
        # The generated bucket ARN is not known until apply, so Terraform may
        # correctly defer the complete policy JSON. Still require the positive
        # plan to create the policy and mark only its rendered value unknown;
        # source-level policy tests independently prove all four exact denies.
        document_policy_change = one_change(plan, "aws_s3_bucket_policy.documents").get("change", {})
        require(
            document_policy_change.get("actions") == ["create"]
            and document_policy_change.get("after_unknown", {}).get("policy") is True,
            "document bucket policy is neither rendered nor a planned generated policy",
        )

    document_task = one(
        resources, 'aws_ecs_task_definition.service["document-store-service"]'
    ).get("values", {})
    document_containers_value = document_task.get("container_definitions")
    expected_document_environment = {
        "DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED": "true",
        "DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED": "true",
        "DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED": "true",
        "DOCUMENT_STORE_ERASURE_JOURNAL_PROVIDER": "s3",
        "DOCUMENT_STORE_ERASURE_JOURNAL_REGION": "eu-west-2",
        "DOCUMENT_STORE_ERASURE_JOURNAL_BUCKET": "jsc-public-beta-erasure-journal-000000000000",
        "DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID": (
            "arn:aws:kms:eu-west-2:000000000000:key/11111111-1111-1111-1111-111111111111"
        ),
        "DOCUMENT_STORE_ERASURE_JOURNAL_CREDENTIALS_PROVIDER": "task-role",
        "DOCUMENT_STORE_ERASURE_JOURNAL_OBJECT_LOCK_ENABLED": "true",
        "DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION": (
            "immutable-erasure-journal-2026-08-15"
        ),
    }
    if isinstance(document_containers_value, str):
        document_containers = json.loads(document_containers_value)
        require(len(document_containers) == 1, "Document Store task must render one application container")
        document_environment = {
            item.get("name"): item.get("value") for item in document_containers[0].get("environment", [])
        }
        for name, expected in expected_document_environment.items():
            require(document_environment.get(name) == expected, f"Document Store journal runtime differs: {name}")
    else:
        # Secret ARNs and other apply-time task inputs can defer the complete
        # container JSON. Require the exact task creation and verify the source
        # runtime contract from which Terraform renders it.
        document_task_change = one_change(
            plan, 'aws_ecs_task_definition.service["document-store-service"]'
        ).get("change", {})
        require(
            document_task_change.get("actions") == ["create"]
            and document_task_change.get("after_unknown", {}).get("container_definitions") is True,
            "Document Store task definition is neither rendered nor a planned generated definition",
        )
        document_environment = runtime.get("services", {}).get("document-store-service", {}).get("environment", {})
        expected_template_environment = {
            **expected_document_environment,
            "DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED": "false",
            "DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED": "false",
            "DOCUMENT_STORE_ERASURE_JOURNAL_REGION": "{{region}}",
            "DOCUMENT_STORE_ERASURE_JOURNAL_BUCKET": "{{erasure_journal_bucket}}",
            "DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID": "{{erasure_journal_kms_key_arn}}",
            "DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION": "UNAPPROVED",
        }
        for name, expected in expected_template_environment.items():
            require(document_environment.get(name) == expected, f"Document Store source runtime differs: {name}")
    for forbidden_name in (
        "DOCUMENT_STORE_ERASURE_JOURNAL_ENDPOINT",
        "DOCUMENT_STORE_ERASURE_JOURNAL_ACCESS_KEY",
        "DOCUMENT_STORE_ERASURE_JOURNAL_SECRET_KEY",
    ):
        require(forbidden_name not in document_environment, f"production journal leaked {forbidden_name}")

    document_iam_value = one(resources, "aws_iam_role_policy.document_store").get("values", {}).get("policy")
    journal_object_arn = "arn:aws:s3:::jsc-public-beta-erasure-journal-000000000000/permanent-erasures/v1/*"
    if isinstance(document_iam_value, str):
        document_iam = json.loads(document_iam_value)
        document_iam_by_sid = {
            statement.get("Sid"): statement for statement in document_iam.get("Statement", [])
        }
        write_journal = document_iam_by_sid.get("WriteOnlyImmutableErasureJournalRecords", {})
        require(
            write_journal.get("Action") == "s3:PutObject"
            and write_journal.get("Resource") == journal_object_arn,
            "Document Store immutable-journal write permission is not exact",
        )
        read_journal = document_iam_by_sid.get("ReadOnlyBoundErasureJournalRecords", {})
        require(
            set(read_journal.get("Action", [])) == {"s3:GetObject", "s3:GetObjectVersion"}
            and read_journal.get("Resource") == journal_object_arn,
            "Document Store journal reconciliation reads are not exact",
        )
        journal_kms = document_iam_by_sid.get("UseOnlyErasureJournalKeyThroughS3", {})
        require(
            set(journal_kms.get("Action", [])) == {"kms:Decrypt", "kms:GenerateDataKey"}
            and journal_kms.get("Resource")
            == "arn:aws:kms:eu-west-2:000000000000:key/11111111-1111-1111-1111-111111111111"
            and journal_kms.get("Condition", {}).get("StringEquals", {}).get("kms:ViaService")
            == "s3.eu-west-2.amazonaws.com"
            and journal_kms.get("Condition", {}).get("StringEquals", {}).get(
                "kms:EncryptionContext:aws:s3:arn"
            ) == "arn:aws:s3:::jsc-public-beta-erasure-journal-000000000000",
            "Document Store journal KMS permission is not S3/bucket constrained",
        )
    else:
        document_iam_change = one_change(plan, "aws_iam_role_policy.document_store").get("change", {})
        require(
            document_iam_change.get("actions") == ["create"]
            and document_iam_change.get("after_unknown", {}).get("policy") is True,
            "Document Store task IAM policy is neither rendered nor a planned generated policy",
        )
    journal_policy_owners = {
        resource.get("address")
        for resource in resources
        if resource.get("type") == "aws_iam_role_policy"
        and "jsc-public-beta-erasure-journal" in str(resource.get("values", {}).get("policy", ""))
    }
    expected_journal_policy_owners = (
        {"aws_iam_role_policy.document_store"} if isinstance(document_iam_value, str) else set()
    )
    require(
        journal_policy_owners == expected_journal_policy_owners,
        "erasure-journal data-plane IAM leaked beyond the Document Store task",
    )

    parameter_group = one(resources, "aws_db_parameter_group.postgres").get("values", {})
    parameters = {parameter.get("name"): str(parameter.get("value")) for parameter in parameter_group.get("parameter", [])}
    for name, value in {
        "log_min_duration_statement": "-1",
        "log_statement": "none",
        "log_parameter_max_length": "0",
        "log_parameter_max_length_on_error": "0",
    }.items():
        require(parameters.get(name) == value, f"rendered PostgreSQL privacy control differs: {name}")

    runtime_json = json.dumps(
        [
            resource
            for resource in resources
            if resource.get("type") in {"aws_ecs_service", "aws_ecs_task_definition"}
        ],
        sort_keys=True,
    ).lower()
    for forbidden in ("system-data-service", "stripe_fixture_", "/internal/fixtures/"):
        require(forbidden not in runtime_json, f"test-only runtime content leaked into production plan: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("runtime_manifest", type=Path)
    args = parser.parse_args()
    try:
        verify_activation_plan(load_json(args.plan), load_json(args.runtime_manifest))
    except (ActivationPlanError, OSError, json.JSONDecodeError) as exc:
        print(f"offline activation plan invalid: {exc}", file=sys.stderr)
        return 1
    print("Rendered activation plan proves the 27-service fleet, scanner/operator, public routes and data controls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
