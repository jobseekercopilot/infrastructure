#!/usr/bin/env python3
"""Render fail-closed AWS Backup restore requests without calling AWS."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from validate_restore_source_evidence import SourceEvidenceError, validate as validate_source_evidence


class RequestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RequestError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"unsafe JSON input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON input must be an object: {path}")
    return value


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_utc(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequestError("created-at must be an ISO-8601 UTC timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0), "created-at must be UTC")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--drill-id", required=True)
    parser.add_argument("--rds-recovery-point-arn", required=True)
    parser.add_argument("--s3-recovery-point-arn", required=True)
    parser.add_argument("--restore-role-arn", required=True)
    parser.add_argument("--data-kms-key-arn", required=True)
    parser.add_argument("--restore-security-group-id", required=True)
    parser.add_argument(
        "--rds-restore-metadata",
        type=Path,
        required=True,
        help="exact GetRecoveryPointRestoreMetadata response for the selected RDS recovery point",
    )
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--restore-source-evidence", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    try:
        require(re.fullmatch(r"[0-9]{12}", args.account_id) is not None, "account ID must be 12 digits")
        require(args.region == "eu-west-2", "restore drills are restricted to eu-west-2")
        require(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{6,30}[a-z0-9])", args.drill_id) is not None,
            "drill ID must be 8-32 lowercase letters, digits or interior hyphens",
        )
        require(re.fullmatch(r"sg-[0-9a-f]{8,17}", args.restore_security_group_id) is not None,
                "restore security group ID is malformed")
        rds_recovery_pattern = re.compile(
            rf"arn:aws:rds:{args.region}:{args.account_id}:snapshot:awsbackup:job-[A-Za-z0-9-]+"
        )
        s3_recovery_pattern = re.compile(
            rf"arn:aws:backup:{args.region}:{args.account_id}:recovery-point:[A-Za-z0-9-]+"
        )
        require(rds_recovery_pattern.fullmatch(args.rds_recovery_point_arn) is not None,
                "RDS recovery point ARN is out of scope")
        require(s3_recovery_pattern.fullmatch(args.s3_recovery_point_arn) is not None,
                "S3 recovery point ARN is out of scope")
        require(args.rds_recovery_point_arn != args.s3_recovery_point_arn,
                "RDS and S3 recovery points must be distinct")
        expected_role = f"arn:aws:iam::{args.account_id}:role/jsc-public-beta-backup-restore"
        require(args.restore_role_arn == expected_role, "restore service role must be the exact boundary-constrained role")
        require(
            re.fullmatch(rf"arn:aws:kms:{args.region}:{args.account_id}:key/[0-9a-f-]{{36}}", args.data_kms_key_arn)
            is not None,
            "data KMS key ARN is malformed or out of scope",
        )

        manifest = load_json(args.image_manifest.resolve())
        provenance = load_json(args.provenance.resolve())
        source_evidence_path = args.restore_source_evidence.resolve()
        source_evidence = load_json(source_evidence_path)
        require(manifest.get("sourceBranch") == "main", "restore candidate must come from protected main")
        release_id = manifest.get("releaseId")
        require(isinstance(release_id, str) and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", release_id),
                "restore candidate release ID is malformed")
        require(provenance.get("releaseId") == release_id, "candidate provenance release ID mismatch")
        require(provenance.get("buildPurpose") == "restore-candidate",
                "candidate provenance is not an isolated restore-candidate build")
        infrastructure_revision = provenance.get("infrastructureRevision")
        require(
            isinstance(infrastructure_revision, str)
            and re.fullmatch(r"[0-9a-f]{40}", infrastructure_revision) is not None
            and infrastructure_revision != "0" * 40,
            "candidate infrastructure revision is not pinned",
        )
        manifest_sha = hashlib.sha256(args.image_manifest.resolve().read_bytes()).hexdigest()
        require(provenance.get("imageManifestSha256") == manifest_sha, "candidate manifest provenance mismatch")
        document_evidence = manifest.get("dependencyEvidence", {}).get("documentStorePermanentErasure", {})
        document_image = manifest.get("images", {}).get("document-store-service", {})
        operator_image = manifest.get("images", {}).get("release-operator", {})
        revision = document_evidence.get("revision")
        openapi_sha = document_evidence.get("openApiSha256")
        digest = document_image.get("digest")
        require(re.fullmatch(r"[0-9a-f]{40}", str(revision)) is not None, "Document Store revision is not pinned")
        require(document_image.get("revision") == revision, "Document Store image/source revision mismatch")
        require(re.fullmatch(r"[0-9a-f]{64}", str(openapi_sha)) is not None, "Document Store OpenAPI hash is not pinned")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)) is not None, "Document Store image digest is not pinned")
        require(document_image.get("scanStatus") == "PASSED", "Document Store restore candidate has not passed scanning")
        operator_digest = operator_image.get("digest")
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", str(operator_digest)) is not None,
            "release-operator image digest is not pinned",
        )
        require(operator_image.get("scanStatus") == "PASSED", "release-operator restore candidate has not passed scanning")
        candidate_build_run_id = str(source_evidence.get("releaseCandidate", {}).get("buildRunId", ""))
        validate_source_evidence(
            source_evidence,
            manifest,
            provenance,
            candidate_build_run_id,
            expected_rds_recovery_point=args.rds_recovery_point_arn,
            expected_s3_recovery_point=args.s3_recovery_point_arn,
        )

        raw_rds_metadata = load_json(args.rds_restore_metadata.resolve())
        source_rds_metadata = raw_rds_metadata.get("RestoreMetadata")
        require(
            isinstance(source_rds_metadata, dict)
            and 1 <= len(source_rds_metadata) <= 100
            and all(
                isinstance(key, str)
                and 1 <= len(key) <= 128
                and isinstance(value, str)
                and len(value) <= 16 * 1024
                for key, value in source_rds_metadata.items()
            ),
            "RDS recovery-point restore metadata must be a bounded string map",
        )
        require(source_rds_metadata.get("Engine") == "postgres",
                "RDS recovery point is not the reviewed PostgreSQL engine")
        require(re.fullmatch(r"db\.[a-z0-9.]+", source_rds_metadata.get("DBInstanceClass", "")) is not None,
                "RDS recovery point does not provide a valid DB instance class")
        if "KmsKeyId" in source_rds_metadata:
            require(source_rds_metadata["KmsKeyId"] == args.data_kms_key_arn,
                    "RDS recovery point uses another data KMS key")
        if "Port" in source_rds_metadata:
            require(source_rds_metadata["Port"] == "5432", "RDS recovery point is not PostgreSQL on port 5432")
        require(
            not any(key in source_rds_metadata for key in ("RestoreTime", "UseLatestRestorableTime")),
            "point-in-time metadata is outside this snapshot restore drill",
        )

        created_at = parse_utc(args.created_at)
        bucket = f"jsc-public-beta-restore-{args.account_id}-{args.drill_id}"
        database = f"jsc-public-beta-restore-{args.drill_id}"
        require(len(bucket) <= 63 and len(database) <= 63, "drill ID makes a destination name too long")
        source_evidence_sha = hashlib.sha256(source_evidence_path.read_bytes()).hexdigest()
        token_seed = (
            f"{release_id}:{args.drill_id}:{args.rds_recovery_point_arn}:"
            f"{args.s3_recovery_point_arn}:{source_evidence_sha}"
        ).encode()

        rds_metadata = dict(source_rds_metadata)
        rds_metadata.pop("AvailabilityZone", None)
        rds_metadata.update({
            "DBInstanceIdentifier": database,
            "DBSubnetGroupName": "jsc-public-beta-postgres",
            "VpcSecurityGroupIds": json.dumps([args.restore_security_group_id], separators=(",", ":")),
            "PubliclyAccessible": "false",
            "MultiAZ": "false",
            "DeletionProtection": "false",
        })
        rds_request = {
            "RecoveryPointArn": args.rds_recovery_point_arn,
            "IamRoleArn": args.restore_role_arn,
            "IdempotencyToken": hashlib.sha256(token_seed + b":rds").hexdigest(),
            "ResourceType": "RDS",
            "CopySourceTagsToRestoredResource": False,
            "Metadata": rds_metadata,
        }
        s3_request = {
            "RecoveryPointArn": args.s3_recovery_point_arn,
            "IamRoleArn": args.restore_role_arn,
            "IdempotencyToken": hashlib.sha256(token_seed + b":s3").hexdigest(),
            "ResourceType": "S3",
            "Metadata": {
                "DestinationBucketName": bucket,
                "EncryptionType": "SSE-KMS",
                "KMSKey": args.data_kms_key_arn,
                "RestoreACLs": "false",
                "RestoreLatestVersionsUpTo": "all",
            },
        }
        rds_bytes = canonical_bytes(rds_request)
        s3_bytes = canonical_bytes(s3_request)
        request_evidence = {
            "schemaVersion": "jsc-public-beta-restore-request.v1",
            "status": "REQUESTS_RENDERED",
            "environment": "public-beta",
            "createdAt": created_at,
            "drillId": args.drill_id,
            "releaseCandidate": {
                "releaseId": release_id,
                "buildRunId": candidate_build_run_id,
                "infrastructureRevision": infrastructure_revision,
                "releaseAttestationId": source_evidence["releaseCandidate"]["releaseAttestationId"],
                "documentStoreRevision": revision,
                "documentStoreOpenApiSha256": openapi_sha,
                "documentStoreImageDigest": digest,
                "releaseOperatorImageDigest": operator_digest,
            },
            "sourceRecoveryPoints": {
                "rds": args.rds_recovery_point_arn,
                "s3": args.s3_recovery_point_arn,
            },
            "restoreSource": {
                "canaryId": source_evidence["sourceCanary"]["marker"]["canaryId"],
                "markerSha256": source_evidence["sourceCanary"]["markerSha256"],
                "evidenceSha256": source_evidence_sha,
                "logicalDatabaseCount": len(source_evidence["sourceCanary"]["marker"]["logicalDatabases"]),
                "documentObjectVersionCount": len(source_evidence["sourceCanary"]["marker"]["document"]["versions"]),
            },
            "isolatedDestinations": {"rds": database, "s3": bucket},
            "requestSha256": {
                "rds": hashlib.sha256(rds_bytes).hexdigest(),
                "s3": hashlib.sha256(s3_bytes).hexdigest(),
            },
        }
        output = args.output_directory.resolve()
        require(not output.is_symlink(), "output directory must not be a symlink")
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(output.is_dir(), "output path is not a directory")
        for name, content in (
            ("rds-restore-request.json", rds_bytes),
            ("s3-restore-request.json", s3_bytes),
            ("restore-request-evidence.json", canonical_bytes(request_evidence)),
        ):
            path = output / name
            require(not path.exists(), f"refusing to overwrite restore request artifact: {path}")
            path.write_bytes(content)
            path.chmod(0o600)
    except (OSError, json.JSONDecodeError, RequestError, SourceEvidenceError, KeyError) as exc:
        print(f"restore request refused: {exc}", file=__import__("sys").stderr)
        return 2

    print(f"isolated restore requests rendered for {args.drill_id}; no AWS calls made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
