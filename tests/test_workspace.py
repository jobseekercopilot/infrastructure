from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.contracts.lock import load_contract_lock, validate_contract_lock
from scripts.workspace.bootstrap import expected_remote, plan
from scripts.workspace.catalog import load_catalog, load_workspace_lock


class CatalogTests(unittest.TestCase):
    def test_repository_names_are_unique(self) -> None:
        catalog = load_catalog()
        self.assertEqual(
            len(catalog.repository_names), len(set(catalog.repository_names))
        )
        self.assertIn("job-matching-service", catalog.repository_names)
        self.assertIn("e2e", catalog.repository_names)
        self.assertEqual(catalog.infrastructure_path, "infrastructure")
        self.assertEqual(
            {profile.name for profile in catalog.profiles},
            {"basic-fixture", "full-fixture"},
        )
        self.assertEqual(
            set(load_workspace_lock(catalog)),
            set(catalog.repository_names),
        )

    def test_invalid_catalog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "organisation": "jobseekercopilot",
                        "workspace": {
                            "layout": "sibling-repositories",
                            "infrastructurePath": "infrastructure",
                            "defaultBranch": "develop",
                            "lock": "config/workspace-lock.json",
                            "runtimeEnvironmentSchema": "config/runtime-environment.schema.json",
                        },
                        "profiles": {
                            "basic-fixture": {
                                "composeFiles": ["docker-compose.yml"],
                                "composeProject": "test",
                                "environmentProfile": "local",
                                "frontendUrl": "http://localhost:3000",
                                "services": ["duplicate"],
                            }
                        },
                        "buildOrder": ["duplicate", "duplicate"],
                        "repositories": [
                            {
                                "name": "duplicate",
                                "kind": "service",
                                "branch": "develop",
                                "build": "maven",
                                "composeServices": ["duplicate"],
                                "dependsOn": [],
                            },
                            {
                                "name": "duplicate",
                                "kind": "service",
                                "branch": "develop",
                                "build": "maven",
                                "composeServices": ["duplicate-two"],
                                "dependsOn": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unique"):
                load_catalog(path)


class BootstrapPlanTests(unittest.TestCase):
    def test_missing_checkout_is_planned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing, conflicts = plan(Path(directory), "owner", ("service",))
        self.assertEqual(missing, ["service"])
        self.assertEqual(conflicts, [])

    def test_unexpected_existing_checkout_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "service").mkdir()
            with patch(
                "scripts.workspace.bootstrap.remote_url",
                return_value="https://github.com/someone-else/service.git",
            ):
                missing, conflicts = plan(Path(directory), "owner", ("service",))
        self.assertEqual(missing, [])
        self.assertEqual(len(conflicts), 1)

    def test_https_and_ssh_remotes_are_accepted(self) -> None:
        self.assertIn(
            "https://github.com/owner/service.git",
            expected_remote("owner", "service"),
        )
        self.assertIn(
            "git@github.com:owner/service.git",
            expected_remote("owner", "service"),
        )


class ContractLockTests(unittest.TestCase):
    def test_repository_lock_is_valid_and_traceable(self) -> None:
        lock = load_contract_lock()
        services = {contract["service"]: contract for contract in lock["contracts"]}

        self.assertEqual(lock["generators"]["java-resttemplate"]["version"], "7.5.0")
        self.assertEqual(
            lock["registry"]["crossRepositoryCredential"],
            "classic-pat",
        )
        self.assertEqual(
            services["authentication-service"]["revision"],
            "2964aeb07b9861cce555d28cc58c6b9fab1f6107",
        )
        self.assertEqual(
            services["authentication-service"]["sha256"],
            "ce7f707b921a16fb8e53b580032bac4542334ed47f8f07c474e63ba2ecc4c812",
        )
        self.assertEqual(
            services["authentication-service"]["consumers"],
            ["document-generation-gateway"],
        )
        self.assertNotIn("javaPackage", services["authentication-service"])
        self.assertEqual(
            services["cv-cover-letter-service"]["javaPackage"]["version"],
            "1.0.0-rev.68b4cf9d3f23",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["revision"],
            "68b4cf9d3f2395abd642180a204db3a67d9ae80e",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["version"],
            "1.0.0-rev.aa7f34693d81",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["document-export-service"]["revision"],
            "aa7f34693d81e55686c90441b105a195b614a545",
        )
        self.assertEqual(
            services["user-profile-service"]["javaPackage"]["version"],
            "1.0.0-rev.86c8510ed319",
        )
        self.assertEqual(
            services["user-profile-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["user-profile-service"]["revision"],
            "86c8510ed319a059b991e6f9f1e43b0e101c5d1f",
        )

    def test_package_version_must_match_contract_and_revision(self) -> None:
        lock = load_contract_lock()
        lock["contracts"][-1]["javaPackage"]["version"] = "1.0.0"

        with self.assertRaisesRegex(ValueError, "first 12 source revision"):
            validate_contract_lock(lock)

    def test_unsafe_contract_path_is_rejected(self) -> None:
        lock = load_contract_lock()
        lock["contracts"][0]["path"] = "../openapi.json"

        with self.assertRaisesRegex(ValueError, "repository-relative"):
            validate_contract_lock(lock)

    def test_maven_cross_repository_auth_cannot_claim_granular_access(self) -> None:
        lock = load_contract_lock()
        lock["registry"]["crossRepositoryCredential"] = "github-token"

        with self.assertRaisesRegex(ValueError, "must be classic-pat"):
            validate_contract_lock(lock)


if __name__ == "__main__":
    unittest.main()
