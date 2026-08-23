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
        return manifest

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
                "--rds-recovery-point-arn", f"arn:aws:backup:eu-west-2:{account}:recovery-point:rds-point",
                "--s3-recovery-point-arn", f"arn:aws:backup:eu-west-2:{account}:recovery-point:s3-point",
                "--restore-role-arn", f"arn:aws:iam::{account}:role/jsc-public-beta-backup-restore",
                "--data-kms-key-arn", f"arn:aws:kms:eu-west-2:{account}:key/00000000-0000-0000-0000-000000000001",
                "--restore-security-group-id", "sg-0123456789abcdef0",
                "--rds-restore-metadata", str(rds_metadata_path),
                "--image-manifest", str(manifest_path),
                "--provenance", str(provenance_path),
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
                "rdsRecoveryPointArn": f"arn:aws:backup:eu-west-2:{account}:recovery-point:rds-point",
                "s3RecoveryPointArn": f"arn:aws:backup:eu-west-2:{account}:recovery-point:s3-point",
                "rdsCompletedAt": "2026-08-22T02:00:00Z",
                "s3CompletedAt": "2026-08-22T02:05:00Z",
                "maximumSkewMinutes": 60,
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


if __name__ == "__main__":
    unittest.main()
