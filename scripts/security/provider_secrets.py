#!/usr/bin/env python3
"""Validate the workspace-root job-provider credential store without revealing values."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

INFRASTRUCTURE_ROOT = Path(__file__).resolve().parents[2]
if str(INFRASTRUCTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(INFRASTRUCTURE_ROOT))

from scripts.workspace.catalog import WORKSPACE_ROOT


SECRET_FILE = WORKSPACE_ROOT / "config" / ".secrets.env"
PROVIDER_VARIABLES = {
    "GOOGLE": ("GOOGLE_MAPS_API_KEY",),
    "REED": ("REED_API_KEY",),
    "ADZUNA": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
    "JSEARCH": ("JSEARCH_API_KEY",),
    "OPENAI": (
        "OPENAI_API_KEY",
        "OPENAI_ENDPOINT",
        "OPENAI_DATA_REGION",
        "OPENAI_DATA_CONTROL_MODE",
        "OPENAI_DATA_SHARING_MODE",
        "OPENAI_PRIVACY_DECISION_ID",
        "OPENAI_PRIVACY_OWNER",
        "OPENAI_PRIVACY_REVIEW_ON",
    ),
}


def parse_secret_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def validate_store(
    providers: tuple[str, ...],
    path: Path = SECRET_FILE,
) -> list[str]:
    failures: list[str] = []
    expected_path = SECRET_FILE.resolve()
    if path.resolve() != expected_path:
        return [f"provider secret store must be {expected_path}"]
    if not path.is_file():
        return [f"provider secret store is missing: {expected_path}"]
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        failures.append(
            f"provider secret store must have mode 0600, found {mode:04o}"
        )
    values = parse_secret_file(path)
    for provider in providers:
        for name in PROVIDER_VARIABLES[provider]:
            if not values.get(name):
                suffix = (
                    " — REPLACEMENT REQUIRED"
                    if name == "REED_API_KEY"
                    else ""
                )
                failures.append(f"{name} is MISSING{suffix}")
    return failures


def secret_files_inside_repositories(
    workspace: Path = WORKSPACE_ROOT,
) -> list[Path]:
    findings: list[Path] = []
    ignored_directories = {".git", "node_modules", "target", ".cache"}
    sensitive_names = {
        name
        for names in PROVIDER_VARIABLES.values()
        for name in names
    }
    for repository in workspace.iterdir():
        if not repository.is_dir() or not (repository / ".git").exists():
            continue
        for root, directories, filenames in os.walk(repository):
            directories[:] = [
                name for name in directories if name not in ignored_directories
            ]
            for filename in filenames:
                if not (
                    filename == ".secrets.env"
                    or filename == ".env"
                    or filename.startswith(".env.")
                ):
                    continue
                path = Path(root) / filename
                if filename.endswith(".example"):
                    continue
                try:
                    values = parse_secret_file(path)
                except (OSError, UnicodeError):
                    continue
                if any(values.get(name) for name in sensitive_names):
                    findings.append(path)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=sorted(PROVIDER_VARIABLES),
        default=sorted(PROVIDER_VARIABLES),
    )
    parser.add_argument(
        "--check-repositories",
        action="store_true",
        help="reject provider credential files located inside sibling Git repositories",
    )
    args = parser.parse_args()
    failures = validate_store(tuple(args.providers))
    if args.check_repositories:
        for path in secret_files_inside_repositories():
            failures.append(
                f"real provider credentials are forbidden inside Git repository: "
                f"{path.relative_to(WORKSPACE_ROOT)}"
            )
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print(
        "Provider secret store validation passed for: "
        + ", ".join(args.providers)
        + ". Values were not printed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
