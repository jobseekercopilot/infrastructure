from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


CONFIRMATION = "I UNDERSTAND LIVE PROVIDERS WILL BE CALLED"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
AUDIT_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,127}$")
REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{1,127}$")
SEMANTIC_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
PROVIDER_SETTINGS = {
    "ADZUNA": (
        "DATA_ACQUISITION_ADZUNA_ENABLED",
        ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
        "adzuna-gateway",
    ),
    "JSEARCH": (
        "DATA_ACQUISITION_JSEARCH_ENABLED",
        ("JSEARCH_API_KEY",),
        "jsearch-gateway",
    ),
    "REED": (
        "DATA_ACQUISITION_REED_ENABLED",
        ("REED_API_KEY",),
        "reed-gateway",
    ),
}


@dataclass(frozen=True)
class AcquisitionAuthorization:
    run_id: str
    terms_approval_reference: str
    provenance_reviewer: str
    approved_providers: tuple[str, ...]
    gateway_services: tuple[str, ...]
    postcode_enabled: bool
    retention_days: int
    dataset_id: str
    dataset_version: str


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"missing ignored acquisition environment: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} is not NAME=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in values:
            raise ValueError(f"{path}:{line_number} has a missing or duplicate name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def required(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def boolean(values: dict[str, str], name: str) -> bool:
    value = values.get(name, "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def authorize(values: dict[str, str]) -> AcquisitionAuthorization:
    run_id = required(values, "DATA_ACQUISITION_RUN_ID")
    if not RUN_ID.fullmatch(run_id):
        raise ValueError(
            "DATA_ACQUISITION_RUN_ID must be a lowercase slug of 3 to 64 characters"
        )
    if required(values, "DATA_ACQUISITION_CONFIRMATION") != CONFIRMATION:
        raise ValueError("the exact live-provider confirmation phrase is required")
    terms_reference = required(
        values, "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE"
    )
    reviewer = required(values, "DATA_ACQUISITION_PROVENANCE_REVIEWER")
    if not AUDIT_REFERENCE.fullmatch(terms_reference):
        raise ValueError(
            "DATA_ACQUISITION_TERMS_APPROVAL_REFERENCE must be a safe audit reference"
        )
    if not REVIEWER.fullmatch(reviewer):
        raise ValueError(
            "DATA_ACQUISITION_PROVENANCE_REVIEWER must be a safe named reviewer"
        )
    dataset_id = required(values, "DATA_ACQUISITION_DATASET_ID")
    if not RUN_ID.fullmatch(dataset_id):
        raise ValueError("DATA_ACQUISITION_DATASET_ID must be a safe dataset slug")
    dataset_version = required(values, "DATA_ACQUISITION_DATASET_VERSION")
    if not SEMANTIC_VERSION.fullmatch(dataset_version):
        raise ValueError("DATA_ACQUISITION_DATASET_VERSION must be semantic")
    try:
        retention_days = int(values.get("DATA_ACQUISITION_RETENTION_DAYS", "14"))
    except ValueError as error:
        raise ValueError("DATA_ACQUISITION_RETENTION_DAYS must be an integer") from error
    if retention_days < 1 or retention_days > 30:
        raise ValueError("DATA_ACQUISITION_RETENTION_DAYS must be between 1 and 30")

    approved = tuple(
        sorted(
            {
                provider.strip().upper()
                for provider in required(
                    values, "DATA_ACQUISITION_APPROVED_PROVIDERS"
                ).split(",")
                if provider.strip()
            }
        )
    )
    if not approved or not set(approved).issubset(PROVIDER_SETTINGS):
        raise ValueError(
            "DATA_ACQUISITION_APPROVED_PROVIDERS must contain only "
            "ADZUNA, JSEARCH, or REED"
        )

    gateway_services: list[str] = []
    for provider, (flag, credentials, service) in PROVIDER_SETTINGS.items():
        enabled = boolean(values, flag)
        if enabled != (provider in approved):
            raise ValueError(f"{flag} must exactly match the approved provider list")
        for credential in credentials:
            credential_present = bool(values.get(credential, "").strip())
            if provider in approved and not credential_present:
                raise ValueError(f"{credential} is required for approved {provider}")
            if provider not in approved and credential_present:
                raise ValueError(
                    f"{credential} must be absent when {provider} is not approved"
                )
        if enabled:
            gateway_services.append(service)

    postcode_enabled = boolean(
        values, "DATA_ACQUISITION_POSTCODE_ENABLED"
    )
    if postcode_enabled:
        gateway_services.append("postcode-io-gateway")
    return AcquisitionAuthorization(
        run_id=run_id,
        terms_approval_reference=terms_reference,
        provenance_reviewer=reviewer,
        approved_providers=approved,
        gateway_services=tuple(gateway_services),
        postcode_enabled=postcode_enabled,
        retention_days=retention_days,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
    )


def safe_run_directory(root: Path, run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("unsafe acquisition run id")
    resolved_root = root.resolve()
    candidate = resolved_root / run_id
    if candidate.parent != resolved_root:
        raise ValueError("acquisition output escaped the quarantine root")
    return candidate


def create_audit_manifest(
    root: Path,
    authorization: AcquisitionAuthorization,
    now: datetime | None = None,
) -> Path:
    created_at = now or datetime.now(UTC)
    if root.is_symlink():
        raise ValueError("the quarantine root must not be a symbolic link")
    root.mkdir(parents=True, exist_ok=True)
    run_directory = safe_run_directory(root, authorization.run_id)
    run_directory.mkdir(mode=0o700)
    manifest = {
        "schemaVersion": 1,
        "runId": authorization.run_id,
        "status": "AUTHORIZED",
        "createdAt": created_at.isoformat(),
        "retainUntil": (
            created_at + timedelta(days=authorization.retention_days)
        ).isoformat(),
        "termsApprovalReference": authorization.terms_approval_reference,
        "provenanceReviewer": authorization.provenance_reviewer,
        "approvedProviders": list(authorization.approved_providers),
        "postcodeEnrichmentEnabled": authorization.postcode_enabled,
        "datasetId": authorization.dataset_id,
        "datasetVersion": authorization.dataset_version,
        "classification": "LIVE_ACQUISITION_QUARANTINED",
        "runtimeEligible": False,
        "redistributionApproved": False,
    }
    path = run_directory / "infrastructure-acquisition-audit.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def update_audit_manifest(path: Path, status: str) -> None:
    if status not in {"RUNNING", "COMPLETED", "FAILED", "TEARDOWN_FAILED"}:
        raise ValueError("unsupported acquisition audit status")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = status
    manifest["updatedAt"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
