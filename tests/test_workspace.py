from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.security.generate_profile_env import PROFILE_TEMPLATES
from scripts.contracts.lock import load_contract_lock, validate_contract_lock
from scripts.workspace.bootstrap import expected_remote, inspect_checkout, plan
from scripts.workspace.catalog import (
    WORKSPACE_ROOT,
    load_catalog,
    load_workspace_lock,
)
from scripts.workspace.lifecycle import (
    compose_command,
    controlled_environment,
    ensure_environment,
    environment_path,
    main as lifecycle_main,
    parse_compose_status,
    selected_repositories,
    stage_runtime_image_contexts,
    validate_runtime_boundary,
)
from scripts.workspace.onboard import main as onboard_main


class CatalogTests(unittest.TestCase):
    def test_missing_e2e_environment_uses_the_e2e_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env.e2e"
            profile = replace(
                load_catalog().profile("e2e"), environment_file=output
            )

            self.assertEqual(ensure_environment(profile), output)

            text = output.read_text(encoding="utf-8")
            self.assertIn("FIXTURE_DATASET_VERSION=1.1.0", text)
            e2e_ports = {
                name: value
                for line in text.splitlines()
                if line.startswith("E2E_") and "=" in line
                for name, value in [line.split("=", 1)]
                if name.endswith("_PORT")
            }
            self.assertEqual(
                e2e_ports,
                {
                    "E2E_FRONTEND_PORT": "3100",
                    "E2E_SYSTEM_DATA_SERVICE_PORT": "9103",
                    "E2E_AUTHENTICATION_SERVICE_PORT": "9104",
                },
            )
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                PROFILE_TEMPLATES[profile.environment_profile].name,
                ".env.e2e.example",
            )

    def test_clean_workspace_onboarding_accepts_e2e(self) -> None:
        with patch(
            "sys.argv", ["onboard", "--profile", "e2e", "--skip-build"]
        ), patch("scripts.workspace.onboard.run") as run, patch(
            "scripts.workspace.onboard.ensure_environment"
        ) as ensure:
            self.assertEqual(onboard_main(), 0)

        self.assertEqual(run.call_count, 3)
        ensure.assert_called_once_with(load_catalog().profile("e2e"))

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
                "e2e",
                "full-local-ses",
                "google-maps-smoke",
                "real-job-providers",
                "real-providers",
            },
        )
        real_providers = catalog.profile("real-job-providers")
        expected_real_environment = (
            WORKSPACE_ROOT / "infrastructure" / ".env.real-job-providers"
        )
        self.assertEqual(real_providers.environment_file, expected_real_environment)
        self.assertEqual(
            real_providers.secret_environment_file,
            WORKSPACE_ROOT / "config" / ".secrets.env",
        )
        self.assertEqual(
            real_providers.compose_files,
            ("docker-compose.yml", "docker-compose.real-job-providers.yml"),
        )
        self.assertEqual(
            real_providers.secret_providers,
            ("REED", "ADZUNA", "JSEARCH", "APPRENTICESHIPS"),
        )
        real_openai = catalog.profile("real-providers")
        self.assertEqual(real_openai.environment_file, expected_real_environment)
        self.assertEqual(environment_path(real_openai), expected_real_environment)
        self.assertEqual(
            real_openai.compose_files,
            (
                "docker-compose.yml",
                "docker-compose.real-job-providers.yml",
                "docker-compose.real-openai.yml",
                "docker-compose.real-google-maps.yml",
                "docker-compose.low-memory.yml",
            ),
        )
        self.assertEqual(real_openai.compose_parallel_limit, 1)
        self.assertEqual(
            real_openai.secret_providers,
            (
                "REED",
                "ADZUNA",
                "JSEARCH",
                "APPRENTICESHIPS",
                "OPENAI",
                "GOOGLE",
            ),
        )
        google_maps = catalog.profile("google-maps-smoke")
        self.assertEqual(google_maps.secret_providers, ("GOOGLE",))
        self.assertEqual(
            google_maps.compose_files,
            (
                "docker-compose.yml",
                "docker-compose.real-google-maps.yml",
                "docker-compose.low-memory.yml",
            ),
        )
        self.assertEqual(
            google_maps.secret_environment_file,
            WORKSPACE_ROOT / "config" / ".secrets.env",
        )
        e2e = catalog.profile("e2e")
        self.assertEqual(
            e2e.compose_files,
            (
                "docker-compose.yml",
                "docker-compose.e2e.yml",
                "docker-compose.low-memory.yml",
            ),
        )
        self.assertEqual(e2e.compose_project, "job-seeker-copilot-e2e")
        self.assertEqual(e2e.compose_parallel_limit, 1)
        self.assertEqual(e2e.environment_profile, "e2e")
        self.assertEqual(e2e.frontend_url, "http://localhost:3100")
        command = compose_command(real_openai, expected_real_environment, "ps")
        self.assertEqual(
            command,
            [
                "docker",
                "compose",
                "--parallel",
                "1",
                "-p",
                "job-seeker-copilot-real-jobs",
                "--env-file",
                str(expected_real_environment),
                "--env-file",
                str(WORKSPACE_ROOT / "config" / ".secrets.env"),
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.real-job-providers.yml",
                "-f",
                "docker-compose.real-openai.yml",
                "-f",
                "docker-compose.real-google-maps.yml",
                "-f",
                "docker-compose.low-memory.yml",
                "ps",
            ],
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
        openai_overlay = yaml.safe_load(
            (WORKSPACE_ROOT / "infrastructure"
             / "docker-compose.real-openai.yml").read_text()
        )
        self.assertEqual(
            openai_overlay["services"]["llm-gateway"]["environment"][
                "EXTERNAL_PROVIDER_MODE"
            ],
            "LIVE",
        )
        self.assertEqual(
            openai_overlay["services"]["job-seeker-copilot-client"][
                "environment"
            ]["DOCUMENT_GENERATION_MODE"],
            "REAL_LLM",
        )
        self.assertEqual(
            {
                secret["target"]
                for secret in openai_overlay["services"]["llm-gateway"]["secrets"]
            },
            {"OPENAI_API_KEY"},
        )
        google_overlay = yaml.safe_load(
            (WORKSPACE_ROOT / "infrastructure"
             / "docker-compose.real-google-maps.yml").read_text()
        )
        google_gateway = google_overlay["services"]["google-maps-gateway"]
        self.assertEqual(google_gateway["environment"]["GOOGLE_MAPS_ENABLED"], "true")
        self.assertEqual(
            google_gateway["environment"]["SPRING_CONFIG_IMPORT"],
            "optional:configtree:/run/secrets/",
        )
        self.assertEqual(
            {secret["target"] for secret in google_gateway["secrets"]},
            {"GOOGLE_MAPS_API_KEY"},
        )
        self.assertEqual(
            set(google_gateway["networks"]),
            {"job-seeker-network", "google-maps-egress-network"},
        )
        base_services = yaml.safe_load(
            (WORKSPACE_ROOT / "infrastructure" / "docker-compose.yml").read_text()
        )["services"]
        low_memory_services = yaml.safe_load(
            (
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.low-memory.yml"
            ).read_text()
        )["services"]
        runtime_services = {
            name
            for name, configuration in base_services.items()
            if not configuration.get("profiles")
        }
        self.assertEqual(set(low_memory_services), runtime_services)
        self.assertTrue(
            all("mem_limit" in service for service in low_memory_services.values())
        )
        self.assertIn(
            "-Xmx240m",
            low_memory_services["llm-gateway"]["environment"][
                "JAVA_TOOL_OPTIONS"
            ],
        )
        self.assertEqual(
            low_memory_services["payment-service"]["mem_limit"],
            "512m",
        )
        self.assertIn(
            "-Xmx160m",
            low_memory_services["payment-service"]["environment"][
                "JAVA_TOOL_OPTIONS"
            ],
        )
        self.assertEqual(
            low_memory_services["application-tracker-service"]["mem_limit"],
            "512m",
        )
        self.assertIn(
            "-Xmx192m",
            low_memory_services["application-tracker-service"]["environment"][
                "JAVA_TOOL_OPTIONS"
            ],
        )
        self.assertIn(
            "-XX:MaxMetaspaceSize=160m",
            low_memory_services["application-tracker-service"]["environment"][
                "JAVA_TOOL_OPTIONS"
            ],
        )
        self.assertEqual(
            low_memory_services["job-seeker-copilot-client"]["environment"][
                "NODE_OPTIONS"
            ],
            "--max-old-space-size=192",
        )
        self.assertIn(
            "shared_buffers=32MB",
            low_memory_services["document-generation-postgres"]["command"],
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

    def test_real_providers_lifecycle_dispatch_accepts_operational_commands(
        self,
    ) -> None:
        profile = load_catalog().profile("real-providers")
        dispatches = (
            (
                "start",
                "scripts.workspace.lifecycle.start",
                (profile, False),
            ),
            (
                "stop",
                "scripts.workspace.lifecycle.stop",
                (profile, False, False),
            ),
            (
                "health",
                "scripts.workspace.lifecycle.health",
                (profile, 600),
            ),
        )
        for command, target, expected in dispatches:
            with self.subTest(command=command), patch(
                "sys.argv",
                ["lifecycle", command, "--profile", "real-providers"],
            ), patch(target) as operation:
                self.assertEqual(lifecycle_main(), 0)
                operation.assert_called_once_with(*expected)

        environment_file = profile.environment_file
        with patch(
            "sys.argv",
            ["lifecycle", "status", "--profile", "real-providers"],
        ), patch(
            "scripts.workspace.lifecycle.ensure_environment",
            return_value=environment_file,
        ), patch("scripts.workspace.lifecycle.run") as run:
            self.assertEqual(lifecycle_main(), 0)
        status_command = run.call_args.args[0]
        self.assertEqual(status_command[-1], "ps")
        self.assertEqual(
            status_command[status_command.index("--env-file") + 1],
            str(environment_file),
        )
        self.assertIn(
            str(WORKSPACE_ROOT / "config" / ".secrets.env"),
            status_command,
        )

    def test_real_providers_startup_preflight_uses_catalogued_overlay_order(
        self,
    ) -> None:
        profile = load_catalog().profile("real-providers")
        rendered = {"services": {}}
        with patch(
            "scripts.workspace.lifecycle.compose_security_model",
            return_value=rendered,
        ) as compose, patch(
            "scripts.workspace.lifecycle.validate_security_model"
        ) as validate:
            validate_runtime_boundary(profile, profile.environment_file)

        compose.assert_called_once_with(
            profile.environment_file,
            [
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.real-job-providers.yml",
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.real-openai.yml",
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.real-google-maps.yml",
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.low-memory.yml",
            ],
            "real-providers",
            secret_env_file=WORKSPACE_ROOT / "config" / ".secrets.env",
        )
        validate.assert_called_once_with(rendered, "real-providers")

    def test_e2e_lifecycle_dispatch_and_compose_command_are_catalogued(self) -> None:
        profile = load_catalog().profile("e2e")
        dispatches = (
            ("start", "scripts.workspace.lifecycle.start", (profile, False)),
            ("stop", "scripts.workspace.lifecycle.stop", (profile, False, False)),
            ("health", "scripts.workspace.lifecycle.health", (profile, 600)),
        )
        for command, target, expected in dispatches:
            with self.subTest(command=command), patch(
                "sys.argv", ["lifecycle", command, "--profile", "e2e"]
            ), patch(target) as operation:
                self.assertEqual(lifecycle_main(), 0)
                operation.assert_called_once_with(*expected)

        command = compose_command(profile, profile.environment_file, "ps")
        self.assertEqual(
            command,
            [
                "docker",
                "compose",
                "--parallel",
                "1",
                "-p",
                "job-seeker-copilot-e2e",
                "--env-file",
                str(profile.environment_file),
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.e2e.yml",
                "-f",
                "docker-compose.low-memory.yml",
                "ps",
            ],
        )

    def test_e2e_startup_preflight_uses_isolation_then_low_memory(self) -> None:
        profile = load_catalog().profile("e2e")
        rendered = {"services": {}}
        with patch(
            "scripts.workspace.lifecycle.compose_security_model",
            return_value=rendered,
        ) as compose, patch(
            "scripts.workspace.lifecycle.validate_security_model"
        ) as validate:
            validate_runtime_boundary(profile, profile.environment_file)

        compose.assert_called_once_with(
            profile.environment_file,
            [
                WORKSPACE_ROOT / "infrastructure" / "docker-compose.e2e.yml",
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.low-memory.yml",
            ],
            "e2e",
        )
        validate.assert_called_once_with(rendered, "e2e")

    def test_google_maps_startup_preflight_enforces_the_gateway_boundary(
        self,
    ) -> None:
        profile = load_catalog().profile("google-maps-smoke")
        rendered = {
            "services": {
                "google-maps-gateway": {
                    "environment": {"GOOGLE_MAPS_ENABLED": "true"},
                    "secrets": [
                        {"target": "GOOGLE_MAPS_API_KEY"}
                    ],
                },
                "location-service": {
                    "environment": {"GOOGLE_MAPS_ENABLED": "true"}
                },
            }
        }
        with patch(
            "scripts.workspace.lifecycle.compose_security_model",
            return_value=rendered,
        ) as compose, patch(
            "scripts.workspace.lifecycle.validate_security_model"
        ) as validate:
            validate_runtime_boundary(profile, profile.environment_file)

        compose.assert_called_once_with(
            profile.environment_file,
            [
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.real-google-maps.yml",
                WORKSPACE_ROOT
                / "infrastructure"
                / "docker-compose.low-memory.yml",
            ],
            "local",
            secret_env_file=WORKSPACE_ROOT / "config" / ".secrets.env",
        )
        validate.assert_called_once_with(rendered, "local")

    def test_google_maps_startup_preflight_rejects_key_environment_exposure(
        self,
    ) -> None:
        profile = load_catalog().profile("google-maps-smoke")
        rendered = {
            "services": {
                "google-maps-gateway": {
                    "environment": {
                        "GOOGLE_MAPS_ENABLED": "true",
                        "GOOGLE_MAPS_API_KEY": "must-not-be-an-environment-value",
                    },
                    "secrets": [
                        {"target": "GOOGLE_MAPS_API_KEY"}
                    ],
                },
                "location-service": {
                    "environment": {"GOOGLE_MAPS_ENABLED": "true"}
                },
            }
        }
        with patch(
            "scripts.workspace.lifecycle.compose_security_model",
            return_value=rendered,
        ):
            with self.assertRaisesRegex(RuntimeError, "container environment"):
                validate_runtime_boundary(profile, profile.environment_file)

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
            "4.2.0-rev.3129864cca5c",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["cv-cover-letter-service"]["revision"],
            "3129864cca5c0eca8fcf9a4df59ce4bda91ef1a1",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["version"],
            "3.1.0-rev.cda9a2af811b",
        )
        self.assertEqual(
            services["document-export-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["document-export-service"]["revision"],
            "cda9a2af811bafe99ecd686faab14db67f21ae32",
        )
        self.assertEqual(
            services["user-profile-service"]["javaPackage"]["version"],
            "2.3.0-rev.a880add6e5c7",
        )
        self.assertEqual(
            services["user-profile-service"]["javaPackage"]["releaseState"],
            "published",
        )
        self.assertEqual(
            services["user-profile-service"]["revision"],
            "a880add6e5c7106a2f3abec08a147823f88edf20",
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
