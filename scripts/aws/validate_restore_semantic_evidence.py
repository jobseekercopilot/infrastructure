#!/usr/bin/env python3
"""Fail closed on public-beta isolated-restore semantic observation evidence.

This validator makes no AWS calls.  The separately authorised observation job is
responsible for collecting the control-plane facts represented by this artifact.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class SemanticEvidenceError(RuntimeError):
    pass


REGION = "eu-west-2"
DATABASES = [
    "authentication",
    "user_profile",
    "job_service",
    "document_generation",
    "document_store",
    "application_tracker",
    "payment",
]
SCOPE_LIMITATIONS = [
    "SYNTHETIC_NON_CUSTOMER_EMPTY_SCOPE",
    "JOURNAL_WRITE_READ_RETRY_AND_ABSENT_OPERATION_RECONSTRUCTION_PROVEN",
    "CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED",
    "CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED",
    "RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY",
    "LIVENESS_AND_FLYWAY_STARTUP_ONLY",
    "AGGREGATE_DOCUMENT_STORAGE_HEALTH_NOT_CLAIMED",
]
HEX_64 = re.compile(r"[0-9a-f]{64}")
RELEASE_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
DRILL_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{6,30}[a-z0-9])")
UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
RESERVED_OPERATION_UUID = re.compile(
    r"7e57c0de-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
OPAQUE_VERSION = re.compile(r"[\x21-\x7e]{1,1024}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SemanticEvidenceError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"unsafe semantic evidence file: {path}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate semantic evidence key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(value, dict), "semantic evidence must be an object")
    return value


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys,
            f"{label} has an incomplete or unexpected shape")
    return value


def timestamp(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str), f"{label} must be a UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SemanticEvidenceError(f"{label} must be a UTC timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} must include an explicit UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def sha256(value: Any, label: str) -> str:
    require(isinstance(value, str) and HEX_64.fullmatch(value) is not None and value != "0" * 64,
            f"{label} is not a non-zero lowercase SHA-256")
    return value


def image_digest(value: Any, label: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
            and value != "sha256:" + "0" * 64, f"{label} is not an immutable image digest")
    return value


def integer(value: Any, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    require(type(value) is int and value >= minimum, f"{label} is not a bounded integer")
    if maximum is not None:
        require(value <= maximum, f"{label} is not a bounded integer")
    return value


def canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


RUN_TASK_STAGES = ("clone", "source", "replay", "verifier")


def _named_values(items: Any, label: str, *, key: str = "name", value: str = "value") -> dict[str, str]:
    require(isinstance(items, list), f"{label} must be a list")
    result: dict[str, str] = {}
    for item in items:
        exact(item, {key, value}, f"{label} item")
        require(isinstance(item[key], str) and isinstance(item[value], str),
                f"{label} item must contain strings")
        require(item[key] not in result, f"{label} contains duplicate {key}: {item[key]}")
        result[item[key]] = item[value]
    return result


def _run_task_token(binding: str, attempt: int, stage: str, definition: str) -> str:
    return hashlib.sha256(
        f"{binding}:attempt-{attempt}:{stage}:{definition}".encode("utf-8")
    ).hexdigest()


def _synthetic(binding: str, label: str) -> str:
    return hashlib.sha256(
        f"jsc-restore-semantic-v1:{label}:{binding}".encode("utf-8")
    ).hexdigest()


def _expected_child_environment(
    context: dict[str, Any],
    attempt_number: int,
    stage: str,
    attempt_tasks: dict[str, str],
    task_facts: dict[str, dict[str, Any]],
) -> dict[str, str]:
    if stage == "clone":
        return {
            "PGHOST": context["databaseHost"],
            "RESTORE_REPLAY_DATABASE": context["replayDatabase"],
            "RESTORE_DRILL_ID": context["drillId"],
            "RESTORE_SOURCE_CANARY_ID": context["sourceCanaryId"],
            "RESTORE_SOURCE_MARKER_SHA256": context["sourceMarkerSha256"],
            "RELEASE_ID": context["releaseId"],
            "RESTORE_ATTEMPT": str(attempt_number),
            "RESTORE_ERASURE_OPERATION_ID": context["operationId"],
            "RESTORE_ERASURE_REPLAY_ID": context["restoreReplayId"],
        }
    if stage in {"source", "replay"}:
        database = "document_store" if stage == "source" else context["replayDatabase"]
        return {
            "DOCUMENT_STORE_DATABASE_URL": (
                f"jdbc:postgresql://{context['databaseHost']}:5432/{database}"
                "?sslmode=verify-full&sslrootcert=/etc/jsc/rds/global-bundle.pem"
            ),
            "DOCUMENT_STORE_OBJECT_BUCKET": context["bucket"],
            "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN": _synthetic(context["inputBindingSha256"], "retention-admin"),
            "DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY": _synthetic(context["inputBindingSha256"], "erasure-fingerprint"),
            "DOCUMENT_STORE_PRODUCER_TOKEN": _synthetic(context["inputBindingSha256"], "document-producer"),
            "DOCUMENT_STORE_READER_TOKEN": _synthetic(context["inputBindingSha256"], "document-reader"),
            "APPLICATION_TRACKER_PRODUCER_TOKEN": _synthetic(context["inputBindingSha256"], "tracker-producer"),
            "APPLICATION_TRACKER_READER_TOKEN": _synthetic(context["inputBindingSha256"], "tracker-reader"),
            "ENVIRONMENT_DATA_TOKEN": _synthetic(context["inputBindingSha256"], "environment-data"),
        }

    require(set(attempt_tasks) >= {"clone", "source", "replay"},
            "verifier RunTask was observed without the exact three prerequisite child tasks")
    source_fact = task_facts.get(attempt_tasks["source"])
    replay_fact = task_facts.get(attempt_tasks["replay"])
    require(source_fact is not None and replay_fact is not None,
            "verifier RunTask prerequisite task facts are absent")
    return {
        "PGHOST": context["databaseHost"],
        "RESTORE_DOCUMENT_BUCKET": context["bucket"],
        "RESTORE_DRILL_ID": context["drillId"],
        "RESTORE_SOURCE_CANARY_ID": context["sourceCanaryId"],
        "RESTORE_SOURCE_EVIDENCE_SHA256": context["sourceEvidenceSha256"],
        "RESTORE_SOURCE_MARKER_SHA256": context["sourceMarkerSha256"],
        "RELEASE_ID": context["releaseId"],
        "RESTORE_REPLAY_DATABASE": context["replayDatabase"],
        "RESTORE_ERASURE_OPERATION_ID": context["operationId"],
        "RESTORE_ERASURE_REPLAY_ID": context["restoreReplayId"],
        "RESTORE_ATTEMPT": str(attempt_number),
        "SOURCE_DOCUMENT_STORE_URL": f"http://{source_fact['privateIp']}:8089",
        "REPLAY_DOCUMENT_STORE_URL": f"http://{replay_fact['privateIp']}:8089",
        "RESTORE_CLONE_TASK_ARN": attempt_tasks["clone"],
        "RESTORE_SOURCE_APP_TASK_ARN": attempt_tasks["source"],
        "RESTORE_REPLAY_APP_TASK_ARN": attempt_tasks["replay"],
        "RESTORE_CLONE_TASK_DEFINITION_ARN": context["definitions"]["clone"],
        "RESTORE_APP_TASK_DEFINITION_ARN": context["definitions"]["source"],
        "RESTORE_VERIFIER_TASK_DEFINITION_ARN": context["definitions"]["verifier"],
        "DOCUMENT_STORE_IMAGE_DIGEST": context["documentStoreImageDigest"],
        "RELEASE_OPERATOR_IMAGE_DIGEST": context["releaseOperatorImageDigest"],
        "RESTORE_VPC_ID": context["vpcId"],
        "RESTORE_DATABASE_SECURITY_GROUP_ID": context["databaseSecurityGroupId"],
        "RESTORE_SEMANTIC_SECURITY_GROUP_ID": context["semanticSecurityGroupId"],
        "RESTORED_DATABASE_ARN": context["restoredDatabaseArn"],
        "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN": _synthetic(context["inputBindingSha256"], "retention-admin"),
    }


def validate_run_task_history(
    events: list[dict[str, Any]],
    tasks_response: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """Validate every broker-role ECS RunTask request across bounded redrives.

    CloudTrail request bodies are inspected in memory and are never copied into
    the final evidence. Duplicate SDK retries are accepted only when the same
    canonical client token resolves to the same task ARN.
    """
    exact(context, {
        "accountId", "region", "drillId", "attempt", "lastAttemptStartedAt",
        "brokerRoleArn", "stateMachineRoleArn", "clusterArn", "startedBy", "inputBindingSha256",
        "definitions", "currentTasks", "privateSubnetIds", "semanticSecurityGroupId",
        "databaseHost", "releaseId", "sourceCanaryId", "sourceMarkerSha256",
        "sourceEvidenceSha256", "replayDatabase", "bucket", "operationId",
        "restoreReplayId", "documentStoreImageDigest", "releaseOperatorImageDigest",
        "vpcId", "databaseSecurityGroupId", "restoredDatabaseArn",
        "brokerDefinitionArn", "brokerExecutionRoleArn", "brokerTaskRoleArn",
        "brokerSecurityGroupId", "executionArn", "stateInput", "markerBrokerTaskArn",
    }, "RunTask context")
    attempt = integer(context["attempt"], "RunTask current attempt", 1, 3)
    definitions = exact(context["definitions"], set(RUN_TASK_STAGES), "RunTask definitions")
    current_tasks = exact(context["currentTasks"], set(RUN_TASK_STAGES), "RunTask current tasks")
    require(definitions["source"] == definitions["replay"],
            "source/replay RunTask definitions differ")
    last_attempt_started = timestamp(context["lastAttemptStartedAt"], "lastAttemptStartedAt")
    require(context["region"] == REGION, "RunTask region is not eu-west-2")
    require(isinstance(events, list), "CloudTrail RunTask history must be a list")
    exact(tasks_response, {"tasks", "failures"}, "ECS task history response")
    require(tasks_response["failures"] == [], "ECS task history contains lookup failures")

    expected_tags = {
        "Application": "Job Seeker Copilot",
        "Environment": "public-beta",
        "ManagedBy": "RestoreSemanticVerification",
        "RestoreDrillId": context["drillId"],
    }
    expected_family = {
        "clone": "jsc-public-beta-restore-semantic-clone",
        "source": "jsc-public-beta-restore-semantic-document-store",
        "replay": "jsc-public-beta-restore-semantic-document-store",
        "verifier": "jsc-public-beta-restore-semantic-verifier",
    }
    expected_digest = {
        "clone": context["releaseOperatorImageDigest"],
        "source": context["documentStoreImageDigest"],
        "replay": context["documentStoreImageDigest"],
        "verifier": context["releaseOperatorImageDigest"],
    }
    token_contract: dict[str, tuple[int, str]] = {}
    for number in range(1, attempt + 1):
        for stage in RUN_TASK_STAGES:
            token = _run_task_token(context["inputBindingSha256"], number, stage, definitions[stage])
            require(token not in token_contract, "RunTask canonical client tokens collided")
            token_contract[token] = (number, stage)

    child_events = [
        event for event in events
        if isinstance(event, dict)
        and event.get("eventSource") == "ecs.amazonaws.com"
        and event.get("eventName") == "RunTask"
        and isinstance(event.get("userIdentity"), dict)
        and event["userIdentity"].get("sessionContext", {}).get("sessionIssuer", {}).get("arn")
        == context["brokerRoleArn"]
    ]
    require(child_events, "CloudTrail has no broker-role child RunTask event")

    successful_by_token: dict[str, str] = {}
    classified: list[tuple[dict[str, Any], int, str, str | None, dt.datetime]] = []
    for event in child_events:
        require(event.get("awsRegion") == context["region"]
                and event.get("recipientAccountId") == context["accountId"],
                "broker RunTask account/region drifted")
        identity = event["userIdentity"]
        issuer = identity.get("sessionContext", {}).get("sessionIssuer", {})
        require(identity.get("type") == "AssumedRole"
                and identity.get("accountId") == context["accountId"]
                and issuer.get("type") == "Role"
                and issuer.get("accountId") == context["accountId"]
                and issuer.get("arn") == context["brokerRoleArn"]
                and issuer.get("userName") == context["brokerRoleArn"].rsplit("/", 1)[-1],
                "broker RunTask assumed-role identity drifted")
        request = exact(event.get("requestParameters"), {
            "clientToken", "cluster", "count", "launchType", "networkConfiguration",
            "overrides", "startedBy", "tags", "taskDefinition",
        }, "broker RunTask request")
        token = request["clientToken"]
        require(isinstance(token, str) and token in token_contract,
                "broker RunTask used an unknown attempt/stage client token")
        number, stage = token_contract[token]
        require(request["cluster"] == context["clusterArn"]
                and request["count"] == 1 and type(request["count"]) is int
                and request["launchType"] == "EC2"
                and request["startedBy"] == context["startedBy"]
                and request["taskDefinition"] == definitions[stage],
                "broker RunTask fixed request tuple drifted")
        network = exact(request["networkConfiguration"], {"awsvpcConfiguration"},
                        "broker RunTask network configuration")
        awsvpc = exact(network["awsvpcConfiguration"],
                       {"assignPublicIp", "securityGroups", "subnets"},
                       "broker RunTask awsvpc configuration")
        require(awsvpc["assignPublicIp"] == "DISABLED"
                and awsvpc["securityGroups"] == [context["semanticSecurityGroupId"]]
                and isinstance(awsvpc["subnets"], list)
                and len(awsvpc["subnets"]) == 2
                and len(set(awsvpc["subnets"])) == 2
                and set(awsvpc["subnets"]) == set(context["privateSubnetIds"]),
                "broker RunTask network escaped the exact private boundary")
        require(_named_values(request["tags"], "broker RunTask tags", key="key", value="value")
                == expected_tags, "broker RunTask tags drifted")
        overrides = exact(request["overrides"], {"containerOverrides"},
                          "broker RunTask overrides")
        containers = overrides["containerOverrides"]
        require(isinstance(containers, list) and len(containers) == 1,
                "broker RunTask must contain exactly one container override")
        container = exact(containers[0], {"environment", "name"},
                          "broker RunTask container override")
        expected_container = (
            "restore-semantic-document-store" if stage in {"source", "replay"}
            else f"restore-semantic-{stage}"
        )
        require(container["name"] == expected_container,
                "broker RunTask container name drifted")

        event_time = timestamp(event.get("eventTime"), "broker RunTask eventTime")
        require((number == attempt and event_time >= last_attempt_started)
                or (number < attempt and event_time < last_attempt_started),
                "broker RunTask event is outside its recorded attempt window")
        failed = event.get("errorCode") is not None or event.get("errorMessage") is not None
        response = event.get("responseElements")
        response_task: str | None = None
        if failed:
            require(event.get("errorCode") is not None and event.get("errorMessage") is not None,
                    "failed broker RunTask has incomplete CloudTrail error evidence")
            require(response is None or (
                isinstance(response, dict)
                and response.get("tasks", []) == []
                and response.get("failures", []) == []
            ), "failed broker RunTask returned a task or placement failure")
        else:
            require(isinstance(response, dict)
                    and isinstance(response.get("failures"), list)
                    and isinstance(response.get("tasks"), list),
                    "broker RunTask response lacks exact tasks/failures arrays")
            if response["tasks"] == []:
                require(1 <= len(response["failures"]) <= 10
                        and all(isinstance(failure, dict)
                                and set(failure).issubset({"arn", "reason", "detail"})
                                and isinstance(failure.get("reason"), str)
                                for failure in response["failures"]),
                        "taskless broker RunTask is not an explicit ECS placement failure")
            else:
                require(response["failures"] == [] and len(response["tasks"]) == 1,
                        "successful broker RunTask is not one task with zero failures")
                response_task = response["tasks"][0].get("taskArn")
                require(isinstance(response_task, str), "successful broker RunTask task ARN is absent")
                previous = successful_by_token.setdefault(token, response_task)
                require(previous == response_task,
                        "duplicate RunTask client token returned more than one task ARN")
        classified.append((event, number, stage, response_task, event_time))

    tasks_by_attempt: dict[int, dict[str, str]] = {number: {} for number in range(1, attempt + 1)}
    for _event, number, stage, task_arn, _event_time in classified:
        if task_arn is None:
            continue
        existing = tasks_by_attempt[number].setdefault(stage, task_arn)
        require(existing == task_arn, "one attempt/stage produced multiple child task ARNs")
    require(tasks_by_attempt[attempt] == current_tasks,
            "current attempt RunTask response ARNs do not match the durable marker")

    successful_stage_times: dict[int, dict[str, dt.datetime]] = {
        number: {} for number in range(1, attempt + 1)
    }
    for _event, number, stage, task_arn, event_time in classified:
        if task_arn is not None:
            previous = successful_stage_times[number].get(stage)
            successful_stage_times[number][stage] = min(previous, event_time) if previous else event_time
    for _event, number, stage, _task_arn, event_time in classified:
        if stage in {"source", "replay"}:
            require("clone" in successful_stage_times[number]
                    and event_time >= successful_stage_times[number]["clone"],
                    f"attempt {number} {stage} RunTask preceded successful clone")
        if stage == "verifier":
            require({"clone", "source", "replay"} <= set(successful_stage_times[number])
                    and event_time >= max(
                        successful_stage_times[number][dependency]
                        for dependency in ("source", "replay")
                    ), f"attempt {number} verifier RunTask preceded exact application prerequisites")

    attempt_windows: dict[int, list[dt.datetime]] = {
        number: [] for number in range(1, attempt + 1)
    }
    for _event, number, _stage, _task_arn, event_time in classified:
        attempt_windows[number].append(event_time)
    nonempty_attempts = [number for number in range(1, attempt + 1) if attempt_windows[number]]
    for earlier, later in zip(nonempty_attempts, nonempty_attempts[1:]):
        require(max(attempt_windows[earlier]) < min(attempt_windows[later]),
                f"attempt {earlier} RunTask history overlaps attempt {later}")

    state_events = [
        event for event in events
        if isinstance(event, dict)
        and event.get("eventSource") == "ecs.amazonaws.com"
        and event.get("eventName") == "RunTask"
        and isinstance(event.get("userIdentity"), dict)
        and event["userIdentity"].get("sessionContext", {}).get("sessionIssuer", {}).get("arn")
        == context["stateMachineRoleArn"]
    ]
    require(state_events, "CloudTrail has no state-machine-role broker RunTask event")
    state_input = exact(context["stateInput"], {
        "drillId", "releaseId", "releaseAttestationId", "sourceCanaryId",
        "sourceEvidenceSha256", "sourceMarkerSha256", "restoreStartEvidenceSha256",
        "rdsRestoreJobId", "s3RestoreJobId", "rdsRecoveryPointArn", "s3RecoveryPointArn",
        "restoreRoleArn",
    }, "state-machine input")
    static_broker_environment = {
        "RESTORE_BROKER_TASK_DEFINITION_ARN": context["brokerDefinitionArn"],
        "RESTORE_BROKER_EXECUTION_ROLE_ARN": context["brokerExecutionRoleArn"],
        "RESTORE_BROKER_TASK_ROLE_ARN": context["brokerTaskRoleArn"],
    }
    start_environment = static_broker_environment | {
        "RESTORE_DRILL_ID": state_input["drillId"],
        "RELEASE_ID": state_input["releaseId"],
        "RELEASE_ATTESTATION_ID": state_input["releaseAttestationId"],
        "RESTORE_SOURCE_CANARY_ID": state_input["sourceCanaryId"],
        "RESTORE_SOURCE_EVIDENCE_SHA256": state_input["sourceEvidenceSha256"],
        "RESTORE_SOURCE_MARKER_SHA256": state_input["sourceMarkerSha256"],
        "RESTORE_START_EVIDENCE_SHA256": state_input["restoreStartEvidenceSha256"],
        "RDS_RESTORE_JOB_ID": state_input["rdsRestoreJobId"],
        "S3_RESTORE_JOB_ID": state_input["s3RestoreJobId"],
        "RDS_RECOVERY_POINT_ARN": state_input["rdsRecoveryPointArn"],
        "S3_RECOVERY_POINT_ARN": state_input["s3RecoveryPointArn"],
        "RESTORE_ROLE_ARN": state_input["restoreRoleArn"],
        "STATE_MACHINE_EXECUTION_ARN": context["executionArn"],
    }
    contain_environment = static_broker_environment | {"RESTORE_DRILL_ID": state_input["drillId"]}
    broker_tags = {
        "Application": "Job Seeker Copilot", "Environment": "public-beta",
        "ManagedBy": "RestoreSemanticBroker", "RestoreDrillId": context["drillId"],
    }
    broker_successful_tasks: set[str] = set()
    broker_start_tasks: set[str] = set()
    broker_containment_tasks: set[str] = set()
    broker_token_tasks: dict[str, str] = {}
    broker_tokens_by_mode: dict[str, set[str]] = {"start": set(), "contain": set()}
    seen_start_event = False
    for event in sorted(state_events, key=lambda value: timestamp(value.get("eventTime"), "state RunTask eventTime")):
        require(event.get("awsRegion") == context["region"]
                and event.get("recipientAccountId") == context["accountId"],
                "state RunTask account/region drifted")
        identity = event["userIdentity"]
        issuer = identity.get("sessionContext", {}).get("sessionIssuer", {})
        require(identity.get("type") == "AssumedRole"
                and identity.get("accountId") == context["accountId"]
                and issuer.get("type") == "Role"
                and issuer.get("accountId") == context["accountId"]
                and issuer.get("arn") == context["stateMachineRoleArn"]
                and issuer.get("userName") == context["stateMachineRoleArn"].rsplit("/", 1)[-1],
                "state RunTask assumed-role identity drifted")
        request = event.get("requestParameters")
        require(isinstance(request, dict), "state RunTask request is absent")
        required_request_keys = {
            "cluster", "count", "enableECSManagedTags", "launchType", "networkConfiguration",
            "overrides", "startedBy", "tags", "taskDefinition",
        }
        require(set(request) == required_request_keys | {"clientToken"},
                "state RunTask request has an incomplete or unexpected shape")
        token = request["clientToken"]
        require(isinstance(token, str) and 1 <= len(token) <= 64
                and re.fullmatch(r"[\x21-\x7e]+", token) is not None,
                "state RunTask generated client token is malformed")
        started_by = request["startedBy"]
        require(started_by in {"jsc-restore-semantic-broker", "jsc-restore-semantic-contain"},
                "state RunTask StartedBy drifted")
        mode = "start" if started_by == "jsc-restore-semantic-broker" else "contain"
        broker_tokens_by_mode[mode].add(token)
        if mode == "start":
            seen_start_event = True
        else:
            require(seen_start_event, "state containment RunTask preceded every broker start request")
        require(request["cluster"] == context["clusterArn"]
                and request["taskDefinition"] == context["brokerDefinitionArn"]
                and request["count"] == 1 and type(request["count"]) is int
                and request["launchType"] == "EC2"
                and request["enableECSManagedTags"] is False,
                "state RunTask fixed broker tuple drifted")
        network = exact(request["networkConfiguration"], {"awsvpcConfiguration"},
                        "state RunTask network configuration")
        awsvpc = exact(network["awsvpcConfiguration"], {"assignPublicIp", "securityGroups", "subnets"},
                       "state RunTask awsvpc configuration")
        require(awsvpc["assignPublicIp"] == "DISABLED"
                and awsvpc["securityGroups"] == [context["brokerSecurityGroupId"]]
                and isinstance(awsvpc["subnets"], list) and len(awsvpc["subnets"]) == 2
                and len(set(awsvpc["subnets"])) == 2
                and set(awsvpc["subnets"]) == set(context["privateSubnetIds"]),
                "state RunTask broker network escaped the exact private boundary")
        require(_named_values(request["tags"], "state RunTask tags", key="key", value="value")
                == broker_tags, "state RunTask broker tags drifted")
        overrides = exact(request["overrides"], {"containerOverrides", "executionRoleArn", "taskRoleArn"},
                          "state RunTask overrides")
        require(overrides["executionRoleArn"] == context["brokerExecutionRoleArn"]
                and overrides["taskRoleArn"] == context["brokerTaskRoleArn"],
                "state RunTask broker role override drifted")
        containers = overrides["containerOverrides"]
        require(isinstance(containers, list) and len(containers) == 1,
                "state RunTask must contain exactly one broker override")
        container = exact(containers[0], {"command", "environment", "name"},
                          "state RunTask broker container override")
        expected_command = ["/opt/jsc/run-restore-semantic-broker.sh", mode]
        expected_environment = start_environment if mode == "start" else contain_environment
        require(container["name"] == "restore-semantic-broker"
                and container["command"] == expected_command
                and _named_values(container["environment"], "state RunTask broker environment")
                == expected_environment,
                "state RunTask broker command/environment drifted")
        failed = event.get("errorCode") is not None or event.get("errorMessage") is not None
        response = event.get("responseElements")
        task_arn: str | None = None
        if failed:
            require(event.get("errorCode") is not None and event.get("errorMessage") is not None
                    and (response is None or (
                        isinstance(response, dict) and response.get("tasks", []) == []
                        and response.get("failures", []) == []
                    )), "failed state RunTask returned a task or placement failure")
        else:
            require(isinstance(response, dict)
                    and isinstance(response.get("tasks"), list)
                    and isinstance(response.get("failures"), list),
                    "state RunTask response lacks tasks/failures arrays")
            if response["tasks"]:
                require(response["failures"] == [] and len(response["tasks"]) == 1
                        and isinstance(response["tasks"][0].get("taskArn"), str),
                        "successful state RunTask is not one task with zero failures")
                task_arn = response["tasks"][0]["taskArn"]
            else:
                require(1 <= len(response["failures"]) <= 10
                        and all(isinstance(failure, dict)
                                and set(failure).issubset({"arn", "reason", "detail"})
                                and isinstance(failure.get("reason"), str)
                                for failure in response["failures"]),
                        "taskless state RunTask is not an explicit ECS placement failure")
        if task_arn is not None:
            previous = broker_token_tasks.setdefault(token, task_arn)
            require(previous == task_arn,
                    "duplicate state RunTask client token returned multiple broker tasks")
            broker_successful_tasks.add(task_arn)
            if mode == "start":
                broker_start_tasks.add(task_arn)
            else:
                broker_containment_tasks.add(task_arn)
    require(all(len(tokens) <= 3 for tokens in broker_tokens_by_mode.values())
            and len(broker_start_tasks) <= 3 and len(broker_containment_tasks) <= 3
            and len(broker_successful_tasks) <= 6,
            "state-machine broker RunTask history exceeded three bounded attempts")
    require(context["markerBrokerTaskArn"] in broker_start_tasks,
            "durable marker broker task is not a state-machine start response")

    task_facts: dict[str, dict[str, Any]] = {}
    for task in tasks_response["tasks"]:
        task_arn = task.get("taskArn") if isinstance(task, dict) else None
        require(isinstance(task_arn, str) and task_arn not in task_facts,
                "ECS task history contains a missing or duplicate task ARN")
        attachments = task.get("attachments")
        require(isinstance(attachments, list) and len(attachments) == 1,
                f"ECS task {task_arn} does not have exactly one ENI attachment")
        attachment = attachments[0]
        require(isinstance(attachment, dict)
                and set(attachment).issubset({"id", "type", "status", "details"})
                and attachment.get("type") == "ElasticNetworkInterface",
                f"ECS task {task_arn} attachment is not the exact ENI type")
        detail_items = attachment.get("details")
        require(isinstance(detail_items, list),
                f"ECS task {task_arn} ENI details are absent")
        details: dict[str, str] = {}
        harmless_detail_names = {
            "subnetId", "networkInterfaceId", "macAddress",
            "privateDnsName", "privateIPv4Address",
        }
        for detail in detail_items:
            exact(detail, {"name", "value"}, f"ECS task {task_arn} ENI detail")
            require(isinstance(detail["name"], str) and isinstance(detail["value"], str)
                    and detail["name"] in harmless_detail_names
                    and detail["name"] not in details,
                    f"ECS task {task_arn} ENI details are duplicate or unexpected")
            details[detail["name"]] = detail["value"]
        require({"subnetId", "networkInterfaceId", "privateIPv4Address"} <= set(details),
                f"ECS task {task_arn} ENI details are incomplete")
        task_facts[task_arn] = {
            "taskDefinitionArn": task.get("taskDefinitionArn"),
            "group": task.get("group"),
            "lastStatus": task.get("lastStatus"),
            "imageDigest": (
                task.get("containers", [{}])[0].get("imageDigest")
                if len(task.get("containers", [])) == 1 else None
            ),
            "tags": _named_values(task.get("tags"), f"ECS task {task_arn} tags", key="key", value="value"),
            "subnetId": details.get("subnetId"),
            "privateIp": details.get("privateIPv4Address"),
            "networkInterfaceId": details.get("networkInterfaceId"),
        }
    successful_tasks = ({task for stages in tasks_by_attempt.values() for task in stages.values()}
                        | broker_successful_tasks)
    require(set(task_facts) == successful_tasks,
            "ECS task history is not the exact successful RunTask response set")
    for number, stages in tasks_by_attempt.items():
        for stage, task_arn in stages.items():
            fact = task_facts[task_arn]
            require(fact["taskDefinitionArn"] == definitions[stage]
                    and fact["group"] == f"family:{expected_family[stage]}"
                    and fact["lastStatus"] == "STOPPED"
                    and fact["imageDigest"] == expected_digest[stage]
                    and fact["tags"] == expected_tags
                    and fact["subnetId"] in context["privateSubnetIds"]
                    and isinstance(fact["privateIp"], str)
                    and re.fullmatch(r"10\.42\.[0-9]{1,3}\.[0-9]{1,3}", fact["privateIp"])
                    and isinstance(fact["networkInterfaceId"], str)
                    and re.fullmatch(r"eni-[0-9a-f]{8,17}", fact["networkInterfaceId"]),
                    f"attempt {number} {stage} task is not exact and STOPPED")
    for task_arn in broker_successful_tasks:
        fact = task_facts[task_arn]
        require(fact["taskDefinitionArn"] == context["brokerDefinitionArn"]
                and fact["group"] == "family:jsc-public-beta-restore-semantic-broker"
                and fact["lastStatus"] == "STOPPED"
                and fact["imageDigest"] == context["releaseOperatorImageDigest"]
                and fact["tags"] == broker_tags
                and fact["subnetId"] in context["privateSubnetIds"]
                and isinstance(fact["privateIp"], str)
                and re.fullmatch(r"10\.42\.[0-9]{1,3}\.[0-9]{1,3}", fact["privateIp"])
                and isinstance(fact["networkInterfaceId"], str)
                and re.fullmatch(r"eni-[0-9a-f]{8,17}", fact["networkInterfaceId"]),
                "state-machine broker task is not exact and STOPPED")

    for event, number, stage, _task_arn, _event_time in classified:
        container = event["requestParameters"]["overrides"]["containerOverrides"][0]
        actual_environment = _named_values(
            container["environment"], f"attempt {number} {stage} RunTask environment"
        )
        marker_b64 = actual_environment.pop("RESTORE_SOURCE_MARKER_B64", None)
        require(actual_environment == _expected_child_environment(
            context, number, stage, tasks_by_attempt[number], task_facts
        ), f"attempt {number} {stage} RunTask environment drifted")
        if stage == "verifier":
            require(isinstance(marker_b64, str), "verifier RunTask source marker bytes are absent")
            try:
                marker_bytes = base64.b64decode(marker_b64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise SemanticEvidenceError("verifier RunTask source marker bytes are malformed") from exc
            require(hashlib.sha256(marker_bytes).hexdigest() == context["sourceMarkerSha256"],
                    "verifier RunTask source marker bytes do not match the source marker")
        else:
            require(marker_b64 is None, f"{stage} RunTask unexpectedly received source marker bytes")


def _secret_map(items: Any, label: str) -> dict[str, str]:
    return _named_values(items, label, key="name", value="valueFrom")


def validate_database_secret_field(value: Any, database: str, account: str, label: str) -> str:
    pattern = (
        rf"arn:aws:secretsmanager:{REGION}:{account}:secret:"
        rf"jsc-public-beta/database/{re.escape(database)}-[A-Za-z0-9]{{6}}:password::"
    )
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None,
            f"{label} secret ARN is not the exact {database} password field")
    return value


def validate_task_definitions(documents: dict[str, Any], context: dict[str, Any]) -> None:
    """Validate the canonical live broker/child ECS task-definition contracts."""
    exact(documents, {"broker", "clone", "application", "verifier"}, "task definitions")
    exact(context, {
        "accountId", "region", "dataKmsKeyArn", "definitions", "roles", "privateSubnetIds",
        "dataSubnetIds", "vpcId", "databaseSecurityGroupId", "semanticSecurityGroupId",
        "brokerSecurityGroupId", "databaseParameterGroupName", "documentStoreImageDigest",
        "releaseOperatorImageDigest",
    }, "task-definition context")
    account = context["accountId"]
    require(context["region"] == REGION, "task-definition region is not eu-west-2")
    definitions = exact(
        context["definitions"], {"broker", "clone", "application", "verifier"},
        "task-definition ARNs",
    )
    roles = exact(context["roles"], {
        "brokerExecution", "brokerTask", "cloneExecution", "applicationExecution",
        "applicationTask", "verifierExecution", "verifierTask",
    }, "task-definition roles")
    common_task_keys = {
        "taskDefinitionArn", "containerDefinitions", "family", "taskRoleArn", "executionRoleArn",
        "networkMode", "revision", "volumes", "status", "requiresAttributes",
        "placementConstraints", "compatibilities", "requiresCompatibilities", "registeredAt",
        "registeredBy", "enableFaultInjection",
    }
    common_container_keys = {
        "name", "image", "cpu", "memory", "portMappings", "essential", "environment",
        "mountPoints", "volumesFrom", "secrets", "readonlyRootFilesystem", "linuxParameters",
        "logConfiguration", "systemControls",
    }
    family = {
        "broker": "jsc-public-beta-restore-semantic-broker",
        "clone": "jsc-public-beta-restore-semantic-clone",
        "application": "jsc-public-beta-restore-semantic-document-store",
        "verifier": "jsc-public-beta-restore-semantic-verifier",
    }
    digest = {
        "broker": context["releaseOperatorImageDigest"],
        "clone": context["releaseOperatorImageDigest"],
        "application": context["documentStoreImageDigest"],
        "verifier": context["releaseOperatorImageDigest"],
    }
    execution_role = {
        "broker": roles["brokerExecution"], "clone": roles["cloneExecution"],
        "application": roles["applicationExecution"], "verifier": roles["verifierExecution"],
    }
    task_role = {
        "broker": roles["brokerTask"], "clone": None,
        "application": roles["applicationTask"], "verifier": roles["verifierTask"],
    }
    purpose = {
        "broker": "restore-semantic-broker", "clone": "restore-semantic-clone",
        "application": "restore-semantic-document-store", "verifier": "restore-semantic-verifier",
    }

    parsed: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, str]]] = {}
    source_commits: dict[str, str] = {}
    for kind, document in documents.items():
        exact(document, {"taskDefinition", "tags"}, f"{kind} task-definition response")
        definition = document["taskDefinition"]
        require(isinstance(definition, dict)
                and set(definition).issubset(common_task_keys)
                and common_task_keys - {"taskRoleArn", "enableFaultInjection"} <= set(definition),
                f"{kind} task definition has extra or missing settings")
        require(definition["taskDefinitionArn"] == definitions[kind]
                and definition["family"] == family[kind]
                and type(definition["revision"]) is int and definition["revision"] >= 1
                and definition["status"] == "ACTIVE"
                and definition["networkMode"] == "awsvpc"
                and definition["requiresCompatibilities"] == ["EC2"]
                and definition["executionRoleArn"] == execution_role[kind]
                and definition.get("taskRoleArn") == task_role[kind]
                and definition["volumes"] == [] and definition["placementConstraints"] == []
                and definition.get("enableFaultInjection", False) is False,
                f"{kind} task definition identity/runtime shape drifted")
        containers = definition["containerDefinitions"]
        require(isinstance(containers, list) and len(containers) == 1,
                f"{kind} task definition does not contain exactly one container")
        container = containers[0]
        allowed_container_keys = set(common_container_keys)
        if kind in {"broker", "clone", "verifier"}:
            allowed_container_keys.add("command")
        if kind == "application":
            allowed_container_keys.update({"user", "healthCheck", "stopTimeout"})
        require(isinstance(container, dict)
                and set(container).issubset(allowed_container_keys)
                and common_container_keys <= set(container),
                f"{kind} container has extra or missing settings")
        expected_name = purpose[kind]
        expected_repository = "document-store-service" if kind == "application" else "release-operator"
        expected_image = (
            f"{account}.dkr.ecr.{REGION}.amazonaws.com/jsc-public-beta/"
            f"{expected_repository}@{digest[kind]}"
        )
        expected_memory = 1024 if kind == "application" else 512
        require(container["name"] == expected_name and container["image"] == expected_image
                and container["cpu"] == 256 and container["memory"] == expected_memory
                and container["essential"] is True and container["readonlyRootFilesystem"] is True
                and container["mountPoints"] == [] and container["volumesFrom"] == []
                and container["systemControls"] == [],
                f"{kind} container immutable/runtime settings drifted")
        linux = exact(container["linuxParameters"], {"initProcessEnabled", "tmpfs"},
                      f"{kind} Linux parameters")
        expected_tmpfs = 128 if kind == "application" else 64 if kind in {"broker", "verifier"} else 32
        require(linux == {"initProcessEnabled": True, "tmpfs": [{
            "containerPath": "/tmp", "size": expected_tmpfs,
            "mountOptions": ["rw", "noexec", "nosuid", "nodev"],
        }]}, f"{kind} Linux parameters drifted")
        log = exact(container["logConfiguration"], {"logDriver", "options", "secretOptions"},
                    f"{kind} log configuration")
        expected_options = {
            "awslogs-group": "/jsc/public-beta/release-operator",
            "awslogs-region": REGION,
            "awslogs-stream-prefix": expected_name,
        }
        if kind == "application":
            expected_options.update({"mode": "non-blocking", "max-buffer-size": "25m"})
        require(log["logDriver"] == "awslogs" and log["options"] == expected_options
                and log["secretOptions"] == [], f"{kind} log configuration drifted")
        tags = _named_values(document["tags"], f"{kind} task-definition tags", key="key", value="value")
        require(set(tags) == {
            "Application", "Environment", "ManagedBy", "Repository", "CostCentre",
            "Purpose", "ImageDigest", "SourceCommit",
        } and tags["Application"] == "Job Seeker Copilot" and tags["Environment"] == "public-beta"
                and tags["ManagedBy"] == "Terraform"
                and tags["Repository"] == "jobseekercopilot/infrastructure"
                and tags["CostCentre"] == "public-beta" and tags["Purpose"] == purpose[kind]
                and tags["ImageDigest"] == digest[kind]
                and re.fullmatch(r"[0-9a-f]{40}", tags["SourceCommit"]) is not None
                and tags["SourceCommit"] != "0" * 40,
                f"{kind} task-definition tags drifted")
        environment = _named_values(container["environment"], f"{kind} base environment")
        secrets = _secret_map(container["secrets"], f"{kind} task-definition secrets")
        source_commits[kind] = tags["SourceCommit"]
        parsed[kind] = (definition, container, environment, secrets)

    require(source_commits["broker"] == source_commits["clone"] == source_commits["verifier"],
            "release-operator task definitions use different source commits")
    broker_env = parsed["broker"][2]
    expected_broker_environment = {
        "AWS_ACCOUNT_ID": account,
        "AWS_REGION": REGION,
        "RESTORE_CLUSTER_ARN": f"arn:aws:ecs:{REGION}:{account}:cluster/jsc-public-beta",
        "RESTORE_CLUSTER_NAME": "jsc-public-beta",
        "RESTORE_VPC_ID": context["vpcId"],
        "RESTORE_PRIVATE_SUBNET_IDS_JSON": json.dumps(context["privateSubnetIds"], separators=(",", ":")),
        "RESTORE_DATA_SUBNET_IDS_JSON": json.dumps(context["dataSubnetIds"], separators=(",", ":")),
        "RESTORE_DATA_KMS_KEY_ARN": context["dataKmsKeyArn"],
        "RESTORE_DB_SUBNET_GROUP_NAME": "jsc-public-beta-postgres",
        "RESTORE_DB_PARAMETER_GROUP_NAME": context["databaseParameterGroupName"],
        "RESTORE_DATABASE_SECURITY_GROUP_ID": context["databaseSecurityGroupId"],
        "RESTORE_SEMANTIC_SECURITY_GROUP_ID": context["semanticSecurityGroupId"],
        "RESTORE_BROKER_SECURITY_GROUP_ID": context["brokerSecurityGroupId"],
        "RESTORE_CLONE_TASK_DEFINITION_ARN": definitions["clone"],
        "RESTORE_APP_TASK_DEFINITION_ARN": definitions["application"],
        "RESTORE_VERIFIER_TASK_DEFINITION_ARN": definitions["verifier"],
        "RESTORE_CLONE_EXECUTION_ROLE_ARN": roles["cloneExecution"],
        "RESTORE_APP_EXECUTION_ROLE_ARN": roles["applicationExecution"],
        "RESTORE_APP_TASK_ROLE_ARN": roles["applicationTask"],
        "RESTORE_VERIFIER_EXECUTION_ROLE_ARN": roles["verifierExecution"],
        "RESTORE_VERIFIER_TASK_ROLE_ARN": roles["verifierTask"],
        "DOCUMENT_STORE_IMAGE_DIGEST": context["documentStoreImageDigest"],
        "DOCUMENT_STORE_SOURCE_COMMIT": source_commits["application"],
        "RELEASE_OPERATOR_IMAGE_DIGEST": context["releaseOperatorImageDigest"],
        "RELEASE_OPERATOR_SOURCE_COMMIT": source_commits["broker"],
    }
    require(broker_env == expected_broker_environment and parsed["broker"][3] == {},
            "broker base environment/secrets drifted")
    require(parsed["broker"][1]["command"] == ["/opt/jsc/run-restore-semantic-broker.sh", "start"]
            and parsed["broker"][1]["portMappings"] == [],
            "broker command/ports drifted")

    document_secret = parsed["application"][3].get("DOCUMENT_STORE_DATABASE_PASSWORD")
    document_secret = validate_database_secret_field(
        document_secret, "document_store", account, "application task"
    )
    clone_env = parsed["clone"][2]
    require(clone_env == {
        "PGHOST": "invalid.restore.local", "PGPORT": "5432", "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": "/etc/jsc/rds/global-bundle.pem", "DOCUMENT_STORE_DATABASE": "document_store",
        "DOCUMENT_STORE_USERNAME": "document_store", "RESTORE_REPLAY_DATABASE": "invalid_restore_replay",
        "RESTORE_DRILL_ID": "invalid-drill", "RESTORE_SOURCE_CANARY_ID": "invalid-canary",
        "RESTORE_SOURCE_MARKER_SHA256": "invalid", "RELEASE_ID": "invalid",
    } and parsed["clone"][1]["command"] == ["/opt/jsc/clone-restored-document-store.sh"]
            and parsed["clone"][1]["portMappings"] == [],
            "clone base environment/command drifted")
    clone_secrets = parsed["clone"][3]
    rds_username = clone_secrets.get("MASTER_USERNAME", "")
    rds_password = clone_secrets.get("MASTER_PASSWORD", "")
    require(set(clone_secrets) == {"MASTER_USERNAME", "MASTER_PASSWORD", "DOCUMENT_STORE_PASSWORD"}
            and rds_username.endswith(":username::")
            and rds_password == rds_username.removesuffix(":username::") + ":password::"
            and re.fullmatch(
                rf"arn:aws:secretsmanager:{REGION}:{account}:secret:rds!db-[A-Za-z0-9-]+:username::",
                rds_username,
            ) is not None
            and clone_secrets["DOCUMENT_STORE_PASSWORD"] == document_secret,
            "clone task secret ARNs drifted")

    app_definition, app_container, app_env, _app_secrets = parsed["application"]
    policy_keys = (
        "DOCUMENT_STORE_RETENTION_POLICY_VERSION",
        "DOCUMENT_STORE_BACKUP_RETENTION_POLICY_VERSION",
        "DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION",
    )
    for key in policy_keys:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", app_env.get(key, "")) is not None
                and app_env[key] not in {"NOT_CONFIGURED", "UNAPPROVED"},
                f"application {key} is not an approved version")
    erasure_key = app_env.get("DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID")
    require(isinstance(erasure_key, str) and re.fullmatch(
        rf"arn:aws:kms:{REGION}:{account}:key/[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}",
        erasure_key,
    ) is not None, "application erasure-journal KMS key ARN is malformed")
    expected_app_environment = {
        "SPRING_PROFILES_ACTIVE": "production", "SERVER_PORT": "8089",
        "SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE": "6", "SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE": "1",
        "SPRING_DATASOURCE_HIKARI_CONNECTION_TIMEOUT": "5000", "SPRING_DATASOURCE_HIKARI_VALIDATION_TIMEOUT": "2000",
        "SPRING_DATASOURCE_HIKARI_MAX_LIFETIME": "1500000", "ENVIRONMENT_DATA_ENABLED": "false",
        "DOCUMENT_STORE_DATABASE_URL": "jdbc:postgresql://invalid.restore.local:5432/document_store?sslmode=verify-full&sslrootcert=/etc/jsc/rds/global-bundle.pem",
        "DOCUMENT_STORE_DATABASE_USERNAME": "document_store", "DOCUMENT_STORE_DATABASE_SSL_MODE": "verify-full",
        "DOCUMENT_STORE_DATABASE_PRODUCTION_SAFETY_CHECK": "true", "DOCUMENT_STORE_ENCRYPTION_AT_REST_ENABLED": "true",
        "DOCUMENT_STORE_ENCRYPTION_KEY_REFERENCE": context["dataKmsKeyArn"], "DOCUMENT_STORE_BACKUP_ENCRYPTION_ENABLED": "true",
        "DOCUMENT_STORE_BACKUP_KEY_REFERENCE": context["dataKmsKeyArn"], "DOCUMENT_STORE_OBJECT_PROVIDER": "s3",
        "DOCUMENT_STORE_OBJECT_REGION": REGION, "DOCUMENT_STORE_OBJECT_BUCKET": "jsc-public-beta-invalid-restore",
        "DOCUMENT_STORE_OBJECT_KMS_KEY_ID": context["dataKmsKeyArn"], "DOCUMENT_STORE_OBJECT_CREDENTIALS_PROVIDER": "task-role",
        "DOCUMENT_STORE_OBJECT_PATH_STYLE": "false", "DOCUMENT_STORE_RECONCILIATION_ENABLED": "true",
        "DOCUMENT_STORE_RECONCILIATION_RUN_ON_STARTUP": "false", "DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED": "false",
        "DOCUMENT_STORE_PURGE_ENABLED": "true", "DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED": "true",
        "DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED": "true", "DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED": "true",
        "DOCUMENT_STORE_RETENTION_POLICY_VERSION": app_env[policy_keys[0]],
        "DOCUMENT_STORE_BACKUP_RETENTION_POLICY_VERSION": app_env[policy_keys[1]],
        "DOCUMENT_STORE_MAXIMUM_BACKUP_RETENTION_DAYS": "35", "DOCUMENT_STORE_ERASURE_JOURNAL_PROVIDER": "s3",
        "DOCUMENT_STORE_ERASURE_JOURNAL_REGION": REGION,
        "DOCUMENT_STORE_ERASURE_JOURNAL_BUCKET": f"jsc-public-beta-erasure-journal-{account}",
        "DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID": erasure_key,
        "DOCUMENT_STORE_ERASURE_JOURNAL_CREDENTIALS_PROVIDER": "task-role",
        "DOCUMENT_STORE_ERASURE_JOURNAL_OBJECT_LOCK_ENABLED": "true",
        "DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION": app_env[policy_keys[2]],
        "DOCUMENT_STORE_PERMANENT_ERASURE_BATCH_SIZE": "10", "DOCUMENT_STORE_PERMANENT_ERASURE_FIXED_DELAY_MS": "28800000",
        "TZ": "UTC", "AUTH_JWKS_URI": "http://127.0.0.1:1/unavailable",
        "DOCUMENT_STORE_JWT_ISSUER": "job-seeker-copilot-authentication",
        "DOCUMENT_STORE_JWT_AUDIENCE": "job-seeker-copilot-services",
        "APPLICATION_TRACKER_SERVICE_URL": "http://127.0.0.1:1", "DOCUMENT_STORE_CLAMAV_HOST": "127.0.0.1",
        "DOCUMENT_STORE_CLAMAV_PORT": "1", "DOCUMENT_STORE_CLAMAV_MAXIMUM_SIGNATURE_AGE_HOURS": "48",
        "DOCUMENT_STORE_RECONCILIATION_INITIAL_DELAY_MS": "28800000",
        "DOCUMENT_STORE_RECONCILIATION_FIXED_DELAY_MS": "28800000",
        "DOCUMENT_STORE_RETENTION_FIXED_DELAY_MS": "28800000", "DOCUMENT_STORE_UPLOAD_CLEANUP_ENABLED": "false",
        "DOCUMENT_STORE_PRODUCER_TOKEN": "invalid-restore-semantic-producer",
        "DOCUMENT_STORE_READER_TOKEN": "invalid-restore-semantic-reader",
        "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN": "invalid-restore-semantic-admin-token-0000",
        "DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY": "invalid-restore-semantic-fingerprint",
        "DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS": "",
        "APPLICATION_TRACKER_PRODUCER_TOKEN": "invalid-restore-semantic-tracker-producer",
        "APPLICATION_TRACKER_READER_TOKEN": "invalid-restore-semantic-tracker-reader",
        "ENVIRONMENT_DATA_TOKEN": "invalid-restore-semantic-environment",
    }
    require(app_env == expected_app_environment,
            "application base environment has extra, missing, or drifted settings")
    require(app_container["portMappings"] == [{
        "name": "http", "containerPort": 8089, "hostPort": 8089,
        "protocol": "tcp", "appProtocol": "http",
    }] and app_container["user"] == "10001:10001" and app_container["stopTimeout"] == 90
            and app_container["healthCheck"] == {
                "command": ["CMD-SHELL", "wget -q --spider http://127.0.0.1:8089/actuator/health/liveness || exit 1"],
                "interval": 15, "timeout": 10, "retries": 4, "startPeriod": 120,
            }, "application ports/user/health/stop settings drifted")

    verifier_definition, verifier_container, verifier_env, verifier_secrets = parsed["verifier"]
    database_names = {
        "AUTHENTICATION": "authentication", "USER_PROFILE": "user_profile",
        "JOB_SERVICE": "job_service", "DOCUMENT_GENERATION": "document_generation",
        "DOCUMENT_STORE": "document_store", "APPLICATION_TRACKER": "application_tracker",
        "PAYMENT": "payment",
    }
    expected_verifier_secrets = {}
    for upper, database in database_names.items():
        value = validate_database_secret_field(
            verifier_secrets.get(f"{upper}_PASSWORD"), database, account,
            f"verifier {upper}_PASSWORD",
        )
        expected_verifier_secrets[f"{upper}_PASSWORD"] = value
    require(verifier_secrets == expected_verifier_secrets
            and verifier_secrets["DOCUMENT_STORE_PASSWORD"] == document_secret,
            "verifier secret set is not the exact seven logical database passwords")
    expected_verifier_environment = {
        "AWS_ACCOUNT_ID": account, "AWS_REGION": REGION, "PGHOST": "invalid.restore.local",
        "PGPORT": "5432", "PGSSLMODE": "verify-full", "PGSSLROOTCERT": "/etc/jsc/rds/global-bundle.pem",
        "DOCUMENT_KMS_KEY_ARN": context["dataKmsKeyArn"],
        "ERASURE_JOURNAL_BUCKET": f"jsc-public-beta-erasure-journal-{account}",
        "ERASURE_JOURNAL_KMS_KEY_ARN": erasure_key,
        "ERASURE_JOURNAL_RETENTION_DAYS": verifier_env.get("ERASURE_JOURNAL_RETENTION_DAYS"),
        "RESTORE_SOURCE_CANARY_MARKER": "/jsc/public-beta/release/restore-source-canary",
        "RESTORE_DOCUMENT_BUCKET": "jsc-public-beta-invalid-restore", "RESTORE_DRILL_ID": "invalid-drill",
        "RESTORE_SOURCE_CANARY_ID": "invalid-canary", "RESTORE_SOURCE_EVIDENCE_SHA256": "invalid",
        "RESTORE_SOURCE_MARKER_SHA256": "invalid", "RELEASE_ID": "invalid",
        "RESTORE_REPLAY_DATABASE": "invalid_restore_replay", "RESTORE_ERASURE_OPERATION_ID": "invalid",
        "RESTORE_ERASURE_REPLAY_ID": "invalid", "SOURCE_DOCUMENT_STORE_URL": "http://127.0.0.1:1",
        "REPLAY_DOCUMENT_STORE_URL": "http://127.0.0.1:1",
        "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN": "invalid-restore-semantic-admin-token-0000",
    }
    for upper, database in database_names.items():
        expected_verifier_environment[f"{upper}_DATABASE"] = database
        expected_verifier_environment[f"{upper}_USERNAME"] = database
    require(re.fullmatch(r"(?:3[6-9]|[4-9][0-9]|[1-3][0-9]{2}|400)",
                         verifier_env.get("ERASURE_JOURNAL_RETENTION_DAYS", "")) is not None
            and verifier_env == expected_verifier_environment,
            "verifier base environment has extra, missing, or drifted settings")
    require(verifier_container["command"] == ["/opt/jsc/verify-restored-semantics.sh"]
            and verifier_container["portMappings"] == [],
            "verifier command/ports drifted")


def _policy_string_list(value: Any, label: str) -> list[str]:
    values = [value] if isinstance(value, str) else value
    require(isinstance(values, list) and values
            and all(isinstance(item, str) for item in values)
            and len(values) == len(set(values)),
            f"{label} must contain unique strings")
    return sorted(values)


def _normalise_policy(document: Any, label: str) -> dict[str, Any]:
    document = exact(document, {"Version", "Statement"}, label)
    require(document["Version"] == "2012-10-17" and isinstance(document["Statement"], list)
            and document["Statement"], f"{label} is not an IAM policy v2012-10-17")
    normalised: list[dict[str, Any]] = []
    seen_sids: set[str] = set()
    for index, raw in enumerate(document["Statement"]):
        require(isinstance(raw, dict), f"{label} statement {index} is not an object")
        allowed = {"Sid", "Effect", "Action", "Resource", "Condition", "Principal"}
        require(set(raw) <= allowed and {"Effect", "Action"} <= set(raw),
                f"{label} statement {index} has an unexpected shape")
        require(("Resource" in raw) != ("Principal" in raw),
                f"{label} statement {index} must contain exactly one of Resource/Principal")
        statement: dict[str, Any] = {
            "Effect": raw["Effect"],
            "Action": _policy_string_list(raw["Action"], f"{label} statement {index} actions"),
        }
        require(statement["Effect"] in {"Allow", "Deny"},
                f"{label} statement {index} effect is invalid")
        if "Sid" in raw:
            require(isinstance(raw["Sid"], str) and raw["Sid"] and raw["Sid"] not in seen_sids,
                    f"{label} contains a missing or duplicate Sid")
            seen_sids.add(raw["Sid"])
            statement["Sid"] = raw["Sid"]
        if "Resource" in raw:
            statement["Resource"] = _policy_string_list(
                raw["Resource"], f"{label} statement {index} resources"
            )
        else:
            principal = raw["Principal"]
            require(isinstance(principal, dict) and principal,
                    f"{label} statement {index} principal is invalid")
            statement["Principal"] = {
                kind: _policy_string_list(values, f"{label} statement {index} {kind} principals")
                for kind, values in sorted(principal.items())
            }
        if "Condition" in raw:
            condition = raw["Condition"]
            require(isinstance(condition, dict) and condition,
                    f"{label} statement {index} condition is invalid")
            normal_condition: dict[str, dict[str, list[str]]] = {}
            for operator, terms in sorted(condition.items()):
                require(isinstance(operator, str) and isinstance(terms, dict) and terms,
                        f"{label} statement {index} condition is invalid")
                normal_condition[operator] = {
                    key: _policy_string_list(
                        value, f"{label} statement {index} condition {operator}/{key}"
                    )
                    for key, value in sorted(terms.items())
                }
            statement["Condition"] = normal_condition
        normalised.append(statement)
    normalised.sort(key=lambda value: (value.get("Sid", ""), json.dumps(value, sort_keys=True)))
    return {"Version": "2012-10-17", "Statement": normalised}


def _iam_statement(
    sid: str,
    actions: str | list[str],
    resources: str | list[str],
    condition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    statement: dict[str, Any] = {
        "Sid": sid, "Effect": "Allow", "Action": actions, "Resource": resources,
    }
    if condition is not None:
        statement["Condition"] = condition
    return statement


def _expected_iam_inline_documents(context: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    account = context["accountId"]
    cluster = context["clusterArn"]
    task_resource = f"arn:aws:ecs:{REGION}:{account}:task/jsc-public-beta/*"
    marker_resource = (
        f"arn:aws:ssm:{REGION}:{account}:parameter/jsc/public-beta/restore-semantic/*/start"
    )
    source_marker_resource = (
        f"arn:aws:ssm:{REGION}:{account}:parameter/jsc/public-beta/release/restore-source-canary"
    )
    journal_bucket = context["erasureJournalBucket"]
    journal_objects = f"arn:aws:s3:::{journal_bucket}/permanent-erasures/v1/7e57c0de-*"
    restore_bucket = f"arn:aws:s3:::jsc-public-beta-restore-{account}-*"
    restore_objects = f"{restore_bucket}/restore-canary/v1/*"
    data_key = context["dataKmsKeyArn"]
    journal_key = context["erasureJournalKmsKeyArn"]
    request_child_tags = {
        "ArnEquals": {"ecs:cluster": cluster},
        "StringEquals": {
            "aws:RequestTag/Application": "Job Seeker Copilot",
            "aws:RequestTag/Environment": "public-beta",
            "aws:RequestTag/ManagedBy": "RestoreSemanticVerification",
        },
        "Null": {"aws:RequestTag/RestoreDrillId": "false"},
        "ForAllValues:StringEquals": {
            "aws:TagKeys": ["Application", "Environment", "ManagedBy", "RestoreDrillId"]
        },
    }
    request_broker_tags = json.loads(json.dumps(request_child_tags))
    request_broker_tags["StringEquals"]["aws:RequestTag/ManagedBy"] = "RestoreSemanticBroker"
    tag_child = json.loads(json.dumps(request_child_tags))
    tag_child.pop("ArnEquals")
    tag_child["StringEquals"]["ecs:CreateAction"] = "RunTask"
    tag_broker = json.loads(json.dumps(request_broker_tags))
    tag_broker.pop("ArnEquals")
    tag_broker["StringEquals"]["ecs:CreateAction"] = "RunTask"
    stop_child = {
        "ArnEquals": {"ecs:cluster": cluster},
        "StringEquals": {
            "aws:ResourceTag/Application": "Job Seeker Copilot",
            "aws:ResourceTag/Environment": "public-beta",
            "aws:ResourceTag/ManagedBy": "RestoreSemanticVerification",
        },
        "Null": {"aws:ResourceTag/RestoreDrillId": "false"},
    }
    stop_broker = json.loads(json.dumps(stop_child))
    stop_broker["StringEquals"]["aws:ResourceTag/ManagedBy"] = "RestoreSemanticBroker"
    pass_to_ecs = {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}
    document_secrets = [context["documentStoreSecretArn"]]
    clone_secrets = sorted([context["rdsMasterSecretArn"], context["documentStoreSecretArn"]])
    database_secrets = sorted(context["databaseSecretArns"])

    state_policy = {"Version": "2012-10-17", "Statement": [
        _iam_statement("RunOnlyExactSecretFreeRestoreSemanticBroker", "ecs:RunTask",
                       context["definitions"]["broker"], request_broker_tags),
        _iam_statement("TagOnlyNewRestoreSemanticBroker", "ecs:TagResource",
                       task_resource, tag_broker),
        _iam_statement("PassOnlyExactRestoreSemanticBrokerRoles", "iam:PassRole", [
            context["roles"]["brokerExecution"], context["roles"]["brokerTask"],
        ], pass_to_ecs),
        _iam_statement("ObserveOnlyBrokerTaskForSynchronousIntegration", "ecs:DescribeTasks", "*"),
        _iam_statement("StopOnlyTaggedBrokerTaskForSynchronousIntegration", "ecs:StopTask",
                       task_resource, stop_broker),
        _iam_statement("UseOnlyStepFunctionsEcsTaskEventsRule", [
            "events:DescribeRule", "events:PutRule", "events:PutTargets",
        ], f"arn:aws:events:{REGION}:{account}:rule/StepFunctionsGetEventsForECSTaskRule"),
    ]}
    broker_policy = {"Version": "2012-10-17", "Statement": [
        _iam_statement("ReadOnlyRestoreSemanticControlPlane", [
            "backup:DescribeRestoreJob", "ec2:DescribeNetworkInterfaces", "ec2:DescribePrefixLists",
            "ec2:DescribeSecurityGroupRules", "ec2:DescribeSecurityGroups", "ecs:DescribeServices",
            "ecs:DescribeTaskDefinition", "ecs:DescribeTasks", "ecs:ListServices",
            "ecs:ListTagsForResource", "ecs:ListTasks", "elasticloadbalancing:DescribeListeners",
            "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeRules",
            "rds:DescribeDBInstances", "rds:ListTagsForResource",
        ], "*"),
        _iam_statement("ReadOnlyExactRestoreBucketControls", [
            "s3:GetBucketLocation", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy",
            "s3:GetBucketPolicyStatus", "s3:GetBucketTagging", "s3:GetBucketVersioning",
            "s3:GetEncryptionConfiguration", "s3:GetPublicAccessBlock",
        ], restore_bucket),
        _iam_statement("ReadOnlyExactRestoreSourceMarker", "ssm:GetParameter", source_marker_resource),
        _iam_statement("ManageOnlyOwnedRestoreSemanticMarker", [
            "ssm:AddTagsToResource", "ssm:GetParameter", "ssm:ListTagsForResource", "ssm:PutParameter",
        ], marker_resource),
        _iam_statement("RunOnlyExactRestoreSemanticChildren", "ecs:RunTask", [
            context["definitions"]["clone"], context["definitions"]["application"],
            context["definitions"]["verifier"],
        ], request_child_tags),
        _iam_statement("TagOnlyNewRestoreSemanticChildren", "ecs:TagResource", task_resource, tag_child),
        _iam_statement("PassOnlyExactRestoreSemanticChildRoles", "iam:PassRole", [
            context["roles"]["cloneExecution"], context["roles"]["applicationExecution"],
            context["roles"]["applicationTask"], context["roles"]["verifierExecution"],
            context["roles"]["verifierTask"],
        ], pass_to_ecs),
        _iam_statement("ContainOnlyTaggedRestoreSemanticChildren", "ecs:StopTask",
                       task_resource, stop_child),
    ]}
    app_journal = {"Version": "2012-10-17", "Statement": [
        _iam_statement("WriteOnlyImmutableErasureJournalRecords", "s3:PutObject", journal_objects, {
            "StringEquals": {
                "s3:x-amz-server-side-encryption": "aws:kms",
                "s3:x-amz-server-side-encryption-aws-kms-key-id": journal_key,
            }
        }),
        _iam_statement("ReadOnlyBoundErasureJournalRecords", ["s3:GetObject", "s3:GetObjectVersion"], journal_objects),
        _iam_statement("UseOnlyErasureJournalKeyThroughS3", ["kms:Decrypt", "kms:GenerateDataKey"], journal_key, {
            "StringEquals": {
                "kms:ViaService": f"s3.{REGION}.amazonaws.com",
                "kms:EncryptionContext:aws:s3:arn": f"arn:aws:s3:::{journal_bucket}",
            }
        }),
    ]}
    verifier_read = {"Version": "2012-10-17", "Statement": [
        _iam_statement("ListOnlyRestoreCanaryVersions", "s3:ListBucketVersions", restore_bucket,
                       {"StringLike": {"s3:prefix": "restore-canary/v1/*"}}),
        _iam_statement("ReadOnlyRestoreCanaryObjects", ["s3:GetObject", "s3:GetObjectVersion"], restore_objects),
        _iam_statement("DecryptOnlyRestoredCanaryThroughS3", "kms:Decrypt", data_key, {
            "StringEquals": {"kms:ViaService": f"s3.{REGION}.amazonaws.com"},
            "StringLike": {"kms:EncryptionContext:aws:s3:arn": restore_bucket},
        }),
        _iam_statement("ListOnlyExactErasureJournalRecord", "s3:ListBucketVersions",
                       f"arn:aws:s3:::{journal_bucket}",
                       {"StringLike": {"s3:prefix": "permanent-erasures/v1/7e57c0de-*"}}),
        _iam_statement("ReadOnlyExactErasureJournalRecord",
                       ["s3:GetObject", "s3:GetObjectRetention", "s3:GetObjectVersion"], journal_objects),
        _iam_statement("DecryptOnlyErasureJournalThroughS3", "kms:Decrypt", journal_key, {
            "StringEquals": {
                "kms:ViaService": f"s3.{REGION}.amazonaws.com",
                "kms:EncryptionContext:aws:s3:arn": f"arn:aws:s3:::{journal_bucket}",
            }
        }),
    ]}
    return {
        "stateMachine": {"restore-semantic-state-machine": state_policy},
        "brokerExecution": {},
        "brokerTask": {"restore-semantic-broker": broker_policy},
        "cloneExecution": {"restore-semantic-clone-secrets": {
            "Version": "2012-10-17", "Statement": [
                _iam_statement("ReadOnlyRestoreCloneDatabaseSecrets", "secretsmanager:GetSecretValue", clone_secrets),
                _iam_statement("DecryptOnlyRestoreCloneDatabaseSecrets", "kms:Decrypt", data_key),
            ],
        }},
        "applicationExecution": {"restore-semantic-document-store-secrets": {
            "Version": "2012-10-17", "Statement": [
                _iam_statement("ReadOnlyRestoreDocumentStoreSecrets", "secretsmanager:GetSecretValue", document_secrets),
                _iam_statement("DecryptOnlyRestoreDocumentStoreSecrets", "kms:Decrypt", data_key),
            ],
        }},
        "applicationTask": {"restore-semantic-document-store-journal": app_journal},
        "verifierExecution": {"restore-semantic-verifier-secrets": {
            "Version": "2012-10-17", "Statement": [
                _iam_statement("ReadOnlyRestoreVerifierSecrets", "secretsmanager:GetSecretValue", database_secrets),
                _iam_statement("DecryptOnlyRestoreVerifierSecrets", "kms:Decrypt", data_key),
            ],
        }},
        "verifierTask": {"restore-semantic-verifier-read-only": verifier_read},
    }


def validate_iam_contracts(documents: dict[str, Any], context: dict[str, Any]) -> None:
    role_kinds = {
        "stateMachine", "brokerExecution", "brokerTask", "cloneExecution",
        "applicationExecution", "applicationTask", "verifierExecution", "verifierTask",
    }
    exact(context, {
        "accountId", "region", "stateMachineArn", "clusterArn", "roles", "definitions",
        "workloadBoundaryArn", "brokerBoundaryArn", "dataKmsKeyArn", "erasureJournalKmsKeyArn",
        "erasureJournalBucket", "rdsMasterSecretArn", "documentStoreSecretArn", "databaseSecretArns",
        "managedExecutionPolicyArn",
    }, "IAM context")
    require(context["region"] == REGION and re.fullmatch(r"[0-9]{12}", context["accountId"]) is not None,
            "IAM context account/region drifted")
    roles = exact(context["roles"], role_kinds, "IAM context roles")
    definitions = exact(context["definitions"], {"broker", "clone", "application", "verifier"},
                        "IAM context definitions")
    del definitions
    exact(documents, {"roles", "managedExecutionPolicy"}, "IAM contracts")
    actual_roles = exact(documents["roles"], role_kinds, "IAM contract roles")
    expected_inline = _expected_iam_inline_documents(context)
    managed_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    require(context["managedExecutionPolicyArn"] == managed_arn,
            "managed ECS execution policy ARN drifted")
    execution_kinds = {"brokerExecution", "cloneExecution", "applicationExecution", "verifierExecution"}
    broker_boundary_kinds = {"stateMachine", "brokerTask"}
    expected_task_trust = {
        "Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Action": "sts:AssumeRole",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
            "Condition": {
                "StringEquals": {"aws:SourceAccount": context["accountId"]},
                "ArnLike": {"aws:SourceArn": f"arn:aws:ecs:{REGION}:{context['accountId']}:*"},
            },
        }],
    }
    expected_state_trust = {
        "Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Action": "sts:AssumeRole",
            "Principal": {"Service": "states.amazonaws.com"},
            "Condition": {
                "StringEquals": {"aws:SourceAccount": context["accountId"]},
                "ArnEquals": {"aws:SourceArn": context["stateMachineArn"]},
            },
        }],
    }
    for kind in sorted(role_kinds):
        contract = exact(actual_roles[kind], {"getRole", "inlinePolicyNames", "attachedPolicies", "inlineDocuments"},
                         f"{kind} IAM contract")
        get_role = contract["getRole"]
        require(isinstance(get_role, dict) and isinstance(get_role.get("Role"), dict),
                f"{kind} get-role response is invalid")
        role = get_role["Role"]
        require(role.get("Arn") == roles[kind]
                and role.get("RoleName") == roles[kind].rsplit("/", 1)[-1],
                f"{kind} role ARN/name drifted")
        expected_boundary = (
            context["brokerBoundaryArn"] if kind in broker_boundary_kinds
            else context["workloadBoundaryArn"]
        )
        require(role.get("PermissionsBoundary") == {
            "PermissionsBoundaryType": "Policy", "PermissionsBoundaryArn": expected_boundary,
        }, f"{kind} permissions-boundary binding drifted")
        expected_trust = expected_state_trust if kind == "stateMachine" else expected_task_trust
        require(_normalise_policy(role.get("AssumeRolePolicyDocument"), f"{kind} trust")
                == _normalise_policy(expected_trust, f"expected {kind} trust"),
                f"{kind} trust policy drifted")
        expected_names = sorted(expected_inline[kind])
        require(contract["inlinePolicyNames"] == expected_names,
                f"{kind} inline policy names drifted")
        inline_documents = exact(contract["inlineDocuments"], set(expected_names),
                                 f"{kind} inline documents")
        for name in expected_names:
            require(_normalise_policy(inline_documents[name], f"{kind}/{name}")
                    == _normalise_policy(expected_inline[kind][name], f"expected {kind}/{name}"),
                    f"{kind}/{name} full policy document drifted")
        expected_attached = [managed_arn] if kind in execution_kinds else []
        require(contract["attachedPolicies"] == expected_attached,
                f"{kind} attached policy set drifted")

    managed = exact(documents["managedExecutionPolicy"], {"metadata", "version"},
                    "managed ECS execution policy")
    metadata = managed["metadata"]
    require(isinstance(metadata, dict) and isinstance(metadata.get("Policy"), dict),
            "managed ECS execution policy metadata is invalid")
    policy = metadata["Policy"]
    require(policy.get("Arn") == managed_arn and isinstance(policy.get("DefaultVersionId"), str)
            and policy["DefaultVersionId"], "managed ECS execution policy metadata drifted")
    version = managed["version"]
    require(isinstance(version, dict) and isinstance(version.get("PolicyVersion"), dict)
            and version["PolicyVersion"].get("VersionId") == policy["DefaultVersionId"],
            "managed ECS execution policy default-version binding drifted")
    expected_managed = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow",
        "Action": [
            "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability",
            "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage",
            "logs:CreateLogStream", "logs:PutLogEvents",
        ],
        "Resource": "*",
    }]}
    require(_normalise_policy(version["PolicyVersion"].get("Document"), "managed ECS execution policy document")
            == _normalise_policy(expected_managed, "expected managed ECS execution policy document"),
            "managed ECS execution policy full document drifted")


def validate_readiness(value: Any, label: str) -> dict[str, Any]:
    readiness = exact(value, {
        "schemaVersion", "enabled", "ready", "status", "policyVersion",
        "backupRetentionPolicyVersion", "recoveryDays", "maximumBackupRetentionDays",
        "backupExpiryEvidenceRequired", "recoveryJournalWritePending",
        "recoveryJournalEvidenceMissing", "liveErasureReconciliationPending",
        "restoreJournalReadPending", "restoreReplayPending", "backupRetentionPending",
        "backupRetentionOverdue",
    }, label)
    require(readiness["schemaVersion"] == "document-permanent-erasure-readiness.v3",
            f"{label} is not readiness v3")
    require(readiness["enabled"] is True and readiness["ready"] is True
            and readiness["status"] == "READY", f"{label} is not READY")
    for key in ("policyVersion", "backupRetentionPolicyVersion"):
        require(isinstance(readiness[key], str) and 1 <= len(readiness[key]) <= 128
                and readiness[key] not in {"NOT_CONFIGURED", "TODO", "TBD"},
                f"{label} {key} is not configured")
    require(readiness["recoveryDays"] == 30, f"{label} recoveryDays is not the reviewed value")
    require(readiness["maximumBackupRetentionDays"] == 35,
            f"{label} maximumBackupRetentionDays is not the reviewed value")
    require(readiness["backupExpiryEvidenceRequired"] is True,
            f"{label} does not require backup-expiry evidence")
    for key in (
        "recoveryJournalWritePending", "recoveryJournalEvidenceMissing",
        "liveErasureReconciliationPending", "restoreJournalReadPending",
        "restoreReplayPending", "backupRetentionOverdue",
    ):
        require(readiness[key] == 0 and type(readiness[key]) is int,
                f"{label} has a blocking {key} count")
    require(readiness["backupRetentionPending"] == 1
            and type(readiness["backupRetentionPending"]) is int,
            f"{label} must contain exactly one synthetic retention-pending operation")
    return readiness


def validate(
    evidence: dict[str, Any],
    *,
    expected_account_id: str | None = None,
    expected_drill_id: str | None = None,
    expected_release_id: str | None = None,
    expected_release_attestation_id: str | None = None,
    expected_source_evidence_sha256: str | None = None,
    expected_source_marker_sha256: str | None = None,
    expected_document_store_image_digest: str | None = None,
    expected_release_operator_image_digest: str | None = None,
    expected_verifier_task_arn: str | None = None,
    expected_execution_arn: str | None = None,
    expected_marker_sha256: str | None = None,
    expected_runtime_binding_sha256: str | None = None,
) -> None:
    exact(evidence, {
        "schemaVersion", "status", "environment", "drillId", "startedAt", "completedAt",
        "verifierTaskArn", "releaseCandidate", "orchestrationBinding", "runtimeBinding", "networkIsolation",
        "publicSafety", "restoreControlPlane", "restoreSource", "databaseVerification", "documentVerification",
        "erasureReplayVerification", "scopeLimitations",
    }, "semantic evidence")
    require(evidence["schemaVersion"] == "jsc-public-beta-restore-semantic-observation.v1",
            "semantic evidence schema mismatch")
    require(evidence["status"] == "VERIFIED", "restore semantic observation is not VERIFIED")
    require(evidence["environment"] == "public-beta", "semantic evidence environment mismatch")
    drill = evidence["drillId"]
    require(isinstance(drill, str) and DRILL_ID.fullmatch(drill) is not None,
            "semantic drill ID is malformed")
    if expected_drill_id is not None:
        require(drill == expected_drill_id, "semantic evidence used another drill ID")
    started = timestamp(evidence["startedAt"], "startedAt")
    completed = timestamp(evidence["completedAt"], "completedAt")
    require(started <= completed and completed - started <= dt.timedelta(hours=8),
            "semantic verification exceeded the 8-hour RTO")
    require(completed <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
            "semantic verification completion is in the future")

    candidate = exact(evidence["releaseCandidate"], {"releaseId", "releaseAttestationId"},
                      "semantic release candidate")
    require(isinstance(candidate["releaseId"], str)
            and RELEASE_ID.fullmatch(candidate["releaseId"]) is not None,
            "semantic release ID is malformed")
    attestation = sha256(candidate["releaseAttestationId"], "semantic release attestation")
    if expected_release_id is not None:
        require(candidate["releaseId"] == expected_release_id,
                "semantic evidence used another release candidate")
    if expected_release_attestation_id is not None:
        require(attestation == expected_release_attestation_id,
                "semantic evidence used another release attestation")

    orchestration = exact(evidence["orchestrationBinding"], {
        "stateMachineArn", "executionArn", "executionStatus", "stateMachineType",
        "stateMachineRoleArn", "brokerTaskArn", "brokerTaskDefinitionArn",
        "brokerExecutionRoleArn", "brokerTaskRoleArn", "brokerImageDigest",
        "brokerInjectedSecretCount", "brokerTaskStoppedSuccessfully",
        "securityCriticalStateMachineContractVerified", "brokerRuntimeBindingsVerified",
        "expectedIamBoundaryBindingsVerified", "expectedInlinePolicyNamesAndActionsVerified",
        "noDangerousIamActionsVerified", "durableMarkerName", "durableMarkerSchemaVersion",
        "durableMarkerSha256", "durableMarkerRetained", "markerPhase", "markerAttempt",
        "inputBindingSha256", "operationId", "restoreReplayId", "replayDatabase",
    }, "semantic orchestration binding")
    state_machine_match = re.fullmatch(
        rf"arn:aws:states:{REGION}:([0-9]{{12}}):stateMachine:jsc-public-beta-restore-semantic",
        str(orchestration["stateMachineArn"]),
    )
    require(state_machine_match is not None, "semantic state machine ARN is not exact")
    account_id = state_machine_match.group(1)
    require(orchestration["executionArn"].startswith(
        f"arn:aws:states:{REGION}:{account_id}:execution:jsc-public-beta-restore-semantic:"
    ), "semantic execution ARN is not bound to the exact state machine")
    execution_name = orchestration["executionArn"].rsplit(":", 1)[-1]
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", execution_name) is not None,
            "semantic execution name is malformed")
    if expected_execution_arn is not None:
        require(orchestration["executionArn"] == expected_execution_arn,
                "semantic evidence used another state-machine execution")
    require(orchestration["executionStatus"] == "SUCCEEDED",
            "semantic state-machine execution did not succeed")
    require(orchestration["stateMachineType"] == "STANDARD",
            "semantic state machine is not STANDARD")
    require(orchestration["stateMachineRoleArn"]
            == f"arn:aws:iam::{account_id}:role/jsc-public-beta-restore-semantic-state-machine",
            "semantic state-machine role is not exact")
    require(orchestration["brokerExecutionRoleArn"]
            == f"arn:aws:iam::{account_id}:role/jsc-public-beta-restore-semantic-broker-execution",
            "semantic broker execution role is not exact")
    require(orchestration["brokerTaskRoleArn"]
            == f"arn:aws:iam::{account_id}:role/jsc-public-beta-restore-semantic-broker-task",
            "semantic broker task role is not exact")
    task_pattern = re.compile(
        rf"arn:aws:ecs:{REGION}:{account_id}:task/jsc-public-beta/[0-9a-f]{{32}}"
    )
    require(task_pattern.fullmatch(str(orchestration["brokerTaskArn"])) is not None,
            "semantic broker task ARN is malformed or outside the exact cluster")
    require(re.fullmatch(
        rf"arn:aws:ecs:{REGION}:{account_id}:task-definition/"
        r"jsc-public-beta-restore-semantic-broker:[1-9][0-9]*",
        str(orchestration["brokerTaskDefinitionArn"]),
    ) is not None, "semantic broker task definition is outside the exact family")
    broker_digest = image_digest(orchestration["brokerImageDigest"], "semantic broker image")
    require(orchestration["brokerInjectedSecretCount"] == 0
            and type(orchestration["brokerInjectedSecretCount"]) is int,
            "semantic broker received an injected secret")
    for key in (
        "brokerTaskStoppedSuccessfully", "securityCriticalStateMachineContractVerified",
        "brokerRuntimeBindingsVerified", "expectedIamBoundaryBindingsVerified",
        "expectedInlinePolicyNamesAndActionsVerified", "noDangerousIamActionsVerified",
        "durableMarkerRetained",
    ):
        require(orchestration[key] is True, f"semantic orchestration verification failed: {key}")
    require(orchestration["durableMarkerName"]
            == f"/jsc/public-beta/restore-semantic/{drill}/start",
            "semantic durable marker path is outside the exact drill")
    require(orchestration["durableMarkerSchemaVersion"]
            == "jsc-public-beta-restore-semantic-start-marker.v2",
            "semantic durable marker schema mismatch")
    marker_sha = sha256(orchestration["durableMarkerSha256"], "semantic durable marker SHA-256")
    if expected_marker_sha256 is not None:
        require(marker_sha == expected_marker_sha256,
                "semantic evidence used another durable marker")
    require(orchestration["markerPhase"] == "COMPLETED",
            "semantic durable marker was not completed")
    integer(orchestration["markerAttempt"], "semantic durable marker attempt", 1, 3)
    sha256(orchestration["inputBindingSha256"], "semantic input binding SHA-256")

    runtime = exact(evidence["runtimeBinding"], {
        "cloneTaskArn", "sourceApplicationTaskArn", "replayApplicationTaskArn",
        "cloneTaskDefinitionArn", "applicationTaskDefinitionArn", "verifierTaskDefinitionArn",
        "documentStoreImageDigest", "releaseOperatorImageDigest", "vpcId",
        "restoreDatabaseSecurityGroupId", "semanticSecurityGroupId", "restoredDatabaseArn",
        "restoredDatabaseEndpoint", "applicationTasksUseDedicatedJournalOnlyRole",
        "verifierHasNoJournalPut", "cloneHasNoTaskRole", "actualTaskImageDigestsVerified",
        "securityCriticalTaskDefinitionContractsVerified", "exactTaskTagsVerified", "exactTaskLifecycleVerified",
    }, "semantic runtime binding")
    for key in ("cloneTaskArn", "sourceApplicationTaskArn", "replayApplicationTaskArn"):
        require(task_pattern.fullmatch(str(runtime[key])) is not None,
                f"semantic runtime {key} is malformed or outside the exact cluster")
    verifier_match = task_pattern.fullmatch(str(evidence["verifierTaskArn"]))
    require(verifier_match is not None, "verifierTaskArn is malformed or outside the exact cluster")
    if expected_verifier_task_arn is not None:
        require(evidence["verifierTaskArn"] == expected_verifier_task_arn,
                "semantic evidence used another verifier task")
    if expected_account_id is not None:
        require(re.fullmatch(r"[0-9]{12}", expected_account_id) is not None,
                "expected account ID is malformed")
        require(account_id == expected_account_id, "semantic evidence used another AWS account")
    require(len({runtime["cloneTaskArn"], runtime["sourceApplicationTaskArn"],
                 runtime["replayApplicationTaskArn"], evidence["verifierTaskArn"],
                 orchestration["brokerTaskArn"]}) == 5,
            "semantic task ARNs are not five distinct tasks")

    definition_families = {
        "cloneTaskDefinitionArn": "jsc-public-beta-restore-semantic-clone",
        "applicationTaskDefinitionArn": "jsc-public-beta-restore-semantic-document-store",
        "verifierTaskDefinitionArn": "jsc-public-beta-restore-semantic-verifier",
    }
    for key, family in definition_families.items():
        pattern = rf"arn:aws:ecs:{REGION}:{account_id}:task-definition/{family}:[1-9][0-9]*"
        require(re.fullmatch(pattern, str(runtime[key])) is not None,
                f"semantic runtime {key} is outside the exact task-definition family")
    document_digest = image_digest(runtime["documentStoreImageDigest"], "Document Store image")
    operator_digest = image_digest(runtime["releaseOperatorImageDigest"], "release-operator image")
    require(broker_digest == operator_digest,
            "semantic broker did not use the exact release-operator image")
    require(document_digest != operator_digest, "semantic application and operator images are not distinct")
    if expected_document_store_image_digest is not None:
        require(document_digest == expected_document_store_image_digest,
                "semantic evidence used another Document Store image")
    if expected_release_operator_image_digest is not None:
        require(operator_digest == expected_release_operator_image_digest,
                "semantic evidence used another release-operator image")
    require(re.fullmatch(r"vpc-[0-9a-f]{8,17}", str(runtime["vpcId"])) is not None,
            "semantic VPC binding is malformed")
    for key in ("restoreDatabaseSecurityGroupId", "semanticSecurityGroupId"):
        require(re.fullmatch(r"sg-[0-9a-f]{8,17}", str(runtime[key])) is not None,
                f"semantic runtime {key} is malformed")
    require(runtime["restoreDatabaseSecurityGroupId"] != runtime["semanticSecurityGroupId"],
            "restore database and semantic security groups are not distinct")
    require(runtime["restoredDatabaseArn"]
            == f"arn:aws:rds:{REGION}:{account_id}:db:jsc-public-beta-restore-{drill}",
            "restored database ARN is outside the exact drill")
    endpoint = str(runtime["restoredDatabaseEndpoint"])
    require(re.fullmatch(
        rf"jsc-public-beta-restore-{re.escape(drill)}\.[a-z0-9.-]+\.{REGION}\.rds\.amazonaws\.com",
        endpoint,
    ) is not None, "restored database endpoint is outside the exact private restore")
    for key in (
        "applicationTasksUseDedicatedJournalOnlyRole", "verifierHasNoJournalPut",
        "cloneHasNoTaskRole", "actualTaskImageDigestsVerified", "securityCriticalTaskDefinitionContractsVerified",
        "exactTaskTagsVerified", "exactTaskLifecycleVerified",
    ):
        require(runtime[key] is True, f"semantic runtime role isolation failed: {key}")
    if expected_runtime_binding_sha256 is not None:
        sha256(expected_runtime_binding_sha256, "expected runtime-binding SHA-256")
        require(canonical_sha256(runtime) == expected_runtime_binding_sha256,
                "semantic runtime binding differs from the observer's exact binding")

    network = exact(evidence["networkIsolation"], {
        "vpcId", "restoreDatabaseSecurityGroupId", "semanticSecurityGroupId",
        "brokerSecurityGroupId", "privateSubnetIds", "staticRulesTerraformOwned",
        "exactReviewedRuleTuplesVerified", "securityGroupRuleCount",
        "semanticDatabaseSecurityGroupRuleCount", "brokerSecurityGroupRuleCount",
        "restoreDatabaseIngressRuleCount",
        "restoreDatabaseEgressRuleCount", "semanticIngressRuleCount", "semanticEgressRuleCount",
        "restoreDatabasePublicIngressRuleCount", "semanticEniCountBeforeStart",
        "semanticEniCountAfterContainment", "brokerEniCountAfterCompletion",
        "restoredDatabasePubliclyAccessible", "restoredDatabaseUsesOnlyRestoreSecurityGroup",
        "semanticTasksUseOnlySemanticSecurityGroup", "brokerTaskUsesOnlyBrokerSecurityGroup",
        "taskPrivateSubnetBindingsVerified",
    }, "semantic network isolation")
    require(network["vpcId"] == runtime["vpcId"]
            and network["restoreDatabaseSecurityGroupId"] == runtime["restoreDatabaseSecurityGroupId"]
            and network["semanticSecurityGroupId"] == runtime["semanticSecurityGroupId"],
            "network isolation is not bound to the exact runtime VPC/security groups")
    require(re.fullmatch(r"sg-[0-9a-f]{8,17}", str(network["brokerSecurityGroupId"])) is not None
            and network["brokerSecurityGroupId"] not in {
                network["restoreDatabaseSecurityGroupId"], network["semanticSecurityGroupId"]
            }, "semantic broker security group is malformed or not distinct")
    subnets = network["privateSubnetIds"]
    require(isinstance(subnets, list) and len(subnets) == 2 and len(set(subnets)) == 2
            and all(isinstance(value, str)
                    and re.fullmatch(r"subnet-[0-9a-f]{8,17}", value) is not None
                    for value in subnets), "semantic private subnet binding is not exactly two subnets")
    require(network["staticRulesTerraformOwned"] is True,
            "semantic security-group rules are not Terraform-owned static rules")
    require(network["exactReviewedRuleTuplesVerified"] is True,
            "semantic network does not contain the exact reviewed rule tuples")
    require(network["securityGroupRuleCount"] == 10 and type(network["securityGroupRuleCount"]) is int,
            "semantic network does not contain exactly ten reviewed rules")
    require(network["semanticDatabaseSecurityGroupRuleCount"] == 7
            and type(network["semanticDatabaseSecurityGroupRuleCount"]) is int,
            "semantic database/child boundary does not contain exactly seven reviewed rules")
    require(network["brokerSecurityGroupRuleCount"] == 3
            and type(network["brokerSecurityGroupRuleCount"]) is int,
            "semantic broker boundary does not contain exactly three reviewed rules")
    expected_rule_counts = {
        "restoreDatabaseIngressRuleCount": 1,
        "restoreDatabaseEgressRuleCount": 0,
        "semanticIngressRuleCount": 1,
        "semanticEgressRuleCount": 5,
        "restoreDatabasePublicIngressRuleCount": 0,
        "semanticEniCountBeforeStart": 0,
        "semanticEniCountAfterContainment": 0,
        "brokerEniCountAfterCompletion": 0,
    }
    for key, expected in expected_rule_counts.items():
        require(network[key] == expected and type(network[key]) is int,
                f"semantic network {key} is not the reviewed exact value")
    require(network["restoredDatabasePubliclyAccessible"] is False,
            "restored database is publicly accessible")
    for key in (
        "restoredDatabaseUsesOnlyRestoreSecurityGroup", "semanticTasksUseOnlySemanticSecurityGroup",
        "brokerTaskUsesOnlyBrokerSecurityGroup", "taskPrivateSubnetBindingsVerified",
    ):
        require(network[key] is True, f"semantic network binding failed: {key}")

    public = exact(evidence["publicSafety"], {
        "publicEntrypointFixed503", "applicationDesiredCount", "runningApplicationTaskCount",
        "pendingApplicationTaskCount", "semanticTasksNotAttachedToPublicFleet",
    }, "public safety")
    require(public["publicEntrypointFixed503"] is True, "public entrypoint was not fixed 503")
    require(public["applicationDesiredCount"] == 0 and type(public["applicationDesiredCount"]) is int,
            "public application desired count was not zero")
    require(public["runningApplicationTaskCount"] == 0
            and type(public["runningApplicationTaskCount"]) is int,
            "public application fleet was running")
    require(public["pendingApplicationTaskCount"] == 0
            and type(public["pendingApplicationTaskCount"]) is int,
            "public application fleet had pending tasks")
    require(public["semanticTasksNotAttachedToPublicFleet"] is True,
            "semantic tasks were attached to the public fleet")

    restore_control = exact(evidence["restoreControlPlane"], {
        "restoreJobsExactBindingsVerified", "restoredDatabaseExactControlsVerified",
        "restoredBucketExactControlsVerified", "restoreOwnershipTagsVerified",
    }, "semantic restore control plane")
    for key, value in restore_control.items():
        require(value is True, f"semantic restore control-plane verification failed: {key}")

    source = exact(evidence["restoreSource"], {
        "canaryId", "sourceEvidenceSha256", "sourceMarkerSha256",
    }, "semantic restore source")
    canary = source["canaryId"]
    require(isinstance(canary, str) and DRILL_ID.fullmatch(canary) is not None,
            "restore-source canary ID is malformed")
    source_evidence_sha = sha256(source["sourceEvidenceSha256"], "restore-source evidence SHA-256")
    marker_sha = sha256(source["sourceMarkerSha256"], "restore-source marker SHA-256")
    if expected_source_evidence_sha256 is not None:
        require(source_evidence_sha == expected_source_evidence_sha256,
                "semantic evidence used another restore-source artifact")
    if expected_source_marker_sha256 is not None:
        require(marker_sha == expected_source_marker_sha256,
                "semantic evidence used another restore-source marker")

    database = exact(evidence["databaseVerification"], {
        "logicalDatabases", "exactCanaryRowCounts", "exactCanaryRowsVerified",
        "preOperationReplayCloneVerified", "preApplicationSchemaFingerprint",
        "schemaAndFlywayFingerprintUnchangedAfterCandidateStartup", "nonPrivilegedRolesVerified",
        "tlsConnectionsVerified", "flywayHistoriesVerified", "emptyBootstrapDomainInvariantsVerified",
        "paymentLedgerSeedAndEmptyStateReconciled",
    }, "semantic database verification")
    require(database["logicalDatabases"] == DATABASES,
            "semantic verification did not cover the exact seven logical databases")
    canary_row_keys = {
        "authentication", "userProfile", "jobService", "documentGeneration",
        "documentStore", "applicationTracker", "payment", "replayClone",
    }
    exact(database["exactCanaryRowCounts"], canary_row_keys, "semantic database canary rows")
    require(all(database["exactCanaryRowCounts"][name] == 1
                and type(database["exactCanaryRowCounts"][name]) is int for name in canary_row_keys),
            "semantic database canary rows are not exactly one per logical database")
    operation = evidence["erasureReplayVerification"].get("operationId") \
        if isinstance(evidence["erasureReplayVerification"], dict) else None
    require(isinstance(operation, str) and RESERVED_OPERATION_UUID.fullmatch(operation) is not None,
            "semantic operation ID is not in the reserved UUIDv4 namespace")
    replay_database_seed = hashlib.sha256(
        f"{drill}:{candidate['releaseId']}:{marker_sha}".encode("utf-8")
    ).hexdigest()
    expected_operation = (
        f"7e57c0de-{replay_database_seed[:4]}-4{replay_database_seed[4:7]}-"
        f"8{replay_database_seed[7:10]}-{replay_database_seed[10:22]}"
    )
    replay_seed = hashlib.sha256(
        f"replay:{drill}:{candidate['releaseId']}:{marker_sha}".encode("utf-8")
    ).hexdigest()
    expected_replay = (
        f"{replay_seed[:8]}-{replay_seed[8:12]}-4{replay_seed[12:15]}-"
        f"8{replay_seed[15:18]}-{replay_seed[18:30]}"
    )
    require(operation == expected_operation and orchestration["operationId"] == expected_operation,
            "semantic operation ID is not deterministically bound to this drill")
    require(orchestration["restoreReplayId"] == expected_replay,
            "semantic replay ID is not deterministically bound to this drill")
    require(orchestration["replayDatabase"] == f"restore_replay_{replay_database_seed[:12]}",
            "replay clone database is not bound with 48 bits of drill entropy")
    sha256(database["preApplicationSchemaFingerprint"], "pre-application schema fingerprint")
    for key in set(database) - {"logicalDatabases", "exactCanaryRowCounts", "preApplicationSchemaFingerprint"}:
        require(database[key] is True, f"semantic database verification failed: {key}")

    documents = exact(evidence["documentVerification"], {
        "mappingType", "bucket", "key", "destinationVersionCount", "deleteMarkerCount",
        "generations", "newDestinationVersionIdsVerified",
        "customerGeneratedDocumentMappingClaimed",
    }, "semantic document verification")
    require(documents["mappingType"] == "NON_CUSTOMER_RESTORE_CANARY",
            "semantic document evidence is not the non-customer restore canary")
    require(documents["bucket"] == f"jsc-public-beta-restore-{account_id}-{drill}",
            "semantic document bucket is outside the exact drill")
    require(documents["key"] == f"restore-canary/v1/{canary}/document.json",
            "semantic document key is outside the exact canary")
    require(documents["destinationVersionCount"] == 2
            and type(documents["destinationVersionCount"]) is int,
            "restored canary destination version count is not two")
    require(documents["deleteMarkerCount"] == 0 and type(documents["deleteMarkerCount"]) is int,
            "restored canary contains a delete marker")
    generations = documents["generations"]
    require(isinstance(generations, list) and len(generations) == 2,
            "restored canary generation evidence is not exactly two entries")
    generation_hashes: list[str] = []
    for expected_generation, generation in enumerate(generations, start=1):
        exact(generation, {
            "generation", "versionId", "sourceSha256", "sizeBytes", "bucketKeyEnabled",
            "exactSourceMetadataVerified", "payloadSha256Verified",
        }, f"restored canary generation {expected_generation}")
        require(generation["generation"] == expected_generation
                and type(generation["generation"]) is int,
                "restored canary generations are not exactly ordered")
        require(isinstance(generation["versionId"], str)
                and OPAQUE_VERSION.fullmatch(generation["versionId"]) is not None,
                "restored generation destination VersionId is malformed")
        generation_hashes.append(sha256(generation["sourceSha256"],
                                        f"restored generation {expected_generation} SHA-256"))
        integer(generation["sizeBytes"], f"restored generation {expected_generation} size", 1, 4096)
        for key in (
            "bucketKeyEnabled", "exactSourceMetadataVerified",
            "payloadSha256Verified",
        ):
            require(generation[key] is True,
                    f"restored generation {expected_generation} verification failed: {key}")
    require(len(set(generation_hashes)) == 2, "restored canary payload generations are not distinct")
    require(len({generation["versionId"] for generation in generations}) == 2,
            "restored canary VersionIds are not distinct")
    require(documents["newDestinationVersionIdsVerified"] is True,
            "restored canary destination VersionIds were not verified")
    require(documents["customerGeneratedDocumentMappingClaimed"] is False,
            "semantic evidence overclaims customer document mapping")

    replay = exact(evidence["erasureReplayVerification"], {
        "attempt", "sourceOperationPreexistingBeforeAttempt", "replayOperationPreexistingBeforeAttempt",
        "operationId", "restoreReplayId", "syntheticOwnerSha256", "documentCount",
        "objectScopeCount", "sourceCanonicalResponseSha256", "replayCanonicalResponseSha256",
        "sourceCanonicalRowSha256", "replayCanonicalRowSha256", "journalContractSha256",
        "sourceCanonicalRetryVerified", "replayCanonicalRetryVerified",
        "sourceReplayJournalContractEqual", "journal", "externalJournalWriteVerified",
        "externalJournalReadVerified", "absentOperationReconstructed", "exactReplayVerified",
        "restoreReplayEvidenceRecorded", "restoreReplayObjectErasedAtVerified",
        "sourceReadiness", "replayReadiness",
    }, "semantic erasure/replay verification")
    replay_attempt = integer(replay["attempt"], "semantic erasure/replay attempt", 1, 3)
    require(replay_attempt == orchestration["markerAttempt"],
            "raw erasure/replay attempt differs from the durable marker")
    source_preexisting = replay["sourceOperationPreexistingBeforeAttempt"]
    replay_preexisting = replay["replayOperationPreexistingBeforeAttempt"]
    require(type(source_preexisting) is bool and type(replay_preexisting) is bool,
            "pre-attempt operation state must be boolean")
    require(not replay_preexisting or source_preexisting,
            "replay operation cannot preexist without the source operation")
    require(replay_attempt > 1 or (not source_preexisting and not replay_preexisting),
            "attempt one cannot contain a preexisting restore operation")
    require(replay["operationId"] == operation, "semantic operation ID changed during validation")
    replay_id = replay["restoreReplayId"]
    require(isinstance(replay_id, str) and UUID_V4.fullmatch(replay_id) is not None
            and replay_id != operation, "restore replay ID is not a distinct UUIDv4")
    require(replay_id == expected_replay, "restore replay ID changed between marker and verifier")
    sha256(replay["syntheticOwnerSha256"], "synthetic owner SHA-256")
    require(replay["documentCount"] == 0 and type(replay["documentCount"]) is int,
            "synthetic operation was not an empty document scope")
    require(replay["objectScopeCount"] == 0 and type(replay["objectScopeCount"]) is int,
            "synthetic operation was not an empty object scope")
    for key in (
        "sourceCanonicalResponseSha256", "replayCanonicalResponseSha256",
        "sourceCanonicalRowSha256", "replayCanonicalRowSha256", "journalContractSha256",
    ):
        sha256(replay[key], f"semantic {key}")
    journal = exact(replay["journal"], {
        "bucket", "key", "versionId", "versionCount", "deleteMarkerCount", "contentSha256",
        "sizeBytes", "objectLockMode", "minimumRetentionDays", "bucketKeyEnabled",
        "contentSha256MetadataVerified", "unchangedAfterSourceAndReplayRetries",
        "writeByCandidateApplicationVerified", "exactVersionReadBySeparateVerifierVerified",
    }, "semantic immutable journal")
    require(journal["bucket"] == f"jsc-public-beta-erasure-journal-{account_id}",
            "semantic journal bucket is outside the exact account")
    require(journal["key"] == f"permanent-erasures/v1/{operation}.json",
            "semantic journal key is outside the reserved operation")
    require(isinstance(journal["versionId"], str)
            and OPAQUE_VERSION.fullmatch(journal["versionId"]) is not None,
            "semantic journal VersionId is malformed")
    require(journal["versionCount"] == 1 and type(journal["versionCount"]) is int,
            "semantic journal does not have exactly one immutable version")
    require(journal["deleteMarkerCount"] == 0 and type(journal["deleteMarkerCount"]) is int,
            "semantic journal contains a delete marker")
    sha256(journal["contentSha256"], "semantic journal content SHA-256")
    integer(journal["sizeBytes"], "semantic journal size", 1, 65536)
    require(journal["objectLockMode"] == "GOVERNANCE", "semantic journal Object Lock mode is invalid")
    integer(journal["minimumRetentionDays"], "semantic journal minimum retention", 36, 400)
    for key in (
        "bucketKeyEnabled", "contentSha256MetadataVerified",
        "unchangedAfterSourceAndReplayRetries", "writeByCandidateApplicationVerified",
        "exactVersionReadBySeparateVerifierVerified",
    ):
        require(journal[key] is True, f"semantic journal verification failed: {key}")
    for key in (
        "externalJournalWriteVerified", "externalJournalReadVerified", "absentOperationReconstructed",
        "exactReplayVerified", "restoreReplayEvidenceRecorded", "restoreReplayObjectErasedAtVerified",
        "sourceCanonicalRetryVerified", "replayCanonicalRetryVerified",
        "sourceReplayJournalContractEqual",
    ):
        require(replay[key] is True, f"semantic erasure/replay verification failed: {key}")
    source_readiness = validate_readiness(replay["sourceReadiness"], "source readiness")
    replay_readiness = validate_readiness(replay["replayReadiness"], "replay readiness")
    require(source_readiness == replay_readiness,
            "source and replay readiness are not the same exact reviewed configuration/state")

    require(evidence["scopeLimitations"] == SCOPE_LIMITATIONS,
            "semantic evidence limitations are incomplete, reordered, or overclaim scope")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--run-task-events", type=Path)
    parser.add_argument("--run-task-tasks", type=Path)
    parser.add_argument("--run-task-context", type=Path)
    parser.add_argument("--task-definitions", type=Path)
    parser.add_argument("--task-definition-context", type=Path)
    parser.add_argument("--iam-contracts", type=Path)
    parser.add_argument("--iam-context", type=Path)
    parser.add_argument("--expected-account-id")
    parser.add_argument("--expected-drill-id")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-release-attestation-id")
    parser.add_argument("--expected-source-evidence-sha256")
    parser.add_argument("--expected-source-marker-sha256")
    parser.add_argument("--expected-document-store-image-digest")
    parser.add_argument("--expected-release-operator-image-digest")
    parser.add_argument("--expected-verifier-task-arn")
    parser.add_argument("--expected-execution-arn")
    parser.add_argument("--expected-marker-sha256")
    parser.add_argument("--expected-runtime-binding-sha256")
    args = parser.parse_args()
    try:
        runtime_inputs = (args.run_task_events, args.run_task_tasks, args.run_task_context)
        if any(runtime_inputs):
            require(all(runtime_inputs), "all RunTask validation inputs are required together")
            events_document = load(args.run_task_events)
            exact(events_document, {"events"}, "CloudTrail RunTask input")
            tasks_document = load(args.run_task_tasks)
            context_document = load(args.run_task_context)
            validate_run_task_history(events_document["events"], tasks_document, context_document)
            print("restore semantic RunTask history valid (raw CloudTrail values were not emitted)")
            return 0
        task_definition_inputs = (args.task_definitions, args.task_definition_context)
        if any(task_definition_inputs):
            require(all(task_definition_inputs), "both task-definition validation inputs are required")
            validate_task_definitions(
                load(args.task_definitions), load(args.task_definition_context)
            )
            print("restore semantic task definitions valid (live values were not emitted)")
            return 0
        iam_inputs = (args.iam_contracts, args.iam_context)
        if any(iam_inputs):
            require(all(iam_inputs), "both IAM validation inputs are required")
            validate_iam_contracts(load(args.iam_contracts), load(args.iam_context))
            print("restore semantic IAM contracts valid (live values were not emitted)")
            return 0
        require(args.evidence is not None, "--evidence is required outside RunTask validation mode")
        validate(
            load(args.evidence),
            expected_account_id=args.expected_account_id,
            expected_drill_id=args.expected_drill_id,
            expected_release_id=args.expected_release_id,
            expected_release_attestation_id=args.expected_release_attestation_id,
            expected_source_evidence_sha256=args.expected_source_evidence_sha256,
            expected_source_marker_sha256=args.expected_source_marker_sha256,
            expected_document_store_image_digest=args.expected_document_store_image_digest,
            expected_release_operator_image_digest=args.expected_release_operator_image_digest,
            expected_verifier_task_arn=args.expected_verifier_task_arn,
            expected_execution_arn=args.expected_execution_arn,
            expected_marker_sha256=args.expected_marker_sha256,
            expected_runtime_binding_sha256=args.expected_runtime_binding_sha256,
        )
    except (SemanticEvidenceError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"restore semantic evidence invalid: {exc}", file=sys.stderr)
        return 2
    print("restore semantic observation valid (offline validation; no live verification claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
