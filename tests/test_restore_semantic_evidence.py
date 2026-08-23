import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "aws" / "validate_restore_semantic_evidence.py"
ACCOUNT = "123456789012"
DRILL = "beta-20260823"
RELEASE = "20260823T030000Z-222222222222"
OPERATION = "7e57c0de-1234-4abc-8def-0123456789ab"
REPLAY = "12345678-1234-4abc-9def-0123456789ab"
DATABASES = [
    "authentication",
    "user_profile",
    "job_service",
    "document_generation",
    "document_store",
    "application_tracker",
    "payment",
]


class RestoreSemanticEvidenceTest(unittest.TestCase):
    def readiness(self) -> dict:
        return {
            "schemaVersion": "document-permanent-erasure-readiness.v3",
            "enabled": True,
            "ready": True,
            "status": "READY",
            "policyVersion": "public-beta-retention-v1",
            "backupRetentionPolicyVersion": "public-beta-backup-retention-v1",
            "recoveryDays": 30,
            "maximumBackupRetentionDays": 35,
            "backupExpiryEvidenceRequired": True,
            "recoveryJournalWritePending": 0,
            "recoveryJournalEvidenceMissing": 0,
            "liveErasureReconciliationPending": 0,
            "restoreJournalReadPending": 0,
            "restoreReplayPending": 0,
            "backupRetentionPending": 1,
            "backupRetentionOverdue": 0,
        }

    def generation(self, number: int, version: str, digest_character: str) -> dict:
        return {
            "generation": number,
            "versionId": version,
            "sha256": digest_character * 64,
            "sizeBytes": 128 + number,
            "contentType": "application/json",
            "serverSideEncryption": "aws:kms",
            "exactKmsKeyVerified": True,
            "bucketKeyEnabled": True,
            "contentSha256MetadataVerified": True,
            "payloadSha256Verified": True,
        }

    def evidence(self) -> dict:
        vpc = "vpc-0123456789abcdef0"
        database_sg = "sg-0123456789abcdef0"
        semantic_sg = "sg-1123456789abcdef0"
        runtime = {
            "cloneTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'1' * 32}",
            "sourceApplicationTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'2' * 32}",
            "replayApplicationTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'3' * 32}",
            "cloneTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-clone:17"
            ),
            "applicationTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-document-store:18"
            ),
            "verifierTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-verifier:19"
            ),
            "documentStoreImageDigest": "sha256:" + "4" * 64,
            "releaseOperatorImageDigest": "sha256:" + "5" * 64,
            "vpcId": vpc,
            "restoreDatabaseSecurityGroupId": database_sg,
            "semanticSecurityGroupId": semantic_sg,
            "restoredDatabaseArn": (
                f"arn:aws:rds:eu-west-2:{ACCOUNT}:db:jsc-public-beta-restore-{DRILL}"
            ),
            "restoredDatabaseEndpoint": (
                f"jsc-public-beta-restore-{DRILL}.abc123.eu-west-2.rds.amazonaws.com"
            ),
            "applicationTasksUseDedicatedJournalOnlyRole": True,
            "verifierHasNoJournalPut": True,
            "cloneHasNoTaskRole": True,
        }
        return {
            "schemaVersion": "jsc-public-beta-restore-semantic-observation.v1",
            "status": "VERIFIED",
            "environment": "public-beta",
            "drillId": DRILL,
            "startedAt": "2026-08-23T04:00:00Z",
            "completedAt": "2026-08-23T04:30:00Z",
            "verifierTaskArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'6' * 32}"
            ),
            "releaseCandidate": {
                "releaseId": RELEASE,
                "releaseAttestationId": "7" * 64,
            },
            "runtimeBinding": runtime,
            "networkIsolation": {
                "vpcId": vpc,
                "restoreDatabaseSecurityGroupId": database_sg,
                "semanticSecurityGroupId": semantic_sg,
                "staticRulesTerraformOwned": True,
                "exactReviewedRuleTuplesVerified": True,
                "securityGroupRuleCount": 7,
                "restoreDatabaseIngressRuleCount": 1,
                "restoreDatabaseEgressRuleCount": 0,
                "semanticIngressRuleCount": 1,
                "semanticEgressRuleCount": 5,
                "restoreDatabasePublicIngressRuleCount": 0,
                "semanticEniCountBeforeStart": 0,
                "restoredDatabasePubliclyAccessible": False,
                "restoredDatabaseUsesOnlyRestoreSecurityGroup": True,
                "semanticTasksUseOnlySemanticSecurityGroup": True,
            },
            "publicSafety": {
                "publicEntrypointFixed503": True,
                "applicationDesiredCount": 0,
                "runningApplicationTaskCount": 0,
                "semanticTasksNotAttachedToPublicFleet": True,
            },
            "restoreSource": {
                "canaryId": "launch-20260823",
                "sourceEvidenceSha256": "8" * 64,
                "sourceMarkerSha256": "9" * 64,
            },
            "databaseVerification": {
                "logicalDatabases": DATABASES,
                "exactCanaryRowCounts": {name: 1 for name in DATABASES},
                "exactCanaryRowsVerified": True,
                "replayCloneDatabase": "restore_replay_7e57c0de1234",
                "preOperationReplayCloneVerified": True,
                "nonPrivilegedRolesVerified": True,
                "tlsConnectionsVerified": True,
                "flywayHistoriesVerified": True,
                "emptyBootstrapDomainInvariantsVerified": True,
                "paymentLedgerSeedAndEmptyStateReconciled": True,
            },
            "documentVerification": {
                "mappingType": "NON_CUSTOMER_RESTORE_CANARY",
                "bucket": f"jsc-public-beta-restore-{ACCOUNT}-{DRILL}",
                "key": "restore-canary/v1/launch-20260823/document.json",
                "dataKmsKeyArn": (
                    f"arn:aws:kms:eu-west-2:{ACCOUNT}:key/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                ),
                "destinationVersionIds": ["destination-version-one", "destination-version-two"],
                "destinationVersionCount": 2,
                "deleteMarkerCount": 0,
                "generations": [
                    self.generation(1, "destination-version-one", "a"),
                    self.generation(2, "destination-version-two", "b"),
                ],
                "newDestinationVersionIdsVerified": True,
                "generationMetadataSizeAndSha256Verified": True,
                "customerMetadataObjectMappingClaimed": False,
                "customerGeneratedDocumentMappingClaimed": False,
                "customerObjectErasureClaimed": False,
            },
            "erasureReplayVerification": {
                "operationId": OPERATION,
                "restoreReplayId": REPLAY,
                "syntheticOwnerSha256": "c" * 64,
                "documentCount": 0,
                "objectScopeCount": 0,
                "customerObjectErasureClaimed": False,
                "journal": {
                    "bucket": f"jsc-public-beta-erasure-journal-{ACCOUNT}",
                    "key": f"permanent-erasures/v1/{OPERATION}.json",
                    "versionId": "journal-version-one",
                    "versionCount": 1,
                    "deleteMarkerCount": 0,
                    "contentSha256": "d" * 64,
                    "sizeBytes": 512,
                    "objectLockMode": "GOVERNANCE",
                    "minimumRetentionDays": 36,
                    "writeByCandidateApplicationVerified": True,
                    "exactVersionReadBySeparateVerifierVerified": True,
                },
                "externalJournalWriteVerified": True,
                "externalJournalReadVerified": True,
                "absentOperationReconstructed": True,
                "exactReplayVerified": True,
                "restoreReplayEvidenceRecorded": True,
                "restoreReplayObjectErasedAtVerified": True,
                "sourceRetryIdempotent": True,
                "replayRetryIdempotent": True,
                "journalVersionHistoryUnchangedAfterRetries": True,
                "sourceReadiness": self.readiness(),
                "replayReadiness": self.readiness(),
            },
            "scopeLimitations": [
                "SYNTHETIC_NON_CUSTOMER_EMPTY_SCOPE",
                "JOURNAL_WRITE_READ_RETRY_AND_ABSENT_OPERATION_RECONSTRUCTION_PROVEN",
                "CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED",
                "CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED",
                "RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY",
            ],
        }

    def run_validator(self, evidence: dict, *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic-evidence.json"
            path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
            return subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(path), *extra],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

    def assert_invalid(self, evidence: dict, message: str) -> None:
        result = self.run_validator(evidence)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(message, result.stderr)

    def test_accepts_exact_offline_observation_and_expected_bindings(self) -> None:
        evidence = self.evidence()
        runtime_sha = hashlib.sha256(json.dumps(
            evidence["runtimeBinding"], sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        result = self.run_validator(
            evidence,
            "--expected-account-id", ACCOUNT,
            "--expected-drill-id", DRILL,
            "--expected-release-id", RELEASE,
            "--expected-release-attestation-id", "7" * 64,
            "--expected-source-evidence-sha256", "8" * 64,
            "--expected-source-marker-sha256", "9" * 64,
            "--expected-document-store-image-digest", "sha256:" + "4" * 64,
            "--expected-release-operator-image-digest", "sha256:" + "5" * 64,
            "--expected-verifier-task-arn", evidence["verifierTaskArn"],
            "--expected-runtime-binding-sha256", runtime_sha,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline validation; no live verification claim", result.stdout)

        wrong_binding = self.run_validator(
            evidence,
            "--expected-runtime-binding-sha256", "e" * 64,
        )
        self.assertEqual(wrong_binding.returncode, 2)
        self.assertIn("observer's exact binding", wrong_binding.stderr)

    def test_schema_and_verified_status_fail_closed(self) -> None:
        evidence = self.evidence()
        evidence["unexpected"] = True
        self.assert_invalid(evidence, "incomplete or unexpected shape")

        evidence = self.evidence()
        evidence["status"] = "PENDING"
        self.assert_invalid(evidence, "not VERIFIED")

        evidence = self.evidence()
        evidence["releaseCandidate"]["unexpected"] = "x"
        self.assert_invalid(evidence, "release candidate")

    def test_runtime_network_and_public_boundary_fail_closed(self) -> None:
        cases = [
            ("runtimeBinding", "cloneTaskArn", "arn:aws:ecs:eu-west-2:123456789012:task/other/" + "1" * 32,
             "exact cluster"),
            ("runtimeBinding", "semanticSecurityGroupId", "sg-0123456789abcdef0",
             "not distinct"),
            ("networkIsolation", "staticRulesTerraformOwned", False, "not Terraform-owned"),
            ("networkIsolation", "securityGroupRuleCount", 8, "exactly seven"),
            ("networkIsolation", "semanticEniCountBeforeStart", 1, "reviewed exact value"),
            ("networkIsolation", "restoredDatabasePubliclyAccessible", True, "publicly accessible"),
            ("publicSafety", "publicEntrypointFixed503", False, "not fixed 503"),
            ("publicSafety", "applicationDesiredCount", 1, "desired count"),
            ("publicSafety", "runningApplicationTaskCount", 1, "fleet was running"),
        ]
        for section, key, value, message in cases:
            with self.subTest(section=section, key=key):
                evidence = self.evidence()
                evidence[section][key] = value
                self.assert_invalid(evidence, message)

    def test_exact_seven_database_canaries_and_clone_binding_are_required(self) -> None:
        evidence = self.evidence()
        evidence["databaseVerification"]["exactCanaryRowCounts"]["payment"] = 0
        self.assert_invalid(evidence, "exactly one per logical database")

        evidence = self.evidence()
        evidence["databaseVerification"]["logicalDatabases"] = DATABASES[:-1]
        self.assert_invalid(evidence, "exact seven")

        evidence = self.evidence()
        evidence["databaseVerification"]["replayCloneDatabase"] = "restore_replay_unbound"
        self.assert_invalid(evidence, "not operation-bound")

    def test_restored_s3_versions_hashes_metadata_and_scope_are_required(self) -> None:
        evidence = self.evidence()
        evidence["documentVerification"]["destinationVersionIds"][1] = "destination-version-one"
        self.assert_invalid(evidence, "two distinct destination VersionIds")

        evidence = self.evidence()
        evidence["documentVerification"]["deleteMarkerCount"] = 1
        self.assert_invalid(evidence, "delete marker")

        evidence = self.evidence()
        evidence["documentVerification"]["generations"][0]["contentSha256MetadataVerified"] = False
        self.assert_invalid(evidence, "contentSha256MetadataVerified")

        evidence = self.evidence()
        evidence["documentVerification"]["generations"][1]["sha256"] = "a" * 64
        self.assert_invalid(evidence, "payload generations are not distinct")

        evidence = self.evidence()
        evidence["documentVerification"]["customerMetadataObjectMappingClaimed"] = True
        self.assert_invalid(evidence, "overclaims non-customer scope")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["customerObjectErasureClaimed"] = True
        self.assert_invalid(evidence, "overclaims customer object erasure")

    def test_journal_retry_retention_and_readiness_are_exact(self) -> None:
        evidence = self.evidence()
        evidence["erasureReplayVerification"]["operationId"] = REPLAY
        self.assert_invalid(evidence, "reserved UUIDv4 namespace")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["versionCount"] = 2
        self.assert_invalid(evidence, "exactly one immutable version")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["deleteMarkerCount"] = 1
        self.assert_invalid(evidence, "delete marker")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["minimumRetentionDays"] = 35
        self.assert_invalid(evidence, "minimum retention")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["sourceRetryIdempotent"] = False
        self.assert_invalid(evidence, "sourceRetryIdempotent")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["replayReadiness"]["backupRetentionPending"] = 0
        self.assert_invalid(evidence, "exactly one synthetic")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["sourceReadiness"]["backupRetentionOverdue"] = 1
        self.assert_invalid(evidence, "backupRetentionOverdue")

        evidence = self.evidence()
        evidence["scopeLimitations"].remove("CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED")
        self.assert_invalid(evidence, "limitations")

    def test_duplicate_json_keys_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schemaVersion":"one","schemaVersion":"two"}', encoding="utf-8")
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(duplicate)],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate semantic evidence key", result.stderr)

            target = root / "target.json"
            target.write_text(json.dumps(self.evidence()), encoding="utf-8")
            symlink = root / "link.json"
            symlink.symlink_to(target)
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(symlink)],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsafe semantic evidence file", result.stderr)


if __name__ == "__main__":
    unittest.main()
