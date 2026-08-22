#!/usr/bin/env python3
"""Validate contract/package lock structure and optional local producer sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.contracts.lock import load_contract_lock, verify_checkout
from scripts.lib.project_paths import CONTRACT_LOCK


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the versioned API contract and generated-client lock."
    )
    parser.add_argument("--lock", type=Path, default=CONTRACT_LOCK)
    parser.add_argument(
        "--verify-checkouts",
        type=Path,
        metavar="WORKSPACE",
        help="also verify every contract at its exact revision in local producer checkouts",
    )
    args = parser.parse_args()

    try:
        lock = load_contract_lock(args.lock)
        if args.verify_checkouts is not None:
            for contract in lock["contracts"]:
                verify_checkout(contract, args.verify_checkouts.resolve())
    except (OSError, ValueError) as error:
        print(f"Contract lock policy failed: {error}", file=sys.stderr)
        return 1

    package_count = sum("javaPackage" in contract for contract in lock["contracts"])
    print(
        "Contract lock policy passed: "
        f"{len(lock['contracts'])} contract(s), {package_count} Java package(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
