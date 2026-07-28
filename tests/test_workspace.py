from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.contracts.lock import load_contract_lock, validate_contract_lock
from scripts.workspace.bootstrap import expected_remote, inspect_checkout, plan
from scripts.workspace.catalog import (
    WORKSPACE_ROOT,
    load_catalog,
    load_workspace_lock,
)
from scripts.workspace.lifecycle import (
    controlled_environment,
    parse_compose_status,
    selected_repositories,
    stage_runtime_image_contexts,
)


class CatalogTests(unittest.TestCase):
    def test_compose_status_parser_supports_array_and_line_delimited_json(
        self,
    ) -> None:
        expected = [
            {"Service": "authentication-service", "State": "running"},
            {"Service": "job-service", "State": "running"},
        ]
        self.assertEqual(parse_compose_status(json.dumps(expected)), expected)
        self.assertEqual(
            parse_compose_status("\n".join(json.dumps(item) for item in expected)),
            expected,
        )
        with self.assertRaisesRegex(
            RuntimeError, "unexpected Docker Compose status output"
        ):
            parse_compose_status('{"Service":"authentication-service"}\nnot-json')

    def test_runtime_commands_reject_inherited_application_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PATH": "/safe/tool/path",
                "OPENAI_API_KEY": "must-not-leak",
                "AUTH_SERVICE_TOKEN": "must-not-override-generated-value",
            },
            clear=True,
        ):
            environment = controlled_environment()

        self.assertEqual(environment["PATH"], "/safe/tool/path")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("AUTH_SERVICE_TOKEN", environment)

    def test_runtime_image_context_uses_current_workspace_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = (
                workspace
                / "jsearch-gateway"
                / "target"
                / "jsearch-gateway-1.0.0.jar"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"locked-workspace-artifact")
            with (
                patch("scripts.workspace.lifecycle.WORKSPACE_ROOT", workspace),
                patch(
                    "scripts.workspace.lifecycle.RUNTIME_IMAGE_CACHE",
                    workspace / ".cache/runtime-images",
                ),
            ):
                stage_runtime_image_contexts({"jsearch-gateway"})

            self.assertEqual(
                (
                    workspace
                    / ".cache/runtime-images/jsearch-gateway/app.jar"
                ).read_bytes(),
                b"locked-workspace-artifact",
            )

    def test_repository_names_are_unique(self) -> None:
        catalog = load_catalog()
        self.assertEqual(
            len(catalog.repository_names), len(set(catalog.repository_names))
        )
        self.assertIn("job-matching-service", catalog.repository_names)
        self.assertIn("e2e", catalog.repository_names)
        self.assertEqual(
            catalog.repository("job-seeker-copilot-client").health, "/"
        )
        self.assertEqual(catalog.infrastructure_path, "infrastructure")
        self.assertEqual(catalog.project_title, "Job Seeker Copilot")
        self.assertEqual(catalog.project_number, 1)
        self.assertEqual(
            {profile.name for profile in catalog.profiles},
            {
                "basic-fixture",
                "full-fixture",
                "real-job-providers",
                "nhs-jobs-fixture",
                "nhs-jobs-development",
            },
        )
        real_providers = catalog.profile("real-job-providers")
        self.assertEqual(
            real_providers.secret_environment_file,
            WORKSPACE_ROOT / "config" / ".secrets.env",
        )
        self.assertEqual(
            real_providers.compose_files,
            ("docker-compose.yml", "docker-compose.real-job-providers.yml"),
        )
        real_provider_overlay = yaml.safe_load(
            (WORKSPACE_ROOT / "infrastructure"
             / "docker-compose.real-job-providers.yml").read_text()
        )
        self.assertFalse(
            real_provider_overlay["networks"]["provider-egress-network"]["internal"]
        )
        provider_secrets = {
            "reed-gateway": {"REED_API_KEY"},
            "adzuna-gateway": {"ADZUNA_APP_ID", "ADZUNA_APP_KEY"},
            "jsearch-gateway": {"JSEARCH_API_KEY"},
        }
        for service, expected_targets in provider_secrets.items():
            configuration = real_provider_overlay["services"][service]
            self.assertEqual(
                configuration["environment"]["SPRING_CONFIG_IMPORT"],
                "optional:configtree:/run/secrets/",
            )
            self.assertTrue(
                expected_targets.isdisjoint(configuration["environment"])
            )
            self.assertEqual(
                {
                    secret["target"]
                    for secret in configuration["secrets"]
                },
                expected_targets,
            )
            self.assertEqual(
                set(configuration["networks"]),
                {"job-seeker-network", "provider-egress-network"},
            )
        nhs_fixture = catalog.profile("nhs-jobs-fixture")
        self.assertEqual(
            nhs_fixture.compose_files,
            ("docker-compose.yml",),
        )
        self.assertEqual(
            nhs_fixture.services,
            ("nhs-jobs-gateway",),
        )
        self.assertEqual(nhs_fixture.frontend_url, "http://localhost:8104")
        nhs_development = catalog.profile("nhs-jobs-development")
        self.assertEqual(
            nhs_development.compose_files,
            ("docker-compose.yml", "docker-compose.real-nhs-jobs.yml"),
        )
        self.assertEqual(
            nhs_development.services,
            ("nhs-jobs-gateway",),
        )
        nhs_overlay = yaml.safe_load(
            (
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.real-nhs-jobs.yml"
            ).read_text()
        )
        self.assertEqual(
            set(nhs_overlay["services"]),
            {"nhs-jobs-gateway"},
        )
        self.assertEqual(
            set(nhs_overlay["services"]["nhs-jobs-gateway"]["networks"]),
            {"job-seeker-network", "nhs-jobs-egress-network"},
        )
        self.assertFalse(
            nhs_overlay["networks"]["nhs-jobs-egress-network"]["internal"]
        )
        self.assertEqual(
            set(load_workspace_lock(catalog)),
            set(catalog.repository_names),
        )
        self.assertFalse(
            (
                Path(__file__).resolve().parents[1]
                / "scripts/clients/config/service_dependencies.json"
            ).exists(),
            "the authoritative catalogue must not have a competing manifest",
        )

    def test_basic_and_full_profiles_have_distinct_source_scope(self) -> None:
        catalog = load_catalog()
        basic = {
            repository.name
            for repository in selected_repositories(
                catalog, catalog.profile("basic-fixture")
            )
        }
        full = {
            repository.name
            for repository in selected_repositories(
                catalog, catalog.profile("full-fixture")
            )
        }
        self.assertIn("job-seeker-copilot-client", basic)
        self.assertIn("job-finder-gateway", basic)
        self.assertNotIn("payment-gateway", basic)
        self.assertIn("payment-gateway", full)
        self.assertNotIn("e2e", full)
        self.assertLess(basic, full)

    def test_compose_uses_sibling_contexts_without_global_container_names(self) -> None:
        infrastructure = Path(__file__).resolve().parents[1]
        for name in (
            "docker-compose.yml",
            "docker-compose.e2e.yml",
            "docker-compose.data-acquisition.yml",
        ):
            text = (infrastructure / name).read_text(encoding="utf-8")
            self.assertNotIn("context: ./", text)
            self.assertNotIn("container_name:", text)
            self.assertNotIn(str(Path.home()), text)

    def test_invalid_catalog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "organisation": "jobseekercopilot",
                        "githubProject": {
                            "title": "Job Seeker Copilot",
                            "number": 1,
                        },
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

    def test_dirty_expected_checkout_fails_without_mutation(self) -> None:
        catalog = load_catalog()
        repository = catalog.repository("authentication-service")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / repository.name
            path.mkdir()
            with (
                patch(
                    "scripts.workspace.bootstrap.remote_url",
                    return_value=expected_remote(catalog.owner, repository.name)[0],
                ),
                patch(
                    "scripts.workspace.bootstrap.git_value",
                    side_effect=[repository.branch, "a" * 40],
                ),
                patch("scripts.workspace.bootstrap.is_clean", return_value=False),
            ):
                state = inspect_checkout(
                    Path(directory), catalog.owner, repository, "b" * 40
                )
        self.assertEqual(state.status, "dirty")
        self.assertIn("no mutation", state.detail or "")

    def test_clean_revision_drift_requires_explicit_update(self) -> None:
        catalog = load_catalog()
        repository = catalog.repository("authentication-service")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / repository.name
            path.mkdir()
            with (
                patch(
                    "scripts.workspace.bootstrap.remote_url",
                    return_value=expected_remote(catalog.owner, repository.name)[0],
                ),
                patch(
                    "scripts.workspace.bootstrap.git_value",
                    side_effect=[repository.branch, "a" * 40],
                ),
                patch("scripts.workspace.bootstrap.is_clean", return_value=True),
            ):
                state = inspect_checkout(
                    Path(directory), catalog.owner, repository, "b" * 40
                )
        self.assertEqual(state.status, "revision-drift")
        self.assertIn("--update", state.detail or "")


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
            "2.0.0-rev.87fc2393309a",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["revision"],
            "87fc2393309ad3007cba6ac27aa618fc3cc81aa9",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["version"],
            "2.0.0-rev.a35fff34f86b",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["document-export-service"]["revision"],
            "a35fff34f86b77457df4b9e324000a32819d5aba",
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
