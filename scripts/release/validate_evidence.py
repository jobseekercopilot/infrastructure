#!/usr/bin/env python3
"""Validate a release evidence manifest and all referenced local evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.evidence import (
    DEFAULT_POLICY,
    load_json,
    validate_release_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless a release has complete, current evidence."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--evidence-root",
        required=True,
        type=Path,
        help="directory containing immutable reports referenced by the manifest",
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    try:
        manifest = load_json(args.manifest)
        policy = load_json(args.policy)
        validate_release_evidence(manifest, args.evidence_root, policy)
    except (OSError, ValueError) as error:
        print(f"Release evidence policy failed: {error}", file=sys.stderr)
        return 1

    print(
        "Release evidence policy passed: "
        f"{len(manifest['artifacts'])} artifact(s), release {manifest['releaseId']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
