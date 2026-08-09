from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.data.acquisition_policy import (
    CONFIRMATION,
    authorize,
    create_audit_manifest,
)
from scripts.data.capture_llm_fixtures import BACKLOG_URL, main as capture_llm
from scripts.data.purge_acquisition import main as purge_acquisition
from scripts.data.run_acquisition import main as run_acquisition
from scripts.docker.stack_config import stack_for
from scripts.docker.start_stack import main as start_stack
from scripts.docker.stop_stack import main as stop_stack
from scripts.security.generate_profile_env import PROFILE_TEMPLATES, render
from scripts.security.validate_compose_runtime import (
    compose_model,
    main as validate_compose_runtime,
    validate_model,
)


def write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


class RenderedModeIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary_directory.name)
        cls.models: dict[str, dict] = {}
        for profile, overlays in (
            ("local", []),
            ("e2e", [Path("docker-compose.e2e.yml")]),
        ):
            env_file = directory / f"{profile}.env"
            render(profile, PROFILE_TEMPLATES[profile], env_file)
            cls.models[profile] = compose_model(env_file, overlays, profile)

        local_ses_env = directory / "local-ses.env"
        render("local", PROFILE_TEMPLATES["local"], local_ses_env)
        cls.models["local-ses"] = compose_model(
            local_ses_env,
            [Path("docker-compose.local-ses.yml")],
            "local-ses",
        )

        e2e_local_ses_env = directory / "e2e-local-ses.env"
        render("e2e", PROFILE_TEMPLATES["e2e"], e2e_local_ses_env)
        cls.models["e2e-local-ses"] = compose_model(
            e2e_local_ses_env,
            [
                Path("docker-compose.e2e.yml"),
                Path("docker-compose.local-ses.yml"),
            ],
            "e2e-local-ses",
        )

        live_env = directory / "live.env"
        render("live-provider", PROFILE_TEMPLATES["live-provider"], live_env)
        live_secrets = directory / "live-secrets.env"
        write_environment(
            live_secrets,
            {
                "REED_API_KEY": "test-reed-key",
                "ADZUNA_APP_ID": "test-adzuna-id",
                "ADZUNA_APP_KEY": "test-adzuna-key",
                "JSEARCH_API_KEY": "test-jsearch-key",
            },
        )
        cls.models["live-provider"] = compose_model(
            live_env,
            [Path("docker-compose.live.yml")],
            "live-provider",
            live_secrets,
        )

        cls.real_providers_env = directory / "real-providers.env"
        render(
            "local",
            PROFILE_TEMPLATES["local"],
            cls.real_providers_env,
        )
        cls.real_provider_credentials = {
            "REED_API_KEY": "synthetic-reed-credential",
            "ADZUNA_APP_ID": "synthetic-adzuna-application",
            "ADZUNA_APP_KEY": "synthetic-adzuna-credential",
            "JSEARCH_API_KEY": "synthetic-jsearch-credential",
            "OPENAI_API_KEY": "synthetic-openai-credential-with-enough-characters",
        }
        cls.real_providers_secrets = directory / "real-providers-secrets.env"
        write_environment(
            cls.real_providers_secrets,
            {
                **cls.real_provider_credentials,
                "OPENAI_ENDPOINT": "https://api.openai.com/v1/chat/completions",
                "OPENAI_DATA_REGION": "GLOBAL",
                "OPENAI_DATA_CONTROL_MODE": (
                    "STANDARD_30_DAY_ABUSE_MONITORING"
                ),
                "OPENAI_DATA_SHARING_MODE": "DISABLED",
                "OPENAI_PRIVACY_DECISION_ID": "privacy-decision/test",
                "OPENAI_PRIVACY_OWNER": "Test owner",
                "OPENAI_PRIVACY_REVIEW_ON": "2026-10-25",
            },
        )
        cls.models["real-providers"] = compose_model(
            cls.real_providers_env,
            [
                Path("docker-compose.real-job-providers.yml"),
                Path("docker-compose.real-openai.yml"),
                Path("docker-compose.low-memory.yml"),
            ],
            "real-providers",
            cls.real_providers_secrets,
        )

        acquisition_env = directory / "acquisition.env"
        render(
            "data-acquisition",
            PROFILE_TEMPLATES["data-acquisition"],
            acquisition_env,
        )
        acquisition_inputs = directory / "acquisition-inputs.env"
        write_environment(
            acquisition_inputs,
            {
                "DATA_ACQUISITION_RUN_ID": "audit-20260726-001",
                "DATA_ACQUISITION_CONFIRMATION": CONFIRMATION,
                "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE": "INFRA-11-review",
                "DATA_ACQUISITION_PROVENANCE_REVIEWER": "local-reviewer",
                "DATA_ACQUISITION_APPROVED_PROVIDERS": "ADZUNA",
                "DATA_ACQUISITION_DATASET_VERSION": "2.0.0",
                "DATA_ACQUISITION_ADZUNA_ENABLED": "true",
                "ADZUNA_APP_ID": "test-adzuna-id",
                "ADZUNA_APP_KEY": "test-adzuna-key",
            },
        )
        cls.models["data-acquisition"] = compose_model(
            acquisition_env,
            [Path("docker-compose.data-acquisition.yml")],
            "data-acquisition",
            acquisition_inputs,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def model(self, profile: str) -> dict:
        return copy.deepcopy(self.models[profile])

    def test_all_seven_rendered_modes_pass_the_policy(self) -> None:
        for profile, model in self.models.items():
            validate_model(model, profile)

    def test_rejected_generation_quarantine_is_enabled_and_persistent(self) -> None:
        for profile in ("local", "e2e", "live-provider", "real-providers"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                service = model["services"]["cv-cover-letter-service"]
                environment = service["environment"]
                self.assertEqual(
                    "true",
                    environment["REJECTED_GENERATION_QUARANTINE_ENABLED"],
                )
                self.assertEqual(
                    "/var/lib/cv-cover-letter/rejected-generations",
                    environment["REJECTED_GENERATION_QUARANTINE_DIRECTORY"],
                )
                self.assertIn("cv-rejected-generation-quarantine", model["volumes"])
                self.assertEqual(
                    1,
                    len([
                        mount
                        for mount in service["volumes"]
                        if mount["source"] == "cv-rejected-generation-quarantine"
                        and mount["target"]
                        == "/var/lib/cv-cover-letter/rejected-generations"
                        and not mount.get("read_only", False)
                    ]),
                )

    def test_rejected_generation_quarantine_wiring_fails_closed(self) -> None:
        mutations = (
            (
                "environment",
                "REJECTED_GENERATION_QUARANTINE_ENABLED",
                "false",
                "must be true",
            ),
            (
                "environment",
                "REJECTED_GENERATION_QUARANTINE_KEY_BASE64",
                "not-valid-base64-value-with-32-bytes",
                "valid Base64",
            ),
            (
                "environment",
                "REJECTED_GENERATION_OPERATOR_TOKEN",
                None,
                "pairwise distinct",
            ),
        )
        for location, variable, value, message in mutations:
            with self.subTest(variable=variable):
                model = self.model("local")
                service_environment = model["services"][
                    "cv-cover-letter-service"
                ][location]
                if variable == "REJECTED_GENERATION_OPERATOR_TOKEN":
                    value = service_environment["CV_COVER_LETTER_GATEWAY_TOKEN"]
                service_environment[variable] = value
                with self.assertRaisesRegex(ValueError, message):
                    validate_model(model, "local")

        model = self.model("local")
        model["services"]["cv-cover-letter-service"]["volumes"] = []
        with self.assertRaisesRegex(ValueError, "must mount"):
            validate_model(model, "local")

    def test_combined_real_providers_keep_egress_and_fixture_payments_bounded(
        self,
    ) -> None:
        model = self.model("real-providers")
        services = model["services"]
        self.assertTrue(model["networks"]["job-seeker-network"]["internal"])
        self.assertFalse(
            model["networks"]["provider-egress-network"].get("internal", False)
        )
        egress_services = {
            name
            for name, service in services.items()
            if "provider-egress-network" in service.get("networks", {})
        }
        self.assertEqual(
            egress_services,
            {
                "reed-gateway",
                "adzuna-gateway",
                "jsearch-gateway",
                "llm-gateway",
            },
        )
        for gateway in ("reed-gateway", "adzuna-gateway", "jsearch-gateway"):
            self.assertEqual(
                services[gateway]["environment"]["EXTERNAL_PROVIDER_MODE"],
                "LIVE",
            )
        self.assertEqual(
            services["llm-gateway"]["environment"]["EXTERNAL_PROVIDER_MODE"],
            "LIVE",
        )
        self.assertEqual(
            services["stripe-gateway"]["environment"]["EXTERNAL_PROVIDER_MODE"],
            "FIXTURE",
        )
        self.assertEqual(
            services["stripe-gateway"]["environment"]["SYSTEM_DATA_SERVICE_URL"],
            "http://system-data-service:8103",
        )
        self.assertEqual(
            services["payment-gateway"]["environment"]["STRIPE_GATEWAY_URL"],
            "http://stripe-gateway:8100",
        )
        self.assertNotIn(
            "provider-egress-network",
            services["stripe-gateway"].get("networks", {}),
        )
        self.assertEqual(
            services["payment-service"]["environment"][
                "PAYMENT_DATABASE_PRODUCTION_SAFETY_CHECK"
            ],
            "false",
        )
        self.assertEqual(
            services["job-seeker-copilot-client"]["environment"][
                "JOB_SEARCH_PROVIDER_MODE"
            ],
            "REAL_PROVIDERS",
        )
        self.assertEqual(
            services["job-seeker-copilot-client"]["environment"][
                "DOCUMENT_GENERATION_MODE"
            ],
            "REAL_LLM",
        )

    def test_combined_real_provider_secrets_are_owned_and_value_free(
        self,
    ) -> None:
        model = self.model("real-providers")
        expected = {
            "reed-gateway": {"reed_api_key": "REED_API_KEY"},
            "adzuna-gateway": {
                "adzuna_app_id": "ADZUNA_APP_ID",
                "adzuna_app_key": "ADZUNA_APP_KEY",
            },
            "jsearch-gateway": {"jsearch_api_key": "JSEARCH_API_KEY"},
            "llm-gateway": {"openai_api_key": "OPENAI_API_KEY"},
        }
        for service_name, bindings in expected.items():
            service = model["services"][service_name]
            self.assertEqual(
                service["environment"]["SPRING_CONFIG_IMPORT"],
                "optional:configtree:/run/secrets/",
            )
            self.assertEqual(
                {
                    secret["source"]: secret["target"]
                    for secret in service["secrets"]
                },
                bindings,
            )
            for source, target in bindings.items():
                self.assertEqual(
                    model["secrets"][source]["environment"],
                    target,
                )
                self.assertNotIn(target, service["environment"])

        rendered = json.dumps(model, sort_keys=True)
        for credential in self.real_provider_credentials.values():
            self.assertNotIn(credential, rendered)

    def test_combined_real_providers_cannot_resolve_openai_as_disabled(
        self,
    ) -> None:
        model = self.model("real-providers")
        model["services"]["llm-gateway"]["environment"][
            "EXTERNAL_PROVIDER_MODE"
        ] = "DISABLED"
        with self.assertRaisesRegex(
            ValueError,
            "llm-gateway:EXTERNAL_PROVIDER_MODE must be LIVE",
        ):
            validate_model(model, "real-providers")

        unsafe_order = compose_model(
            self.real_providers_env,
            [
                Path("docker-compose.real-job-providers.yml"),
                Path("docker-compose.real-openai.yml"),
                Path("docker-compose.live.yml"),
                Path("docker-compose.low-memory.yml"),
            ],
            "real-providers",
            self.real_providers_secrets,
        )
        self.assertEqual(
            unsafe_order["services"]["llm-gateway"]["environment"][
                "EXTERNAL_PROVIDER_MODE"
            ],
            "DISABLED",
        )
        with self.assertRaises(ValueError):
            validate_model(unsafe_order, "real-providers")

    def test_combined_real_providers_fail_closed_on_boundary_crossover(
        self,
    ) -> None:
        model = self.model("real-providers")
        model["services"]["stripe-gateway"]["environment"][
            "EXTERNAL_PROVIDER_MODE"
        ] = "LIVE"
        with self.assertRaisesRegex(
            ValueError,
            "stripe-gateway:EXTERNAL_PROVIDER_MODE must be FIXTURE",
        ):
            validate_model(model, "real-providers")

        model = self.model("real-providers")
        model["services"]["payment-service"]["networks"][
            "provider-egress-network"
        ] = None
        with self.assertRaisesRegex(ValueError, "provider-egress-network"):
            validate_model(model, "real-providers")

        model = self.model("real-providers")
        model["services"]["llm-gateway"]["environment"].pop(
            "SPRING_CONFIG_IMPORT"
        )
        with self.assertRaisesRegex(ValueError, "SPRING_CONFIG_IMPORT"):
            validate_model(model, "real-providers")

        model = self.model("real-providers")
        model["services"]["llm-gateway"]["environment"][
            "OPENAI_API_KEY"
        ] = "must-not-be-an-environment-value"
        with self.assertRaisesRegex(ValueError, "mounted as an owned secret"):
            validate_model(model, "real-providers")

    def test_combined_validator_output_never_contains_provider_values(
        self,
    ) -> None:
        output = StringIO()
        with patch(
            "sys.argv",
            [
                "validate_compose_runtime",
                "--profile",
                "real-providers",
                "--env-file",
                str(self.real_providers_env),
                "--secret-env-file",
                str(self.real_providers_secrets),
                "--overlay",
                "docker-compose.real-job-providers.yml",
                "--overlay",
                "docker-compose.real-openai.yml",
                "--overlay",
                "docker-compose.low-memory.yml",
            ],
        ), redirect_stdout(output):
            self.assertEqual(validate_compose_runtime(), 0)
        text = output.getvalue()
        self.assertEqual(
            text,
            "real-providers Compose trust graph is valid; "
            "no values were printed.\n",
        )
        for credential in self.real_provider_credentials.values():
            self.assertNotIn(credential, text)

    def test_local_ses_profile_keeps_localstack_isolated_and_ephemeral(self) -> None:
        model = self.model("local-ses")
        localstack = model["services"]["localstack"]
        self.assertEqual(localstack["image"], "localstack/localstack:4.14.0")
        self.assertEqual(
            set(localstack["networks"]),
            {"job-seeker-network", "host-access"},
        )
        self.assertEqual(localstack["environment"]["SERVICES"], "ses")
        self.assertEqual(localstack["ports"][0]["host_ip"], "127.0.0.1")
        self.assertFalse(any(
            mount.get("type") == "volume"
            for mount in localstack["volumes"]
        ))
        authentication = model["services"]["authentication-service"]["environment"]
        self.assertEqual(
            authentication["AUTH_ACCOUNT_EMAIL_DELIVERY_MODE"],
            "local-ses",
        )
        self.assertEqual(
            authentication["AUTH_ACCOUNT_EMAIL_SES_ENDPOINT"],
            "http://localstack:4566",
        )

    def test_application_healthchecks_use_portable_alpine_wget(self) -> None:
        model = self.model("local")
        healthchecks = {
            service: configuration["healthcheck"]["test"]
            for service, configuration in model["services"].items()
            if "healthcheck" in configuration
            and configuration["healthcheck"]["test"][0] == "CMD"
            and "/actuator/health" in configuration["healthcheck"]["test"][-1]
        }
        self.assertTrue(healthchecks)
        for service, command in healthchecks.items():
            with self.subTest(service=service):
                self.assertEqual(command[:4], ["CMD", "wget", "-q", "--spider"])

    def test_e2e_rejects_live_mode_before_startup(self) -> None:
        model = self.model("e2e")
        model["services"]["reed-gateway"]["environment"][
            "EXTERNAL_PROVIDER_MODE"
        ] = "LIVE"
        with self.assertRaisesRegex(ValueError, "must be FIXTURE"):
            validate_model(model, "e2e")

    def test_fixture_network_cannot_gain_external_egress(self) -> None:
        for profile in ("local", "e2e"):
            model = self.model(profile)
            model["networks"]["job-seeker-network"]["internal"] = False
            with self.assertRaisesRegex(ValueError, "no external egress"):
                validate_model(model, profile)

    def test_only_approved_services_can_join_loopback_host_access_network(self) -> None:
        for profile in ("local", "e2e"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                host_access_services = {
                    service
                    for service, configuration in model["services"].items()
                    if "host-access" in configuration.get("networks", {})
                }
                expected_services = (
                    {"job-seeker-copilot-client"}
                    if profile == "local"
                    else {
                        "job-seeker-copilot-client",
                        "authentication-service",
                        "system-data-service",
                    }
                )
                self.assertEqual(
                    host_access_services, expected_services
                )
                self.assertEqual(
                    model["networks"]["host-access"]["driver_opts"][
                        "com.docker.network.bridge.host_binding_ipv4"
                    ],
                    "127.0.0.1",
                )

    def test_e2e_rejects_live_credentials_and_obsolete_mock_switch(self) -> None:
        for service, variable, value in (
            ("reed-gateway", "REED_API_KEY", "credential"),
            ("llm-gateway", "OPENAI_API_KEY", "credential"),
            ("stripe-gateway", "STRIPE_SECRET_KEY", "credential"),
            ("llm-gateway", "LLM_MOCK_MODE", "false"),
        ):
            with self.subTest(service=service, variable=variable):
                model = self.model("e2e")
                model["services"][service]["environment"][variable] = value
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_e2e_requires_exact_seed_profile_and_allowlist(self) -> None:
        for service, variable in (
            ("application-tracker-service", "ENVIRONMENT_DATA_ENABLED"),
            (
                "application-tracker-service",
                "ENVIRONMENT_DATA_ALLOWED_ENVIRONMENTS",
            ),
            (
                "system-data-service",
                "SYSTEM_DATA_ENVIRONMENT_ALLOWED_PROFILES",
            ),
        ):
            with self.subTest(service=service, variable=variable):
                model = self.model("e2e")
                model["services"][service]["environment"][variable] = "local"
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_app11_producer_consumer_pair_uses_the_internal_target_and_shared_identity(
        self,
    ) -> None:
        model = self.model("e2e")
        model["services"]["system-data-service"]["environment"][
            "APPLICATION_TRACKER_SERVICE_URL"
        ] = "https://application-tracker.example"
        with self.assertRaisesRegex(
            ValueError,
            "APPLICATION_TRACKER_SERVICE_URL must be "
            "http://application-tracker-service:8088",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["system-data-service"]["environment"][
            "SYSTEM_DATA_DOWNSTREAM_ENVIRONMENT_DATA_TOKEN"
        ] = "different-environment-data-identity-value"
        with self.assertRaisesRegex(
            ValueError,
            "ENVIRONMENT_DATA_TOKEN does not match",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["payment-service"]["environment"][
            "ENVIRONMENT_DATA_TOKEN"
        ] = "different-environment-data-identity-value"
        with self.assertRaisesRegex(
            ValueError,
            "ENVIRONMENT_DATA_TOKEN does not match",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["application-tracker-service"]["environment"][
            "SPRING_PROFILES_ACTIVE"
        ] = "local"
        with self.assertRaisesRegex(
            ValueError,
            "application-tracker-service:SPRING_PROFILES_ACTIVE must be e2e",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["user-profile-service"]["environment"][
            "SPRING_PROFILES_ACTIVE"
        ] = "e2e,local"
        with self.assertRaisesRegex(
            ValueError,
            "user-profile-service:SPRING_PROFILES_ACTIVE must be exactly "
            "e2e,environment-data in e2e",
        ):
            validate_model(model, "e2e")

        model = self.model("e2e")
        model["services"]["user-profile-service"]["environment"][
            "ENVIRONMENT_DATA_TOKEN"
        ] = "different-environment-data-identity-value"
        with self.assertRaisesRegex(
            ValueError,
            "ENVIRONMENT_DATA_TOKEN does not match",
        ):
            validate_model(model, "e2e")

    def test_application_tracker_uses_isolated_postgres_in_runtime_profiles(
        self,
    ) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                tracker = model["services"]["application-tracker-service"]
                database = model["services"]["application-tracker-postgres"]
                self.assertIn(
                    "application-tracker-postgres:5432",
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_URL"],
                )
                self.assertEqual(
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_PASSWORD"],
                    database["environment"]["POSTGRES_PASSWORD"],
                )
                self.assertEqual(
                    tracker["environment"][
                        "APPLICATION_TRACKER_DATABASE_PRODUCTION_SAFETY_CHECK"
                    ],
                    "false",
                )
                self.assertEqual(
                    tracker["environment"]["APPLICATION_TRACKER_DATABASE_SSL_MODE"],
                    "disable",
                )
                self.assertIn(
                    "application-tracker-postgres-data",
                    self.models[profile]["volumes"],
                )

    def test_application_tracker_database_binding_fails_closed(self) -> None:
        mutations = (
            ("APPLICATION_TRACKER_DATABASE_PASSWORD", "different-database-secret"),
            ("APPLICATION_TRACKER_DATABASE_PRODUCTION_SAFETY_CHECK", "true"),
            ("APPLICATION_TRACKER_DATABASE_SSL_MODE", "verify-full"),
            (
                "APPLICATION_TRACKER_DATABASE_URL",
                "jdbc:postgresql://shared-postgres:5432/application_tracker",
            ),
        )
        for variable, value in mutations:
            with self.subTest(variable=variable):
                model = self.model("e2e")
                model["services"]["application-tracker-service"]["environment"][
                    variable
                ] = value
                with self.assertRaises(ValueError):
                    validate_model(model, "e2e")

    def test_authentication_uses_isolated_postgres_in_runtime_profiles(
        self,
    ) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                authentication = model["services"]["authentication-service"]
                database = model["services"]["authentication-postgres"]
                self.assertIn(
                    "authentication-postgres:5432",
                    authentication["environment"]["AUTH_DB_URL"],
                )
                self.assertEqual(
                    authentication["environment"]["AUTH_DB_PASSWORD"],
                    database["environment"]["POSTGRES_PASSWORD"],
                )

        model = self.model("e2e")
        model["services"]["authentication-service"]["environment"][
            "AUTH_DB_URL"
        ] = "jdbc:h2:file:/app/data/e2e/authentication"
        with self.assertRaisesRegex(
            ValueError,
            "Authentication must use its isolated PostgreSQL service",
        ):
            validate_model(model, "e2e")

    def test_user_profile_uses_isolated_postgres_in_local_fixture(self) -> None:
        model = self.model("local")
        user_profile = model["services"]["user-profile-service"]
        database = model["services"]["user-profile-postgres"]
        self.assertIn(
            "user-profile-postgres:5432",
            user_profile["environment"]["PROFILE_DB_URL"],
        )
        self.assertEqual(
            user_profile["environment"]["PROFILE_DB_PASSWORD"],
            database["environment"]["POSTGRES_PASSWORD"],
        )
        self.assertIn("user-profile-postgres-data", model["volumes"])

    def test_job_service_uses_isolated_postgres_without_fixture_cycle(self) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                job_service = model["services"]["job-service"]
                database = model["services"]["job-service-postgres"]
                self.assertIn(
                    "job-service-postgres:5432",
                    job_service["environment"]["JOB_SERVICE_DATABASE_URL"],
                )
                self.assertEqual(
                    job_service["environment"]["JOB_SERVICE_DATABASE_PASSWORD"],
                    database["environment"]["POSTGRES_PASSWORD"],
                )
                self.assertNotIn(
                    "depends_on",
                    model["services"]["system-data-service"],
                )

    def test_document_generation_uses_isolated_postgres(self) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                gateway = model["services"]["document-generation-gateway"]
                database = model["services"]["document-generation-postgres"]
                self.assertIn(
                    "document-generation-postgres:5432",
                    gateway["environment"]["DOCUMENT_GENERATION_DATABASE_URL"],
                )
                self.assertEqual(
                    gateway["environment"]["DOCUMENT_GENERATION_DATABASE_PASSWORD"],
                    database["environment"]["POSTGRES_PASSWORD"],
                )
                self.assertEqual(
                    gateway["depends_on"]["document-generation-postgres"]["condition"],
                    "service_healthy",
                )
                self.assertIn("document-generation-postgres-data", model["volumes"])

    def test_document_store_lifecycle_coordination_and_purge_gate_are_exact(self) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                store = model["services"]["document-store-service"]["environment"]
                tracker = model["services"]["application-tracker-service"]["environment"]

                self.assertEqual(
                    store["APPLICATION_TRACKER_SERVICE_URL"],
                    "http://application-tracker-service:8088",
                )
                self.assertEqual(
                    store["APPLICATION_TRACKER_READER_TOKEN"],
                    tracker["APPLICATION_TRACKER_READER_TOKEN"],
                )
                self.assertEqual(
                    store["APPLICATION_TRACKER_PRODUCER_TOKEN"],
                    tracker["APPLICATION_TRACKER_PRODUCER_TOKEN"],
                )
                self.assertEqual(store["DOCUMENT_STORE_RECOVERY_DAYS"], "30")
                self.assertEqual(
                    store["DOCUMENT_STORE_COMPLETED_OPERATION_RETENTION_DAYS"],
                    "90",
                )
                self.assertEqual(
                    store["DOCUMENT_STORE_LIFECYCLE_AUDIT_DAYS"], "365"
                )
                self.assertEqual(
                    store["DOCUMENT_STORE_RETENTION_POLICY_VERSION"],
                    "DOC-09-2026-08-07",
                )
                self.assertEqual(store["DOCUMENT_STORE_PURGE_ENABLED"], "false")

    def test_authentication_account_lifecycle_dependencies_are_bounded(self) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                authentication = model["services"]["authentication-service"]
                environment = authentication["environment"]

                self.assertEqual(
                    environment["USER_PROFILE_SERVICE_URL"],
                    "http://user-profile-service:8085",
                )
                self.assertEqual(
                    environment["APPLICATION_TRACKER_SERVICE_URL"],
                    "http://application-tracker-service:8088",
                )
                self.assertEqual(
                    environment["DOCUMENT_STORE_SERVICE_URL"],
                    "http://document-store-service:8089",
                )
                self.assertEqual(
                    environment["AUTH_ACCOUNT_LIFECYCLE_RECENT_AUTHENTICATION_AGE"],
                    "15m",
                )
                self.assertEqual(
                    environment["AUTH_ACCOUNT_LIFECYCLE_COMPLETED_RETENTION"],
                    "365d",
                )
                self.assertEqual(
                    environment["AUTH_ACCOUNT_LIFECYCLE_CONNECT_TIMEOUT"],
                    "2s",
                )
                self.assertEqual(
                    environment["AUTH_ACCOUNT_LIFECYCLE_READ_TIMEOUT"],
                    "5s",
                )
                self.assertNotIn("user-profile-service", authentication["depends_on"])
                self.assertNotIn("application-tracker-service", authentication["depends_on"])
                self.assertNotIn("document-store-service", authentication["depends_on"])

    def test_document_store_purge_cannot_be_enabled_in_local_profiles(self) -> None:
        for profile in ("local", "e2e", "live-provider"):
            with self.subTest(profile=profile):
                model = self.model(profile)
                model["services"]["document-store-service"]["environment"][
                    "DOCUMENT_STORE_PURGE_ENABLED"
                ] = "true"
                with self.assertRaisesRegex(
                    ValueError, "DOCUMENT_STORE_PURGE_ENABLED must remain false"
                ):
                    validate_model(model, profile)

    def test_real_provider_document_store_has_bounded_heap_headroom(self) -> None:
        document_store = self.model("real-providers")["services"][
            "document-store-service"
        ]

        self.assertEqual(document_store["mem_limit"], "536870912")
        self.assertIn(
            "-Xmx240m",
            document_store["environment"]["JAVA_TOOL_OPTIONS"],
        )

    def test_reporting_gateway_tracker_and_store_reader_identities_are_exact(
        self,
    ) -> None:
        model = self.model("e2e")
        gateway = model["services"]["reporting-gateway"]["environment"]
        reporting = model["services"]["reporting-service"]["environment"]
        tracker = model["services"]["application-tracker-service"]["environment"]
        store = model["services"]["document-store-service"]["environment"]

        self.assertEqual(
            gateway["REPORTING_GATEWAY_SERVICE_TOKEN"],
            reporting["REPORTING_GATEWAY_SERVICE_TOKEN"],
        )
        self.assertEqual(
            reporting["APPLICATION_TRACKER_READER_TOKEN"],
            tracker["APPLICATION_TRACKER_READER_TOKEN"],
        )
        self.assertEqual(
            reporting["DOCUMENT_STORE_READER_TOKEN"],
            store["DOCUMENT_STORE_READER_TOKEN"],
        )
        self.assertEqual(
            reporting["DOCUMENT_STORE_SERVICE_URL"],
            "http://document-store-service:8089",
        )
        self.assertIn(
            "document-store-service",
            model["services"]["reporting-service"]["depends_on"],
        )
        self.assertEqual(
            gateway["REPORTING_GATEWAY_JWT_ISSUER"],
            model["services"]["authentication-service"]["environment"][
                "JWT_ISSUER"
            ],
        )

        for service, variable in (
            ("reporting-service", "REPORTING_GATEWAY_SERVICE_TOKEN"),
            ("reporting-service", "APPLICATION_TRACKER_READER_TOKEN"),
            ("reporting-service", "DOCUMENT_STORE_READER_TOKEN"),
            ("reporting-gateway", "REPORTING_GATEWAY_SERVICE_TOKEN"),
        ):
            with self.subTest(service=service, variable=variable):
                mutated = self.model("e2e")
                mutated["services"][service]["environment"][variable] = (
                    "different-reporting-identity-value-32-bytes"
                )
                with self.assertRaises(ValueError):
                    validate_model(mutated, "e2e")

    def test_local_and_live_profiles_keep_destructive_endpoints_disabled(self) -> None:
        for profile in ("local", "live-provider"):
            model = self.model(profile)
            model["services"]["system-data-service"]["environment"][
                "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED"
            ] = "true"
            with self.assertRaisesRegex(ValueError, "must be false"):
                validate_model(model, profile)

    def test_live_job_provider_profile_cannot_enable_llm_or_stripe(self) -> None:
        for service in ("llm-gateway", "stripe-gateway"):
            model = self.model("live-provider")
            model["services"][service]["environment"][
                "EXTERNAL_PROVIDER_MODE"
            ] = "LIVE"
            with self.assertRaises(ValueError):
                validate_model(model, "live-provider")

    def test_acquisition_contains_no_payment_llm_browser_or_host_port(self) -> None:
        model = self.model("data-acquisition")
        model["services"]["payment-service"] = {"environment": {}}
        with self.assertRaisesRegex(ValueError, "only approved"):
            validate_model(model, "data-acquisition")

        model = self.model("data-acquisition")
        model["services"]["adzuna-gateway"]["ports"] = [{"published": "8101"}]
        with self.assertRaisesRegex(ValueError, "must not publish"):
            validate_model(model, "data-acquisition")

    def test_acquisition_rejects_unapproved_credentials_and_mutable_source(self) -> None:
        model = self.model("data-acquisition")
        model["services"]["reed-gateway"]["environment"][
            "REED_API_KEY"
        ] = "unexpected"
        with self.assertRaisesRegex(ValueError, "must be absent"):
            validate_model(model, "data-acquisition")

        model = self.model("data-acquisition")
        mounts = model["services"]["system-data-service"]["volumes"]
        source_mount = next(
            mount
            for mount in mounts
            if mount["target"] == "/app/dataset-repository"
        )
        source_mount["read_only"] = False
        with self.assertRaisesRegex(ValueError, "read-only"):
            validate_model(model, "data-acquisition")

    def test_acquisition_project_is_separate_and_not_generically_startable(self) -> None:
        local = stack_for("local")
        live = stack_for("live")
        e2e = stack_for("e2e")
        acquisition = stack_for("data-acquisition")
        self.assertEqual(
            len({local.project, live.project, e2e.project, acquisition.project}),
            4,
        )
        self.assertNotEqual(acquisition.project, e2e.project)
        self.assertEqual(
            acquisition.files, ("docker-compose.data-acquisition.yml",)
        )
        self.assertFalse(acquisition.startable)
        self.assertIsNone(acquisition.frontend_url)

    def test_runtime_start_stops_before_compose_up_when_preflight_fails(self) -> None:
        with patch("sys.argv", ["start_stack", "e2e"]), patch(
            "scripts.docker.start_stack.subprocess.run"
        ) as run, redirect_stdout(StringIO()):
            run.return_value.returncode = 1
            self.assertEqual(start_stack(), 1)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertTrue(
            any(value.endswith("validate_compose_runtime.py") for value in command)
        )

    def test_volume_reset_requires_explicit_destructive_confirmation(self) -> None:
        error = StringIO()
        with patch(
            "sys.argv", ["stop_stack", "e2e", "--delete-volumes"]
        ), patch(
            "scripts.docker.stop_stack.subprocess.run"
        ) as run, redirect_stderr(error):
            with self.assertRaises(SystemExit):
                stop_stack()
        run.assert_not_called()
        self.assertIn("without --yes", error.getvalue())


class AcquisitionAuthorizationTests(unittest.TestCase):
    def values(self) -> dict[str, str]:
        return {
            "DATA_ACQUISITION_RUN_ID": "audit-20260726-001",
            "DATA_ACQUISITION_CONFIRMATION": CONFIRMATION,
            "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE": "INFRA-11-review",
            "DATA_ACQUISITION_PROVENANCE_REVIEWER": "local-reviewer",
            "DATA_ACQUISITION_APPROVED_PROVIDERS": "ADZUNA",
            "DATA_ACQUISITION_RETENTION_DAYS": "14",
            "DATA_ACQUISITION_DATASET_ID": "live-provider-acquisition",
            "DATA_ACQUISITION_DATASET_VERSION": "2.0.0",
            "DATA_ACQUISITION_ADZUNA_ENABLED": "true",
            "DATA_ACQUISITION_JSEARCH_ENABLED": "false",
            "DATA_ACQUISITION_REED_ENABLED": "false",
            "DATA_ACQUISITION_POSTCODE_ENABLED": "false",
            "ADZUNA_APP_ID": "test-adzuna-id",
            "ADZUNA_APP_KEY": "test-adzuna-key",
        }

    def test_authorization_creates_redacted_bounded_retention_record(self) -> None:
        authorization = authorize(self.values())
        with tempfile.TemporaryDirectory() as directory:
            path = create_audit_manifest(
                Path(directory),
                authorization,
                now=datetime(2026, 7, 26, tzinfo=UTC),
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "AUTHORIZED")
        self.assertEqual(manifest["approvedProviders"], ["ADZUNA"])
        self.assertEqual(manifest["retainUntil"], "2026-08-09T00:00:00+00:00")
        self.assertNotIn("credential", json.dumps(manifest).lower())
        self.assertFalse(manifest["runtimeEligible"])

    def test_confirmation_flags_credentials_and_retention_fail_closed(self) -> None:
        mutations = (
            ("DATA_ACQUISITION_CONFIRMATION", "yes"),
            ("DATA_ACQUISITION_ADZUNA_ENABLED", "false"),
            ("ADZUNA_APP_KEY", ""),
            ("REED_API_KEY", "unapproved-credential"),
            ("DATA_ACQUISITION_RETENTION_DAYS", "31"),
            ("DATA_ACQUISITION_DATASET_ID", "../escape"),
            ("DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE", "reference with spaces"),
        )
        for variable, value in mutations:
            with self.subTest(variable=variable):
                values = self.values()
                values[variable] = value
                with self.assertRaises(ValueError):
                    authorize(values)

    def test_legacy_live_llm_capture_is_fail_closed_without_network_activity(
        self,
    ) -> None:
        error = StringIO()
        with patch(
            "sys.argv",
            [
                "capture_llm_fixtures",
                "--dataset-path",
                "fixture",
                "--job-id",
                "job",
                "--yes",
            ],
        ), redirect_stderr(error):
            self.assertEqual(capture_llm(), 2)
        self.assertIn("No provider call was made", error.getvalue())
        self.assertIn(BACKLOG_URL, error.getvalue())

    def test_invalid_acquisition_never_reaches_compose(self) -> None:
        values = self.values()
        values["DATA_ACQUISITION_CONFIRMATION"] = "yes"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.data-acquisition"
            env_file.write_text(
                "\n".join(f"{name}={value}" for name, value in values.items())
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "sys.argv",
                [
                    "run_acquisition",
                    "--env-file",
                    str(env_file),
                    "--authorize-live-provider-costs",
                ],
            ), patch("scripts.data.run_acquisition.run") as run, redirect_stderr(
                StringIO()
            ):
                self.assertEqual(run_acquisition(), 2)
        run.assert_not_called()

    def test_rejected_quarantine_is_exactly_deleted_and_audited(self) -> None:
        authorization = authorize(self.values())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "quarantine"
            audit_path = create_audit_manifest(root, authorization)
            run_directory = audit_path.parent
            with patch(
                "scripts.data.purge_acquisition.QUARANTINE_ROOT", root
            ), patch(
                "sys.argv",
                [
                    "purge_acquisition",
                    "--run-id",
                    authorization.run_id,
                    "--reason",
                    "rejected",
                    "--reviewer",
                    "local-reviewer",
                    "--yes",
                ],
            ), redirect_stdout(StringIO()):
                self.assertEqual(purge_acquisition(), 0)
            self.assertFalse(run_directory.exists())
            records = [
                json.loads(line)
                for line in (root / "deletion-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
        self.assertEqual(
            [record["status"] for record in records],
            ["DELETE_REQUESTED", "DELETED"],
        )


if __name__ == "__main__":
    unittest.main()
