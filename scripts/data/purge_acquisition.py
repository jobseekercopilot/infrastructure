#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.acquisition_policy import REVIEWER, safe_run_directory
from scripts.lib.project_paths import WORKSPACE_ROOT


QUARANTINE_ROOT = (
    WORKSPACE_ROOT / "system-data-service" / "quarantined-acquisitions"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete one explicitly targeted quarantined acquisition."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--reason",
        required=True,
        choices=("rejected", "retention-expired"),
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        parser.error("refusing destructive quarantine deletion without --yes")
    if not REVIEWER.fullmatch(args.reviewer):
        parser.error("reviewer must be a safe named identity")

    try:
        run_directory = safe_run_directory(QUARANTINE_ROOT, args.run_id)
    except ValueError as error:
        parser.error(str(error))
    if run_directory.is_symlink() or not run_directory.is_dir():
        parser.error("the targeted acquisition directory does not exist safely")
    audit_path = run_directory / "infrastructure-acquisition-audit.json"
    if audit_path.is_symlink() or not audit_path.is_file():
        parser.error("the targeted directory has no trusted acquisition audit")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("runId") != args.run_id:
        parser.error("the acquisition audit does not match the targeted run")
    now = datetime.now(UTC)
    retain_until = datetime.fromisoformat(audit["retainUntil"])
    if args.reason == "retention-expired" and now < retain_until:
        parser.error("the recorded retention period has not expired")

    deletion_record = {
        "schemaVersion": 1,
        "runId": args.run_id,
        "requestedAt": now.isoformat(),
        "reason": args.reason,
        "reviewer": args.reviewer,
        "formerStatus": audit.get("status"),
        "status": "DELETE_REQUESTED",
    }
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    with (QUARANTINE_ROOT / "deletion-audit.jsonl").open(
        "a", encoding="utf-8"
    ) as deletion_audit:
        deletion_audit.write(json.dumps(deletion_record) + "\n")
    shutil.rmtree(run_directory)
    deletion_record["status"] = "DELETED"
    deletion_record["deletedAt"] = datetime.now(UTC).isoformat()
    with (QUARANTINE_ROOT / "deletion-audit.jsonl").open(
        "a", encoding="utf-8"
    ) as deletion_audit:
        deletion_audit.write(json.dumps(deletion_record) + "\n")
    print(f"Deleted quarantined acquisition {args.run_id}; this is not recoverable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
