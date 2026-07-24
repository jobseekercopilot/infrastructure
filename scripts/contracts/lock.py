"""Load and validate the Infrastructure contract/package lock."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from scripts.lib.project_paths import CONTRACT_LOCK


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
PACKAGE_STATES = {"pilot", "published", "retired"}


def load_contract_lock(path: Path = CONTRACT_LOCK) -> dict:
    with path.open(encoding="utf-8") as handle:
        lock = json.load(handle)
    validate_contract_lock(lock)
    return lock


def _required_string(item: dict, field: str, context: str, errors: list[str]) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        errors.append(f"{context}.{field} must be a non-empty string")
        return ""
    return value


def _validate_relative_path(value: str, context: str, errors: list[str]) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        errors.append(f"{context}.path must be a normalised repository-relative path")


def _validate_java_package(
    package: dict,
    contract: dict,
    generators: dict,
    context: str,
    errors: list[str],
) -> None:
    if not isinstance(package, dict):
        errors.append(f"{context}.javaPackage must be an object")
        return

    group_id = _required_string(package, "groupId", f"{context}.javaPackage", errors)
    artifact_id = _required_string(package, "artifactId", f"{context}.javaPackage", errors)
    version = _required_string(package, "version", f"{context}.javaPackage", errors)
    generator = _required_string(package, "generator", f"{context}.javaPackage", errors)
    state = _required_string(package, "releaseState", f"{context}.javaPackage", errors)

    expected_version = (
        f"{contract.get('contractVersion', '')}-rev."
        f"{contract.get('revision', '')[:12]}"
    )
    if group_id != "com.jobseekercopilot.clients":
        errors.append(f"{context}.javaPackage.groupId must be com.jobseekercopilot.clients")
    if artifact_id != f"{contract.get('service', '')}-client":
        errors.append(f"{context}.javaPackage.artifactId must match the producer service")
    if version != expected_version:
        errors.append(
            f"{context}.javaPackage.version must be the contract version plus "
            "the first 12 source revision characters"
        )
    if generator not in generators:
        errors.append(f"{context}.javaPackage.generator is not declared")
    if state not in PACKAGE_STATES:
        errors.append(
            f"{context}.javaPackage.releaseState must be one of "
            f"{', '.join(sorted(PACKAGE_STATES))}"
        )


def validate_contract_lock(lock: dict) -> None:
    errors: list[str] = []
    if lock.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    owner = _required_string(lock, "owner", "lock", errors)
    registry = lock.get("registry")
    if not isinstance(registry, dict):
        errors.append("registry must be an object")
    else:
        if registry.get("type") != "github-packages":
            errors.append("registry.type must be github-packages")
        expected_registry = f"https://maven.pkg.github.com/{owner}"
        if registry.get("mavenBaseUrl") != expected_registry:
            errors.append(f"registry.mavenBaseUrl must be {expected_registry}")

    generators = lock.get("generators")
    if not isinstance(generators, dict) or not generators:
        errors.append("generators must be a non-empty object")
        generators = {}
    for name, generator in generators.items():
        context = f"generators.{name}"
        if not isinstance(generator, dict):
            errors.append(f"{context} must be an object")
            continue
        _required_string(generator, "name", context, errors)
        _required_string(generator, "version", context, errors)
        _required_string(generator, "library", context, errors)

    contracts = lock.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        errors.append("contracts must be a non-empty array")
        contracts = []

    seen_services: set[str] = set()
    seen_coordinates: set[tuple[str, str, str]] = set()
    for index, contract in enumerate(contracts):
        context = f"contracts[{index}]"
        if not isinstance(contract, dict):
            errors.append(f"{context} must be an object")
            continue

        service = _required_string(contract, "service", context, errors)
        repository = _required_string(contract, "repository", context, errors)
        revision = _required_string(contract, "revision", context, errors)
        path = _required_string(contract, "path", context, errors)
        contract_version = _required_string(contract, "contractVersion", context, errors)
        digest = _required_string(contract, "sha256", context, errors)

        if service in seen_services:
            errors.append(f"{context}.service is duplicated: {service}")
        seen_services.add(service)
        if repository != f"{owner}/{service}":
            errors.append(f"{context}.repository must be {owner}/{service}")
        if not SHA_PATTERN.fullmatch(revision):
            errors.append(f"{context}.revision must be a full lowercase Git SHA")
        if path:
            _validate_relative_path(path, context, errors)
        if not SEMVER_PATTERN.fullmatch(contract_version):
            errors.append(f"{context}.contractVersion must be strict semantic versioning")
        if not SHA256_PATTERN.fullmatch(digest):
            errors.append(f"{context}.sha256 must be a lowercase SHA-256 digest")

        consumers = contract.get("consumers")
        if (
            not isinstance(consumers, list)
            or not consumers
            or any(not isinstance(consumer, str) or not consumer for consumer in consumers)
            or len(consumers) != len(set(consumers))
        ):
            errors.append(f"{context}.consumers must be a non-empty unique string array")

        package = contract.get("javaPackage")
        if package is not None:
            _validate_java_package(package, contract, generators, context, errors)
            if isinstance(package, dict):
                coordinates = (
                    package.get("groupId", ""),
                    package.get("artifactId", ""),
                    package.get("version", ""),
                )
                if coordinates in seen_coordinates:
                    errors.append(f"{context}.javaPackage coordinates are duplicated")
                seen_coordinates.add(coordinates)

    if errors:
        raise ValueError("Invalid contract lock:\n- " + "\n- ".join(errors))


def verify_checkout(contract: dict, workspace_root: Path) -> None:
    checkout = workspace_root / contract["service"]
    if not checkout.is_dir():
        raise ValueError(f"missing producer checkout: {checkout}")

    result = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "show",
            f"{contract['revision']}:{contract['path']}",
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"{contract['service']}: cannot read locked source "
            f"{contract['revision']}:{contract['path']}: {message}"
        )

    digest = hashlib.sha256(result.stdout).hexdigest()
    if digest != contract["sha256"]:
        raise ValueError(
            f"{contract['service']}: locked source digest is {digest}, "
            f"expected {contract['sha256']}"
        )
