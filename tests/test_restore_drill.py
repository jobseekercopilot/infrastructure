import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "aws" / "render_backup_restore_requests.py"
VALIDATOR = ROOT / "scripts" / "aws" / "validate_restore_drill_evidence.py"
PROMOTER = ROOT / "scripts" / "aws" / "promote_restore_candidate.py"
SOURCE_VALIDATOR = ROOT / "scripts" / "aws" / "validate_restore_source_evidence.py"
SOURCE_RENDERER = ROOT / "scripts" / "aws" / "render_restore_source_evidence.py"
IMAGE_TEMPLATE = ROOT / "aws" / "public-beta" / "config" / "image-manifest.json"


class RestoreDrillContractTest(unittest.TestCase):
    def candidate(self) -> dict:
        manifest = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        revision = "1" * 40
        manifest["releaseId"] = "20260823T030000Z-" + "2" * 12
        manifest["sourceBranch"] = "main"
        manifest["dependencyEvidence"]["documentStorePermanentErasure"].update({
            "revision": revision,
            "openApiSha256": "3" * 64,
        })
        manifest["images"]["document-store-service"].update({
            "revision": revision,
            "digest": "sha256:" + "4" * 64,
            "scanStatus": "PASSED",
        })
        manifest["images"]["release-operator"].update({
            "revision": revision,
            "digest": "sha256:" + "5" * 64,
            "scanStatus": "PASSED",
        })
        return manifest

    def restore_source_evidence(self, manifest: dict, manifest_path: Path, provenance: dict) -> dict:
        account = "123456789012"
        canary = "launch-20260823"
        marker = {
            "schemaVersion": "jsc-public-beta-restore-source-canary.v1",
            "releaseId": manifest["releaseId"],
            "releaseAttestationId": "6" * 64,
            "canaryId": canary,
            "preparedAt": "2026-08-23T01:20:00Z",
            "databaseBootstrapMarkerVerified": True,
            "flywayHistoriesVerified": True,
            "logicalDatabases": [
                "authentication", "user_profile", "job_service", "document_generation",
                "document_store", "application_tracker", "payment",
            ],
            "document": {
                "bucket": f"jsc-public-beta-documents-{account}",
                "key": f"restore-canary/v1/{canary}/document.json",
                "versions": [
                    {"generation": 1, "versionId": "version-one", "sha256": "7" * 64, "sizeBytes": 128},
                    {"generation": 2, "versionId": "version-two", "sha256": "8" * 64, "sizeBytes": 128},
                ],
            },
        }
        marker_sha = hashlib.sha256(json.dumps(marker, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        tags = {
            "Application": "Job Seeker Copilot", "Environment": "public-beta", "RestoreTest": "quarterly",
            "ReleaseId": manifest["releaseId"], "RestoreSourceCanary": canary, "RestoreSourceMarker": marker_sha,
        }
        role = f"arn:aws:iam::{account}:role/jsc-public-beta-backup"
        vault = f"arn:aws:backup:eu-west-2:{account}:backup-vault:jsc-public-beta-customer-data"
        return {
            "schemaVersion": "jsc-public-beta-restore-source-evidence.v1",
            "status": "PAIRED_BACKUPS_COMPLETED",
            "environment": "public-beta",
            "createdAt": "2026-08-23T04:10:00Z",
            "releaseCandidate": {
                "releaseId": manifest["releaseId"], "buildRunId": "123456",
                "infrastructureRevision": provenance["infrastructureRevision"],
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "releaseAttestationId": marker["releaseAttestationId"],
            },
            "sourceCanary": {"markerSha256": marker_sha, "marker": marker},
            "livePreconditions": {
                "publicEntrypointFixed503": True, "applicationDesiredCount": 0,
                "databaseBootstrapMarkerVerified": True, "flywayHistoriesVerified": True,
                "canaryReverifiedAfterQuiesce": True,
            },
            "backupJobs": {
                "rds": {
                    "jobId": "43ca0000-1111-2222-3333-444444444444", "state": "COMPLETED", "resourceType": "RDS",
                    "resourceArn": f"arn:aws:rds:eu-west-2:{account}:db:jsc-public-beta-postgres",
                    "recoveryPointArn": f"arn:aws:rds:eu-west-2:{account}:snapshot:awsbackup:job-43ca0000-1111-2222-3333-444444444444",
                    "creationDate": "2026-08-23T02:22:30.034+01:00", "completionDate": "2026-08-23T05:04:25.430+01:00",
                    "deleteAfterDays": 35, "backupVaultArn": vault, "iamRoleArn": role,
                },
                "s3": {
                    "jobId": "53ca0000-1111-2222-3333-444444444444", "state": "COMPLETED", "resourceType": "S3",
                    "resourceArn": f"arn:aws:s3:::jsc-public-beta-documents-{account}",
                    "recoveryPointArn": f"arn:aws:backup:eu-west-2:{account}:recovery-point:jsc-public-beta-documents-point",
                    "creationDate": "2026-08-23T02:22:29.510+01:00", "completionDate": "2026-08-23T03:08:30.703+01:00",
                    "deleteAfterDays": 35, "backupVaultArn": vault, "iamRoleArn": role,
                },
            },
            "recoveryPointTags": tags,
        }

    def test_renderer_forces_private_rds_and_all_s3_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            manifest = self.candidate()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance = {
                "releaseId": manifest["releaseId"],
                "infrastructureRevision": "5" * 40,
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "buildPurpose": "restore-candidate",
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            source_evidence_path = root / "restore-source-evidence.json"
            source_evidence_path.write_text(
                json.dumps(self.restore_source_evidence(manifest, manifest_path, provenance), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            rds_metadata_path = root / "rds-restore-metadata.json"
            rds_metadata_path.write_text(json.dumps({"RestoreMetadata": {
                "DBInstanceClass": "db.t4g.micro",
                "Engine": "postgres",
                "Port": "5432",
                "KmsKeyId": "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000001",
                "AvailabilityZone": "eu-west-2a",
                "PubliclyAccessible": "true",
                "VpcSecurityGroupIds": '["sg-fffffffffffffffff"]',
            }}), encoding="utf-8")
            account = "123456789012"
            command = [
                "python3", str(RENDERER),
                "--account-id", account,
                "--drill-id", "beta-20260823",
                "--rds-recovery-point-arn", f"arn:aws:rds:eu-west-2:{account}:snapshot:awsbackup:job-43ca0000-1111-2222-3333-444444444444",
                "--s3-recovery-point-arn", f"arn:aws:backup:eu-west-2:{account}:recovery-point:jsc-public-beta-documents-point",
                "--restore-role-arn", f"arn:aws:iam::{account}:role/jsc-public-beta-backup-restore",
                "--data-kms-key-arn", f"arn:aws:kms:eu-west-2:{account}:key/00000000-0000-0000-0000-000000000001",
                "--restore-security-group-id", "sg-0123456789abcdef0",
                "--rds-restore-metadata", str(rds_metadata_path),
                "--image-manifest", str(manifest_path),
                "--provenance", str(provenance_path),
                "--restore-source-evidence", str(source_evidence_path),
                "--created-at", "2026-08-23T03:00:00Z",
                "--output-directory", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rds = json.loads((output / "rds-restore-request.json").read_text())
            s3 = json.loads((output / "s3-restore-request.json").read_text())
            self.assertEqual(rds["Metadata"]["PubliclyAccessible"], "false")
            self.assertEqual(rds["Metadata"]["DBSubnetGroupName"], "jsc-public-beta-postgres")
            self.assertEqual(rds["Metadata"]["VpcSecurityGroupIds"], '["sg-0123456789abcdef0"]')
            self.assertEqual(rds["Metadata"]["Engine"], "postgres")
            self.assertNotIn("AvailabilityZone", rds["Metadata"])
            self.assertNotIn("NewBucket", s3["Metadata"])
            self.assertNotIn("CopySourceTagsToRestoredResource", s3)
            self.assertEqual(s3["Metadata"]["RestoreACLs"], "false")
            self.assertEqual(s3["Metadata"]["EncryptionType"], "SSE-KMS")
            self.assertEqual(s3["Metadata"]["RestoreLatestVersionsUpTo"], "all")
            evidence = json.loads((output / "restore-request-evidence.json").read_text())
            self.assertEqual(evidence["releaseCandidate"]["documentStoreImageDigest"], "sha256:" + "4" * 64)
            self.assertEqual(evidence["restoreSource"]["logicalDatabaseCount"], 7)
            self.assertEqual(evidence["restoreSource"]["documentObjectVersionCount"], 2)

            repeated = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("refusing to overwrite", repeated.stderr)

            escaped = subprocess.run(
                [*command[:command.index("--drill-id") + 1], "../../production", *command[command.index("--drill-id") + 2:]],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(escaped.returncode, 0)

    def test_release_promotion_reuses_exact_candidate_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.candidate()
            manifest["launchApprovalManifestSha256"] = "6" * 64
            manifest_path = root / "candidate-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance = {
                "schemaVersion": 1,
                "releaseId": manifest["releaseId"],
                "infrastructureRevision": "5" * 40,
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "launchApprovalManifestSha256": "6" * 64,
                "buildPurpose": "restore-candidate",
            }
            provenance_path = root / "candidate-provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            approval = {"schemaVersion": 1, "reviewed": True}
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            output = root / "promoted"
            command = [
                "python3", str(PROMOTER),
                "--candidate-image-manifest", str(manifest_path),
                "--candidate-provenance", str(provenance_path),
                "--approval-manifest", str(approval_path),
                "--candidate-build-run-id", "123456",
                "--promoted-at", "2026-08-22T05:00:00Z",
                "--output-directory", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            promoted = json.loads((output / "image-manifest.json").read_text())
            self.assertEqual(promoted["images"], manifest["images"])
            self.assertEqual(promoted["dependencyEvidence"], manifest["dependencyEvidence"])
            self.assertEqual(
                promoted["launchApprovalManifestSha256"],
                hashlib.sha256(approval_path.read_bytes()).hexdigest(),
            )
            promoted_provenance = json.loads((output / "provenance.json").read_text())
            self.assertEqual(promoted_provenance["buildPurpose"], "release")
            self.assertEqual(promoted_provenance["promotedFrom"]["buildRunId"], "123456")
            self.assertEqual(
                promoted_provenance["promotedFrom"]["imageManifestSha256"],
                provenance["imageManifestSha256"],
            )
            self.assertEqual(
                promoted_provenance["imageManifestSha256"],
                hashlib.sha256((output / "image-manifest.json").read_bytes()).hexdigest(),
            )
            repeated = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("overwrite", repeated.stderr)

    def test_source_evidence_accepts_live_arn_offsets_and_long_completion_skew(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.candidate()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance = {
                "releaseId": manifest["releaseId"],
                "infrastructureRevision": "5" * 40,
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "buildPurpose": "restore-candidate",
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            evidence = self.restore_source_evidence(manifest, manifest_path, provenance)

            def run(value: dict) -> subprocess.CompletedProcess[str]:
                evidence_path = root / "source-evidence.json"
                evidence_path.write_text(json.dumps(value), encoding="utf-8")
                return subprocess.run(
                    [
                        "python3", str(SOURCE_VALIDATOR), "--evidence", str(evidence_path),
                        "--image-manifest", str(manifest_path), "--provenance", str(provenance_path),
                        "--candidate-build-run-id", "123456",
                        "--expected-rds-recovery-point", value["backupJobs"]["rds"]["recoveryPointArn"],
                        "--expected-s3-recovery-point", value["backupJobs"]["s3"]["recoveryPointArn"],
                    ],
                    cwd=ROOT, check=False, capture_output=True, text=True,
                )

            valid = run(evidence)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertGreater(
                abs(
                    __import__("datetime").datetime.fromisoformat(evidence["backupJobs"]["rds"]["completionDate"])
                    - __import__("datetime").datetime.fromisoformat(evidence["backupJobs"]["s3"]["completionDate"])
                ).total_seconds(),
                3600,
            )

            empty_document = copy.deepcopy(evidence)
            empty_document["sourceCanary"]["marker"]["document"]["versions"] = []
            self.assertIn("exactly two", run(empty_document).stderr)
            late_pair = copy.deepcopy(evidence)
            late_pair["backupJobs"]["s3"]["creationDate"] = "2026-08-23T02:40:00+01:00"
            self.assertIn("ten-minute capture window", run(late_pair).stderr)
            pre_canary = copy.deepcopy(evidence)
            pre_canary["backupJobs"]["rds"]["creationDate"] = "2026-08-23T02:19:00+01:00"
            self.assertIn("predates the exact canary", run(pre_canary).stderr)
            short_retention = copy.deepcopy(evidence)
            short_retention["backupJobs"]["s3"]["deleteAfterDays"] = 7
            self.assertIn("35-day lifecycle", run(short_retention).stderr)

    def test_source_renderer_uses_actual_tags_and_normalises_live_cli_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.candidate()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance = {
                "releaseId": manifest["releaseId"], "infrastructureRevision": "5" * 40,
                "imageManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "buildPurpose": "restore-candidate",
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            source = self.restore_source_evidence(manifest, manifest_path, provenance)
            marker_path = root / "marker.json"
            marker_path.write_text(json.dumps(source["sourceCanary"]["marker"]), encoding="utf-8")

            job_paths = {}
            for kind in ("rds", "s3"):
                job = source["backupJobs"][kind]
                raw = {
                    "BackupJobId": job["jobId"], "State": job["state"], "ResourceType": job["resourceType"],
                    "ResourceArn": job["resourceArn"], "RecoveryPointArn": job["recoveryPointArn"],
                    "CreationDate": job["creationDate"], "CompletionDate": job["completionDate"],
                    "RecoveryPointLifecycle": {"DeleteAfterDays": job["deleteAfterDays"]},
                    "BackupVaultArn": job["backupVaultArn"], "IamRoleArn": job["iamRoleArn"],
                }
                job_paths[kind] = root / f"{kind}-job.json"
                job_paths[kind].write_text(json.dumps(raw), encoding="utf-8")
            tag_paths = {}
            for kind in ("rds", "s3"):
                tag_paths[kind] = root / f"{kind}-tags.json"
                tag_paths[kind].write_text(json.dumps({
                    "Tags": {**source["recoveryPointTags"], "aws:backup:system-observation": "ignored"}
                }), encoding="utf-8")
            output = root / "rendered.json"
            result = subprocess.run([
                "python3", str(SOURCE_RENDERER), "--marker", str(marker_path),
                "--rds-backup-job", str(job_paths["rds"]), "--s3-backup-job", str(job_paths["s3"]),
                "--rds-recovery-point-tags", str(tag_paths["rds"]),
                "--s3-recovery-point-tags", str(tag_paths["s3"]),
                "--image-manifest", str(manifest_path), "--provenance", str(provenance_path),
                "--candidate-build-run-id", "123456", "--created-at", "2026-08-23T04:10:00Z",
                "--output", str(output),
            ], cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = json.loads(output.read_text())
            self.assertEqual(rendered["backupJobs"]["rds"]["creationDate"], "2026-08-23T01:22:30.034Z")
            self.assertEqual(rendered["backupJobs"]["rds"]["deleteAfterDays"], 35)
            self.assertNotIn("aws:backup:system-observation", rendered["recoveryPointTags"])

    def test_source_preparation_is_protected_idempotent_and_uses_bounded_polling(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text()
        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text()
        canary = (ROOT / "aws" / "public-beta" / "operator" / "prepare-restore-source-canary.sh").read_text()
        drill = (ROOT / "scripts" / "aws" / "run_backup_restore_drill.sh").read_text()
        operator = (ROOT / "aws" / "public-beta" / "operator.tf").read_text()
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text()
        self.assertIn("prepare-restore-source", workflow)
        self.assertIn("environment: production-aws", workflow)
        self.assertIn("public-beta-restore-candidate-", workflow)
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("Upload canary-bound paired-backup evidence", workflow)
        self.assertNotIn("aws backup wait", release)
        self.assertIn("wait_for_paired_backup_jobs", release)
        for state in ("FAILED", "ABORTED", "EXPIRED", "PARTIAL"):
            self.assertIn(state, release)
        self.assertIn("BACKUP_WAIT_TIMEOUT_SECONDS:-14400", release)
        self.assertGreater(14400, (2 * 60 * 60) + (41 * 60) + 55)
        self.assertIn("timeout-minutes: ${{ inputs.action == 'prepare-restore-source' && 360 || 180 }}", workflow)
        self.assertIn("timeout-minutes: ${{ inputs.action == 'prepare-restore-source' && 300 || 180 }}", workflow)
        self.assertIn("prepare-restore-source' && 21600 || 10800", workflow)
        self.assertIn("Contain failed restore-source preparation", workflow)
        self.assertIn("steps.release.outcome == 'failure' || steps.release.outcome == 'cancelled'", workflow)
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertIn('applied_release_id="$(terraform -chdir=aws/public-beta output', workflow)
        self.assertIn('RELEASE_CONFIRMATION="DARKEN $applied_release_id"', workflow)
        self.assertIn("length(var.additional_tags) == 0", locals_source)
        self.assertIn("$marker_sha:rds", release)
        self.assertIn("already exists for the exact candidate", canary)
        self.assertLess(canary.index("existing_marker="), canary.index("aws s3api put-object"))
        self.assertIn("ParameterNotFound", canary)
        self.assertIn("ambiguous or paginated version history", canary)
        self.assertIn("duplicate generation-one versions", canary)
        self.assertIn("exact two-version history", canary)
        self.assertIn("PGOPTIONS='-c statement_timeout=120000", canary)
        self.assertIn("ssm list-tags-for-resource", canary)
        self.assertIn("aws elbv2 describe-rules", release)
        self.assertIn("aws ecs list-tasks", release)
        self.assertEqual(release.count("verify_current_iam_contract 1 false preflight-operator-iam"), 1)
        self.assertEqual(drill.count('echo "Observe requires the immutable exact restore-start evidence artifact."'), 1)
        self.assertNotRegex(drill, r"exit 3\n\s*exit 3")
        release_operator = (ROOT / "scripts" / "aws" / "run_release_operator.sh").read_text()
        self.assertIn("aws ecs stop-task", release_operator)
        self.assertIn("key=Purpose,value=ReleaseOperator", release_operator)
        bootstrap_marker_policy = operator.split('sid       = "ReadOnlyExactDatabaseBootstrapMarker"', 1)[1].split("  }", 1)[0]
        self.assertIn('actions   = ["ssm:GetParameter"]', bootstrap_marker_policy)
        self.assertNotIn("ssm:PutParameter", bootstrap_marker_policy)
        self.assertIn('sid = "ManageOnlyExactRestoreSourceCanaryMarker"', operator)
        self.assertIn('"ssm:ListTagsForResource"', operator)

    def verified_evidence(self, manifest: dict) -> dict:
        revision = manifest["dependencyEvidence"]["documentStorePermanentErasure"]["revision"]
        openapi = manifest["dependencyEvidence"]["documentStorePermanentErasure"]["openApiSha256"]
        digest = manifest["images"]["document-store-service"]["digest"]
        account = "123456789012"
        drill = "beta-20260823"
        return {
            "schemaVersion": "jsc-public-beta-restore-drill-evidence.v1",
            "status": "VERIFIED",
            "environment": "public-beta",
            "drillId": drill,
            "startedAt": "2026-08-22T03:00:00Z",
            "completedAt": "2026-08-22T04:00:00Z",
            "reviewedBy": "Bernard McGeever",
            "reviewedOn": "2026-08-23",
            "evidenceReference": "restore-drill-run-123456",
            "releaseCandidate": {
                "releaseId": manifest["releaseId"],
                "infrastructureRevision": "5" * 40,
                "documentStoreRevision": revision,
                "documentStoreOpenApiSha256": openapi,
                "documentStoreImageDigest": digest,
            },
            "recoveryWindow": {
                "rdsRecoveryPointArn": f"arn:aws:rds:eu-west-2:{account}:snapshot:awsbackup:job-rds-point",
                "s3RecoveryPointArn": f"arn:aws:backup:eu-west-2:{account}:recovery-point:s3-point",
                "rdsCreatedAt": "2026-08-22T01:59:30Z",
                "s3CreatedAt": "2026-08-22T01:59:35Z",
                "rdsCompletedAt": "2026-08-22T02:00:00Z",
                "s3CompletedAt": "2026-08-22T02:05:00Z",
                "maximumCreationSkewMinutes": 10,
            },
            "restoreSource": {
                "canaryId": "launch-20260823",
                "sourceEvidenceSha256": "6" * 64,
                "canaryMarkerSha256": "7" * 64,
                "logicalDatabaseCount": 7,
                "documentObjectVersionCount": 2,
                "restoredDocumentObjectVersionCount": 2,
                "restoredDeleteMarkerCount": 0,
                "restoredGenerationPayloadsVerified": True,
                "sourceVersionIdsPreserved": False,
            },
            "isolatedDestinations": {
                "rdsIdentifier": f"jsc-public-beta-restore-{drill}",
                "s3Bucket": f"jsc-public-beta-restore-{account}-{drill}",
                "privateRds": True,
                "isolatedSecurityGroupVerified": True,
                "notAttachedToPublicFleet": True,
            },
            "restoreJobs": {
                kind: {
                    "jobId": f"{kind}-restore-job-1234",
                    "status": "COMPLETED",
                    "startedAt": "2026-08-22T03:00:00Z",
                    "completedAt": "2026-08-22T03:30:00Z",
                } for kind in ("rds", "s3")
            },
            "s3RestoreControls": {
                "newBucket": False,
                "restoreAcls": False,
                "encryptionType": "SSE-KMS",
                "kmsKeyVerified": True,
                "restoreLatestVersionsUpTo": "all",
                "versioningEnabled": True,
                "bucketOwnerEnforced": True,
                "blockPublicAccess": True,
                "tlsPolicyVerified": True,
                "exactKmsPolicyVerified": True,
            },
            "databaseVerification": {
                "logicalDatabaseCount": 7,
                "rolesVerified": True,
                "flywayHistoriesVerified": True,
                "domainInvariantsVerified": True,
                "paymentLedgerReconciled": True,
                "syntheticJourneyVerified": True,
            },
            "documentVerification": {
                "metadataObjectMappingVerified": True,
                "sampleChecksumsVerified": True,
                "retentionReportOnlyVerified": True,
                "integrityIncidentOpen": False,
            },
            "erasureReplayVerification": {
                "externalJournalReadVerified": True,
                "exactReplayVerified": True,
                "schemaVersion": "document-permanent-erasure-readiness.v3",
                "enabled": True,
                "ready": True,
                "status": "READY",
                "recoveryJournalWritePending": 0,
                "recoveryJournalEvidenceMissing": 0,
                "liveErasureReconciliationPending": 0,
                "restoreJournalReadPending": 0,
                "restoreReplayPending": 0,
                "backupRetentionPending": 1,
                "backupRetentionOverdue": 0,
            },
            "cleanupStatus": "PENDING_SEPARATE_APPROVAL",
        }

    def test_evidence_accepts_in_window_pending_but_rejects_overdue_or_latest_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.candidate()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            evidence = self.verified_evidence(manifest)

            def run(value: dict) -> subprocess.CompletedProcess[str]:
                path = root / "evidence.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                return subprocess.run(
                    ["python3", str(VALIDATOR), "--evidence", str(path), "--image-manifest", str(manifest_path)],
                    cwd=ROOT, check=False, capture_output=True, text=True,
                )

            valid = run(evidence)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            overdue = copy.deepcopy(evidence)
            overdue["erasureReplayVerification"]["backupRetentionOverdue"] = 1
            self.assertIn("backupRetentionOverdue", run(overdue).stderr)
            latest_only = copy.deepcopy(evidence)
            latest_only["s3RestoreControls"]["restoreLatestVersionsUpTo"] = "1"
            self.assertIn("every object version", run(latest_only).stderr)
            wrong_source = copy.deepcopy(evidence)
            wrong_source["releaseCandidate"]["documentStoreRevision"] = "9" * 40
            self.assertIn("another Document Store revision", run(wrong_source).stderr)
            wrong_candidate = copy.deepcopy(evidence)
            wrong_candidate["releaseCandidate"]["releaseId"] = "20260823T040000Z-" + "9" * 12
            self.assertIn("another release candidate", run(wrong_candidate).stderr)
            extra_source_version = copy.deepcopy(evidence)
            extra_source_version["restoreSource"]["documentObjectVersionCount"] = 3
            self.assertIn("exactly two", run(extra_source_version).stderr)
            preserved_source_ids = copy.deepcopy(evidence)
            preserved_source_ids["restoreSource"]["sourceVersionIdsPreserved"] = True
            self.assertIn("preserved source S3 VersionIds", run(preserved_source_ids).stderr)
            restored_delete_marker = copy.deepcopy(evidence)
            restored_delete_marker["restoreSource"]["restoredDeleteMarkerCount"] = 1
            self.assertIn("delete marker", run(restored_delete_marker).stderr)

            pending_path = root / "pending-cleanup.json"
            pending_path.write_text(json.dumps(evidence), encoding="utf-8")
            strict_cleanup = subprocess.run(
                [
                    "python3", str(VALIDATOR),
                    "--evidence", str(pending_path),
                    "--image-manifest", str(manifest_path),
                    "--expected-infrastructure-revision", "5" * 40,
                    "--require-cleanup",
                ],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertIn("cleanup", strict_cleanup.stderr)
            complete = copy.deepcopy(evidence)
            complete["cleanupStatus"] = "COMPLETED"
            complete_path = root / "complete-cleanup.json"
            complete_path.write_text(json.dumps(complete), encoding="utf-8")
            strict_complete = subprocess.run(
                [
                    "python3", str(VALIDATOR),
                    "--evidence", str(complete_path),
                    "--image-manifest", str(manifest_path),
                    "--expected-infrastructure-revision", "5" * 40,
                    "--require-cleanup",
                ],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(strict_complete.returncode, 0, strict_complete.stderr)

    def test_bootstrap_separates_restore_initiation_service_execution_and_cleanup(self) -> None:
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", intrinsic)
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(),
            Loader=CloudFormationLoader,
        )
        resources = template["Resources"]
        initiator = resources["RestoreDrillRole"]["Properties"]
        cleanup = resources["RestoreCleanupRole"]["Properties"]
        self.assertIn("${RestoreEnvironmentName}", json.dumps(initiator["AssumeRolePolicyDocument"]))
        self.assertIn("${RestoreCleanupEnvironmentName}", json.dumps(cleanup["AssumeRolePolicyDocument"]))

        def statements(role: dict) -> list[dict]:
            return role["Policies"][0]["PolicyDocument"]["Statement"]

        initiator_json = json.dumps(statements(initiator))
        cleanup_json = json.dumps(statements(cleanup))
        self.assertIn("backup:StartRestoreJob", initiator_json)
        self.assertIn("iam:PassRole", initiator_json)
        self.assertNotIn("DeleteObject", initiator_json)
        self.assertNotIn("DeleteDBInstance", initiator_json)
        self.assertNotIn("backup:StartRestoreJob", cleanup_json)
        self.assertNotIn("iam:PassRole", cleanup_json)
        self.assertIn("s3:DeleteObjectVersion", cleanup_json)
        self.assertIn("rds:DeleteDBInstance", cleanup_json)
        self.assertNotIn("jsc-public-beta-postgres\"", cleanup_json)
        self.assertNotIn("jsc-public-beta-documents", cleanup_json)

        restore_statements = resources["BackupRestoreWorkloadBoundary"]["Properties"]["PolicyDocument"]["Statement"]
        boundary_by_sid = {statement["Sid"]: statement for statement in restore_statements}
        # AWS' managed restore policies require these actions during service
        # execution. The boundary confines both to drill-prefixed destinations;
        # the GitHub initiator itself still has no deletion permission.
        rds_lifecycle = boundary_by_sid["ExactIsolatedRdsRestoreTargetLifecycle"]
        self.assertIn("rds:DeleteDBInstance", rds_lifecycle["Action"])
        self.assertIn("db:jsc-public-beta-restore-*", rds_lifecycle["Resource"])
        s3_objects = boundary_by_sid["ExactIsolatedRestoreObjects"]
        self.assertIn("s3:DeleteObject", s3_objects["Action"])
        self.assertIn("jsc-public-beta-restore-${AWS::AccountId}-*/*", s3_objects["Resource"])
        self.assertEqual(template["Outputs"]["RestoreDrillRoleArn"]["Value"], "RestoreDrillRole.Arn")
        self.assertEqual(template["Outputs"]["RestoreCleanupRoleArn"]["Value"], "RestoreCleanupRole.Arn")

        workflow = (ROOT / ".github" / "workflows" / "aws-public-beta-restore-drill.yml").read_text()
        self.assertIn("environment: production-aws-restore", workflow)
        self.assertIn("environment: production-aws-restore-cleanup", workflow)
        self.assertIn("AWS_RESTORE_DRILL_ROLE_ARN", workflow)
        self.assertIn("AWS_RESTORE_CLEANUP_ROLE_ARN", workflow)
        self.assertLess(
            workflow.index("Verify protected restore environment"),
            workflow.index("Configure restore-initiator AWS role"),
        )
        script = (ROOT / "scripts" / "aws" / "run_backup_restore_drill.sh").read_text()
        self.assertIn('RestoreLatestVersionsUpTo": "all"',
                      (ROOT / "scripts" / "aws" / "render_backup_restore_requests.py").read_text())
        self.assertIn('DELETE ISOLATED RESTORE DRILL ${drill_id}', script)
        self.assertIn("s3api delete-objects", script)
        self.assertIn("RESTORE_START_EVIDENCE", script)
        self.assertIn("tag_restored_database_when_created", script)
        self.assertIn(".RecoveryPointArn == $recovery", script)
        self.assertIn(".CreatedResourceArn == $destination", script)
        self.assertIn("verify_restore_bucket_tags", script)
        self.assertIn("existing destination bucket is not owned by this exact drill", script)
        self.assertIn("public-beta-restore-start-", workflow)
        self.assertIn("restore_start_run_id", workflow)

        initiator_json = json.dumps(statements(initiator))
        self.assertIn("rds:AddTagsToResource", initiator_json)
        self.assertIn("aws:RequestTag/RestoreDrillId", initiator_json)
        self.assertIn("rds:RemoveTagsFromResource", initiator_json)
        initiator_by_sid = {statement["Sid"]: statement for statement in statements(initiator)}
        recovery_points = initiator_by_sid["ReadAndStartOnlyTaggedCustomerRecoveryPoints"]
        self.assertEqual(
            recovery_points["Condition"]["StringEquals"]["aws:ResourceTag/RestoreTest"],
            "quarterly",
        )
        self.assertNotIn("ForAllValues:StringEquals", recovery_points["Condition"])
        remove_tags = initiator_by_sid["RemoveOnlyCopiedTagsFromNamedRestoreDatabases"]
        self.assertEqual(
            set(remove_tags["Condition"]["ForAllValues:StringEquals"]["aws:TagKeys"]),
            {"Name", "Repository", "DataClass", "Backup", "BetaBlocker"},
        )
        self.assertEqual(
            remove_tags["Condition"]["StringEquals"]["aws:ResourceTag/ManagedBy"],
            "RestoreDrill",
        )
        self.assertEqual(remove_tags["Condition"]["Null"]["aws:ResourceTag/RestoreDrillId"], "false")
        self.assertEqual(remove_tags["Condition"]["Null"]["aws:TagKeys"], "false")
        self.assertLess(
            script.index("aws rds add-tags-to-resource"),
            script.index("aws rds remove-tags-from-resource"),
        )
        release_operations = resources["ApplyReleaseOperationsPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        release_by_sid = {statement["Sid"]: statement for statement in release_operations}
        self.assertNotIn(
            "restore-source-canary",
            json.dumps(release_by_sid["WriteOnlyExactReleaseMarkers"]["Resource"]),
        )
        marker_reader = release_by_sid["ReadOnlyExactRestoreSourceCanaryMarker"]
        self.assertEqual(marker_reader["Action"], "ssm:GetParameter")
        self.assertIn("restore-source-canary", marker_reader["Resource"])
        guard_operations = resources["ApplyTagAndStateGuardPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        guard_by_sid = {statement["Sid"]: statement for statement in guard_operations}
        stop_operator = guard_by_sid["StopOnlyHungReleaseOperatorTasks"]
        self.assertIn("task/jsc-public-beta/*", stop_operator["Resource"])
        self.assertEqual(
            stop_operator["Condition"]["StringEquals"]["aws:ResourceTag/Purpose"],
            "ReleaseOperator",
        )
        tag_operator = guard_by_sid["TagOnlyReviewedOperatorTasksDuringRun"]
        self.assertEqual(tag_operator["Condition"]["StringEquals"]["ecs:CreateAction"], "RunTask")

    def test_semantic_oidc_roles_orchestrator_and_cleanup_are_fail_closed(self) -> None:
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", intrinsic)
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(),
            Loader=CloudFormationLoader,
        )
        resources = template["Resources"]

        def statements(role_name: str) -> list[dict]:
            return resources[role_name]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]

        start = statements("RestoreSemanticStartRole")
        self.assertEqual(
            {action for statement in start for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )},
            {"states:StartExecution", "states:DescribeExecution"},
        )
        self.assertIn("stateMachine:jsc-public-beta-restore-semantic", json.dumps(start))
        self.assertNotIn("ecs:", json.dumps(start))
        self.assertNotIn("iam:PassRole", json.dumps(start))

        observe = statements("RestoreSemanticObserveRole")
        observe_json = json.dumps(observe)
        self.assertIn("cloudtrail:LookupEvents", observe_json)
        self.assertIn("ecs:ListServices", observe_json)
        observe_actions = {
            action
            for statement in observe
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
        }
        self.assertEqual(
            observe_actions,
            {
                "backup:DescribeRestoreJob",
                "cloudtrail:LookupEvents",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribePrefixLists",
                "ec2:DescribeSecurityGroupRules",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSubnets",
                "ecs:DescribeServices",
                "ecs:DescribeTaskDefinition",
                "ecs:DescribeTasks",
                "ecs:ListServices",
                "ecs:ListTagsForResource",
                "ecs:ListTasks",
                "elasticloadbalancing:DescribeListeners",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeRules",
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:GetPolicy",
                "iam:GetPolicyVersion",
                "iam:ListAttachedRolePolicies",
                "iam:ListRolePolicies",
                "logs:GetLogEvents",
                "rds:DescribeDBInstances",
                "rds:ListTagsForResource",
                "s3:GetBucketLocation",
                "s3:GetBucketOwnershipControls",
                "s3:GetBucketPolicy",
                "s3:GetBucketPolicyStatus",
                "s3:GetBucketTagging",
                "s3:GetBucketVersioning",
                "s3:GetEncryptionConfiguration",
                "s3:GetPublicAccessBlock",
                "ssm:GetParameter",
                "ssm:ListTagsForResource",
                "states:DescribeExecution",
                "states:DescribeStateMachine",
            },
        )
        for mutation in (
            "states:StartExecution", "states:StopExecution", "ecs:RunTask", "ecs:StopTask",
            "iam:PassRole", "ssm:PutParameter", "ssm:DeleteParameter",
        ):
            self.assertNotIn(mutation, observe_json)

        cleanup = statements("RestoreCleanupRole")
        cleanup_json = json.dumps(cleanup)
        self.assertIn("backup:DescribeRestoreJob", cleanup_json)
        self.assertIn("states:DescribeExecution", cleanup_json)
        self.assertNotIn("states:StopExecution", cleanup_json)
        self.assertNotIn("ssm:DeleteParameter", cleanup_json)
        stop_tasks = next(statement for statement in cleanup if statement["Sid"] == "StopOnlyTaggedRestoreSemanticTasks")
        self.assertEqual(
            set(stop_tasks["Condition"]["StringEquals"]["aws:ResourceTag/ManagedBy"]),
            {"RestoreSemanticVerification", "RestoreSemanticBroker"},
        )
        boundary = resources["RestoreSemanticBrokerPermissionsBoundary"]
        self.assertEqual(boundary["DeletionPolicy"], "Retain")
        self.assertEqual(boundary["UpdateReplacePolicy"], "Retain")
        boundary_json = json.dumps(boundary)
        self.assertIn("s3:GetBucketOwnershipControls", boundary_json)
        self.assertNotIn("s3:GetObject", boundary_json)
        backup_restore_boundary = resources["BackupRestoreWorkloadBoundary"]["Properties"]["PolicyDocument"]
        restore_objects = next(
            statement for statement in backup_restore_boundary["Statement"]
            if statement["Sid"] == "ExactIsolatedRestoreObjects"
        )
        self.assertEqual(restore_objects["Action"][0], "s3:DeleteObject")

        script = (ROOT / "scripts" / "aws" / "run_restore_semantic_verification.sh").read_text()
        self.assertIn("stepfunctions start-execution", script)
        self.assertIn("stepfunctions describe-execution", script)
        self.assertNotIn("stepfunctions stop-execution", script)
        self.assertNotIn("ssm delete-parameter", script)
        self.assertIn("AttributeKey=EventName,AttributeValue=RunTask", script)
        self.assertIn("stable_count >= 2", script)
        self.assertIn("+ 300", script)
        self.assertNotIn("AttributeValue=CreateNetworkInterface", script)
        self.assertIn("JSC_RESTORE_SEMANTIC_RAW_EVIDENCE_B64=", script)
        self.assertIn("permanent marker retained", script)
        self.assertIn("for desired in PENDING RUNNING", script)
        self.assertIn("ExecutionAlreadyExists", script)
        self.assertIn("ExecutionDoesNotExist", script)
        self.assertIn("ParameterNotFound", script)
        self.assertIn("prove_semantic_never_started", script)
        self.assertIn("wait_for_exact_restore_jobs_terminal", script)
        self.assertIn('--resource-id "$marker_name"', script)
        self.assertIn('ln -- "$start_temporary" "$start_output"', script)
        self.assertNotIn('>"$start_output"', script)
        no_semantic_branch = script[script.index('if [[ "$action" == cleanup && -z "$semantic_start_evidence" ]]'):]
        self.assertLess(
            no_semantic_branch.index("wait_for_exact_restore_jobs_terminal"),
            no_semantic_branch.index("prove_semantic_never_started"),
        )

        semantic_workflow = (
            ROOT / ".github" / "workflows" / "aws-public-beta-restore-semantic.yml"
        ).read_text()
        self.assertIn("environment: production-aws-restore-observe", semantic_workflow)
        self.assertIn("AWS_RESTORE_SEMANTIC_START_ROLE_ARN", semantic_workflow)
        self.assertIn("AWS_RESTORE_SEMANTIC_OBSERVE_ROLE_ARN", semantic_workflow)
        self.assertIn("Hold the global mutation lock until the Standard execution is terminal", semantic_workflow)
        self.assertIn("role-duration-seconds: 10800", semantic_workflow)
        self.assertIn("SECONDS + 9000", semantic_workflow)
        self.assertIn("PENDING_REDRIVE", semantic_workflow)
        self.assertIn("id: initial_binding_upload", semantic_workflow)
        self.assertIn("continue-on-error: true", semantic_workflow)
        self.assertIn("if: always()", semantic_workflow)
        self.assertIn("Retry semantic execution binding upload after lock hold", semantic_workflow)
        self.assertIn("Transient DescribeExecution failure; retaining the global mutation lock", semantic_workflow)
        self.assertGreaterEqual(
            semantic_workflow.count("scripts/aws/run_restore_semantic_verification.sh start"), 2
        )
        self.assertEqual(
            semantic_workflow.count("group: jsc-public-beta-aws-mutation"),
            1,
        )
        self.assertLess(
            semantic_workflow.index("Verify containment artifact origins before AWS authentication"),
            semantic_workflow.index("Configure deletion-only cleanup role"),
        )
        restore_workflow = (
            ROOT / ".github" / "workflows" / "aws-public-beta-restore-drill.yml"
        ).read_text()
        self.assertLess(
            restore_workflow.index("Refuse deletion until semantic execution is terminal and contained"),
            restore_workflow.index("Delete only the exact isolated drill resources"),
        )
        self.assertIn("if: inputs.semantic_start_run_id != ''", restore_workflow)
        self.assertIn('if [[ -n "$SEMANTIC_START_RUN_ID" ]]', restore_workflow)


if __name__ == "__main__":
    unittest.main()
