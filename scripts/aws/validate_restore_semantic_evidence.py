#!/usr/bin/env python3
"""Fail closed on public-beta isolated-restore semantic observation evidence.

This validator makes no AWS calls.  The separately authorised observation job is
responsible for collecting the control-plane facts represented by this artifact.
"""

from __future__ import annotations

import argparse
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
    "CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED",
    "CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED",
    "RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY",
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
    expected_runtime_binding_sha256: str | None = None,
) -> None:
    exact(evidence, {
        "schemaVersion", "status", "environment", "drillId", "startedAt", "completedAt",
        "verifierTaskArn", "releaseCandidate", "runtimeBinding", "networkIsolation",
        "publicSafety", "restoreSource", "databaseVerification", "documentVerification",
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

    runtime = exact(evidence["runtimeBinding"], {
        "cloneTaskArn", "sourceApplicationTaskArn", "replayApplicationTaskArn",
        "cloneTaskDefinitionArn", "applicationTaskDefinitionArn", "verifierTaskDefinitionArn",
        "documentStoreImageDigest", "releaseOperatorImageDigest", "vpcId",
        "restoreDatabaseSecurityGroupId", "semanticSecurityGroupId", "restoredDatabaseArn",
        "restoredDatabaseEndpoint", "applicationTasksUseDedicatedJournalOnlyRole",
        "verifierHasNoJournalPut", "cloneHasNoTaskRole",
    }, "semantic runtime binding")
    account_pattern = r"([0-9]{12})"
    task_pattern = re.compile(rf"arn:aws:ecs:{REGION}:{account_pattern}:task/jsc-public-beta/[0-9a-f]{{32}}")
    task_accounts: set[str] = set()
    for key in ("cloneTaskArn", "sourceApplicationTaskArn", "replayApplicationTaskArn"):
        match = task_pattern.fullmatch(str(runtime[key]))
        require(match is not None, f"semantic runtime {key} is malformed or outside the exact cluster")
        task_accounts.add(match.group(1))
    verifier_match = task_pattern.fullmatch(str(evidence["verifierTaskArn"]))
    require(verifier_match is not None, "verifierTaskArn is malformed or outside the exact cluster")
    task_accounts.add(verifier_match.group(1))
    if expected_verifier_task_arn is not None:
        require(evidence["verifierTaskArn"] == expected_verifier_task_arn,
                "semantic evidence used another verifier task")
    require(len(task_accounts) == 1, "semantic task ARNs span AWS accounts")
    account_id = next(iter(task_accounts))
    if expected_account_id is not None:
        require(re.fullmatch(r"[0-9]{12}", expected_account_id) is not None,
                "expected account ID is malformed")
        require(account_id == expected_account_id, "semantic evidence used another AWS account")
    require(len({runtime["cloneTaskArn"], runtime["sourceApplicationTaskArn"],
                 runtime["replayApplicationTaskArn"], evidence["verifierTaskArn"]}) == 4,
            "semantic task ARNs are not four distinct tasks")

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
    for key in ("applicationTasksUseDedicatedJournalOnlyRole", "verifierHasNoJournalPut", "cloneHasNoTaskRole"):
        require(runtime[key] is True, f"semantic runtime role isolation failed: {key}")
    if expected_runtime_binding_sha256 is not None:
        sha256(expected_runtime_binding_sha256, "expected runtime-binding SHA-256")
        require(canonical_sha256(runtime) == expected_runtime_binding_sha256,
                "semantic runtime binding differs from the observer's exact binding")

    network = exact(evidence["networkIsolation"], {
        "vpcId", "restoreDatabaseSecurityGroupId", "semanticSecurityGroupId",
        "staticRulesTerraformOwned", "exactReviewedRuleTuplesVerified", "securityGroupRuleCount",
        "restoreDatabaseIngressRuleCount",
        "restoreDatabaseEgressRuleCount", "semanticIngressRuleCount", "semanticEgressRuleCount",
        "restoreDatabasePublicIngressRuleCount", "semanticEniCountBeforeStart",
        "restoredDatabasePubliclyAccessible", "restoredDatabaseUsesOnlyRestoreSecurityGroup",
        "semanticTasksUseOnlySemanticSecurityGroup",
    }, "semantic network isolation")
    require(network["vpcId"] == runtime["vpcId"]
            and network["restoreDatabaseSecurityGroupId"] == runtime["restoreDatabaseSecurityGroupId"]
            and network["semanticSecurityGroupId"] == runtime["semanticSecurityGroupId"],
            "network isolation is not bound to the exact runtime VPC/security groups")
    require(network["staticRulesTerraformOwned"] is True,
            "semantic security-group rules are not Terraform-owned static rules")
    require(network["exactReviewedRuleTuplesVerified"] is True,
            "semantic network does not contain the exact reviewed rule tuples")
    require(network["securityGroupRuleCount"] == 7 and type(network["securityGroupRuleCount"]) is int,
            "semantic network does not contain exactly seven reviewed rules")
    expected_rule_counts = {
        "restoreDatabaseIngressRuleCount": 1,
        "restoreDatabaseEgressRuleCount": 0,
        "semanticIngressRuleCount": 1,
        "semanticEgressRuleCount": 5,
        "restoreDatabasePublicIngressRuleCount": 0,
        "semanticEniCountBeforeStart": 0,
    }
    for key, expected in expected_rule_counts.items():
        require(network[key] == expected and type(network[key]) is int,
                f"semantic network {key} is not the reviewed exact value")
    require(network["restoredDatabasePubliclyAccessible"] is False,
            "restored database is publicly accessible")
    for key in ("restoredDatabaseUsesOnlyRestoreSecurityGroup", "semanticTasksUseOnlySemanticSecurityGroup"):
        require(network[key] is True, f"semantic network binding failed: {key}")

    public = exact(evidence["publicSafety"], {
        "publicEntrypointFixed503", "applicationDesiredCount", "runningApplicationTaskCount",
        "semanticTasksNotAttachedToPublicFleet",
    }, "public safety")
    require(public["publicEntrypointFixed503"] is True, "public entrypoint was not fixed 503")
    require(public["applicationDesiredCount"] == 0 and type(public["applicationDesiredCount"]) is int,
            "public application desired count was not zero")
    require(public["runningApplicationTaskCount"] == 0
            and type(public["runningApplicationTaskCount"]) is int,
            "public application fleet was running")
    require(public["semanticTasksNotAttachedToPublicFleet"] is True,
            "semantic tasks were attached to the public fleet")

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
        "replayCloneDatabase", "preOperationReplayCloneVerified", "nonPrivilegedRolesVerified",
        "tlsConnectionsVerified", "flywayHistoriesVerified", "emptyBootstrapDomainInvariantsVerified",
        "paymentLedgerSeedAndEmptyStateReconciled",
    }, "semantic database verification")
    require(database["logicalDatabases"] == DATABASES,
            "semantic verification did not cover the exact seven logical databases")
    exact(database["exactCanaryRowCounts"], set(DATABASES), "semantic database canary rows")
    require(all(database["exactCanaryRowCounts"][name] == 1
                and type(database["exactCanaryRowCounts"][name]) is int for name in DATABASES),
            "semantic database canary rows are not exactly one per logical database")
    operation = evidence["erasureReplayVerification"].get("operationId") \
        if isinstance(evidence["erasureReplayVerification"], dict) else None
    require(isinstance(operation, str) and RESERVED_OPERATION_UUID.fullmatch(operation) is not None,
            "semantic operation ID is not in the reserved UUIDv4 namespace")
    operation_hex = operation.replace("-", "")
    require(database["replayCloneDatabase"] == f"restore_replay_{operation_hex[:12]}",
            "replay clone database is not operation-bound")
    for key in set(database) - {"logicalDatabases", "exactCanaryRowCounts", "replayCloneDatabase"}:
        require(database[key] is True, f"semantic database verification failed: {key}")

    documents = exact(evidence["documentVerification"], {
        "mappingType", "bucket", "key", "dataKmsKeyArn", "destinationVersionIds",
        "destinationVersionCount", "deleteMarkerCount", "generations",
        "newDestinationVersionIdsVerified", "generationMetadataSizeAndSha256Verified",
        "customerMetadataObjectMappingClaimed", "customerGeneratedDocumentMappingClaimed",
        "customerObjectErasureClaimed",
    }, "semantic document verification")
    require(documents["mappingType"] == "NON_CUSTOMER_RESTORE_CANARY",
            "semantic document evidence is not the non-customer restore canary")
    require(documents["bucket"] == f"jsc-public-beta-restore-{account_id}-{drill}",
            "semantic document bucket is outside the exact drill")
    require(documents["key"] == f"restore-canary/v1/{canary}/document.json",
            "semantic document key is outside the exact canary")
    require(re.fullmatch(rf"arn:aws:kms:{REGION}:{account_id}:key/[0-9a-f-]{{36}}",
                         str(documents["dataKmsKeyArn"])) is not None,
            "semantic document KMS key is malformed or in another account")
    version_ids = documents["destinationVersionIds"]
    require(isinstance(version_ids, list) and len(version_ids) == 2
            and all(isinstance(value, str) and OPAQUE_VERSION.fullmatch(value) is not None
                    for value in version_ids)
            and len(set(version_ids)) == 2,
            "restored canary does not have exactly two distinct destination VersionIds")
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
            "generation", "versionId", "sha256", "sizeBytes", "contentType",
            "serverSideEncryption", "exactKmsKeyVerified", "bucketKeyEnabled",
            "contentSha256MetadataVerified", "payloadSha256Verified",
        }, f"restored canary generation {expected_generation}")
        require(generation["generation"] == expected_generation
                and type(generation["generation"]) is int,
                "restored canary generations are not exactly ordered")
        require(generation["versionId"] == version_ids[expected_generation - 1],
                "restored generation does not bind its destination VersionId")
        generation_hashes.append(sha256(generation["sha256"],
                                        f"restored generation {expected_generation} SHA-256"))
        integer(generation["sizeBytes"], f"restored generation {expected_generation} size", 1, 4096)
        require(generation["contentType"] == "application/json",
                "restored generation content type is not application/json")
        require(generation["serverSideEncryption"] == "aws:kms",
                "restored generation is not SSE-KMS")
        for key in (
            "exactKmsKeyVerified", "bucketKeyEnabled", "contentSha256MetadataVerified",
            "payloadSha256Verified",
        ):
            require(generation[key] is True,
                    f"restored generation {expected_generation} verification failed: {key}")
    require(len(set(generation_hashes)) == 2, "restored canary payload generations are not distinct")
    for key in ("newDestinationVersionIdsVerified", "generationMetadataSizeAndSha256Verified"):
        require(documents[key] is True, f"restored canary verification failed: {key}")
    for key in (
        "customerMetadataObjectMappingClaimed", "customerGeneratedDocumentMappingClaimed",
        "customerObjectErasureClaimed",
    ):
        require(documents[key] is False, f"semantic evidence overclaims non-customer scope: {key}")

    replay = exact(evidence["erasureReplayVerification"], {
        "operationId", "restoreReplayId", "syntheticOwnerSha256", "documentCount",
        "objectScopeCount", "customerObjectErasureClaimed", "journal",
        "externalJournalWriteVerified", "externalJournalReadVerified",
        "absentOperationReconstructed", "exactReplayVerified", "restoreReplayEvidenceRecorded",
        "restoreReplayObjectErasedAtVerified", "sourceRetryIdempotent", "replayRetryIdempotent",
        "journalVersionHistoryUnchangedAfterRetries", "sourceReadiness", "replayReadiness",
    }, "semantic erasure/replay verification")
    require(replay["operationId"] == operation, "semantic operation ID changed during validation")
    replay_id = replay["restoreReplayId"]
    require(isinstance(replay_id, str) and UUID_V4.fullmatch(replay_id) is not None
            and replay_id != operation, "restore replay ID is not a distinct UUIDv4")
    sha256(replay["syntheticOwnerSha256"], "synthetic owner SHA-256")
    require(replay["documentCount"] == 0 and type(replay["documentCount"]) is int,
            "synthetic operation was not an empty document scope")
    require(replay["objectScopeCount"] == 0 and type(replay["objectScopeCount"]) is int,
            "synthetic operation was not an empty object scope")
    require(replay["customerObjectErasureClaimed"] is False,
            "semantic erasure evidence overclaims customer object erasure")
    journal = exact(replay["journal"], {
        "bucket", "key", "versionId", "versionCount", "deleteMarkerCount", "contentSha256",
        "sizeBytes", "objectLockMode", "minimumRetentionDays",
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
    for key in ("writeByCandidateApplicationVerified", "exactVersionReadBySeparateVerifierVerified"):
        require(journal[key] is True, f"semantic journal verification failed: {key}")
    for key in (
        "externalJournalWriteVerified", "externalJournalReadVerified", "absentOperationReconstructed",
        "exactReplayVerified", "restoreReplayEvidenceRecorded", "restoreReplayObjectErasedAtVerified",
        "sourceRetryIdempotent", "replayRetryIdempotent",
        "journalVersionHistoryUnchangedAfterRetries",
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
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-account-id")
    parser.add_argument("--expected-drill-id")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-release-attestation-id")
    parser.add_argument("--expected-source-evidence-sha256")
    parser.add_argument("--expected-source-marker-sha256")
    parser.add_argument("--expected-document-store-image-digest")
    parser.add_argument("--expected-release-operator-image-digest")
    parser.add_argument("--expected-verifier-task-arn")
    parser.add_argument("--expected-runtime-binding-sha256")
    args = parser.parse_args()
    try:
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
            expected_runtime_binding_sha256=args.expected_runtime_binding_sha256,
        )
    except (SemanticEvidenceError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"restore semantic evidence invalid: {exc}", file=sys.stderr)
        return 2
    print("restore semantic observation valid (offline validation; no live verification claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
