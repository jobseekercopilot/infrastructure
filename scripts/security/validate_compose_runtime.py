#!/usr/bin/env python3
"""Validate the rendered Compose trust graph without printing credentials."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.workspace.runtime_env import controlled_environment


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
    "REJECTED_GENERATION_OPERATOR_TOKEN",
    "REJECTED_GENERATION_QUARANTINE_KEY_BASE64",
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
REAL_PROVIDER_SECRET_BINDINGS = {
    "reed-gateway": {"reed_api_key": "REED_API_KEY"},
    "adzuna-gateway": {
        "adzuna_app_id": "ADZUNA_APP_ID",
        "adzuna_app_key": "ADZUNA_APP_KEY",
    },
    "jsearch-gateway": {"jsearch_api_key": "JSEARCH_API_KEY"},
    "llm-gateway": {"openai_api_key": "OPENAI_API_KEY"},
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
CLAMAV_IMAGE = (
    "clamav/clamav:1.4.5_base@"
    "sha256:38850b4560ce21c36cacfb8d8ce2c172dcf0029db6c47342d882e04b818a2fef"
)


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


def require_single_secret(model: dict, service: str, variable: str) -> str:
    value = environment(model, service).get(variable)
    if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
        raise ValueError(f"{service}:{variable} must contain at least 32 bytes")
    return value


def require_private_volume_mount(
    model: dict, service: str, source: str, target: str
) -> None:
    volumes = model.get("volumes", {})
    if source not in volumes:
        raise ValueError(f"missing private volume: {source}")
    mounts = model.get("services", {}).get(service, {}).get("volumes", [])
    matches = [
        mount
        for mount in mounts
        if mount.get("type") == "volume"
        and mount.get("source") == source
        and mount.get("target") == target
        and not mount.get("read_only", False)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{service} must mount {source} once at {target} read-write"
        )


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


def service_networks(service: dict) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, dict):
        return set(networks)
    if isinstance(networks, list):
        return set(networks)
    raise ValueError("Compose service networks must render as a mapping or list")


def validate_document_scanner(model: dict) -> None:
    services = model.get("services", {})
    scanner = services.get("clamav", {})
    store = services.get("document-store-service", {})
    if scanner.get("image") != CLAMAV_IMAGE:
        raise ValueError("ClamAV must use the reviewed version-and-digest pin")
    if scanner.get("ports"):
        raise ValueError("ClamAV must not publish a host port")
    if scanner.get("mem_limit") != str(4 * 1024 * 1024 * 1024):
        raise ValueError("ClamAV must retain its bounded 4 GiB memory allocation")
    if service_networks(scanner) != {
        "document-scanner-network",
        "malware-signature-egress-network",
    }:
        raise ValueError("ClamAV must use only scan and signature-update networks")
    if "document-scanner-network" not in service_networks(store):
        raise ValueError("Document Store must join the private scanner network")

    scan_members = {
        name
        for name, service in services.items()
        if "document-scanner-network" in service_networks(service)
    }
    if scan_members != {"clamav", "document-store-service"}:
        raise ValueError(
            "the private scanner network must contain only ClamAV and Document Store"
        )
    update_members = {
        name
        for name, service in services.items()
        if "malware-signature-egress-network" in service_networks(service)
    }
    if update_members != {"clamav"}:
        raise ValueError("only ClamAV may use malware-signature egress")

    networks = model.get("networks", {})
    if networks.get("document-scanner-network", {}).get("internal") is not True:
        raise ValueError("the document scanner network must be internal")
    if networks.get("malware-signature-egress-network", {}).get("internal") is True:
        raise ValueError("ClamAV signature updates require explicit isolated egress")

    expected_scanner = {
        "FRESHCLAM_CHECKS": "12",
        "FRESHCLAM_CONF_ConnectTimeout": "10",
        "FRESHCLAM_CONF_ReceiveTimeout": "30",
        "CLAMD_CONF_StreamMaxLength": "11M",
        "CLAMD_CONF_MaxFileSize": "11M",
        "CLAMD_CONF_MaxScanSize": "32M",
        "CLAMD_CONF_MaxScanTime": "30000",
        "CLAMD_CONF_MaxFiles": "512",
        "CLAMD_CONF_MaxRecursion": "16",
        "CLAMD_CONF_SelfCheck": "60",
    }
    for variable, expected in expected_scanner.items():
        require_value(model, "clamav", variable, expected)
    require_private_volume_mount(
        model, "clamav", "clamav-signatures", "/var/lib/clamav"
    )

    store_environment = environment(model, "document-store-service")
    expected_store = {
        "DOCUMENT_STORE_CLAMAV_HOST": "clamav",
        "DOCUMENT_STORE_CLAMAV_PORT": "3310",
        "DOCUMENT_STORE_CLAMAV_CONNECT_TIMEOUT_MS": "2000",
        "DOCUMENT_STORE_CLAMAV_READ_TIMEOUT_MS": "30000",
        "DOCUMENT_STORE_CLAMAV_MAXIMUM_SIGNATURE_AGE_HOURS": "48",
    }
    for variable, expected in expected_store.items():
        if store_environment.get(variable) != expected:
            raise ValueError(
                f"Document Store scanner setting {variable} must be {expected}"
            )
    if (
        store.get("depends_on", {}).get("clamav", {}).get("condition")
        != "service_healthy"
    ):
        raise ValueError("Document Store must wait for healthy ClamAV")

    health_test = scanner.get("healthcheck", {}).get("test", [])
    health = scanner.get("healthcheck", {})
    health_command = " ".join(str(part) for part in health_test)
    if (
        "clamdcheck.sh" not in health_command
        or "freshclam --version" not in health_command
        or "172800" not in health_command
    ):
        raise ValueError("ClamAV health must verify daemon and signature freshness")
    if (
        health.get("retries") != 3
        or health.get("start_period") != "10m0s"
        or health.get("timeout") != "10s"
    ):
        raise ValueError("ClamAV health must allow bounded signature initialization")


def validate_real_provider_secret_bindings(model: dict) -> None:
    services = model.get("services", {})
    provider_network = model.get("networks", {}).get(
        "provider-egress-network"
    )
    if not isinstance(provider_network, dict) or (
        provider_network.get("internal", False) is not False
    ):
        raise ValueError(
            "real-providers requires the explicit external provider-egress-network"
        )
    actual_egress = {
        name
        for name, service in services.items()
        if "provider-egress-network" in service_networks(service)
    }
    expected_egress = set(REAL_PROVIDER_SECRET_BINDINGS)
    if actual_egress != expected_egress:
        raise ValueError(
            "provider-egress-network must contain only Reed, Adzuna, JSearch "
            "and LLM gateways"
        )

    declared_secrets = model.get("secrets", {})
    for service_name, expected_bindings in REAL_PROVIDER_SECRET_BINDINGS.items():
        service = services.get(service_name, {})
        require_value(
            model,
            service_name,
            "SPRING_CONFIG_IMPORT",
            "optional:configtree:/run/secrets/",
        )
        service_environment = environment(model, service_name)
        for target in expected_bindings.values():
            if target in service_environment:
                raise ValueError(
                    f"{service_name}:{target} must be mounted as an owned secret, "
                    "not injected into the environment"
                )
        actual_bindings = {
            secret.get("source"): secret.get("target")
            for secret in service.get("secrets", [])
            if isinstance(secret, dict)
        }
        if actual_bindings != expected_bindings:
            raise ValueError(
                f"{service_name} must receive exactly its owned provider secrets"
            )
        for source, target in expected_bindings.items():
            definition = declared_secrets.get(source, {})
            if definition.get("environment") != target:
                raise ValueError(
                    f"{source} must resolve only from the {target} environment source"
                )
            if any(key in definition for key in ("value", "content")):
                raise ValueError(
                    f"{source} must not embed a credential value in the Compose model"
                )


def validate_runtime_modes(model: dict, profile: str) -> None:
    e2e = profile in {"e2e", "e2e-local-ses"}
    local_ses = profile in {"local-ses", "e2e-local-ses"}
    local_runtime = profile in {"local", "local-ses"}
    real_providers = profile == "real-providers"
    runtime_network = model.get("networks", {}).get("job-seeker-network", {})
    if (local_runtime or e2e) and runtime_network.get("internal") is not True:
        raise ValueError(
            f"{profile} must use an internal-only network with no external egress"
        )
    if real_providers and runtime_network.get("internal") is not True:
        raise ValueError(
            "real-providers must keep the application network internal and use "
            "only the dedicated provider-egress-network for external calls"
        )
    if profile == "live-provider" and runtime_network.get("internal") is True:
        raise ValueError("live-provider requires deliberate job-provider egress")

    require_value(
        model,
        "system-data-service",
        "APPLICATION_TRACKER_SERVICE_URL",
        "http://application-tracker-service:8088",
    )

    if local_runtime or e2e:
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
    elif real_providers:
        for service in LIVE_CREDENTIALS:
            require_value(model, service, "EXTERNAL_PROVIDER_MODE", "LIVE")
        require_value(
            model,
            "postcode-io-gateway",
            "EXTERNAL_PROVIDER_MODE",
            "FIXTURE",
        )
        require_value(model, "llm-gateway", "EXTERNAL_PROVIDER_MODE", "LIVE")
        require_value(model, "stripe-gateway", "EXTERNAL_PROVIDER_MODE", "FIXTURE")
        require_value(
            model,
            "stripe-gateway",
            "SYSTEM_DATA_SERVICE_URL",
            "http://system-data-service:8103",
        )
        require_value(
            model,
            "payment-gateway",
            "STRIPE_GATEWAY_URL",
            "http://stripe-gateway:8100",
        )
        require_value(
            model,
            "job-seeker-copilot-client",
            "JOB_SEARCH_PROVIDER_MODE",
            "REAL_PROVIDERS",
        )
        require_value(
            model,
            "job-seeker-copilot-client",
            "DOCUMENT_GENERATION_MODE",
            "REAL_LLM",
        )
        validate_real_provider_secret_bindings(model)
        stripe = environment(model, "stripe-gateway")
        for variable in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
            if stripe.get(variable):
                raise ValueError(
                    f"stripe-gateway:{variable} is forbidden in real-providers"
                )
        if "provider-egress-network" in service_networks(
            model["services"]["stripe-gateway"]
        ):
            raise ValueError(
                "fixture Stripe Gateway must not join provider-egress-network"
            )
    else:
        raise ValueError(f"unsupported runtime profile: {profile}")

    for service in ENVIRONMENT_DATA_SERVICES:
        expected = "true" if e2e else "false"
        require_value(model, service, "ENVIRONMENT_DATA_ENABLED", expected)
        if e2e:
            require_value(
                model,
                service,
                "ENVIRONMENT_DATA_ALLOWED_ENVIRONMENTS",
                "e2e",
            )

    authentication = environment(model, "authentication-service")
    if local_ses:
        required = {
            "AUTH_ACCOUNT_EMAIL_DELIVERY_MODE": "local-ses",
            "AUTH_ACCOUNT_EMAIL_SES_ENDPOINT": "http://localstack:4566",
            "AUTH_ACCOUNT_EMAIL_SES_REGION": "eu-west-2",
            "AWS_REGION": "eu-west-2",
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
        }
        for variable, expected in required.items():
            require_value(model, "authentication-service", variable, expected)
        localstack = model.get("services", {}).get("localstack", {})
        if localstack.get("image") != "localstack/localstack:4.14.0":
            raise ValueError("local-ses requires the pinned LocalStack image")
        if environment(model, "localstack").get("SERVICES") != "ses":
            raise ValueError("LocalStack must emulate SES only")
        if set(localstack.get("networks", {})) != {"job-seeker-network", "host-access"}:
            raise ValueError("LocalStack may use only the application and loopback-bound networks")
        ports = localstack.get("ports", [])
        if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1":
            raise ValueError("LocalStack must publish its gateway to loopback only")
        if any(
            mount.get("type") == "volume"
            for mount in localstack.get("volumes", [])
            if isinstance(mount, dict)
        ):
            raise ValueError("LocalStack state must not use a persistent volume")
    else:
        require_value(
            model,
            "authentication-service",
            "AUTH_ACCOUNT_EMAIL_DELIVERY_MODE",
            "fixture",
        )
        if "localstack" in model.get("services", {}):
            raise ValueError("fixture profiles must not start LocalStack")

    if e2e:
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
            "test",
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
            "test",
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
            "test",
        )
    else:
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_ENVIRONMENT_MANAGEMENT_ENABLED",
            "false",
        )
        uses_local_fixtures = local_runtime or real_providers
        expected_fixtures = "true" if uses_local_fixtures else "false"
        require_value(
            model,
            "system-data-service",
            "SYSTEM_DATA_FIXTURES_ENABLED",
            expected_fixtures,
        )
        if uses_local_fixtures:
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
    validate_document_scanner(model)
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
                ("payment-service", "ENVIRONMENT_DATA_TOKEN"),
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
                ("document-store-service", "APPLICATION_TRACKER_PRODUCER_TOKEN"),
            ),
        ),
        "APPLICATION_TRACKER_READER_TOKEN": require_shared(
            model,
            "APPLICATION_TRACKER_READER_TOKEN",
            (
                ("application-tracker-service", "APPLICATION_TRACKER_READER_TOKEN"),
                ("document-store-service", "APPLICATION_TRACKER_READER_TOKEN"),
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
                ("reporting-service", "DOCUMENT_STORE_READER_TOKEN"),
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
        "REJECTED_GENERATION_OPERATOR_TOKEN": require_single_secret(
            model,
            "cv-cover-letter-service",
            "REJECTED_GENERATION_OPERATOR_TOKEN",
        ),
        "REJECTED_GENERATION_QUARANTINE_KEY_BASE64": require_single_secret(
            model,
            "cv-cover-letter-service",
            "REJECTED_GENERATION_QUARANTINE_KEY_BASE64",
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
    try:
        quarantine_key = base64.b64decode(
            credential_values["REJECTED_GENERATION_QUARANTINE_KEY_BASE64"],
            validate=True,
        )
    except ValueError as error:
        raise ValueError(
            "rejected generation quarantine key must be valid Base64"
        ) from error
    if len(quarantine_key) != 32:
        raise ValueError(
            "rejected generation quarantine key must decode to exactly 32 bytes"
        )
    require_value(
        model,
        "cv-cover-letter-service",
        "REJECTED_GENERATION_QUARANTINE_ENABLED",
        "true",
    )
    require_value(
        model,
        "cv-cover-letter-service",
        "REJECTED_GENERATION_QUARANTINE_DIRECTORY",
        "/var/lib/cv-cover-letter/rejected-generations",
    )
    require_private_volume_mount(
        model,
        "cv-cover-letter-service",
        "cv-rejected-generation-quarantine",
        "/var/lib/cv-cover-letter/rejected-generations",
    )

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
    if (
        document_store.get("APPLICATION_TRACKER_SERVICE_URL")
        != "http://application-tracker-service:8088"
    ):
        raise ValueError(
            "Document Store must coordinate lifecycle state with Application Tracker"
        )
    expected_retention = {
        "DOCUMENT_STORE_RECOVERY_DAYS": "30",
        "DOCUMENT_STORE_COMPLETED_OPERATION_RETENTION_DAYS": "90",
        "DOCUMENT_STORE_LIFECYCLE_AUDIT_DAYS": "365",
        "DOCUMENT_STORE_RETENTION_POLICY_VERSION": "DOC-09-2026-08-07",
        "DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED": "false",
        "DOCUMENT_STORE_PURGE_ENABLED": "false",
    }
    for variable, expected in expected_retention.items():
        if document_store.get(variable) != expected:
            raise ValueError(
                f"Document Store lifecycle setting {variable} must remain {expected}"
            )

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


def compose_model(
    env_file: Path,
    overlays: list[Path],
    profile: str,
    secret_env_file: Path | None = None,
) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
    ]
    if secret_env_file is not None:
        command.extend(("--env-file", str(secret_env_file)))
    if profile != "data-acquisition":
        command.extend(("-f", str(ROOT / "docker-compose.yml")))
    for overlay in overlays:
        command.extend(("-f", str(overlay)))
    if profile == "data-acquisition":
        command.extend(("--profile", "*"))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=controlled_environment(),
    )
    if result.returncode != 0:
        raise RuntimeError("Docker Compose model could not be rendered")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        required=True,
        choices=(
            "local",
            "local-ses",
            "e2e",
            "e2e-local-ses",
            "live-provider",
            "real-providers",
            "data-acquisition",
        ),
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--secret-env-file", type=Path)
    parser.add_argument("--overlay", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.profile == "data-acquisition" and len(args.overlay) != 1:
        parser.error("data-acquisition requires exactly one standalone Compose file")
    if args.profile == "real-providers":
        expected = (
            (ROOT / "docker-compose.real-job-providers.yml").resolve(),
            (ROOT / "docker-compose.real-openai.yml").resolve(),
            (ROOT / "docker-compose.low-memory.yml").resolve(),
        )
        actual = tuple(path.resolve() for path in args.overlay)
        if actual != expected:
            parser.error(
                "real-providers requires overlays in exact order: "
                "docker-compose.real-job-providers.yml then "
                "docker-compose.real-openai.yml then "
                "docker-compose.low-memory.yml"
            )
        if args.secret_env_file is None:
            parser.error("real-providers requires --secret-env-file")
    validate_model(
        compose_model(
            args.env_file,
            args.overlay,
            args.profile,
            args.secret_env_file,
        ),
        args.profile,
    )
    print(f"{args.profile} Compose trust graph is valid; no values were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
