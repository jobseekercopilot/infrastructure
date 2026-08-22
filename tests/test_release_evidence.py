from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.release.evidence import (
    DEFAULT_POLICY,
    load_json,
    validate_release_evidence,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.evidence_root = Path(self.directory.name)
        self.policy = load_json(DEFAULT_POLICY)
        digest = self._evidence("clean evidence")
        self.manifest = {
            "schemaVersion": 1,
            "releaseId": "beta-2026-07-26.1",
            "createdAt": "2026-07-26T11:30:00Z",
            "artifacts": [
                {
                    "name": "reporting-service",
                    "type": "container-image",
                    "owner": "Reporting",
                    "source": {
                        "repository": (
                            "https://github.com/jobseekercopilot/reporting-service"
                        ),
                        "revision": "a" * 40,
                    },
                    "builder": {
                        "name": "docker-buildx",
                        "version": "0.28.0",
                        "invocation": "docker buildx build --provenance=true",
                    },
                    "artifact": {
                        "reference": (
                            "ghcr.io/jobseekercopilot/reporting-service:beta"
                        ),
                        "digest": "sha256:" + "b" * 64,
                    },
                    "sbom": {
                        "format": "CycloneDX-1.6",
                        "path": "evidence.txt",
                        "sha256": digest,
                    },
                    "vulnerabilityScan": {
                        "scanner": "trivy",
                        "version": "0.72.0",
                        "completedAt": "2026-07-26T11:20:00Z",
                        "databaseUpdatedAt": "2026-07-26T11:00:00Z",
                        "report": "evidence.txt",
                        "reportSha256": digest,
                        "findings": [],
                    },
                    "licenceScan": {
                        "scanner": "dependency-check",
                        "version": "12.1.3",
                        "completedAt": "2026-07-26T11:20:00Z",
                        "report": "evidence.txt",
                        "reportSha256": digest,
                        "findings": [],
                    },
                    "provenance": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "path": "evidence.txt",
                        "sha256": digest,
                    },
                    "signature": {
                        "scheme": "sigstore-keyless",
                        "identity": "release-workflow",
                        "issuer": "https://token.actions.githubusercontent.com",
                        "verification": "evidence.txt",
                        "verificationSha256": digest,
                    },
                    "secretScan": {
                        "scanner": "gitleaks",
                        "version": "8.30.1",
                        "scope": "all-reachable-history",
                        "completedAt": "2026-07-26T11:20:00Z",
                        "commitsScanned": 12,
                        "bytesScanned": 431227,
                        "report": "evidence.txt",
                        "reportSha256": digest,
                    },
                    "exceptions": [],
                }
            ],
        }

    def _evidence(self, content: str) -> str:
        evidence = self.evidence_root / "evidence.txt"
        evidence.write_text(content, encoding="utf-8")
        return hashlib.sha256(evidence.read_bytes()).hexdigest()

    def validate(self, manifest: dict | None = None) -> None:
        validate_release_evidence(
            manifest or self.manifest,
            self.evidence_root,
            self.policy,
            now=NOW,
        )

    def test_complete_evidence_chain_is_accepted(self) -> None:
        self.validate()

    def test_evidence_checksum_mismatch_is_rejected(self) -> None:
        self.manifest["artifacts"][0]["sbom"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.validate()

    def test_mutable_source_revision_is_rejected(self) -> None:
        self.manifest["artifacts"][0]["source"]["revision"] = "develop"
        with self.assertRaisesRegex(ValueError, "full commit SHA"):
            self.validate()

    def test_zero_commit_secret_scan_is_rejected(self) -> None:
        self.manifest["artifacts"][0]["secretScan"]["commitsScanned"] = 0
        with self.assertRaisesRegex(ValueError, "integer >= 1"):
            self.validate()

    def test_stale_vulnerability_database_is_rejected(self) -> None:
        scan = self.manifest["artifacts"][0]["vulnerabilityScan"]
        scan["databaseUpdatedAt"] = "2026-07-24T11:00:00Z"
        with self.assertRaisesRegex(ValueError, "older than policy permits"):
            self.validate()

    def test_unapproved_high_vulnerability_is_rejected(self) -> None:
        self.manifest["artifacts"][0]["vulnerabilityScan"]["findings"] = [
            {"id": "CVE-TEST-1", "component": "example", "severity": "HIGH"}
        ]
        with self.assertRaisesRegex(ValueError, "lack an active exception"):
            self.validate()

    def test_finding_ids_are_unique_across_scanners(self) -> None:
        artifact = self.manifest["artifacts"][0]
        artifact["vulnerabilityScan"]["findings"] = [
            {"id": "SHARED-1", "component": "example", "severity": "LOW"}
        ]
        artifact["licenceScan"]["findings"] = [
            {"id": "SHARED-1", "component": "example", "spdxId": "MIT"}
        ]
        with self.assertRaisesRegex(ValueError, "unique across all scans"):
            self.validate()

    def test_owned_bounded_exception_is_accepted(self) -> None:
        artifact = self.manifest["artifacts"][0]
        artifact["vulnerabilityScan"]["findings"] = [
            {"id": "CVE-TEST-1", "component": "example", "severity": "HIGH"}
        ]
        artifact["exceptions"] = [
            {
                "id": "EX-1",
                "findingIds": ["CVE-TEST-1"],
                "owner": "Platform Security",
                "justification": "No fixed version is currently available.",
                "expiresAt": "2026-08-10T11:30:00Z",
                "compensatingControl": "Affected endpoint is not externally exposed.",
            }
        ]
        self.validate()

    def test_expired_exception_is_rejected(self) -> None:
        artifact = self.manifest["artifacts"][0]
        artifact["vulnerabilityScan"]["findings"] = [
            {"id": "CVE-TEST-1", "component": "example", "severity": "CRITICAL"}
        ]
        artifact["exceptions"] = [
            {
                "id": "EX-1",
                "findingIds": ["CVE-TEST-1"],
                "owner": "Platform Security",
                "justification": "Temporary approval.",
                "expiresAt": "2026-07-26T11:59:00Z",
                "compensatingControl": "Component disabled.",
            }
        ]
        with self.assertRaisesRegex(ValueError, "exception is expired"):
            self.validate()

    def test_prohibited_or_unknown_licence_requires_exception(self) -> None:
        for spdx_id in ("AGPL-3.0-only", "UNKNOWN"):
            with self.subTest(spdx_id=spdx_id):
                manifest = copy.deepcopy(self.manifest)
                manifest["artifacts"][0]["licenceScan"]["findings"] = [
                    {
                        "id": f"LICENCE-{spdx_id}",
                        "component": "example",
                        "spdxId": spdx_id,
                    }
                ]
                with self.assertRaisesRegex(ValueError, "lack an active exception"):
                    self.validate(manifest)

    def test_evidence_path_cannot_escape_root(self) -> None:
        self.manifest["artifacts"][0]["sbom"]["path"] = "../evidence.txt"
        with self.assertRaisesRegex(ValueError, "safe evidence-relative path"):
            self.validate()

    def test_cli_input_loader_rejects_non_object(self) -> None:
        path = self.evidence_root / "array.json"
        path.write_text(json.dumps([]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "expected a JSON object"):
            load_json(path)

    def test_unknown_policy_version_is_rejected(self) -> None:
        self.policy["schemaVersion"] = 2
        with self.assertRaisesRegex(ValueError, "policy.schemaVersion"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
