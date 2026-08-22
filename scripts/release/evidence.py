"""Validate the auditable evidence chain for a Job Seeker Copilot release."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "release-policy.json"

SHA256 = re.compile(r"^[a-f0-9]{64}$")
REVISION = re.compile(r"^[a-f0-9]{40}$")
ARTIFACT_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
REPOSITORY = re.compile(
    r"^https://github\.com/jobseekercopilot/[A-Za-z0-9._-]+$"
)
ARTIFACT_TYPES = {
    "container-image",
    "java-package",
    "web-bundle",
    "infrastructure",
}
SBOM_FORMATS = {"CycloneDX-1.5", "CycloneDX-1.6", "SPDX-2.3"}
SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected an object")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected an array")
    return value


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: expected a non-empty string")
    return value


def _integer(value: Any, location: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{location}: expected an integer >= {minimum}")
    return value


def _required(value: dict[str, Any], location: str, names: set[str]) -> None:
    missing = sorted(names - value.keys())
    if missing:
        raise ValueError(f"{location}: missing required field(s): {', '.join(missing)}")


def _timestamp(value: Any, location: str) -> datetime:
    timestamp = _text(value, location)
    if not timestamp.endswith("Z"):
        raise ValueError(f"{location}: timestamp must use UTC and end in Z")
    try:
        result = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{location}: invalid timestamp") from error
    if result.tzinfo != timezone.utc:
        raise ValueError(f"{location}: timestamp must use UTC")
    return result


def _sha256(value: Any, location: str) -> str:
    digest = _text(value, location)
    if not SHA256.fullmatch(digest):
        raise ValueError(f"{location}: expected a lower-case SHA-256 digest")
    return digest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_file(
    path_value: Any,
    digest_value: Any,
    evidence_root: Path,
    location: str,
) -> None:
    relative = Path(_text(path_value, f"{location}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{location}.path: must be a safe evidence-relative path")
    evidence_root = evidence_root.resolve()
    candidate = evidence_root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"{location}.path: missing regular evidence file: {relative}")
    resolved = candidate.resolve()
    if evidence_root not in resolved.parents:
        raise ValueError(f"{location}.path: resolves outside the evidence directory")
    expected = _sha256(digest_value, f"{location}.sha256")
    actual = _file_sha256(candidate)
    if actual != expected:
        raise ValueError(f"{location}: evidence checksum mismatch for {relative}")


def _fresh(
    value: Any,
    location: str,
    created_at: datetime,
    now: datetime,
    maximum_age: timedelta,
) -> datetime:
    timestamp = _timestamp(value, location)
    if timestamp > created_at:
        raise ValueError(f"{location}: cannot be newer than the manifest")
    if timestamp > now:
        raise ValueError(f"{location}: cannot be in the future")
    if now - timestamp > maximum_age:
        raise ValueError(f"{location}: evidence is older than policy permits")
    return timestamp


def _findings(
    value: Any,
    location: str,
    finding_kind: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(value, location)):
        item_location = f"{location}[{index}]"
        item = _object(raw, item_location)
        _required(item, item_location, {"id", "component", finding_kind})
        finding_id = _text(item["id"], f"{item_location}.id")
        if finding_id in seen:
            raise ValueError(f"{item_location}.id: finding IDs must be unique")
        seen.add(finding_id)
        component = _text(item["component"], f"{item_location}.component")
        finding_value = _text(item[finding_kind], f"{item_location}.{finding_kind}")
        if finding_kind == "severity" and finding_value not in SEVERITIES:
            raise ValueError(f"{item_location}.severity: unsupported severity")
        findings.append(
            {"id": finding_id, "component": component, finding_kind: finding_value}
        )
    return findings


def _exceptions(
    value: Any,
    location: str,
    finding_ids: set[str],
    created_at: datetime,
    now: datetime,
    maximum_lifetime: timedelta,
) -> set[str]:
    covered: set[str] = set()
    exception_ids: set[str] = set()
    for index, raw in enumerate(_list(value, location)):
        item_location = f"{location}[{index}]"
        item = _object(raw, item_location)
        _required(
            item,
            item_location,
            {
                "id",
                "findingIds",
                "owner",
                "justification",
                "expiresAt",
                "compensatingControl",
            },
        )
        exception_id = _text(item["id"], f"{item_location}.id")
        if exception_id in exception_ids:
            raise ValueError(f"{item_location}.id: exception IDs must be unique")
        exception_ids.add(exception_id)
        for field in ("owner", "justification", "compensatingControl"):
            _text(item[field], f"{item_location}.{field}")
        expires_at = _timestamp(item["expiresAt"], f"{item_location}.expiresAt")
        if expires_at <= now:
            raise ValueError(f"{item_location}.expiresAt: exception is expired")
        if expires_at - created_at > maximum_lifetime:
            raise ValueError(
                f"{item_location}.expiresAt: exceeds the maximum exception lifetime"
            )
        ids = _list(item["findingIds"], f"{item_location}.findingIds")
        if not ids:
            raise ValueError(f"{item_location}.findingIds: must not be empty")
        for finding_index, raw_id in enumerate(ids):
            finding_id = _text(
                raw_id, f"{item_location}.findingIds[{finding_index}]"
            )
            if finding_id not in finding_ids:
                raise ValueError(
                    f"{item_location}.findingIds: unknown finding {finding_id}"
                )
            if finding_id in covered:
                raise ValueError(
                    f"{item_location}.findingIds: {finding_id} has multiple exceptions"
                )
            covered.add(finding_id)
    return covered


def _scan_file(
    scan: dict[str, Any],
    location: str,
    evidence_root: Path,
    created_at: datetime,
    now: datetime,
    maximum_age: timedelta,
) -> None:
    _required(
        scan,
        location,
        {"scanner", "version", "completedAt", "report", "reportSha256"},
    )
    _text(scan["scanner"], f"{location}.scanner")
    _text(scan["version"], f"{location}.version")
    _fresh(
        scan["completedAt"],
        f"{location}.completedAt",
        created_at,
        now,
        maximum_age,
    )
    _evidence_file(
        scan["report"],
        scan["reportSha256"],
        evidence_root,
        location,
    )


def _validate_artifact(
    artifact: dict[str, Any],
    index: int,
    evidence_root: Path,
    policy: dict[str, Any],
    created_at: datetime,
    now: datetime,
) -> None:
    location = f"artifacts[{index}]"
    _required(
        artifact,
        location,
        {
            "name",
            "type",
            "owner",
            "source",
            "builder",
            "artifact",
            "sbom",
            "vulnerabilityScan",
            "licenceScan",
            "provenance",
            "signature",
            "secretScan",
            "exceptions",
        },
    )
    _text(artifact["name"], f"{location}.name")
    _text(artifact["owner"], f"{location}.owner")
    if artifact["type"] not in ARTIFACT_TYPES:
        raise ValueError(f"{location}.type: unsupported artifact type")

    source = _object(artifact["source"], f"{location}.source")
    _required(source, f"{location}.source", {"repository", "revision"})
    repository = _text(source["repository"], f"{location}.source.repository")
    if not REPOSITORY.fullmatch(repository):
        raise ValueError(
            f"{location}.source.repository: must be a jobseekercopilot GitHub URL"
        )
    revision = _text(source["revision"], f"{location}.source.revision")
    if not REVISION.fullmatch(revision):
        raise ValueError(f"{location}.source.revision: must be a full commit SHA")

    builder = _object(artifact["builder"], f"{location}.builder")
    _required(builder, f"{location}.builder", {"name", "version", "invocation"})
    for field in ("name", "version", "invocation"):
        _text(builder[field], f"{location}.builder.{field}")

    built = _object(artifact["artifact"], f"{location}.artifact")
    _required(built, f"{location}.artifact", {"reference", "digest"})
    _text(built["reference"], f"{location}.artifact.reference")
    digest = _text(built["digest"], f"{location}.artifact.digest")
    if not ARTIFACT_DIGEST.fullmatch(digest):
        raise ValueError(f"{location}.artifact.digest: must be sha256-pinned")

    sbom = _object(artifact["sbom"], f"{location}.sbom")
    _required(sbom, f"{location}.sbom", {"format", "path", "sha256"})
    if sbom["format"] not in SBOM_FORMATS:
        raise ValueError(f"{location}.sbom.format: unsupported SBOM format")
    _evidence_file(
        sbom["path"], sbom["sha256"], evidence_root, f"{location}.sbom"
    )

    evidence_policy = _object(policy["evidence"], "policy.evidence")
    maximum_age = timedelta(
        hours=_integer(
            evidence_policy["maximumAgeHours"],
            "policy.evidence.maximumAgeHours",
            1,
        )
    )
    vulnerability = _object(
        artifact["vulnerabilityScan"], f"{location}.vulnerabilityScan"
    )
    _scan_file(
        vulnerability,
        f"{location}.vulnerabilityScan",
        evidence_root,
        created_at,
        now,
        maximum_age,
    )
    _required(
        vulnerability,
        f"{location}.vulnerabilityScan",
        {"databaseUpdatedAt", "findings"},
    )
    database_updated = _fresh(
        vulnerability["databaseUpdatedAt"],
        f"{location}.vulnerabilityScan.databaseUpdatedAt",
        created_at,
        now,
        timedelta(
            hours=_integer(
                policy["vulnerabilities"]["maximumDatabaseAgeHours"],
                "policy.vulnerabilities.maximumDatabaseAgeHours",
                1,
            )
        ),
    )
    completed = _timestamp(
        vulnerability["completedAt"],
        f"{location}.vulnerabilityScan.completedAt",
    )
    if database_updated > completed:
        raise ValueError(
            f"{location}.vulnerabilityScan.databaseUpdatedAt: "
            "database cannot be newer than the scan"
        )
    vulnerability_findings = _findings(
        vulnerability["findings"],
        f"{location}.vulnerabilityScan.findings",
        "severity",
    )

    licence = _object(artifact["licenceScan"], f"{location}.licenceScan")
    _scan_file(
        licence,
        f"{location}.licenceScan",
        evidence_root,
        created_at,
        now,
        maximum_age,
    )
    _required(licence, f"{location}.licenceScan", {"findings"})
    licence_findings = _findings(
        licence["findings"], f"{location}.licenceScan.findings", "spdxId"
    )

    provenance = _object(artifact["provenance"], f"{location}.provenance")
    _required(
        provenance, f"{location}.provenance", {"predicateType", "path", "sha256"}
    )
    _text(provenance["predicateType"], f"{location}.provenance.predicateType")
    _evidence_file(
        provenance["path"],
        provenance["sha256"],
        evidence_root,
        f"{location}.provenance",
    )

    signature = _object(artifact["signature"], f"{location}.signature")
    _required(
        signature,
        f"{location}.signature",
        {"scheme", "identity", "issuer", "verification", "verificationSha256"},
    )
    for field in ("scheme", "identity", "issuer"):
        _text(signature[field], f"{location}.signature.{field}")
    _evidence_file(
        signature["verification"],
        signature["verificationSha256"],
        evidence_root,
        f"{location}.signature",
    )

    secret = _object(artifact["secretScan"], f"{location}.secretScan")
    _scan_file(
        secret,
        f"{location}.secretScan",
        evidence_root,
        created_at,
        now,
        maximum_age,
    )
    _required(
        secret,
        f"{location}.secretScan",
        {"scope", "commitsScanned", "bytesScanned"},
    )
    secret_policy = _object(policy["secretScan"], "policy.secretScan")
    if secret["scope"] != secret_policy["requiredScope"]:
        raise ValueError(
            f"{location}.secretScan.scope: incomplete history coverage"
        )
    _integer(
        secret["commitsScanned"],
        f"{location}.secretScan.commitsScanned",
        _integer(
            secret_policy["minimumCommitsScanned"],
            "policy.secretScan.minimumCommitsScanned",
            1,
        ),
    )
    _integer(
        secret["bytesScanned"],
        f"{location}.secretScan.bytesScanned",
        _integer(
            secret_policy["minimumBytesScanned"],
            "policy.secretScan.minimumBytesScanned",
            1,
        ),
    )

    all_findings = vulnerability_findings + licence_findings
    all_ids = {finding["id"] for finding in all_findings}
    if len(all_ids) != len(all_findings):
        raise ValueError(f"{location}: finding IDs must be unique across all scans")
    covered = _exceptions(
        artifact["exceptions"],
        f"{location}.exceptions",
        all_ids,
        created_at,
        now,
        timedelta(
            days=_integer(
                policy["exceptions"]["maximumLifetimeDays"],
                "policy.exceptions.maximumLifetimeDays",
                1,
            )
        ),
    )
    blocked_severities = set(policy["vulnerabilities"]["blockedSeverities"])
    prohibited_licences = set(policy["licences"]["prohibitedSpdxIds"])
    review_licences = set(policy["licences"]["reviewRequiredValues"])
    blocked = {
        finding["id"]
        for finding in vulnerability_findings
        if finding["severity"] in blocked_severities
    }
    blocked.update(
        finding["id"]
        for finding in licence_findings
        if finding["spdxId"] in prohibited_licences
        or finding["spdxId"] in review_licences
    )
    uncovered = sorted(blocked - covered)
    if uncovered:
        raise ValueError(
            f"{location}: blocked finding(s) lack an active exception: "
            + ", ".join(uncovered)
        )


def validate_release_evidence(
    manifest: dict[str, Any],
    evidence_root: Path,
    policy: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Raise ValueError when a release manifest does not satisfy policy."""

    if policy.get("schemaVersion") != 1:
        raise ValueError("policy.schemaVersion: only version 1 is supported")
    if manifest.get("schemaVersion") != 1:
        raise ValueError("schemaVersion: only version 1 is supported")
    _required(manifest, "manifest", {"releaseId", "createdAt", "artifacts"})
    _text(manifest["releaseId"], "releaseId")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo != timezone.utc:
        raise ValueError("validation time must use UTC")
    created_at = _timestamp(manifest["createdAt"], "createdAt")
    if created_at > current_time:
        raise ValueError("createdAt: release manifest cannot be in the future")
    artifacts = _list(manifest["artifacts"], "artifacts")
    if not artifacts:
        raise ValueError("artifacts: at least one released artifact is required")
    names: set[str] = set()
    references: set[str] = set()
    for index, raw in enumerate(artifacts):
        artifact = _object(raw, f"artifacts[{index}]")
        _validate_artifact(
            artifact,
            index,
            evidence_root,
            policy,
            created_at,
            current_time,
        )
        name = artifact["name"]
        reference = artifact["artifact"]["reference"]
        if name in names:
            raise ValueError(f"artifacts[{index}].name: artifact names must be unique")
        if reference in references:
            raise ValueError(
                f"artifacts[{index}].artifact.reference: references must be unique"
            )
        names.add(name)
        references.add(reference)
