#!/usr/bin/env python3
"""Account-free validation of the reviewed public-beta AWS release contract."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "aws" / "public-beta"
ZERO_DIGEST = "sha256:" + "0" * 64
DOCUMENT_STORE_TASK_ROLE_REVISION = "1183ce5a54ab60999ca37d826ceb16857d5763ff"
ADZUNA_RUNTIME_HEALTH_REVISION = "594ac33862c6360fe05768905bab0e2cb9ac1898"
JSEARCH_RUNTIME_HEALTH_REVISION = "79677c6586207f5aa30b9c6d0720f5ed2cfe728a"
POSTCODES_NI_GATE_REVISION = "f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb"
POSTCODES_NI_GATE_OPENAPI_SHA256 = "8321009c305d2d22986224e366df6f0b451c1b5587d05dd0ec4876441e09d7ff"
LOCATION_SERVICE_NI_REVISION = "91857140c71bfda8b807c535272f918fe7741263"
LOCATION_SERVICE_NI_OPENAPI_SHA256 = "cd74fbf278c710a2782bbbe6473f9f708a19b6dd9329f42927ce302bb53f5f6b"
LOCATION_GATEWAY_NI_REVISION = "777ec7e8885fcb07368e05ad2543181e4ef7a891"
LOCATION_GATEWAY_NI_OPENAPI_SHA256 = "30d71d6b2508c7cbd452b522c30c26bfa7a571e1f1ebcda979008422db469cfc"
AUTH_PAYMENT_V2_REVISION = "d447addae21714f51267c0ab073377c24e3cfe81"
AUTH_PAYMENT_V2_OPENAPI_SHA256 = "8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884"
UMG_PAYMENT_V2_REVISION = "5dc8aa1e7afb9492a96d3dedde847c530b6209b0"
UMG_PAYMENT_V2_OPENAPI_SHA256 = "dde3349e015f2cd7ef7bf9bc810681bebe98fca1ed1510005aa0b1a8b0e6d08e"
UMG_AUTH_SNAPSHOT_SHA256 = "95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0"
DGG_PAYMENT_V2_REVISION = "cd9b71a3d4dbfbe41d6784f3eeeb7b1b113f5218"
DGG_PAYMENT_V2_OPENAPI_SHA256 = "864ba3c36b2ba4bcd1749edc597ed903a21e7dfa515bb2809d3bc9b9cf878f42"
PAYMENT_SERVICE_V2_REVISION = "63a2f3f2c6e29bb2d2744124c4b1ebe3a3b895ff"
PAYMENT_SERVICE_V2_OPENAPI_SHA256 = "40aa59f62a4ad4d956c2324c9c8d9fa154e4b04b49c029cbda0d80cc2c5dcdc9"
PAYMENT_GATEWAY_V2_REVISION = "c49f9dc7441d146e58b428793a9c1a833c24aec5"
PAYMENT_GATEWAY_V2_OPENAPI_SHA256 = "addd12e77307194d1635e49da9195dfe616a7e7653662492592764dd9092a4ec"
STRIPE_GATEWAY_V2_REVISION = "0e84d1bd97a00194809322307682c557069f30d4"
STRIPE_GATEWAY_V2_OPENAPI_SHA256 = "9fff5cff738ab51c24be85e989dcb6b9fe01bd2397289695660deff2c83a6ef7"
SYSTEM_DATA_PAYMENT_FIXTURE_REVISION = "ca4bafeafbfe41b25a8507f6f08d97490ef71a28"
E2E_PAYMENT_FIXTURE_REVISION = "1541d92f34a3068bb160e1638834a06af6a60796"
INFRASTRUCTURE_PAYMENT_FIXTURE_REVISION = "412566a750ead55740e0b2b4b81cebe29d3e0ad9"
CLIENT_RELEASE_REVISION = "3092e46157105a3d8702221c53623184f276a896"
CLIENT_ARTIFACT_CONTRACT_SHA256 = "801fab5beb7ea81798677086ef00a94759294a1e85915f74da843632de2c6f75"
LANDING_RELEASE_REVISION = "743e42475319330be70e4d6d8f47000f913626f9"
LANDING_ARTIFACT_CONTRACT_SHA256 = "9682372ef2d909de3b2b49c6d0fed232565b61e1b1fe0ac666ace58bfdb0804f"
EXCLUDED_REPOSITORIES = {"system-data-service", "e2e"}
DATABASE_SERVICES = {
    "authentication-service",
    "user-profile-service",
    "job-service",
    "document-generation-gateway",
    "document-store-service",
    "application-tracker-service",
    "payment-service",
}
CAPABILITIES = {
    "documentStoreTaskRoleCredentials",
    "documentStoreS3KmsEncryption",
    "runtimeHealthcheckCommandsVerified",
    "rdsCaBundleVerified",
    "postcodesNorthernIrelandCoverageChainVerified",
    "frontendArtifactsVerified",
    "paymentV2ProductionContractVerified",
    "paymentFixtureAcceptanceVerified",
}
FORBIDDEN_AWS_CREDENTIAL_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "DOCUMENT_STORE_OBJECT_ACCESS_KEY",
    "DOCUMENT_STORE_OBJECT_SECRET_KEY",
}
LANDING_RUNTIME_FIELDS = {
    "environmentName",
    "enableLiveSubmissions",
    "publicBetaEnabled",
    "searchIndexingEnabled",
    "analyticsEnabled",
    "analyticsEndpointUrl",
    "waitlistApiUrl",
    "waitlistConfirmationApiUrl",
    "waitlistResendApiUrl",
    "waitlistUnsubscribeApiUrl",
    "contactApiUrl",
    "mainApplicationUrl",
    "registrationUrl",
    "signInUrl",
    "pricingUrl",
    "legalDocumentsReviewed",
    "minimumUserAge",
    "legalEffectiveDate",
    "legalVersion",
    "legalEntityType",
    "taxStatus",
    "legalEntityName",
    "tradingName",
    "businessAddress",
    "privacyEmail",
    "supportEmail",
    "icoRegistrationStatus",
    "icoRegistrationReference",
    "accountDeletionCompletionDays",
    "documentDeletionCompletionDays",
    "securityLogRetentionDays",
    "supportRecordRetentionDays",
    "financialRecordRetentionYears",
    "publicWebsiteUrl",
    "privacyPolicyUrl",
    "termsUrl",
    "supportUrl",
    "antiBotProvider",
    "antiBotSiteKey",
    "consentVersion",
    "minimumFormCompletionMs",
    "contactMessageMaxLength",
    "copyrightNotice",
}


class ContractError(RuntimeError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        display_path = path.relative_to(ROOT)
    except ValueError:
        display_path = path
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"{display_path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{display_path}: root must be an object")
    return value


def load_landing_runtime_config(archive_path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = [member for member in archive.getmembers() if member.name == "config/app-config.json"]
            require(len(members) == 1, "Landing artifact must contain exactly one config/app-config.json")
            member = members[0]
            require(member.isfile() and member.size <= 64 * 1024, "Landing runtime config must be a bounded regular file")
            handle = archive.extractfile(member)
            require(handle is not None, "Landing runtime config cannot be read")
            config = json.loads(handle.read().decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"invalid Landing static artifact: {exc}") from exc
    require(isinstance(config, dict), "Landing runtime config must be an object")
    return config


def validate_landing_runtime_config(config: dict[str, Any], approvals: dict[str, Any]) -> None:
    require(set(config) == LANDING_RUNTIME_FIELDS, "Landing runtime config differs from its reviewed public schema")
    legal = approvals["publicLegal"]
    require(legal.get("reviewed") is True, "Landing release requires the reviewed public legal contract")
    require(config.get("environmentName") == "production", "Landing release must use the production environment class")
    require(config.get("publicWebsiteUrl") == "https://www.jobseekercopilot.com", "Landing release must use the canonical public origin")
    require(config.get("minimumUserAge") == 18, "Landing release must retain the UK-adult minimum age")
    for switch in (
        "enableLiveSubmissions",
        "publicBetaEnabled",
        "searchIndexingEnabled",
        "analyticsEnabled",
        "legalDocumentsReviewed",
    ):
        require(type(config.get(switch)) is bool, f"Landing release switch must be an explicit boolean: {switch}")
    require(config["legalDocumentsReviewed"] is True, "Landing artifact cannot contain draft legal configuration")

    legal_bindings = {
        "legalEffectiveDate": "effectiveOn",
        "legalVersion": "legalVersion",
        "legalEntityType": "legalEntityType",
        "taxStatus": "taxStatus",
        "legalEntityName": "legalEntityName",
        "tradingName": "tradingName",
        "businessAddress": "businessAddress",
        "privacyEmail": "privacyEmail",
        "supportEmail": "supportEmail",
        "icoRegistrationStatus": "icoRegistrationStatus",
        "icoRegistrationReference": "icoRegistrationReference",
        "accountDeletionCompletionDays": "accountDeletionCompletionDays",
        "documentDeletionCompletionDays": "documentDeletionCompletionDays",
        "securityLogRetentionDays": "securityLogRetentionDays",
        "supportRecordRetentionDays": "supportRecordRetentionDays",
        "financialRecordRetentionYears": "financialRecordRetentionYears",
    }
    mismatches = [
        runtime_name
        for runtime_name, approval_name in legal_bindings.items()
        if config.get(runtime_name) != legal.get(approval_name)
    ]
    require(not mismatches, f"Landing legal/runtime values differ from protected launch approval: {mismatches}")

    terms_url = str(legal.get("termsUrl", ""))
    privacy_url = str(legal.get("privacyNoticeUrl", ""))
    terms = urlsplit(terms_url)
    privacy = urlsplit(privacy_url)
    require(
        terms.scheme == "https" and bool(terms.netloc) and terms.path == "/terms" and not terms.query and not terms.fragment,
        "protected Terms URL must be an absolute query-free HTTPS /terms URL",
    )
    require(
        privacy.scheme == "https" and privacy.netloc == terms.netloc and privacy.path == "/privacy"
        and not privacy.query and not privacy.fragment,
        "protected Privacy URL must be the matching absolute query-free HTTPS /privacy URL",
    )
    application_origin = f"https://{terms.netloc}"
    require(config.get("mainApplicationUrl", "").rstrip("/") == application_origin, "Landing app origin must match protected legal URLs")
    require(config.get("registrationUrl") == f"{application_origin}/register", "Landing registration URL differs from the app release")
    require(config.get("signInUrl") == f"{application_origin}/sign-in", "Landing sign-in URL differs from the app release")
    require(config.get("pricingUrl") == f"{application_origin}/payment", "Landing pricing URL differs from the app release")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_runtime(catalog: dict[str, Any], runtime: dict[str, Any]) -> set[str]:
    catalog_repositories = catalog.get("repositories")
    services = runtime.get("services")
    require(isinstance(catalog_repositories, list), "config/services.json: repositories must be a list")
    require(isinstance(services, dict), "runtime-services.json: services must be an object")

    expected = {
        entry["name"]: entry
        for entry in catalog_repositories
        if entry.get("name") not in EXCLUDED_REPOSITORIES
    }
    require(set(services) == set(expected), "runtime service set must exactly match the 27 production repositories")
    require(len(services) == 27, f"expected 27 runtime services, found {len(services)}")

    total_cpu = 0
    total_memory = 0
    for name, service in services.items():
        require(service.get("port") == expected[name].get("port"), f"{name}: port differs from service catalogue")
        expected_health = "/" if name == "job-seeker-copilot-client" else expected[name].get("health")
        require(service.get("healthPath") == expected_health, f"{name}: health path differs from reviewed catalogue")
        cpu = service.get("cpu")
        memory = service.get("memory")
        require(isinstance(cpu, int) and cpu > 0, f"{name}: positive integer cpu reservation required")
        require(isinstance(memory, int) and memory >= 128, f"{name}: memory reservation below 128 MiB")
        total_cpu += cpu
        total_memory += memory

        environment = service.get("environment")
        secrets = service.get("secrets")
        require(isinstance(environment, dict), f"{name}: environment must be an object")
        require(isinstance(secrets, dict), f"{name}: secrets must be an object")
        names = set(environment) | set(secrets)
        require(not names.intersection(FORBIDDEN_AWS_CREDENTIAL_NAMES), f"{name}: static AWS credentials are forbidden")
        require(all(isinstance(value, str) for value in environment.values()), f"{name}: environment values must be strings")
        require(all(isinstance(value, str) for value in secrets.values()), f"{name}: secret specifications must be strings")

    # One m7i.2xlarge: 8192 CPU units / 32768 MiB, retaining 1024 CPU / 4096 MiB
    # for OS/ECS plus 512/4096 for isolated ClamAV and 256/512 for an operator.
    require(total_cpu + 512 + 256 + 1024 <= 8192, "lean fleet CPU no longer fits one m7i.2xlarge")
    require(total_memory + 4096 + 512 + 4096 <= 32768, "lean fleet memory no longer fits one m7i.2xlarge")
    require(len(services) + 2 <= 40, "lean fleet exceeds m7i.2xlarge awsvpcTrunking task slots")

    document = services["document-store-service"]
    require(
        document["environment"].get("DOCUMENT_STORE_OBJECT_CREDENTIALS_PROVIDER") == "task-role",
        "Document Store must use the fail-closed ECS task-role credential provider",
    )
    require(document["environment"].get("DOCUMENT_STORE_OBJECT_PROVIDER") == "s3", "Document Store must use S3")
    require(document["environment"].get("DOCUMENT_STORE_OBJECT_PATH_STYLE") == "false", "custom/path-style S3 endpoints are forbidden")
    require(
        document["environment"].get("DOCUMENT_STORE_CLAMAV_HOST") == "clamav.{{namespace}}",
        "Document Store must use the isolated private ClamAV service",
    )
    require(
        services["cv-cover-letter-service"]["environment"].get("REJECTED_GENERATION_QUARANTINE_ENABLED") == "false",
        "filesystem-only rejected-generation quarantine must remain disabled for public beta",
    )
    require(
        services["postcode-io-gateway"]["environment"].get("POSTCODES_IO_NORTHERN_IRELAND_ENABLED") == "false",
        "Northern Ireland/BT postcode lookup must default disabled until its licence gate is verified",
    )

    authentication = services["authentication-service"]
    require("PAYMENT_SERVICE_URL" in authentication["environment"], "Authentication account lifecycle requires PAYMENT_SERVICE_URL")
    require("STRIPE_GATEWAY_URL" not in authentication["environment"], "Authentication must not bypass Payment for Stripe lifecycle work")
    lifecycle_bindings = {
        "ACCOUNT_LIFECYCLE_TO_PAYMENT_SERVICE_TOKEN": ("authentication-service", "payment-service"),
        "PAYMENT_SERVICE_TO_STRIPE_GATEWAY_LIFECYCLE_TOKEN": ("payment-service", "stripe-gateway"),
    }
    for token, owners in lifecycle_bindings.items():
        for owner in owners:
            require(
                services[owner]["secrets"].get(token) == f"core:{token}",
                f"{owner}: missing distinct {token} account-lifecycle binding",
            )

    payment = services["payment-service"]["environment"]
    payment_defaults = {
        "PAYMENT_LEDGER_VERIFY_ON_STARTUP": "true",
        "PAYMENT_RESERVATION_RECOVERY_ENABLED": "true",
        "PAYMENT_RESERVATION_TTL": "PT15M",
        "PAYMENT_RESERVATION_RECOVERY_INTERVAL": "PT30S",
        "PAYMENT_RESERVATION_RECOVERY_BATCH_SIZE": "100",
        "PAYMENT_STRIPE_LIFECYCLE_GATEWAY_URL": "http://stripe-gateway.{{namespace}}:8100",
        "PAYMENT_PROVIDER_SESSION_RECOVERY_ENABLED": "true",
        "PAYMENT_PROVIDER_SESSION_RECOVERY_INTERVAL": "PT30S",
        "PAYMENT_PROVIDER_SESSION_RECOVERY_BATCH_SIZE": "50",
        "FREE_DOCUMENT_CREDITS": "2",
        "PAYMENT_CHECKOUT_ORDER_TTL": "PT1H",
        "PAYMENT_DEMO_PURCHASE_ENABLED": "false",
        "PAYMENT_LEGACY_STRIPE_CONFIRMATION_ENABLED": "false",
        "PAYMENT_CHECKOUT_ENABLED": "false",
        "PAYMENT_CHECKOUT_RELEASE_AUTHORISED": "false",
        "PAYMENT_PROVIDER_LIVE_MODE_EXPECTED": "false",
        "PAYMENT_TAX_TREATMENT": "VAT_NOT_CHARGED",
        "PAYMENT_TAX_STATUS": "NOT_CONFIGURED",
        "PAYMENT_LEGAL_ENTITY_TYPE": "NOT_CONFIGURED",
        "PAYMENT_LEGAL_ENTITY_CONFIGURATION_VERSION": "NOT_CONFIGURED",
        "PAYMENT_LEGAL_ENTITY_REVIEWED": "false",
        "PAYMENT_FOUNDING_PROMOTION_ENABLED": "false",
        "PAYMENT_FOUNDING_PROMOTION_RELEASE_AUTHORISED": "false",
        "PAYMENT_CATALOG_VERSION": "UNAPPROVED",
        "PAYMENT_CONSUMER_TERMS_VERSION": "UNAPPROVED",
        "PAYMENT_FINANCIAL_RECORD_RETENTION_YEARS": "0",
    }
    for name, expected_value in payment_defaults.items():
        require(payment.get(name) == expected_value, f"Payment checked-in default must fail closed: {name}")

    client = services["job-seeker-copilot-client"]["environment"]
    client_defaults = {
        "HOST": "0.0.0.0",
        "PORT": "3000",
        "BFF_SESSION_COOKIE_PROFILE": "production",
        "NG_ALLOWED_HOSTS": "NOT_CONFIGURED",
        "COMMUTE_ROUTING_MODE": "DISTANCE_ONLY",
        "LEGAL_DOCUMENTS_REVIEWED": "false",
        "LEGAL_VERSION": "NOT_CONFIGURED",
        "LEGAL_ENTITY_TYPE": "NOT_CONFIGURED",
        "TAX_STATUS": "NOT_CONFIGURED",
        "ICO_REGISTRATION_STATUS": "NOT_CONFIGURED",
    }
    for name, expected_value in client_defaults.items():
        require(client.get(name) == expected_value, f"Client checked-in production boundary is incomplete: {name}")
    authentication_legal = services["authentication-service"]["environment"]
    require(
        authentication_legal.get("AUTH_LEGAL_DOCUMENTS_REVIEWED") == "false",
        "Authentication production legal-review gate must fail closed in the checked-in template",
    )
    require(
        authentication_legal.get("AUTH_LEGAL_CURRENT_VERSION") == "NOT_CONFIGURED",
        "Authentication legal version must fail closed in the checked-in template",
    )
    require(
        authentication_legal.get("AUTH_LEGAL_TERMS_URL") == "{{application_base_url}}/terms"
        and authentication_legal.get("AUTH_LEGAL_PRIVACY_NOTICE_URL") == "{{application_base_url}}/privacy",
        "Authentication registration requirements must use the public application legal routes",
    )

    stripe = services["stripe-gateway"]["environment"]
    require(stripe.get("EXTERNAL_PROVIDER_MODE") == "DISABLED", "Stripe checked-in mode must be DISABLED")
    require(stripe.get("STRIPE_LIVE_RELEASE_AUTHORISED") == "false", "Stripe live release must default false")
    require(stripe.get("STRIPE_LEGACY_CHECKOUT_ENABLED") == "false", "legacy Stripe checkout must stay disabled")
    require(stripe.get("STRIPE_API_BASE_URL") == "https://api.stripe.com", "Stripe API host must remain authoritative")
    require(stripe.get("STRIPE_API_VERSION") == "UNAPPROVED", "Stripe API version template must fail closed")
    for return_url in ("STRIPE_SUCCESS_URL", "STRIPE_CANCEL_URL"):
        value = stripe.get(return_url, "")
        require(value.startswith("{{application_base_url}}/payment/"), f"{return_url}: plain application HTTPS page required")
        require("?" not in value and "{" not in value.replace("{{application_base_url}}", ""), f"{return_url}: provider placeholders/query data forbidden")

    for name in DATABASE_SERVICES:
        urls = [value for key, value in services[name]["environment"].items() if key.endswith("_URL")]
        database_urls = [value for value in urls if value.startswith("jdbc:postgresql:")]
        require(len(database_urls) == 1, f"{name}: exactly one JDBC PostgreSQL URL is required")
        require("sslmode=verify-full" in database_urls[0], f"{name}: hostname-verifying database TLS is required")
        require(
            "sslrootcert=/etc/jsc/rds/global-bundle.pem" in database_urls[0],
            f"{name}: checksum-pinned RDS root bundle path is required",
        )

    return set(services)


def validate_images(images: dict[str, Any], runtime_names: set[str], release: bool) -> None:
    image_entries = images.get("images")
    require(isinstance(image_entries, dict), "image-manifest.json: images must be an object")
    expected = runtime_names | {"clamav", "release-operator"}
    require(set(image_entries) == expected, "image manifest must contain every and only runtime/operator image")
    require(images.get("schemaVersion") == 1, "image manifest schemaVersion must be 1")
    evidence = images.get("dependencyEvidence", {})
    require(
        evidence.get("documentStoreTaskRoleStorage") == DOCUMENT_STORE_TASK_ROLE_REVISION,
        "image manifest must retain exact Document Store task-role dependency evidence",
    )
    require(evidence.get("adzunaRuntimeHealth") == ADZUNA_RUNTIME_HEALTH_REVISION, "image manifest must retain exact Adzuna health dependency evidence")
    require(evidence.get("jsearchRuntimeHealth") == JSEARCH_RUNTIME_HEALTH_REVISION, "image manifest must retain exact JSearch health dependency evidence")
    postcode_evidence = evidence.get("postcodesNorthernIrelandCoverageChain")
    frontend_evidence = evidence.get("frontendArtifacts")
    payment_evidence = evidence.get("paymentV2ProductionContract")
    fixture_evidence = evidence.get("paymentFixtureAcceptance")
    if not release:
        require(
            frontend_evidence == {
                "client": {
                    "revision": CLIENT_RELEASE_REVISION,
                    "artifactContractSha256": CLIENT_ARTIFACT_CONTRACT_SHA256,
                    "packaging": "OCI_SSR_BFF",
                },
                "landing": {
                    "revision": LANDING_RELEASE_REVISION,
                    "artifactContractSha256": LANDING_ARTIFACT_CONTRACT_SHA256,
                    "staticArtifactSha256": "PENDING",
                    "runtimeConfigSha256": "PENDING",
                    "selectedSamTemplate": "infrastructure/waitlist-backend/template.yaml",
                    "selectedSamTemplateSha256": "PENDING",
                    "deploymentStatus": "NOT_DEPLOYED",
                },
            },
            "checked-in Client/Landing source contracts must be pinned while generated artifact hashes remain blockers",
        )
    require(isinstance(frontend_evidence, dict), "frontend artifact dependency evidence must be an object")
    require(
        set(frontend_evidence) == {"client", "landing"}
        and set(frontend_evidence.get("client", {})) == {"revision", "artifactContractSha256", "packaging"}
        and set(frontend_evidence.get("landing", {})) == {
            "revision", "artifactContractSha256", "staticArtifactSha256", "runtimeConfigSha256",
            "selectedSamTemplate", "selectedSamTemplateSha256", "deploymentStatus",
        },
        "frontend evidence must cover the exact Client OCI and Landing static artifact contracts",
    )
    require(frontend_evidence["client"].get("packaging") == "OCI_SSR_BFF", "Client must remain one SSR/BFF OCI artifact")
    require(
        frontend_evidence["client"].get("revision") == CLIENT_RELEASE_REVISION
        and frontend_evidence["client"].get("artifactContractSha256") == CLIENT_ARTIFACT_CONTRACT_SHA256
        and frontend_evidence["landing"].get("revision") == LANDING_RELEASE_REVISION
        and frontend_evidence["landing"].get("artifactContractSha256") == LANDING_ARTIFACT_CONTRACT_SHA256,
        "frontend evidence must retain the exact reviewed Client/Landing source and artifact contracts",
    )
    require(
        frontend_evidence["landing"].get("selectedSamTemplate") == "infrastructure/waitlist-backend/template.yaml"
        and frontend_evidence["landing"].get("deploymentStatus") == "NOT_DEPLOYED",
        "Landing evidence must select one SAM owner and must not claim deployment",
    )
    require(isinstance(payment_evidence, dict), "payment-v2 dependency evidence must be a service-to-revision object")
    require(
        set(payment_evidence) == {
            "authenticationService",
            "userManagementGateway",
            "documentGenerationGateway",
            "paymentService",
            "paymentGateway",
            "stripeGateway",
        },
        "payment-v2 dependency evidence must cover every participating service",
    )
    require(
        all(
            isinstance(item, dict)
            and set(item) == (
                {"revision", "openApiSha256", "authSnapshotSha256"}
                if name == "userManagementGateway"
                else {"revision", "openApiSha256"}
            )
            for name, item in payment_evidence.items()
        ),
        "payment-v2 evidence must bind each revision to its exported OpenAPI and reviewed consumer snapshot",
    )
    require(
        payment_evidence == {
            "authenticationService": {
                "revision": AUTH_PAYMENT_V2_REVISION,
                "openApiSha256": AUTH_PAYMENT_V2_OPENAPI_SHA256,
            },
            "userManagementGateway": {
                "revision": UMG_PAYMENT_V2_REVISION,
                "openApiSha256": UMG_PAYMENT_V2_OPENAPI_SHA256,
                "authSnapshotSha256": UMG_AUTH_SNAPSHOT_SHA256,
            },
            "documentGenerationGateway": {
                "revision": DGG_PAYMENT_V2_REVISION,
                "openApiSha256": DGG_PAYMENT_V2_OPENAPI_SHA256,
            },
            "paymentService": {
                "revision": PAYMENT_SERVICE_V2_REVISION,
                "openApiSha256": PAYMENT_SERVICE_V2_OPENAPI_SHA256,
            },
            "paymentGateway": {
                "revision": PAYMENT_GATEWAY_V2_REVISION,
                "openApiSha256": PAYMENT_GATEWAY_V2_OPENAPI_SHA256,
            },
            "stripeGateway": {
                "revision": STRIPE_GATEWAY_V2_REVISION,
                "openApiSha256": STRIPE_GATEWAY_V2_OPENAPI_SHA256,
            },
        },
        "payment-v2 evidence must retain the exact final tested lifecycle/saga revisions and OpenAPI hashes",
    )
    require(
        fixture_evidence == {
            "systemDataServiceRevision": SYSTEM_DATA_PAYMENT_FIXTURE_REVISION,
            "e2eRevision": E2E_PAYMENT_FIXTURE_REVISION,
            "infrastructureRevision": INFRASTRUCTURE_PAYMENT_FIXTURE_REVISION,
            "profile": "test",
            "providerMode": "FIXTURE",
            "healthyServiceCount": 36,
            "scenarioCount": 4,
            "stepCount": 33,
        },
        "payment fixture evidence must retain the exact isolated signed-settlement acceptance revisions/counts",
    )
    require(
        postcode_evidence == {
            "postcodeIoGateway": {
                "revision": POSTCODES_NI_GATE_REVISION,
                "openApiSha256": POSTCODES_NI_GATE_OPENAPI_SHA256,
            },
            "locationService": {
                "revision": LOCATION_SERVICE_NI_REVISION,
                "openApiSha256": LOCATION_SERVICE_NI_OPENAPI_SHA256,
            },
            "locationGateway": {
                "revision": LOCATION_GATEWAY_NI_REVISION,
                "openApiSha256": LOCATION_GATEWAY_NI_OPENAPI_SHA256,
            },
        },
        "image manifest must retain the exact tested Postcodes NI/BT coverage chain and OpenAPI hashes",
    )
    capabilities = images.get("capabilities", {})
    require(CAPABILITIES.issubset(capabilities), "image manifest is missing a release capability attestation")

    for name, image in image_entries.items():
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", str(image.get("digest", ""))) is not None, f"{name}: invalid digest")
        if name != "clamav":
            require(re.fullmatch(r"[0-9a-f]{40}", str(image.get("revision", ""))) is not None, f"{name}: invalid source revision")
        require(image.get("scanStatus") in {"UNSCANNED", "PASSED"}, f"{name}: invalid scanStatus")
    require(
        image_entries["clamav"].get("repository") == "upstream/clamav"
        and image_entries["clamav"].get("revision") == "1.4.5",
        "ClamAV image evidence must retain the reviewed preloaded LTS revision",
    )

    if release:
        require(images.get("sourceBranch") == "main", "release image manifest sourceBranch must be main")
        require(images.get("releaseId") not in {None, "", "UNRELEASED"}, "releaseId must be immutable")
        require(
            re.fullmatch(r"[0-9a-f]{64}", str(images.get("launchApprovalManifestSha256", ""))) is not None,
            "release manifest must checksum-bind its protected launch approval",
        )
        require(
            re.fullmatch(r"[0-9a-f]{40}", str(frontend_evidence["client"]["revision"])) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(frontend_evidence["client"]["artifactContractSha256"])) is not None
            and re.fullmatch(r"[0-9a-f]{40}", str(frontend_evidence["landing"]["revision"])) is not None
            and all(
                re.fullmatch(r"[0-9a-f]{64}", str(frontend_evidence["landing"][name])) is not None
                for name in (
                    "artifactContractSha256", "staticArtifactSha256", "runtimeConfigSha256",
                    "selectedSamTemplateSha256",
                )
            )
            and image_entries["job-seeker-copilot-client"]["revision"] == frontend_evidence["client"]["revision"],
            "release requires exact immutable Client and Landing artifact evidence",
        )
        require(
            all(
                re.fullmatch(r"[0-9a-f]{40}", str(item["revision"])) is not None
                and re.fullmatch(r"[0-9a-f]{64}", str(item["openApiSha256"])) is not None
                for item in payment_evidence.values()
            ),
            "release requires exact payment-v2 dependency revisions and OpenAPI hashes",
        )
        require(all(capabilities.get(name) is True for name in CAPABILITIES), "every release capability must be attested true")
        require(all(image["digest"] != ZERO_DIGEST for image in image_entries.values()), "release images require non-placeholder digests")
        require(all(image["scanStatus"] == "PASSED" for image in image_entries.values()), "release images must pass scanning")
    else:
        require(images.get("sourceBranch") == "develop", "template image manifest must remain develop-bound")
        require(images.get("releaseId") == "UNRELEASED", "checked-in template must remain non-releasable")
        require(
            images.get("launchApprovalManifestSha256") == "PENDING",
            "checked-in launch approval checksum must remain an explicit blocker",
        )
        require(all(capabilities.get(name) is False for name in CAPABILITIES), "checked-in capabilities must default false")
        require(all(image["digest"] == ZERO_DIGEST for image in image_entries.values()), "checked-in image digests must remain placeholders")


def validate_approvals(approvals: dict[str, Any], release: bool) -> None:
    legal = approvals.get("publicLegal")
    legal_fields = {
        "reviewed", "reviewedBy", "evidenceReference", "legalVersion", "effectiveOn",
        "legalEntityType", "taxStatus", "legalEntityName", "tradingName", "businessAddress",
        "privacyEmail", "supportEmail", "icoRegistrationStatus", "icoRegistrationReference",
        "accountDeletionCompletionDays", "documentDeletionCompletionDays", "securityLogRetentionDays",
        "supportRecordRetentionDays", "financialRecordRetentionYears", "termsUrl", "termsContentSha256",
        "privacyNoticeUrl", "privacyNoticeContentSha256",
    }
    require(isinstance(legal, dict) and legal_fields.issubset(legal), "public legal approval metadata is incomplete")
    if not release:
        require(legal["reviewed"] is False, "checked-in public legal review must fail closed")
        require(legal["legalVersion"] == "NOT_CONFIGURED", "checked-in public legal version must be NOT_CONFIGURED")
        require(legal["legalEntityType"] == "NOT_CONFIGURED", "checked-in seller type must be NOT_CONFIGURED")
        require(legal["taxStatus"] == "NOT_CONFIGURED", "checked-in public tax status must be NOT_CONFIGURED")
    else:
        require(legal["reviewed"] is True, "release requires reviewed public legal identity")
        require(len(str(legal["reviewedBy"]).strip()) >= 3, "release legal review needs an accountable reviewer")
        require(len(str(legal["evidenceReference"]).strip()) >= 3, "release legal review needs evidence")
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(legal["legalVersion"])) is not None
            and legal["legalVersion"] != "NOT_CONFIGURED",
            "release requires an exact non-placeholder legal version",
        )
        try:
            effective_on = datetime.date.fromisoformat(str(legal["effectiveOn"]))
        except ValueError as exc:
            raise ContractError("release requires a valid ISO legal effective date") from exc
        require(2000 <= effective_on.year <= 2099, "release legal effective date is outside the reviewed range")
        require(legal["legalEntityType"] in {"SOLE_TRADER", "LIMITED_COMPANY"}, "release seller type is not configured")
        require(legal["taxStatus"] in {"NOT_VAT_REGISTERED", "VAT_REGISTERED"}, "release tax status is not configured")
        for name, minimum in (("legalEntityName", 2), ("tradingName", 2), ("businessAddress", 8)):
            value = str(legal[name]).strip()
            require(len(value) >= minimum and re.search(r"(?i)\b(?:todo|tbd|placeholder|pending|not configured)\b", value) is None,
                    f"release public legal value is missing or a placeholder: {name}")
        for name in ("privacyEmail", "supportEmail"):
            require(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(legal[name])) is not None,
                    f"release public legal email is invalid: {name}")
        require(
            legal["icoRegistrationStatus"] == "NOT_REQUIRED_CONFIRMED"
            or (
                legal["icoRegistrationStatus"] == "REGISTERED"
                and re.fullmatch(r"[A-Za-z0-9-]{4,40}", str(legal["icoRegistrationReference"])) is not None
            ),
            "release requires reviewed ICO status/reference",
        )
        for name, minimum, maximum in (
            ("accountDeletionCompletionDays", 35, 365),
            ("documentDeletionCompletionDays", 35, 365),
            ("securityLogRetentionDays", 30, 3650),
            ("supportRecordRetentionDays", 30, 3650),
            ("financialRecordRetentionYears", 7, 10),
        ):
            require(type(legal[name]) is int and minimum <= legal[name] <= maximum,
                    f"release legal retention is outside its reviewed bound: {name}")
        for name in ("termsContentSha256", "privacyNoticeContentSha256"):
            require(re.fullmatch(r"[0-9a-f]{64}", str(legal[name])) is not None,
                    f"release legal content checksum is invalid: {name}")

    integrations = approvals.get("integrations")
    require(isinstance(integrations, dict), "launch approvals must contain integrations")
    expected = {
        "postcodes_gb", "postcodes_ni", "reed", "adzuna", "jsearch", "nhs_jobs",
        "apprenticeships", "google_maps", "openai", "stripe", "account_email",
    }
    require(set(integrations) == expected, "launch approval manifest integration set differs from Terraform switches")
    common = {
        "approved", "approvalReference", "approvedBy", "termsReviewedOn", "expiresOn",
        "monthlyRequestLimit", "monthlyCostCeilingGbp", "attributionRequirement",
    }
    for name, approval in integrations.items():
        require(common.issubset(approval), f"{name}: approval/quota/cost/attribution metadata is incomplete")
        if not release:
            require(approval["approved"] is False, f"{name}: checked-in approval template must fail closed")
    google_fields = {
        "googleBillingQuotasVerified", "billingQuotaEvidenceReference", "gcpProjectId",
        "placesQuotaId", "placesDailyQuota", "routeMatrixEssentialsQuotaId",
        "routeMatrixEssentialsDailyElementQuota", "routeMatrixProQuotaId",
        "routeMatrixProDailyElementQuota", "gcpBudgetAlertGbp",
        "gcpBudgetAlertThresholdPercents", "emergencyDisableOwner",
        "emergencyDisableRunbookReference",
    }
    google = integrations["google_maps"]
    require(google_fields.issubset(google), "Google Maps needs separately attested GCP quota, budget and disable metadata")
    require(
        google["gcpBudgetAlertThresholdPercents"] == [50, 75, 90, 100],
        "Google Maps billing alerts must retain the reviewed 50/75/90/100 percent thresholds",
    )
    if not release:
        require(google["googleBillingQuotasVerified"] is False, "checked-in Google billing quota capability must fail closed")
    payment_fields = {
        "paymentReadinessStatus", "refundRunbookReference", "reconciliationRunbookReference",
        "checkoutEnabled", "checkoutReleaseAuthorised", "providerLiveModeExpected",
        "stripeLiveReleaseAuthorised", "stripeApiVersion", "legalEntityType",
        "legalEntityConfigurationVersion", "legalEntityReviewed", "legalEntityEvidenceReference",
        "merchantTermsTraderDisclosureVerified", "taxTreatment", "taxStatus", "catalogVersion", "catalogPlans",
        "freeDocumentCredits", "billingCountry", "currency", "creditUnit", "automaticRenewal",
        "displayedPriceIsCheckoutTotal", "consumerTermsVersion", "consumerTermsEffectiveOn",
        "consumerTermsUrl", "consumerTermsContentSha256", "financialRecordRetentionYears",
        "foundingPromotionEnabled", "foundingPromotionReleaseAuthorised",
    }
    stripe = integrations["stripe"]
    require(payment_fields.issubset(stripe), "Stripe/payment commercial release metadata is incomplete")
    require(
        stripe["catalogPlans"] == [
            {"id": "starter", "documentCredits": 10, "priceGbpPence": 799},
            {"id": "active", "documentCredits": 25, "priceGbpPence": 1699},
            {"id": "power", "documentCredits": 60, "priceGbpPence": 3499},
        ],
        "Payment catalog must retain the approved 10/25/60-credit GBP pricing",
    )
    require(stripe["freeDocumentCredits"] == 2, "Payment free allowance must remain two document credits")
    if not release:
        require(stripe["taxTreatment"] == "VAT_NOT_CHARGED", "Payment tax treatment must default VAT_NOT_CHARGED")
        require(stripe["taxStatus"] == "NOT_CONFIGURED", "payment tax status must default NOT_CONFIGURED")
        require(stripe["legalEntityType"] == "NOT_CONFIGURED", "legal entity type must default NOT_CONFIGURED")
        require(stripe["legalEntityConfigurationVersion"] == "NOT_CONFIGURED", "legal entity version must default NOT_CONFIGURED")
        for flag in (
            "checkoutEnabled", "checkoutReleaseAuthorised", "providerLiveModeExpected",
            "stripeLiveReleaseAuthorised", "legalEntityReviewed",
            "foundingPromotionEnabled", "foundingPromotionReleaseAuthorised",
            "merchantTermsTraderDisclosureVerified",
        ):
            require(stripe[flag] is False, f"checked-in payment flag must fail closed: {flag}")


def validate_source_guards() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(MODULE.glob("*.tf")))
    required_fragments = {
        'name  = "awsvpcTrunking"': "awsvpcTrunking account setting",
        'max_size = local.node_count': "cost-bounded ASG maximum",
        'version = aws_launch_template.ecs.latest_version': "immutable numeric launch-template version",
        'min_healthy_percentage       = var.high_availability ? 50 : 0': "bounded stop-first host refresh",
        'max_healthy_percentage       = 100': "instance refresh cannot add a cost node",
        'scale_in_protected_instances = "Refresh"': "ECS protected instances can be drained during refresh",
        'auto_rollback                = true': "failed host refresh rolls back",
        'for_each = var.high_availability ? local.raw_services : {}': "autoscaling disabled in the fixed one-node lean shape",
        'deployment_maximum_percent         = 100': "capacity-bounded stop-first deployment",
        'deployment_minimum_healthy_percent = 0': "ordered replacement without extra task copies",
        'for_each = local.service_dependencies': "dependency-derived service security groups",
        'resource "aws_security_group" "clamav"': "isolated ClamAV security group",
        'resource "aws_ecs_service" "clamav"': "independent ClamAV ECS service",
        'execution_role_arn       = aws_iam_role.clamav_execution.arn': "ClamAV pull/log execution role",
        'referenced_security_group_id = aws_security_group.clamav.id': "Document Store to isolated scanner egress",
        'memory = 4096': "reviewed ClamAV native-memory ceiling",
        '172800': "ClamAV signature freshness task health",
        'SizeRestrictions_BODY': "narrow WAF upload-body override",
        'authenticated_document_uploads': "exact WAF upload paths",
        'threshold           = 100': "RDS connection reserve alarm",
        'default     = 750': "$750 monthly alert budget",
        'subscriber_sns_topic_arns': "budget SNS notifications",
        'aws_backup_selection': "RDS/S3 backup selection",
        'database_bootstrap': "database bootstrap release gate",
        'runtime_attestations': "exact-release SSM attestation gate",
        'quarantine/application-uploads/*': "durable application-upload quarantine IAM path",
        'stale-application-upload-quarantine': "bounded application-upload quarantine cleanup",
        'containerPath = "/var/log/clamav"': "bounded ephemeral ClamAV log storage",
        '"uid=100", "gid=101", "mode=0750"': "ClamAV-owned log/socket tmpfs",
        'clamdscan --reload': "fail-closed ClamAV initial signature reload",
        'mountOptions  = ["rw", "noexec", "nosuid", "nodev"]': "bounded hardened application scratch storage",
        'user                   = each.key == "job-seeker-copilot-client" ? "1000:1000" : "10001:10001"': "explicit non-root application task users",
        'payment_contract_complete': "payment catalog/tax/terms/retention release gate",
        'public_legal_contract_complete': "shared Client/Authentication/Payment legal release gate",
        'POSTCODES_IO_NORTHERN_IRELAND_ENABLED': "fail-closed NI/BT postcode runtime binding",
        'STRIPE_API_VERSION': "explicit Stripe API version contract",
        'release_attestation_id': "runtime-configuration-bound release markers",
        'output "emergency_darken_contract"': "state-bound emergency containment identifiers",
        'filesha256(local.approval_manifest_path)': "signed launch-approval checksum binding",
        'operator_preflight_secret': "least-privilege payment-readiness preflight identity",
        '/alb/AWSLogs/${var.aws_account_id}/*': "account-scoped ALB access-log delivery path",
        'elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:loadbalancer/*': "source-scoped ALB log delivery",
        'variable = "aws:SourceAccount"': "source-account-bound ECS task trust",
        '"aws:SourceAccount" = var.aws_account_id': "source-account-bound AWS service trusts",
    }
    for fragment, description in required_fragments.items():
        require(fragment in source, f"Terraform is missing {description}")
    require('self        = true' not in source, "shared self-referencing task security group is forbidden")
    require("AWS_ACCESS_KEY_ID" not in source, "Terraform must not inject static AWS access keys")
    locals_source = (MODULE / "locals.tf").read_text(encoding="utf-8")
    stripe_runtime_block = locals_source.split("stripe_commercial_environment = {", maxsplit=1)[1].split(
        "\n  }", maxsplit=1
    )[0]
    require(
        'EXTERNAL_PROVIDER_MODE         = var.enabled_integrations.stripe ? "LIVE" : "DISABLED"'
        in stripe_runtime_block
        and '"FIXTURE"' not in stripe_runtime_block,
        "production Stripe runtime mode must be exactly gated LIVE/DISABLED and never fixture-backed",
    )
    require('variable = "s3:x-amz-acl"' not in source, "ALB log delivery must not require an unsupported canned-ACL header")
    compute = (MODULE / "compute.tf").read_text(encoding="utf-8")
    clamav_task = compute.split('resource "aws_ecs_task_definition" "clamav" {', maxsplit=1)[1].split(
        'resource "aws_ecs_service" "clamav" {', maxsplit=1
    )[0]
    require("task_role_arn" not in clamav_task, "ClamAV task definition must not receive an AWS task role")
    require(
        'containerPath = "/var/lib/clamav"' not in clamav_task,
        "ClamAV task must not hide the preloaded signature database behind an empty tmpfs",
    )

    edge = (MODULE / "edge.tf").read_text(encoding="utf-8")
    for suffix in ("document-uploads$", "replace$"):
        require(suffix in edge, f"WAF exception missing exact authenticated upload path ending {suffix}")
    require(edge.count("AWSManagedRulesCommonRuleSet") == 2, "WAF must apply CRS separately to upload/non-upload traffic")
    require(
        re.search(r'name\s*=\s*"SizeRestrictions_BODY"[\s\S]*?action_to_use\s*\{\s*count\s*\{\}', edge) is not None,
        "WAF must override only upload body-size rule",
    )


def validate_workflow_boundary() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    require("id-token: write" not in ci, "develop/PR CI must never receive a GitHub OIDC token")

    release_path = ROOT / ".github" / "workflows" / "aws-public-beta-release.yml"
    build_path = ROOT / ".github" / "workflows" / "aws-public-beta-build.yml"
    privileged_workflows: list[tuple[Path, str, str]] = []
    if release_path.exists():
        release = release_path.read_text(encoding="utf-8")
        require("workflow_dispatch:" in release, "AWS release workflow must be explicitly dispatched")
        require("github.ref == 'refs/heads/main'" in release, "AWS release workflow must fail outside main")
        require("environment: production-aws" in release, "AWS apply must require the protected production environment")
        require("gh attestation verify" in release, "AWS release workflow must verify signed build provenance")
        require('.head_sha <<<"$run_json"' in release, "AWS release workflow must bind the build to the exact main revision")
        require("workspaceLockSha256" in release, "AWS release workflow must bind the build to the workspace lock")
        require(
            'if [ "$RELEASE_ACTION" = rollback ]; then' in release
            and 'test "$build_sha" = "$GITHUB_SHA"' in release,
            "only rollback may consume an ancestor build; activation must use exact current protected main",
        )
        privileged_workflows.append((release_path, release, "production-aws"))
    if build_path.exists():
        build = build_path.read_text(encoding="utf-8")
        require("workflow_dispatch:" in build, "AWS build workflow must be explicitly dispatched")
        require("github.ref == 'refs/heads/main'" in build, "AWS build workflow must fail outside main")
        require("environment: production-build" in build, "ECR publication must require the protected build environment")
        require("permission-contents: read" in build, "GitHub App checkout token must be contents-read-only")
        require("repositories: |" in build, "GitHub App token must be limited to the locked repository set")
        require("job-seeker-copilot-landing" in build, "immutable build must include the Landing release repository")
        require("LANDING_RUNTIME_ENV_B64" in build, "Landing build needs a protected, explicit runtime-config input")
        require("LAUNCH_APPROVALS_FILE" in build, "immutable build must bind the protected launch approval manifest")
        prepare_script = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        landing_builder = (ROOT / "scripts" / "aws" / "build_landing_artifact.py").read_text(encoding="utf-8")
        require("build_landing_artifact.py" in prepare_script,
                "immutable build must produce checksum-bound Landing static/SAM evidence")
        require(
            '${GITHUB_REF:-}' in prepare_script and '${GITHUB_REF:-refs/heads/main}' not in prepare_script,
            "local source builds must not impersonate protected main when GITHUB_REF is absent",
        )
        require(
            "clamav/clamav:1.4.5@sha256:4de20bd9ab45a4b763c5412b769217ef5082572ebc8a63aff1a77943419e5dd8"
            in prepare_script
            and "1.4.5_base" not in prepare_script,
            "immutable build must use the reviewed preloaded ClamAV image digest",
        )
        require(
            "clamav_health_command=" in prepare_script
            and "clamdscan --reload" in prepare_script
            and "exit 42" in prepare_script
            and "clamav_reload_observed=true" in prepare_script
            and prepare_script.count('docker exec "$clamav_probe" /bin/sh -c "$clamav_health_command"') == 2,
            "immutable build must prove initial ClamAV reload plus a healthy idempotent pass",
        )
        require(
            "uid=100,gid=101,mode=0750" in prepare_script
            and "--tmpfs /var/lib/clamav" not in prepare_script,
            "ClamAV exact-image probe must preserve preloaded signatures and own mutable tmpfs paths",
        )
        require(
            "paymentFixtureAcceptance" in prepare_script
            and '[system-data-service]=' in prepare_script
            and '[e2e]=' in prepare_script
            and "Infrastructure does not contain the reviewed isolated payment fixture overlay" in prepare_script
            and ".capabilities.paymentFixtureAcceptanceVerified=true" in prepare_script,
            "immutable build must ancestor-verify isolated payment acceptance without making fixture code runtime",
        )
        require(
            'build_environment.pop("AMPLIFY_RELEASE_AUTHORISED", None)' in landing_builder,
            "central Landing evidence build must strip legacy Amplify publication authority",
        )
        prepare_job = build.split("\n  publish:\n", maxsplit=1)[0]
        require("id-token: write" not in prepare_job, "source-build job must not have a GitHub OIDC capability")
        require(
            build.index("Build and verify release artifacts without AWS credentials")
            < build.index("Configure build-only AWS role"),
            "AWS role assumption must occur only after the isolated source-build job",
        )
        require("load_prepared_release_images.sh" in build, "publisher must checksum-load the prepared image archive before AWS access")
        publish_script = (ROOT / "scripts" / "aws" / "publish_release_images.sh").read_text(encoding="utf-8")
        require("aws ecr" not in prepare_script, "credential-free source build must not contain ECR calls")
        require("aws ecr get-login-password" in publish_script, "protected publisher must own ECR mutation")
        require('push_image clamav "$clamav_image" 1.4.5' in publish_script,
                "publisher must retain the reviewed ClamAV source revision")
        privileged_workflows.append((build_path, build, "production-build"))

    if release_path.exists():
        release = release_path.read_text(encoding="utf-8")
        require(
            release.count("verify_frontend_release_artifact.sh") == 2,
            "plan and mutation paths must verify Client/Landing evidence before AWS access",
        )
        emergency = (ROOT / "scripts" / "aws" / "emergency_darken.sh").read_text(encoding="utf-8")
        require(
            "inputs.action != 'foundation' && inputs.action != 'darken'" in release,
            "emergency darkening must not depend on a retained build artifact",
        )
        require(
            "Execute approval-independent emergency containment" in release,
            "protected release workflow must expose the reviewed emergency containment path",
        )
        require("APPROVAL_MANIFEST" not in emergency, "emergency darkening must not depend on current approvals")
        require("validate_public_beta.py" not in emergency, "emergency darkening must bypass launch-readiness validation")
        require('current_release_id=$(jq -er .release_id' in emergency, "emergency darkening must bind applied release state")
        require(
            emergency.index("aws elbv2 modify-rule")
            < emergency.index("aws elbv2 modify-listener")
            < emergency.index("aws ecs update-service"),
            "emergency darkening must close webhook/default public routes before task drain",
        )

    for path, workflow, environment in privileged_workflows:
        references = re.findall(r"^\s*uses:\s*[^\s#]+@([^\s#]+)", workflow, flags=re.MULTILINE)
        require(references, f"{path.name}: expected at least one reusable action")
        require(
            all(re.fullmatch(r"[0-9a-f]{40}", reference) is not None for reference in references),
            f"{path.name}: every reusable action must be pinned to an immutable 40-character commit",
        )
        require(
            "role-duration-seconds: 10800" in workflow,
            f"{path.name}: the reviewed three-hour OIDC session is required for {environment}",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true", help="require a launchable immutable manifest")
    parser.add_argument("--landing-only", action="store_true", help="validate protected Landing/legal input before image publication")
    parser.add_argument("--image-manifest", type=Path, default=MODULE / "config" / "image-manifest.json")
    parser.add_argument("--approval-manifest", type=Path, default=MODULE / "config" / "launch-approvals.json")
    parser.add_argument("--landing-archive", type=Path, help="checksum-verified Landing static artifact")
    args = parser.parse_args()

    try:
        if args.landing_only:
            require(not args.release, "--landing-only and --release are mutually exclusive")
            require(args.landing_archive is not None, "Landing-only validation requires the static artifact")
            approvals = load_json(args.approval_manifest.resolve())
            validate_approvals(approvals, True)
            validate_landing_runtime_config(load_landing_runtime_config(args.landing_archive.resolve()), approvals)
            print("public-beta Landing/legal contract valid (account-free; no AWS calls)")
            return 0
        runtime_names = validate_runtime(
            load_json(ROOT / "config" / "services.json"),
            load_json(MODULE / "config" / "runtime-services.json"),
        )
        validate_images(load_json(args.image_manifest.resolve()), runtime_names, args.release)
        approvals = load_json(args.approval_manifest.resolve())
        validate_approvals(approvals, args.release)
        if args.release:
            require(args.landing_archive is not None, "release validation requires the Landing static artifact")
            validate_landing_runtime_config(load_landing_runtime_config(args.landing_archive.resolve()), approvals)
        validate_source_guards()
        validate_workflow_boundary()
    except ContractError as exc:
        print(f"public-beta AWS contract invalid: {exc}", file=sys.stderr)
        return 1

    mode = "release" if args.release else "account-free template"
    print(f"public-beta AWS contract valid ({mode}; no AWS calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
