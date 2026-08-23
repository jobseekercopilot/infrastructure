#!/usr/bin/env python3
"""Validate the protected, non-customer source-canary and paired-backup evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class SourceEvidenceError(RuntimeError):
    pass


DATABASES = [
    "authentication",
    "user_profile",
    "job_service",
    "document_generation",
    "document_store",
    "application_tracker",
    "payment",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceEvidenceError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"unsafe JSON input: {path}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, f"duplicate JSON key: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(value, dict), f"JSON input must be an object: {path}")
    return value


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, f"{label} has an incomplete or unexpected shape")
    return value


def canonical_bytes(value: dict[str, Any], newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + suffix).encode()


def timestamp(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str), f"{label} must be a timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceEvidenceError(f"{label} must be an ISO-8601 UTC timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} must include an explicit UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def validate_marker(marker: dict[str, Any], account_id: str) -> None:
    exact(marker, {
        "schemaVersion", "releaseId", "releaseAttestationId", "canaryId", "preparedAt",
        "databaseBootstrapMarkerVerified", "flywayHistoriesVerified", "logicalDatabases", "document",
    }, "restore-source canary marker")
    require(marker["schemaVersion"] == "jsc-public-beta-restore-source-canary.v1", "source marker schema mismatch")
    require(re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}", str(marker["releaseId"])) is not None,
            "source marker release ID is malformed")
    require(re.fullmatch(r"[0-9a-f]{64}", str(marker["releaseAttestationId"])) is not None,
            "source marker release attestation is malformed")
    require(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{6,30}[a-z0-9])", str(marker["canaryId"])) is not None,
            "source marker canary ID is malformed")
    timestamp(marker["preparedAt"], "source marker preparedAt")
    require(marker["databaseBootstrapMarkerVerified"] is True, "source database bootstrap was not verified")
    require(marker["flywayHistoriesVerified"] is True, "source Flyway histories were not verified")
    require(marker["logicalDatabases"] == DATABASES, "source canary does not cover all seven logical databases")
    document = exact(marker["document"], {"bucket", "key", "versions"}, "source document marker")
    require(document["bucket"] == f"jsc-public-beta-documents-{account_id}", "source document bucket is out of scope")
    require(document["key"] == f"restore-canary/v1/{marker['canaryId']}/document.json",
            "source document key is out of scope")
    versions = document["versions"]
    require(isinstance(versions, list) and len(versions) == 2, "source document needs exactly two bound versions")
    for expected_generation, version in enumerate(versions, start=1):
        exact(version, {"generation", "versionId", "sha256", "sizeBytes"}, "source document version")
        require(version["generation"] == expected_generation, "source document generations are not ordered")
        require(isinstance(version["versionId"], str) and 1 <= len(version["versionId"]) <= 1024,
                "source document VersionId is invalid")
        require(re.fullmatch(r"[0-9a-f]{64}", str(version["sha256"])) is not None,
                "source document checksum is malformed")
        require(type(version["sizeBytes"]) is int and 0 < version["sizeBytes"] <= 4096,
                "source document is empty or unbounded")
    require(versions[0]["versionId"] != versions[1]["versionId"],
            "source document versions are not distinct")
    require(versions[0]["sha256"] != versions[1]["sha256"],
            "source document payload generations are not distinct")


def validate(
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    provenance: dict[str, Any],
    candidate_build_run_id: str,
    expected_rds_recovery_point: str | None = None,
    expected_s3_recovery_point: str | None = None,
    expected_canary_id: str | None = None,
) -> None:
    exact(evidence, {
        "schemaVersion", "status", "environment", "createdAt", "releaseCandidate", "sourceCanary",
        "livePreconditions", "backupJobs", "recoveryPointTags",
    }, "restore-source evidence")
    require(evidence["schemaVersion"] == "jsc-public-beta-restore-source-evidence.v1", "source evidence schema mismatch")
    require(evidence["status"] == "PAIRED_BACKUPS_COMPLETED", "paired source backups are not complete")
    require(evidence["environment"] == "public-beta", "source evidence environment mismatch")
    created_at = timestamp(evidence["createdAt"], "source evidence createdAt")

    candidate = exact(evidence["releaseCandidate"], {
        "releaseId", "buildRunId", "infrastructureRevision", "imageManifestSha256", "releaseAttestationId",
    }, "source release candidate")
    release_id = manifest.get("releaseId")
    require(candidate["releaseId"] == release_id == provenance.get("releaseId"),
            "source evidence used another release candidate")
    require(candidate["buildRunId"] == candidate_build_run_id and re.fullmatch(r"[0-9]+", candidate_build_run_id),
            "source evidence used another candidate build run")
    require(provenance.get("buildPurpose") == "restore-candidate", "source provenance is not a restore candidate")
    require(candidate["infrastructureRevision"] == provenance.get("infrastructureRevision")
            and re.fullmatch(r"[0-9a-f]{40}", str(candidate["infrastructureRevision"])),
            "source evidence infrastructure revision mismatch")
    require(candidate["imageManifestSha256"] == provenance.get("imageManifestSha256"),
            "source evidence manifest provenance mismatch")
    require(re.fullmatch(r"[0-9a-f]{64}", str(candidate["imageManifestSha256"])),
            "source image-manifest checksum is malformed")

    source = exact(evidence["sourceCanary"], {"markerSha256", "marker"}, "source canary evidence")
    marker = source["marker"]
    account_match = re.search(r":([0-9]{12}):", evidence["backupJobs"]["rds"].get("resourceArn", ""))
    require(account_match is not None, "source RDS resource ARN is malformed")
    account_id = account_match.group(1)
    validate_marker(marker, account_id)
    if expected_canary_id is not None:
        require(marker["canaryId"] == expected_canary_id, "source evidence used another canary ID")
    require(marker["releaseId"] == candidate["releaseId"], "source marker used another release ID")
    require(marker["releaseAttestationId"] == candidate["releaseAttestationId"],
            "source marker used another release attestation")
    marker_sha = hashlib.sha256(canonical_bytes(marker)).hexdigest()
    require(source["markerSha256"] == marker_sha, "source marker checksum mismatch")
    marker_prepared_at = timestamp(marker["preparedAt"], "source marker preparedAt")

    preconditions = exact(evidence["livePreconditions"], {
        "publicEntrypointFixed503", "applicationDesiredCount", "databaseBootstrapMarkerVerified",
        "flywayHistoriesVerified", "canaryReverifiedAfterQuiesce",
    }, "source live preconditions")
    require(preconditions == {
        "publicEntrypointFixed503": True,
        "applicationDesiredCount": 0,
        "databaseBootstrapMarkerVerified": True,
        "flywayHistoriesVerified": True,
        "canaryReverifiedAfterQuiesce": True,
    }, "source was not dark, quiesced and independently reverified before backup")

    jobs = exact(evidence["backupJobs"], {"rds", "s3"}, "source backup jobs")
    vault = f"arn:aws:backup:eu-west-2:{account_id}:backup-vault:jsc-public-beta-customer-data"
    role = f"arn:aws:iam::{account_id}:role/jsc-public-beta-backup"
    creations: list[dt.datetime] = []
    for kind, resource_type in (("rds", "RDS"), ("s3", "S3")):
        job = exact(jobs[kind], {
            "jobId", "state", "resourceType", "resourceArn", "recoveryPointArn", "creationDate",
            "completionDate", "deleteAfterDays", "backupVaultArn", "iamRoleArn",
        }, f"{kind} source backup job")
        require(re.fullmatch(r"[A-Za-z0-9-]{8,128}", str(job["jobId"])) is not None,
                f"{kind} source backup job ID is malformed")
        require(job["state"] == "COMPLETED" and job["resourceType"] == resource_type,
                f"{kind} source backup did not complete")
        require(job["backupVaultArn"] == vault and job["iamRoleArn"] == role,
                f"{kind} source backup escaped the exact vault/service role")
        require(job["deleteAfterDays"] == 35,
                f"{kind} source backup does not retain the reviewed 35-day lifecycle")
        if kind == "rds":
            recovery_pattern = re.compile(
                rf"arn:aws:rds:eu-west-2:{account_id}:snapshot:awsbackup:job-[A-Za-z0-9-]+"
            )
        else:
            recovery_pattern = re.compile(
                rf"arn:aws:backup:eu-west-2:{account_id}:recovery-point:[A-Za-z0-9-]+"
            )
        require(recovery_pattern.fullmatch(str(job["recoveryPointArn"])) is not None,
                f"{kind} source recovery point ARN has the wrong live resource shape")
        started = timestamp(job["creationDate"], f"{kind} source backup creationDate")
        completed = timestamp(job["completionDate"], f"{kind} source backup completionDate")
        require(marker_prepared_at <= started <= completed <= created_at,
                f"{kind} source backup predates the exact canary or has incoherent timestamps")
        require(completed - started <= dt.timedelta(hours=8), f"{kind} source backup exceeded the 8-hour RTO")
        creations.append(started)
    require(jobs["rds"]["resourceArn"] == f"arn:aws:rds:eu-west-2:{account_id}:db:jsc-public-beta-postgres",
            "RDS source backup used another database")
    require(jobs["s3"]["resourceArn"] == f"arn:aws:s3:::jsc-public-beta-documents-{account_id}",
            "S3 source backup used another bucket")
    require(abs((creations[0] - creations[1]).total_seconds()) <= 600,
            "paired source backup starts exceed the ten-minute capture window")
    if expected_rds_recovery_point is not None:
        require(jobs["rds"]["recoveryPointArn"] == expected_rds_recovery_point,
                "selected RDS recovery point is not the canary-bound source backup")
    if expected_s3_recovery_point is not None:
        require(jobs["s3"]["recoveryPointArn"] == expected_s3_recovery_point,
                "selected S3 recovery point is not the canary-bound source backup")

    tags = exact(evidence["recoveryPointTags"], {
        "Application", "Environment", "RestoreTest", "ReleaseId", "RestoreSourceCanary", "RestoreSourceMarker",
    }, "source recovery-point tags")
    require(tags == {
        "Application": "Job Seeker Copilot",
        "Environment": "public-beta",
        "RestoreTest": "quarterly",
        "ReleaseId": candidate["releaseId"],
        "RestoreSourceCanary": marker["canaryId"],
        "RestoreSourceMarker": marker_sha,
    }, "source recovery-point tags do not bind the exact canary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--candidate-build-run-id", required=True)
    parser.add_argument("--expected-rds-recovery-point")
    parser.add_argument("--expected-s3-recovery-point")
    parser.add_argument("--expected-canary-id")
    args = parser.parse_args()
    try:
        evidence = load(args.evidence.resolve())
        manifest_path = args.image_manifest.resolve()
        manifest = load(manifest_path)
        provenance = load(args.provenance.resolve())
        validate(
            evidence,
            manifest,
            provenance,
            args.candidate_build_run_id,
            expected_rds_recovery_point=args.expected_rds_recovery_point,
            expected_s3_recovery_point=args.expected_s3_recovery_point,
            expected_canary_id=args.expected_canary_id,
        )
        require(evidence["releaseCandidate"]["imageManifestSha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "source evidence does not bind the exact image-manifest bytes")
    except (SourceEvidenceError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"restore-source evidence invalid: {exc}", file=sys.stderr)
        return 2
    print("restore-source canary and paired-backup evidence valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
