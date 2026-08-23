#!/usr/bin/env python3
"""Validate non-secret, source-bound public-beta restore/replay evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    pass


PLACEHOLDER = re.compile(r"(?i)(?:^|[^a-z0-9])(?:todo|tbd|pending|placeholder|unknown)(?:$|[^a-z0-9])")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"unsafe evidence file: {path}")
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, f"duplicate evidence key: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(value, dict), "restore evidence must be an object")
    return value


def timestamp(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str), f"{label} must be a UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label} must be a UTC timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0), f"{label} must be UTC")
    return parsed


def exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, f"{label} has an incomplete or unexpected shape")
    return value


def validate(
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    expected_infrastructure_revision: str | None = None,
    require_cleanup: bool = False,
) -> None:
    exact_keys(evidence, {
        "schemaVersion", "status", "environment", "drillId", "startedAt", "completedAt",
        "reviewedBy", "reviewedOn", "evidenceReference", "releaseCandidate", "recoveryWindow",
        "isolatedDestinations", "restoreJobs", "s3RestoreControls", "databaseVerification",
        "documentVerification", "erasureReplayVerification", "cleanupStatus",
    }, "restore evidence")
    require(evidence["schemaVersion"] == "jsc-public-beta-restore-drill-evidence.v1", "restore evidence schema mismatch")
    require(evidence["status"] == "VERIFIED", "restore drill is not VERIFIED")
    require(evidence["environment"] == "public-beta", "restore evidence environment mismatch")
    drill = evidence["drillId"]
    require(isinstance(drill, str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{6,30}[a-z0-9])", drill),
            "restore drill ID is malformed")
    started = timestamp(evidence["startedAt"], "startedAt")
    completed = timestamp(evidence["completedAt"], "completedAt")
    require(started <= completed and completed - started <= dt.timedelta(hours=8), "restore drill exceeded the 8-hour RTO")
    require(completed <= dt.datetime.now(dt.timezone.utc), "restore drill completion cannot be in the future")
    require(isinstance(evidence["reviewedBy"], str) and len(evidence["reviewedBy"].strip()) >= 3,
            "restore evidence reviewer is absent")
    require(PLACEHOLDER.search(evidence["reviewedBy"]) is None, "restore evidence reviewer is a placeholder")
    reviewed_on = dt.date.fromisoformat(evidence["reviewedOn"])
    require(reviewed_on >= completed.date(), "restore review predates drill completion")
    require(reviewed_on <= dt.datetime.now(dt.timezone.utc).date(), "restore review cannot be in the future")
    require(isinstance(evidence["evidenceReference"], str) and len(evidence["evidenceReference"].strip()) >= 8,
            "restore evidence reference is absent")
    require(PLACEHOLDER.search(evidence["evidenceReference"]) is None,
            "restore evidence reference is a placeholder")

    source = manifest["dependencyEvidence"]["documentStorePermanentErasure"]
    image = manifest["images"]["document-store-service"]
    candidate = exact_keys(evidence["releaseCandidate"], {
        "releaseId", "infrastructureRevision", "documentStoreRevision",
        "documentStoreOpenApiSha256", "documentStoreImageDigest",
    }, "release candidate")
    require(
        isinstance(candidate["releaseId"], str)
        and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}", candidate["releaseId"]) is not None,
        "restore candidate release ID is malformed",
    )
    require(candidate["releaseId"] == manifest.get("releaseId"),
            "restore evidence used another release candidate")
    require(
        isinstance(candidate["infrastructureRevision"], str)
        and re.fullmatch(r"[0-9a-f]{40}", candidate["infrastructureRevision"]) is not None
        and candidate["infrastructureRevision"] != "0" * 40,
        "restore candidate infrastructure revision is not pinned",
    )
    if expected_infrastructure_revision is not None:
        require(
            candidate["infrastructureRevision"] == expected_infrastructure_revision,
            "restore evidence used another Infrastructure revision",
        )
    require(candidate["documentStoreRevision"] == source["revision"], "restore evidence used another Document Store revision")
    require(candidate["documentStoreOpenApiSha256"] == source["openApiSha256"], "restore evidence used another OpenAPI contract")
    require(candidate["documentStoreImageDigest"] == image["digest"], "restore evidence used another Document Store image")

    window = exact_keys(evidence["recoveryWindow"], {
        "rdsRecoveryPointArn", "s3RecoveryPointArn", "rdsCompletedAt", "s3CompletedAt", "maximumSkewMinutes",
    }, "recovery window")
    for label in ("rdsRecoveryPointArn", "s3RecoveryPointArn"):
        require(re.fullmatch(r"arn:aws:backup:eu-west-2:[0-9]{12}:recovery-point:[A-Za-z0-9-]+", str(window[label])),
                f"{label} is malformed")
    rds_completed = timestamp(window["rdsCompletedAt"], "rdsCompletedAt")
    s3_completed = timestamp(window["s3CompletedAt"], "s3CompletedAt")
    require(rds_completed <= started and s3_completed <= started,
            "selected recovery points were not complete before the drill started")
    require(started - rds_completed <= dt.timedelta(days=35)
            and started - s3_completed <= dt.timedelta(days=35),
            "selected recovery points are outside the reviewed 35-day backup window")
    skew = abs((rds_completed - s3_completed).total_seconds()) / 60
    require(type(window["maximumSkewMinutes"]) is int and 0 <= window["maximumSkewMinutes"] <= 1440,
            "recovery-window skew bound is invalid")
    require(skew <= window["maximumSkewMinutes"], "RDS and S3 recovery points exceed the reviewed consistency window")

    destinations = exact_keys(evidence["isolatedDestinations"], {
        "rdsIdentifier", "s3Bucket", "privateRds", "isolatedSecurityGroupVerified", "notAttachedToPublicFleet",
    }, "isolated destinations")
    require(destinations["rdsIdentifier"] == f"jsc-public-beta-restore-{drill}", "RDS destination is out of scope")
    require(re.fullmatch(rf"jsc-public-beta-restore-[0-9]{{12}}-{re.escape(drill)}", str(destinations["s3Bucket"])),
            "S3 destination is out of scope")
    require(all(destinations[key] is True for key in ("privateRds", "isolatedSecurityGroupVerified", "notAttachedToPublicFleet")),
            "restore destinations were not proven isolated")

    jobs = exact_keys(evidence["restoreJobs"], {"rds", "s3"}, "restore jobs")
    for kind in ("rds", "s3"):
        job = exact_keys(jobs[kind], {"jobId", "status", "startedAt", "completedAt"}, f"{kind} restore job")
        require(re.fullmatch(r"[A-Za-z0-9-]{8,128}", str(job["jobId"])), f"{kind} restore job ID is malformed")
        require(job["status"] == "COMPLETED", f"{kind} restore job did not complete")
        job_started = timestamp(job["startedAt"], f"{kind}.startedAt")
        job_completed = timestamp(job["completedAt"], f"{kind}.completedAt")
        require(started <= job_started <= job_completed <= completed, f"{kind} restore timestamps are incoherent")

    s3 = exact_keys(evidence["s3RestoreControls"], {
        "newBucket", "restoreAcls", "encryptionType", "kmsKeyVerified", "restoreLatestVersionsUpTo",
        "versioningEnabled", "bucketOwnerEnforced", "blockPublicAccess", "tlsPolicyVerified", "exactKmsPolicyVerified",
    }, "S3 restore controls")
    require(s3["newBucket"] is False and s3["restoreAcls"] is False, "S3 restore must use a pre-created ACL-free bucket")
    require(s3["encryptionType"] == "SSE-KMS" and s3["kmsKeyVerified"] is True, "S3 restore encryption is unverified")
    require(s3["restoreLatestVersionsUpTo"] == "all", "S3 restore did not include every object version")
    require(all(s3[key] is True for key in (
        "versioningEnabled", "bucketOwnerEnforced", "blockPublicAccess", "tlsPolicyVerified", "exactKmsPolicyVerified",
    )), "S3 destination controls are incomplete")

    database = exact_keys(evidence["databaseVerification"], {
        "logicalDatabaseCount", "rolesVerified", "flywayHistoriesVerified", "domainInvariantsVerified",
        "paymentLedgerReconciled", "syntheticJourneyVerified",
    }, "database verification")
    require(database["logicalDatabaseCount"] == 7, "all seven logical databases were not verified")
    require(all(database[key] is True for key in set(database) - {"logicalDatabaseCount"}),
            "database restore verification is incomplete")
    documents = exact_keys(evidence["documentVerification"], {
        "metadataObjectMappingVerified", "sampleChecksumsVerified", "retentionReportOnlyVerified", "integrityIncidentOpen",
    }, "document verification")
    require(all(documents[key] is True for key in (
        "metadataObjectMappingVerified", "sampleChecksumsVerified", "retentionReportOnlyVerified",
    )) and documents["integrityIncidentOpen"] is False, "document restore verification is incomplete")

    replay = exact_keys(evidence["erasureReplayVerification"], {
        "externalJournalReadVerified", "exactReplayVerified", "schemaVersion", "enabled", "ready", "status",
        "recoveryJournalWritePending", "recoveryJournalEvidenceMissing", "liveErasureReconciliationPending",
        "restoreJournalReadPending", "restoreReplayPending", "backupRetentionPending", "backupRetentionOverdue",
    }, "erasure replay verification")
    require(replay["externalJournalReadVerified"] is True and replay["exactReplayVerified"] is True,
            "isolated permanent-erasure replay was not verified")
    require(replay["schemaVersion"] == "document-permanent-erasure-readiness.v3", "readiness v3 evidence is required")
    require(replay["enabled"] is True and replay["ready"] is True and replay["status"] == "READY",
            "restored Document Store was not ready")
    for key in (
        "recoveryJournalWritePending", "recoveryJournalEvidenceMissing", "liveErasureReconciliationPending",
        "restoreJournalReadPending", "restoreReplayPending", "backupRetentionOverdue",
    ):
        require(replay[key] == 0, f"restore evidence has a blocking {key} count")
    require(type(replay["backupRetentionPending"]) is int and replay["backupRetentionPending"] >= 0,
            "backupRetentionPending must remain a non-negative informational count")
    require(evidence["cleanupStatus"] in {"PENDING_SEPARATE_APPROVAL", "COMPLETED"}, "cleanup status is invalid")
    if require_cleanup:
        require(evidence["cleanupStatus"] == "COMPLETED", "release requires separately approved restore cleanup to be complete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--expected-infrastructure-revision")
    parser.add_argument("--require-cleanup", action="store_true")
    args = parser.parse_args()
    try:
        if args.expected_infrastructure_revision is not None:
            require(
                re.fullmatch(r"[0-9a-f]{40}", args.expected_infrastructure_revision) is not None,
                "expected Infrastructure revision is malformed",
            )
        validate(
            load(args.evidence.resolve()),
            load(args.image_manifest.resolve()),
            expected_infrastructure_revision=args.expected_infrastructure_revision,
            require_cleanup=args.require_cleanup,
        )
    except (EvidenceError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"restore evidence invalid: {exc}", file=sys.stderr)
        return 1
    print("restore drill evidence valid (no AWS calls; no customer payloads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
