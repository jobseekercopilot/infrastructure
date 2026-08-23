#!/usr/bin/env python3
"""Render exact source-canary/paired-backup evidence after protected live checks."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from validate_restore_source_evidence import SourceEvidenceError, canonical_bytes, load, require, validate


def normalise_timestamp(value: Any, label: str) -> str:
    require(isinstance(value, str), f"{label} is not an ISO-8601 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceEvidenceError(f"{label} is not an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} has no UTC offset")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def backup_job(raw: dict[str, Any], expected_type: str) -> dict[str, Any]:
    require(raw.get("State") == "COMPLETED", f"{expected_type} backup job is not complete")
    require(raw.get("ResourceType") == expected_type, f"backup job is not {expected_type}")
    return {
        "jobId": raw.get("BackupJobId"),
        "state": raw.get("State"),
        "resourceType": raw.get("ResourceType"),
        "resourceArn": raw.get("ResourceArn"),
        "recoveryPointArn": raw.get("RecoveryPointArn"),
        "creationDate": normalise_timestamp(raw.get("CreationDate"), f"{expected_type} CreationDate"),
        "completionDate": normalise_timestamp(raw.get("CompletionDate"), f"{expected_type} CompletionDate"),
        "deleteAfterDays": raw.get("RecoveryPointLifecycle", {}).get("DeleteAfterDays"),
        "backupVaultArn": raw.get("BackupVaultArn"),
        "iamRoleArn": raw.get("IamRoleArn"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--rds-backup-job", type=Path, required=True)
    parser.add_argument("--s3-backup-job", type=Path, required=True)
    parser.add_argument("--rds-recovery-point-tags", type=Path, required=True)
    parser.add_argument("--s3-recovery-point-tags", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--candidate-build-run-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        require(not output.exists() and not output.is_symlink(), "refusing to overwrite source evidence")
        marker = load(args.marker.resolve())
        rds = backup_job(load(args.rds_backup_job.resolve()), "RDS")
        s3 = backup_job(load(args.s3_backup_job.resolve()), "S3")
        rds_tags = load(args.rds_recovery_point_tags.resolve()).get("Tags")
        s3_tags = load(args.s3_recovery_point_tags.resolve()).get("Tags")
        required_tag_keys = {
            "Application", "Environment", "RestoreTest", "ReleaseId", "RestoreSourceCanary", "RestoreSourceMarker",
        }
        require(isinstance(rds_tags, dict) and required_tag_keys.issubset(rds_tags),
                "RDS recovery point does not carry every required source-binding tag")
        require(isinstance(s3_tags, dict) and required_tag_keys.issubset(s3_tags),
                "S3 recovery point does not carry every required source-binding tag")
        bound_tags = {key: rds_tags[key] for key in sorted(required_tag_keys)}
        require(bound_tags == {key: s3_tags[key] for key in sorted(required_tag_keys)},
                "paired recovery points carry different source-binding tags")
        manifest_path = args.image_manifest.resolve()
        manifest = load(manifest_path)
        provenance = load(args.provenance.resolve())
        marker_sha = hashlib.sha256(canonical_bytes(marker)).hexdigest()
        evidence = {
            "schemaVersion": "jsc-public-beta-restore-source-evidence.v1",
            "status": "PAIRED_BACKUPS_COMPLETED",
            "environment": "public-beta",
            "createdAt": args.created_at,
            "releaseCandidate": {
                "releaseId": manifest.get("releaseId"),
                "buildRunId": args.candidate_build_run_id,
                "infrastructureRevision": provenance.get("infrastructureRevision"),
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "releaseAttestationId": marker.get("releaseAttestationId"),
            },
            "sourceCanary": {"markerSha256": marker_sha, "marker": marker},
            "livePreconditions": {
                "publicEntrypointFixed503": True,
                "applicationDesiredCount": 0,
                "databaseBootstrapMarkerVerified": True,
                "flywayHistoriesVerified": True,
                "canaryReverifiedAfterQuiesce": True,
            },
            "backupJobs": {"rds": rds, "s3": s3},
            "recoveryPointTags": bound_tags,
        }
        validate(evidence, manifest, provenance, args.candidate_build_run_id)
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_bytes(canonical_bytes(evidence, newline=True))
        output.chmod(0o600)
    except (SourceEvidenceError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"restore-source evidence rendering refused: {exc}", file=sys.stderr)
        return 2
    print(f"restore-source evidence rendered: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
