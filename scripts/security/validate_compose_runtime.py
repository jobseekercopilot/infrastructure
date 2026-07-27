#!/usr/bin/env python3
"""Validate the rendered Compose trust graph without printing credentials."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_CREDENTIALS = (
    "AUTH_SERVICE_TOKEN",
    "ENVIRONMENT_DATA_TOKEN",
    "APPLICATION_TRACKER_PRODUCER_TOKEN",
    "APPLICATION_TRACKER_READER_TOKEN",
    "REPORTING_GATEWAY_SERVICE_TOKEN",
    "DOCUMENT_STORE_PRODUCER_TOKEN",
    "DOCUMENT_STORE_READER_TOKEN",
    "DOCUMENT_EXPORT_GATEWAY_TOKEN",
    "CV_COVER_LETTER_GATEWAY_TOKEN",
    "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN",
    "BFF_TO_PAYMENT_GATEWAY_TOKEN",
    "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
    "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN",
    "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
)
FIXTURE_GATEWAYS = (
    "reed-gateway",
    "adzuna-gateway",
    "jsearch-gateway",
    "postcode-io-gateway",
    "llm-gateway",
    "stripe-gateway",
)
JOB_PROVIDER_GATEWAYS = (
    "reed-gateway",
    "adzuna-gateway",
    "jsearch-gateway",
    "postcode-io-gateway",
)
LIVE_CREDENTIALS = {
    "reed-gateway": ("REED_API_KEY",),
    "adzuna-gateway": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
    "jsearch-gateway": ("JSEARCH_API_KEY",),
}
ENVIRONMENT_DATA_SERVICES = (
    "authentication-service",
    "user-profile-service",
    "document-store-service",
    "application-tracker-service",
    "payment-service",
)
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ACQUISITION_CONFIRMATION = "I UNDERSTAND LIVE PROVIDERS WILL BE CALLED"


def environment(model: dict, service: str) -> dict[str, str]:
    try:
        result = model["services"][service]["environment"]
    except KeyError as error:
        raise ValueError(f"missing Compose service or environment: {service}") from error
    if not isinstance(result, dict):
        raise ValueError(f"Compose environment for {service} must render as a mapping")
    return result


def require_shared(
    model: dict, credential: str, bindings: tuple[tuple[str, str], ...]
) -> str:
    values = []
    for service, variable in bindings:
        value = environment(model, service).get(variable)
        if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
            raise ValueError(f"{service}:{variable} must contain at least 32 bytes")
        values.append(value)
    if len(set(values)) != 1:
        raise ValueError(f"{credential} does not match across approved consumers")
    return values[0]


def require_value(
    model: dict, service: str, variable: str, expected: str
) -> None:
    value = environment(model, service).get(variable)
    if value != expected:
        raise ValueError(f"{service}:{variable} must be {expected}")


def require_no_live_credentials(model: dict) -> None:
    for service, variables in LIVE_CREDENTIALS.items():
        service_environment = environment(model, service)
        for variable in variables:
            if service_environment.get(variable):
                raise ValueError(
                    f"{service}:{variable} must not be injected into a fixture runtime"
                )
    stripe_environment = environment(model, "stripe-gateway")
    for variable in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
        if stripe_environment.get(variable):
            raise ValueError(
                f"stripe-gateway:{variable} must not be injected into a fixture runtime"
            )
    llm_environment = environment(model, "llm-gateway")
    if llm_environment.get("OPENAI_API_KEY"):
        raise ValueError(
            "llm-gateway:OPENAI_API_KEY must not be injected into a fixture runtime"
        )
    if "LLM_MOCK_MODE" in llm_environment:
        raise ValueError("llm-gateway must not receive the obsolete LLM_MOCK_MODE")


def validate_runtime_modes(model: dict, profile: str) -> None:
    runtime_network = model.get("networks", {}).get("job-seeker-network", {})
    if profile in {"local", "e2e"} and runtime_network.get("internal") is not True:
        raise ValueError(
            f"{profile} must use an internal-only network with no external egress"
        )
    if profile == "live-provider" and runtime_network.get("internal") is True:
        raise ValueError("live-provider requires deliberate job-provider egress")

    require_value(
        model,
        "system-data-service",
        "APPLICATION_TRACKER_SERVICE_URL",
        "http://application-tracker-service:8088",
    )

    if profile in {"local", "e2e"}:
        for service in FIXTURE_GATEWAYS:
            require_value(model, service, "EXTERNAL_PROVIDER_MODE", "FIXTURE")
        require_no_live_credentials(model)
    elif profile == "live-provider":
        for service in JOB_PROVIDER_GATEWAYS:
            require_value(model, service, "EXTERNAL_PROVIDER_MODE", "LIVE")
        require_value(model, "llm-gateway", "EXTERNAL_PROVIDER_MODE", "DISABLED")
        require_value(model, "stripe-gateway", "EXTERNAL_PROVIDER_MODE", "FIXTURE")
        for service, variables in LIVE_CREDENTIALS.items():
            for variable in variables:
                value = environment(model, service).get(variable, "")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{service}:{variable} is required for live-provider mode"
                    )
        for service, variable in (
            ("llm-gateway", "OPENAI_API_KEY"),
            ("stripe-gateway", "STRIPE_SECRET_KEY"),
            ("stripe-gateway", "STRIPE_WEBHOOK_SECRET"),
        ):
            if environment(model, service).get(variable):
                raise ValueError(
                    f"{service}:{variable} is forbidden in the job-provider-only live stack"
                )
    else:
        raise ValueError(f"unsupported runtime profile: {profile}")

    for service in ENVIRONMENT_DATA_SERVICES:
        expected = "true" if profile == "e2e" else "false"
        require_value(model, service, "ENVIRONMENT_DATA_ENABLED", expected)
        if profile == "e2e":
            require_value(
                model,
                service,
                "ENVIRONMENT_DATA_ALLOWED_ENVIRONMENTS",
                "e2e",
            )

    if profile == "e2e":
        for service in FIXTURE_GATEWAYS:
            require_value(model, service, "SPRING_PROFILES_ACTIVE", "e2e")
        require_value(
            model,
            "postcode-io-gateway",
            "DEPLOYMENT_ENVIRONMENT_CLASS",
            "TEST",
        )
        require_value(
            model,
            "system-data-service",
            "SPRING_PROFILES_ACTIVE",
            "e2e",
        )
        require_value(
            model,
            "application-tracker-service",
            "SPRING_PROFILES_ACTIVE",
            "e2e",
        )
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED",
            "true",
        )
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_ENVIRONMENT_ALLOWED_PROFILES",
            "e2e",
        )
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_FIXTURES_ENABLED",
            "true",
        )
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_FIXTURE_ALLOWED_PROFILES",
            "e2e",
        )
    else:
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED",
            "false",
        )
        expected_fixtures = "true" if profile == "local" else "false"
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_FIXTURES_ENABLED",
            expected_fixtures,
        )
        if profile == "local":
            require_value(
                model,
                "system-data-service",
                "SYSTEM_DATA_FIXTURE_ALLOWED_PROFILES",
                "local",
            )
        require_value(
            model,
            "postcode-io-gateway",
            "DEPLOYMENT_ENVIRONMENT_CLASS",
            "LOCAL",
        )


def validate_runtime_model(model: dict, profile: str) -> None:
    services = model.get("services", {})
    for service_name, service in services.items():
        if "JWT_SECRET" in service.get("environment", {}):
            raise ValueError(f"{service_name} still receives forbidden JWT_SECRET")

    credential_values = {
        "AUTH_SERVICE_TOKEN": require_shared(
            model,
            "AUTH_SERVICE_TOKEN",
            (
                ("authentication-service", "AUTH_SERVICE_TOKEN"),
                ("document-generation-gateway", "AUTH_SERVICE_TOKEN"),
                ("user-management-gateway", "AUTHENTICATION_SERVICE_TOKEN"),
            ),
        ),
        "ENVIRONMENT_DATA_TOKEN": require_shared(
            model,
            "ENVIRONMENT_DATA_TOKEN",
            (
                ("authentication-service", "AUTH_ENVIRONMENT_DATA_TOKEN"),
                ("application-tracker-service", "ENVIRONMENT_DATA_TOKEN"),
                ("document-store-service", "ENVIRONMENT_DATA_TOKEN"),
                (
                    "system-data-service",
                    "SYSTEM_DATA_DOWNSTREAM_ENVIRONMENT_DATA_TOKEN",
                ),
            ),
        ),
        "APPLICATION_TRACKER_PRODUCER_TOKEN": require_shared(
            model,
            "APPLICATION_TRACKER_PRODUCER_TOKEN",
            (
                (
                    "application-tracker-service",
                    "APPLICATION_TRACKER_PRODUCER_TOKEN",
                ),
                (
                    "document-generation-gateway",
                    "APPLICATION_TRACKER_PRODUCER_TOKEN",
                ),
                ("cv-cover-letter-service", "APPLICATION_TRACKER_PRODUCER_TOKEN"),
            ),
        ),
        "APPLICATION_TRACKER_READER_TOKEN": require_shared(
            model,
            "APPLICATION_TRACKER_READER_TOKEN",
            (
                ("application-tracker-service", "APPLICATION_TRACKER_READER_TOKEN"),
                ("job-matching-service", "APPLICATION_TRACKER_READER_TOKEN"),
                ("reporting-service", "APPLICATION_TRACKER_READER_TOKEN"),
            ),
        ),
        "REPORTING_GATEWAY_SERVICE_TOKEN": require_shared(
            model,
            "REPORTING_GATEWAY_SERVICE_TOKEN",
            (
                ("reporting-gateway", "REPORTING_GATEWAY_SERVICE_TOKEN"),
                ("reporting-service", "REPORTING_GATEWAY_SERVICE_TOKEN"),
            ),
        ),
        "DOCUMENT_STORE_PRODUCER_TOKEN": require_shared(
            model,
            "DOCUMENT_STORE_PRODUCER_TOKEN",
            (
                ("document-store-service", "DOCUMENT_STORE_PRODUCER_TOKEN"),
                ("document-generation-gateway", "DOCUMENT_STORE_PRODUCER_TOKEN"),
                ("document-export-service", "DOCUMENT_STORE_PRODUCER_TOKEN"),
                ("cv-cover-letter-service", "DOCUMENT_STORE_PRODUCER_TOKEN"),
            ),
        ),
        "DOCUMENT_STORE_READER_TOKEN": require_shared(
            model,
            "DOCUMENT_STORE_READER_TOKEN",
            (
                ("document-store-service", "DOCUMENT_STORE_READER_TOKEN"),
                ("document-generation-gateway", "DOCUMENT_STORE_READER_TOKEN"),
                ("document-export-service", "DOCUMENT_STORE_READER_TOKEN"),
            ),
        ),
        "DOCUMENT_EXPORT_GATEWAY_TOKEN": require_shared(
            model,
            "DOCUMENT_EXPORT_GATEWAY_TOKEN",
            (
                ("document-export-service", "DOCUMENT_EXPORT_GATEWAY_TOKEN"),
                ("document-generation-gateway", "DOCUMENT_EXPORT_GATEWAY_TOKEN"),
            ),
        ),
        "CV_COVER_LETTER_GATEWAY_TOKEN": require_shared(
            model,
            "CV_COVER_LETTER_GATEWAY_TOKEN",
            (
                ("cv-cover-letter-service", "CV_COVER_LETTER_GATEWAY_TOKEN"),
                ("document-generation-gateway", "CV_COVER_LETTER_GATEWAY_TOKEN"),
            ),
        ),
        "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN": require_shared(
            model,
            "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN",
            (
                (
                    "cv-cover-letter-service",
                    "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN",
                ),
                ("payment-service", "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN"),
            ),
        ),
        "BFF_TO_PAYMENT_GATEWAY_TOKEN": require_shared(
            model,
            "BFF_TO_PAYMENT_GATEWAY_TOKEN",
            (
                ("job-seeker-copilot-client", "BFF_TO_PAYMENT_GATEWAY_TOKEN"),
                ("payment-gateway", "BFF_TO_PAYMENT_GATEWAY_TOKEN"),
            ),
        ),
        "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN": require_shared(
            model,
            "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
            (
                (
                    "payment-gateway",
                    "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
                ),
                (
                    "payment-service",
                    "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
                ),
            ),
        ),
        "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN": require_shared(
            model,
            "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN",
            (
                (
                    "payment-gateway",
                    "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN",
                ),
                (
                    "stripe-gateway",
                    "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN",
                ),
            ),
        ),
        "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN": require_shared(
            model,
            "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
            (
                ("stripe-gateway", "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN"),
                ("payment-service", "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN"),
            ),
        ),
    }
    if any(
        not isinstance(value, str) or len(value.encode("utf-8")) < 32
        for value in credential_values.values()
    ):
        raise ValueError("every core credential must contain at least 32 bytes")
    if len(set(credential_values.values())) != len(CORE_CREDENTIALS):
        raise ValueError("core credentials must be pairwise distinct")

    authentication = environment(model, "authentication-service")
    authentication_password = authentication.get("AUTH_DB_PASSWORD", "")
    if (
        len(authentication_password.encode("utf-8")) < 32
        or authentication_password
        != environment(model, "authentication-postgres").get("POSTGRES_PASSWORD")
    ):
        raise ValueError(
            "Authentication database credential must match and contain 32 bytes"
        )
    if "authentication-postgres:5432" not in authentication.get(
        "AUTH_DB_URL", ""
    ):
        raise ValueError(
            "Authentication must use its isolated PostgreSQL service"
        )
    private_key = authentication.get("JWT_PRIVATE_KEY_BASE64", "")
    public_key = authentication.get("JWT_PUBLIC_KEY_BASE64", "")
    if not private_key or not public_key or private_key == public_key:
        raise ValueError("Authentication requires a distinct generated RSA key pair")

    issuers = {
        authentication.get("JWT_ISSUER"),
        environment(model, "application-tracker-service").get(
            "APPLICATION_TRACKER_JWT_ISSUER"
        ),
        environment(model, "document-generation-gateway").get(
            "DOCUMENT_GENERATION_JWT_ISSUER"
        ),
        environment(model, "document-store-service").get(
            "DOCUMENT_STORE_JWT_ISSUER"
        ),
        environment(model, "job-finder-gateway").get("JOB_FINDER_JWT_ISSUER"),
        environment(model, "reporting-gateway").get(
            "REPORTING_GATEWAY_JWT_ISSUER"
        ),
    }
    audiences = {
        authentication.get("JWT_AUDIENCE"),
        environment(model, "application-tracker-service").get(
            "APPLICATION_TRACKER_JWT_AUDIENCE"
        ),
        environment(model, "document-generation-gateway").get(
            "DOCUMENT_GENERATION_JWT_AUDIENCE"
        ),
        environment(model, "document-store-service").get(
            "DOCUMENT_STORE_JWT_AUDIENCE"
        ),
        environment(model, "job-finder-gateway").get("JOB_FINDER_JWT_AUDIENCE"),
        environment(model, "reporting-gateway").get(
            "REPORTING_GATEWAY_JWT_AUDIENCE"
        ),
    }
    if len(issuers) != 1 or None in issuers:
        raise ValueError("JWT issuer must match across producer and consumers")
    if len(audiences) != 1 or None in audiences:
        raise ValueError("JWT audience must match across producer and consumers")

    document_store = environment(model, "document-store-service")
    document_store_password = document_store.get(
        "DOCUMENT_STORE_DATABASE_PASSWORD", ""
    )
    if (
        len(document_store_password.encode("utf-8")) < 32
        or document_store_password
        != environment(model, "document-store-postgres").get("POSTGRES_PASSWORD")
    ):
        raise ValueError(
            "Document Store database credential must match and contain 32 bytes"
        )
    if document_store.get("DOCUMENT_STORE_DATABASE_PRODUCTION_SAFETY_CHECK") != "false":
        raise ValueError(
            "local profiles must explicitly disable the production storage attestation"
        )
    if document_store.get("DOCUMENT_STORE_OBJECT_PROVIDER") != "filesystem":
        raise ValueError("local profiles must use isolated filesystem object storage")
    if "document-store-postgres:5432" not in document_store.get(
        "DOCUMENT_STORE_DATABASE_URL", ""
    ):
        raise ValueError("Document Store must use its isolated PostgreSQL service")

    application_tracker = environment(model, "application-tracker-service")
    application_tracker_postgres = environment(
        model, "application-tracker-postgres"
    )
    application_tracker_password = application_tracker.get(
        "APPLICATION_TRACKER_DATABASE_PASSWORD", ""
    )
    if (
        len(application_tracker_password.encode("utf-8")) < 32
        or application_tracker_password
        != application_tracker_postgres.get("POSTGRES_PASSWORD")
    ):
        raise ValueError(
            "Application Tracker database credential must match and contain 32 bytes"
        )
    if (
        application_tracker.get(
            "APPLICATION_TRACKER_DATABASE_PRODUCTION_SAFETY_CHECK"
        )
        != "false"
    ):
        raise ValueError(
            "local profiles must explicitly disable Application Tracker "
            "production storage attestation"
        )
    if application_tracker.get("APPLICATION_TRACKER_DATABASE_SSL_MODE") != "disable":
        raise ValueError(
            "local profiles must explicitly disable Application Tracker "
            "database TLS"
        )
    if "application-tracker-postgres:5432" not in application_tracker.get(
        "APPLICATION_TRACKER_DATABASE_URL", ""
    ):
        raise ValueError(
            "Application Tracker must use its isolated PostgreSQL service"
        )

    payment = environment(model, "payment-service")
    payment_postgres = environment(model, "payment-postgres")
    payment_password = payment.get("PAYMENT_DATABASE_PASSWORD", "")
    if (
        len(payment_password.encode("utf-8")) < 32
        or payment_password != payment_postgres.get("POSTGRES_PASSWORD")
    ):
        raise ValueError("Payment database credential must match and contain 32 bytes")
    if payment.get("PAYMENT_DATABASE_PRODUCTION_SAFETY_CHECK") != "false":
        raise ValueError(
            "local profiles must explicitly disable Payment production attestation"
        )
    if "payment-postgres:5432" not in payment.get("PAYMENT_DATABASE_URL", ""):
        raise ValueError("Payment Service must use its isolated PostgreSQL service")

    validate_runtime_modes(model, profile)


def validate_acquisition_model(model: dict) -> None:
    expected_services = {
        "adzuna-gateway",
        "jsearch-gateway",
        "reed-gateway",
        "postcode-io-gateway",
        "system-data-service",
    }
    services = model.get("services", {})
    if set(services) != expected_services:
        raise ValueError(
            "data acquisition must contain only approved job-provider gateways "
            "and System Data"
        )
    if model.get("volumes"):
        raise ValueError("data acquisition must not create named persistent volumes")
    acquisition_network = model.get("networks", {}).get(
        "data-acquisition-network", {}
    )
    if acquisition_network.get("internal") is True:
        raise ValueError("approved acquisition gateways require deliberate egress")

    for service_name, service in services.items():
        if service.get("ports"):
            raise ValueError(
                f"{service_name} must not publish host ports in data acquisition"
            )
        networks = service.get("networks", {})
        if set(networks) != {"data-acquisition-network"}:
            raise ValueError(
                f"{service_name} must use only the acquisition network"
            )
        if service_name != "system-data-service":
            require_value(
                model,
                service_name,
                "SPRING_PROFILES_ACTIVE",
                "live-acquisition",
            )

    acquisition = environment(model, "system-data-service")
    required_values = {
        "SPRING_PROFILES_ACTIVE": "live-acquisition",
        "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED": "false",
        "SYSTEM_DATA_FIXTURES_ENABLED": "false",
        "SYSTEM_DATA_LIVE_ACQUISITION_ENABLED": "true",
        "SYSTEM_DATA_LIVE_ACQUISITION_EXECUTE": "true",
        "SYSTEM_DATA_LIVE_ACQUISITION_CONFIRMATION": ACQUISITION_CONFIRMATION,
    }
    for variable, expected in required_values.items():
        if acquisition.get(variable) != expected:
            raise ValueError(
                f"system-data-service:{variable} must be {expected}"
            )
    run_id = acquisition.get("DATA_ACQUISITION_RUN_ID", "")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("DATA_ACQUISITION_RUN_ID must be a safe unique slug")
    if acquisition.get("SYSTEM_DATA_ACQUISITION_OUTPUT_DIRECTORY") != (
        f"/app/quarantine/{run_id}"
    ):
        raise ValueError("System Data output must use the unique quarantine run")
    if (
        acquisition.get("SYSTEM_DATA_REPOSITORY_DIRECTORY")
        != "/app/dataset-repository"
    ):
        raise ValueError("System Data source must use the read-only fixture mount")
    try:
        retention_days = int(acquisition.get("DATA_ACQUISITION_RETENTION_DAYS", ""))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "DATA_ACQUISITION_RETENTION_DAYS must be an integer"
        ) from error
    if retention_days < 1 or retention_days > 30:
        raise ValueError("data acquisition retention must be between 1 and 30 days")
    for variable in (
        "SYSTEM_DATA_LIVE_ACQUISITION_TERMS_APPROVAL_REFERENCE",
        "SYSTEM_DATA_LIVE_ACQUISITION_PROVENANCE_REVIEWER",
        "SYSTEM_DATA_ACQUISITION_DATASET_VERSION",
    ):
        value = acquisition.get(variable, "")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"system-data-service:{variable} is required")

    approved_value = acquisition.get(
        "SYSTEM_DATA_LIVE_ACQUISITION_APPROVED_PROVIDERS", ""
    )
    approved = {
        value.strip().upper()
        for value in approved_value.split(",")
        if value.strip()
    }
    allowed = {"ADZUNA", "JSEARCH", "REED"}
    if not approved or not approved.issubset(allowed):
        raise ValueError("approved providers must be a non-empty ADZUNA/JSEARCH/REED subset")
    provider_settings = {
        "ADZUNA": ("adzuna-gateway", "SYSTEM_DATA_ACQUISITION_ADZUNA_ENABLED"),
        "JSEARCH": ("jsearch-gateway", "SYSTEM_DATA_ACQUISITION_JSEARCH_ENABLED"),
        "REED": ("reed-gateway", "SYSTEM_DATA_ACQUISITION_REED_ENABLED"),
    }
    for provider, (service, flag) in provider_settings.items():
        expected = "true" if provider in approved else "false"
        if acquisition.get(flag) != expected:
            raise ValueError(f"{flag} must exactly match the approved provider list")
        profile = services[service].get("profiles", [])
        if profile != [provider.lower()]:
            raise ValueError(f"{service} must require its dedicated Compose profile")
        require_value(model, service, "EXTERNAL_PROVIDER_MODE", "LIVE")
        for credential in LIVE_CREDENTIALS[service]:
            credential_value = environment(model, service).get(credential, "")
            if provider in approved and (
                not isinstance(credential_value, str) or not credential_value.strip()
            ):
                raise ValueError(f"{service}:{credential} is required when approved")
            if provider not in approved and credential_value:
                raise ValueError(
                    f"{service}:{credential} must be absent when the provider is not approved"
                )

    postcode_enabled = acquisition.get(
        "SYSTEM_DATA_ACQUISITION_POSTCODE_ENABLED", "false"
    )
    if postcode_enabled not in {"true", "false"}:
        raise ValueError("SYSTEM_DATA_ACQUISITION_POSTCODE_ENABLED must be boolean")
    if services["postcode-io-gateway"].get("profiles", []) != ["postcode"]:
        raise ValueError(
            "postcode-io-gateway must require its dedicated Compose profile"
        )
    require_value(model, "postcode-io-gateway", "EXTERNAL_PROVIDER_MODE", "LIVE")
    require_value(
        model,
        "postcode-io-gateway",
        "DEPLOYMENT_ENVIRONMENT_CLASS",
        "LOCAL",
    )

    mounts = services["system-data-service"].get("volumes", [])
    if len(mounts) != 2:
        raise ValueError(
            "System Data acquisition requires one read-only source and one quarantine mount"
        )
    read_only_targets = {
        mount.get("target")
        for mount in mounts
        if isinstance(mount, dict) and mount.get("read_only")
    }
    writable_targets = {
        mount.get("target")
        for mount in mounts
        if isinstance(mount, dict) and not mount.get("read_only")
    }
    if read_only_targets != {"/app/dataset-repository"}:
        raise ValueError("the governed dataset repository must be read-only")
    if writable_targets != {"/app/quarantine"}:
        raise ValueError("live output must be confined to the quarantine mount")
    sources_by_target = {
        mount.get("target"): Path(mount.get("source", ""))
        for mount in mounts
        if isinstance(mount, dict)
    }
    if sources_by_target["/app/dataset-repository"].parts[-2:] != (
        "system-data-service",
        "dataset-repository",
    ):
        raise ValueError("the read-only source must be the System Data fixture repository")
    if sources_by_target["/app/quarantine"].parts[-2:] != (
        "system-data-service",
        "quarantined-acquisitions",
    ):
        raise ValueError("acquisition output must use the System Data quarantine root")


def validate_model(model: dict, profile: str) -> None:
    if profile == "data-acquisition":
        validate_acquisition_model(model)
        return
    validate_runtime_model(model, profile)


def compose_model(env_file: Path, overlays: list[Path], profile: str) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
    ]
    if profile != "data-acquisition":
        command.extend(("-f", str(ROOT / "docker-compose.yml")))
    for overlay in overlays:
        command.extend(("-f", str(overlay)))
    if profile == "data-acquisition":
        command.extend(("--profile", "*"))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Docker Compose model could not be rendered")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        required=True,
        choices=("local", "e2e", "live-provider", "data-acquisition"),
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.profile == "data-acquisition" and len(args.overlay) != 1:
        parser.error("data-acquisition requires exactly one standalone Compose file")
    validate_model(
        compose_model(args.env_file, args.overlay, args.profile),
        args.profile,
    )
    print(f"{args.profile} Compose trust graph is valid; no values were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
