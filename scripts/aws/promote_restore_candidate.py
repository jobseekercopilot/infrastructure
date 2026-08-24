#!/usr/bin/env python3
"""Promote a digest-verified restore candidate without rebuilding any image."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class PromotionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"unsafe promotion input: {path}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, f"duplicate input key: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(value, dict), f"promotion input must be an object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_timestamp(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError("promoted-at must be an ISO-8601 UTC timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0), "promoted-at must be UTC")
    require(parsed <= dt.datetime.now(dt.timezone.utc), "promoted-at cannot be in the future")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-image-manifest", type=Path, required=True)
    parser.add_argument("--candidate-provenance", type=Path, required=True)
    parser.add_argument("--approval-manifest", type=Path, required=True)
    parser.add_argument("--candidate-build-run-id", required=True)
    parser.add_argument("--promoted-at", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest_path = args.candidate_image_manifest.resolve()
        provenance_path = args.candidate_provenance.resolve()
        approval_path = args.approval_manifest.resolve()
        manifest = load(manifest_path)
        provenance = load(provenance_path)
        load(approval_path)

        require(re.fullmatch(r"[0-9]+", args.candidate_build_run_id) is not None,
                "candidate build run ID must be numeric")
        release_id = manifest.get("releaseId")
        require(
            isinstance(release_id, str)
            and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}", release_id) is not None,
            "candidate release ID is malformed",
        )
        require(manifest.get("sourceBranch") == "main", "candidate manifest is not protected-main bound")
        require(provenance.get("releaseId") == release_id, "candidate provenance release ID mismatch")
        require(provenance.get("buildPurpose") == "restore-candidate",
                "only a restore-candidate provenance may be promoted")
        require("promotedFrom" not in provenance and "promotedAt" not in provenance,
                "candidate provenance already claims promotion")
        candidate_manifest_sha = sha256(manifest_path)
        require(provenance.get("imageManifestSha256") == candidate_manifest_sha,
                "candidate provenance does not bind the candidate manifest")
        require(provenance.get("launchApprovalManifestSha256") == manifest.get("launchApprovalManifestSha256"),
                "candidate approval bindings are incoherent")
        require(
            re.fullmatch(r"[0-9a-f]{40}", str(provenance.get("infrastructureRevision", ""))) is not None,
            "candidate Infrastructure revision is not pinned",
        )

        approval_sha = sha256(approval_path)
        promoted_manifest = dict(manifest)
        promoted_manifest["launchApprovalManifestSha256"] = approval_sha
        promoted_manifest_bytes = canonical(promoted_manifest)
        promoted_manifest_sha = hashlib.sha256(promoted_manifest_bytes).hexdigest()

        promoted_provenance = dict(provenance)
        promoted_provenance.update({
            "imageManifestSha256": promoted_manifest_sha,
            "launchApprovalManifestSha256": approval_sha,
            "buildPurpose": "release",
            "promotedFrom": {
                "buildPurpose": "restore-candidate",
                "buildRunId": args.candidate_build_run_id,
                "imageManifestSha256": candidate_manifest_sha,
            },
            "promotedAt": utc_timestamp(args.promoted_at),
        })

        output = args.output_directory.resolve()
        require(not output.exists() and not output.is_symlink(), "refusing to overwrite promotion output")
        output.mkdir(parents=True, mode=0o700)
        for name, content in (
            ("image-manifest.json", promoted_manifest_bytes),
            ("provenance.json", canonical(promoted_provenance)),
        ):
            path = output / name
            path.write_bytes(content)
            path.chmod(0o600)
    except (OSError, ValueError, json.JSONDecodeError, PromotionError) as exc:
        print(f"restore candidate promotion refused: {exc}", file=sys.stderr)
        return 2

    print("restore candidate promoted without rebuilding images or calling AWS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
