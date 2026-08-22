#!/usr/bin/env python3
"""Build a deterministic, non-deployed landing release artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Any


ENVIRONMENT_KEYS = {
    "ACCOUNT_DELETION_COMPLETION_DAYS",
    "ANALYTICS_ENDPOINT_URL",
    "ANTI_BOT_PROVIDER",
    "ANTI_BOT_SITE_KEY",
    "BUSINESS_ADDRESS",
    "CONTACT_API_URL",
    "CONTACT_MESSAGE_MAX_LENGTH",
    "CONSENT_VERSION",
    "COPYRIGHT_NOTICE",
    "DOCUMENT_DELETION_COMPLETION_DAYS",
    "ENABLE_ANALYTICS",
    "ENABLE_LIVE_SUBMISSIONS",
    "ENABLE_SEARCH_INDEXING",
    "FINANCIAL_RECORD_RETENTION_YEARS",
    "ICO_REGISTRATION_REFERENCE",
    "ICO_REGISTRATION_STATUS",
    "LEGAL_DOCUMENTS_REVIEWED",
    "LEGAL_EFFECTIVE_DATE",
    "LEGAL_ENTITY_NAME",
    "LEGAL_ENTITY_TYPE",
    "LEGAL_VERSION",
    "MAIN_APPLICATION_URL",
    "MINIMUM_FORM_COMPLETION_MS",
    "PRICING_URL",
    "PRIVACY_EMAIL",
    "PRIVACY_POLICY_URL",
    "PUBLIC_BETA_ENABLED",
    "PUBLIC_ENVIRONMENT_NAME",
    "PUBLIC_WEBSITE_URL",
    "REGISTRATION_URL",
    "SECURITY_LOG_RETENTION_DAYS",
    "SIGN_IN_URL",
    "SUPPORT_EMAIL",
    "SUPPORT_RECORD_RETENTION_DAYS",
    "SUPPORT_URL",
    "TAX_STATUS",
    "TERMS_URL",
    "TRADING_NAME",
    "WAITLIST_API_URL",
    "WAITLIST_CONFIRMATION_API_URL",
    "WAITLIST_RESEND_API_URL",
    "WAITLIST_UNSUBSCRIBE_API_URL",
}
BOOLEAN_KEYS = {
    "ENABLE_ANALYTICS",
    "ENABLE_LIVE_SUBMISSIONS",
    "ENABLE_SEARCH_INDEXING",
    "LEGAL_DOCUMENTS_REVIEWED",
    "PUBLIC_BETA_ENABLED",
}
SELECTED_SAM_TEMPLATE = Path("infrastructure/waitlist-backend/template.yaml")
CONTRACT_PATH = Path("docs/launch/release-artifact-contract.md")
STATIC_DIRECTORY = Path("dist/job-seeker-copilot-landing/browser")
RUNTIME_CONFIG_PATH = Path("config/app-config.json")


class ReleaseInputError(RuntimeError):
    pass


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = item
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], checkout: Path, environment: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=checkout, env=environment, check=True)


def create_deterministic_tar(source: Path, target: Path) -> None:
    entries = sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix())
    if not entries:
        raise ReleaseInputError("landing build produced an empty static artifact")
    with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in entries:
            relative = entry.relative_to(source).as_posix()
            status = entry.lstat()
            if stat.S_ISLNK(status.st_mode) or not (entry.is_dir() or entry.is_file()):
                raise ReleaseInputError(f"unsupported landing artifact entry: {relative}")
            info = tarfile.TarInfo(relative + ("/" if entry.is_dir() else ""))
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.mode = stat.S_IMODE(status.st_mode)
            if entry.is_dir():
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = status.st_size
                with entry.open("rb") as handle:
                    archive.addfile(info, handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--runtime-environment", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    args = parser.parse_args()

    checkout = args.checkout.resolve()
    if not (checkout / ".git").exists():
        raise ReleaseInputError("landing checkout is missing")
    if not all(character in "0123456789abcdef" for character in args.expected_revision) or len(args.expected_revision) != 40:
        raise ReleaseInputError("landing revision must be an exact 40-character commit")
    if not all(character in "0123456789abcdef" for character in args.expected_contract_sha256) or len(args.expected_contract_sha256) != 64:
        raise ReleaseInputError("landing artifact-contract checksum must be an exact SHA-256")

    actual_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    if actual_revision != args.expected_revision:
        raise ReleaseInputError("landing checkout does not match its reviewed release revision")
    if subprocess.run(["git", "status", "--porcelain"], cwd=checkout, check=True, capture_output=True, text=True).stdout:
        raise ReleaseInputError("landing checkout must be clean before its release build")

    contract = checkout / CONTRACT_PATH
    if sha256(contract) != args.expected_contract_sha256:
        raise ReleaseInputError("landing artifact-contract checksum differs from reviewed evidence")

    try:
        environment_input = json.loads(
            args.runtime_environment.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseInputError(f"invalid landing runtime-environment JSON: {exc}") from exc
    if not isinstance(environment_input, dict) or set(environment_input) != ENVIRONMENT_KEYS:
        missing = sorted(ENVIRONMENT_KEYS - set(environment_input) if isinstance(environment_input, dict) else ENVIRONMENT_KEYS)
        extra = sorted(set(environment_input) - ENVIRONMENT_KEYS if isinstance(environment_input, dict) else set())
        raise ReleaseInputError(f"landing runtime environment must have the exact reviewed keys; missing={missing}, extra={extra}")
    if not all(isinstance(value, str) and "\x00" not in value for value in environment_input.values()):
        raise ReleaseInputError("landing runtime environment values must be NUL-free strings")
    if any(environment_input[key] not in {"true", "false"} for key in BOOLEAN_KEYS):
        raise ReleaseInputError("landing release switches must be explicit true/false strings")
    if environment_input["PUBLIC_ENVIRONMENT_NAME"] != "production":
        raise ReleaseInputError("landing release artifact must use the production environment class")
    if environment_input["PUBLIC_WEBSITE_URL"] != "https://www.jobseekercopilot.com":
        raise ReleaseInputError("landing release artifact must use the canonical public origin")

    build_environment = os.environ.copy()
    build_environment.update(environment_input)
    build_environment["AWS_BRANCH"] = "main"
    # This central step produces evidence only. Even if a runner/environment
    # accidentally defines the legacy Amplify publication switch, never pass
    # that authority into Landing repository code.
    build_environment.pop("AMPLIFY_RELEASE_AUTHORISED", None)
    build_environment.pop("RUNTIME_CONFIG_OUTPUT_PATH", None)
    build_environment.pop("SEO_PUBLIC_OUTPUT_DIR", None)

    run(["npm", "ci"], checkout)
    run(["npm", "run", "lint"], checkout)
    run(["npm", "test"], checkout)
    run(["npm", "run", "config:generate"], checkout, build_environment)
    run(["npm", "run", "build"], checkout, build_environment)
    run(["npm", "run", "security:artifacts"], checkout, build_environment)

    static_directory = checkout / STATIC_DIRECTORY
    runtime_config = static_directory / RUNTIME_CONFIG_PATH
    selected_sam_template = checkout / SELECTED_SAM_TEMPLATE
    if not static_directory.is_dir() or not runtime_config.is_file() or not selected_sam_template.is_file():
        raise ReleaseInputError("landing build omitted its static directory, runtime config or selected SAM template")

    args.output_directory.mkdir(parents=True, exist_ok=True)
    artifact = args.output_directory / "landing-static.tar"
    sam_artifact = args.output_directory / "landing-waitlist-backend-template.yaml"
    create_deterministic_tar(static_directory, artifact)
    shutil.copyfile(selected_sam_template, sam_artifact)
    metadata = {
        "schemaVersion": 1,
        "repository": "jobseekercopilot/job-seeker-copilot-landing",
        "revision": actual_revision,
        "artifactContractSha256": sha256(contract),
        "staticArtifactSha256": sha256(artifact),
        "runtimeConfigSha256": sha256(runtime_config),
        "selectedSamTemplate": SELECTED_SAM_TEMPLATE.as_posix(),
        "selectedSamTemplateSha256": sha256(selected_sam_template),
        "deploymentStatus": "NOT_DEPLOYED",
    }
    (args.output_directory / "landing-artifact.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for output in (artifact, sam_artifact, args.output_directory / "landing-artifact.json"):
        output.chmod(0o444)
    print(f"Built deterministic, non-deployed landing artifact: {artifact}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseInputError, subprocess.CalledProcessError) as exc:
        print(f"landing release build refused: {exc}", file=os.sys.stderr)
        raise SystemExit(3) from exc
