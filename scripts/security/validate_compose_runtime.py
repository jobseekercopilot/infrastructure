#!/usr/bin/env python3
"""Validate the rendered Compose trust graph without printing credentials."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_CREDENTIALS = (
    "AUTH_SERVICE_TOKEN",
    "ENVIRONMENT_DATA_TOKEN",
    "APPLICATION_TRACKER_PRODUCER_TOKEN",
    "APPLICATION_TRACKER_READER_TOKEN",
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


def validate_model(model: dict, profile: str) -> None:
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

    if profile == "e2e":
        for service in (
            "reed-gateway",
            "adzuna-gateway",
            "jsearch-gateway",
            "llm-gateway",
            "stripe-gateway",
        ):
            if environment(model, service).get("EXTERNAL_PROVIDER_MODE") != "FIXTURE":
                raise ValueError(f"{service} must be fixture-only in E2E")


def compose_model(env_file: Path, overlays: list[Path]) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(ROOT / "docker-compose.yml"),
    ]
    for overlay in overlays:
        command.extend(("-f", str(overlay)))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Docker Compose model could not be rendered")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", required=True, choices=("local", "e2e", "live-provider")
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, action="append", default=[])
    args = parser.parse_args()
    validate_model(compose_model(args.env_file, args.overlay), args.profile)
    print(f"{args.profile} Compose trust graph is valid; no values were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
