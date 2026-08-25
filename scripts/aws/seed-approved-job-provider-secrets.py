#!/usr/bin/env python3
"""Seed approved public-beta job-provider credentials without exposing values."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence


REGION = "eu-west-2"
ENVIRONMENT = "public-beta"
CONFIRMATION = "SEED APPROVED JOB PROVIDER SECRETS public-beta"
PROVIDER_FIELDS = {
    "reed": {"api_key": "REED_API_KEY"},
    "adzuna": {
        "app_id": "ADZUNA_APP_ID",
        "app_key": "ADZUNA_APP_KEY",
    },
    "jsearch": {"api_key": "JSEARCH_API_KEY"},
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", maxsplit=1)
        values[name.strip()] = value.strip()
    return values


def provider_payloads(path: Path) -> dict[str, dict[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("provider secret input must be an existing regular file, not a symlink")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError(f"provider secret input must have mode 0600, found {mode:04o}")

    values = parse_env_file(path)
    payloads: dict[str, dict[str, str]] = {}
    for provider, fields in PROVIDER_FIELDS.items():
        payload: dict[str, str] = {}
        for json_name, environment_name in fields.items():
            value = values.get(environment_name, "")
            if len(value) < 8 or any(character in value for character in "\r\n\0"):
                raise ValueError(
                    f"{environment_name} is missing or fails the minimum credential policy"
                )
            payload[json_name] = value
        payloads[provider] = payload
    return payloads


def run_checked(command: Sequence[str], *, runner: Runner, capture: bool = False) -> str:
    result = runner(
        list(command),
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"provider secret operation failed: {command[0]}")
    return result.stdout if capture else ""


def seed_and_verify(
    path: Path,
    *,
    put_script: Path,
    runner: Runner = subprocess.run,
) -> None:
    payloads = provider_payloads(path)
    if not put_script.is_file():
        raise ValueError(f"external-secret writer is missing: {put_script}")

    with tempfile.TemporaryDirectory(prefix="jsc-approved-provider-secrets.") as directory:
        temporary_root = Path(directory)
        temporary_root.chmod(0o700)
        inputs: dict[str, Path] = {}
        for provider, payload in payloads.items():
            input_path = temporary_root / f"{provider}.json"
            input_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            input_path.chmod(0o600)
            inputs[provider] = input_path

        for provider, input_path in inputs.items():
            run_checked(
                [str(put_script), provider, str(input_path)],
                runner=runner,
            )

        for provider, expected_payload in payloads.items():
            secret_id = f"jsc-{ENVIRONMENT}/integration/{provider}"
            version_output = run_checked(
                [
                    "aws",
                    "secretsmanager",
                    "list-secret-version-ids",
                    "--region",
                    REGION,
                    "--secret-id",
                    secret_id,
                    "--query",
                    "length(Versions[?contains(VersionStages, `AWSCURRENT`)])",
                    "--output",
                    "text",
                ],
                runner=runner,
                capture=True,
            )
            if version_output.strip() != "1":
                raise RuntimeError(f"{provider} secret has no unique AWSCURRENT version")

            secret_output = run_checked(
                [
                    "aws",
                    "secretsmanager",
                    "get-secret-value",
                    "--region",
                    REGION,
                    "--secret-id",
                    secret_id,
                    "--query",
                    "SecretString",
                    "--output",
                    "text",
                ],
                runner=runner,
                capture=True,
            )
            try:
                stored_payload = json.loads(secret_output)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"{provider} secret schema is not valid JSON") from error
            if stored_payload != expected_payload:
                raise RuntimeError(f"{provider} secret schema verification failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-env-file", required=True, type=Path)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the local owner-only input without making AWS calls",
    )
    args = parser.parse_args()

    if args.confirmation != CONFIRMATION:
        print(f"ERROR: confirmation must equal {CONFIRMATION!r}", file=sys.stderr)
        return 2
    try:
        provider_payloads(args.secrets_env_file)
        if args.validate_only:
            print(
                "Approved provider secret input is valid for Reed, Adzuna and JSearch. "
                "Values were not printed."
            )
            return 0
        seed_and_verify(
            args.secrets_env_file,
            put_script=Path(__file__).with_name("put-external-secret.sh"),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        "Stored and schema-verified AWSCURRENT credentials for Reed, Adzuna and "
        "JSearch. Values were not printed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
