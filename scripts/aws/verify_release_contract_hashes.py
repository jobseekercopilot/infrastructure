#!/usr/bin/env python3
"""Bind manifest contract attestations to bytes exported by exact locked checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class ContractHashError(ValueError):
    pass


# JSON path in image-manifest.json -> exact file produced/owned by the locked
# checkout.  Generated targets are intentionally checked only after the full
# repository export/build gate has completed.
CONTRACT_FILES: dict[tuple[str, ...], Path] = {
    ("dependencyEvidence", "documentStorePermanentErasure", "openApiSha256"):
        Path("document-store-service/contracts/openapi.json"),
    ("dependencyEvidence", "postcodesNorthernIrelandCoverageChain", "postcodeIoGateway", "openApiSha256"):
        Path("postcode-io-gateway/target/openapi.json"),
    ("dependencyEvidence", "postcodesNorthernIrelandCoverageChain", "locationService", "openApiSha256"):
        Path("location-service/api/openapi.yaml"),
    ("dependencyEvidence", "postcodesNorthernIrelandCoverageChain", "locationGateway", "openApiSha256"):
        Path("location-gateway/target/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "authenticationService", "openApiSha256"):
        Path("authentication-service/contracts/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "userManagementGateway", "openApiSha256"):
        Path("user-management-gateway/target/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "userManagementGateway", "authSnapshotSha256"):
        Path("user-management-gateway/src/main/openapi/authentication-service.yaml"),
    ("dependencyEvidence", "paymentV2ProductionContract", "documentGenerationGateway", "openApiSha256"):
        Path("document-generation-gateway/contracts/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "paymentService", "openApiSha256"):
        Path("payment-service/contracts/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "paymentGateway", "openApiSha256"):
        Path("payment-gateway/contracts/openapi.json"),
    ("dependencyEvidence", "paymentV2ProductionContract", "stripeGateway", "openApiSha256"):
        Path("stripe-gateway/contracts/openapi.json"),
}


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractHashError(f"duplicate manifest key: {key}")
        value[key] = item
    return value


def nested_value(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for component in path:
        if not isinstance(value, dict) or component not in value:
            raise ContractHashError(f"manifest contract path is missing: {'.'.join(path)}")
        value = value[component]
    return value


def find_named_hash_paths(value: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key == "openApiSha256":
                found.add(child_path)
            found.update(find_named_hash_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(find_named_hash_paths(child, (*path, str(index))))
    return found


def verify_hashes(workspace_root: Path, manifest: dict[str, Any]) -> None:
    mapped_openapi = {path for path in CONTRACT_FILES if path[-1] == "openApiSha256"}
    actual_openapi = find_named_hash_paths(manifest)
    if actual_openapi != mapped_openapi:
        missing = sorted(".".join(path) for path in actual_openapi - mapped_openapi)
        stale = sorted(".".join(path) for path in mapped_openapi - actual_openapi)
        raise ContractHashError(
            f"every manifest openApiSha256 needs an exact locked-checkout mapping; unmapped={missing}, absent={stale}"
        )

    for manifest_path, relative_file in CONTRACT_FILES.items():
        expected = str(nested_value(manifest, manifest_path))
        source = workspace_root / relative_file
        if not source.is_file() or source.is_symlink():
            raise ContractHashError(f"contract export is missing or unsafe: {relative_file}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise ContractHashError(
                f"locked contract hash differs for {relative_file}: manifest={expected}, exact-checkout={actual}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(
            args.image_manifest.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
        if not isinstance(manifest, dict):
            raise ContractHashError("image manifest root must be an object")
        verify_hashes(args.workspace_root.resolve(), manifest)
    except (OSError, json.JSONDecodeError, ContractHashError) as exc:
        print(f"Contract hash verification failed: {exc}", file=sys.stderr)
        return 3
    print(f"Verified {len(CONTRACT_FILES)} exact locked-checkout contract hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
