#!/usr/bin/env python3
"""Materialise the locked sibling-repository workspace without losing work."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

INFRASTRUCTURE_ROOT = Path(__file__).resolve().parents[2]
if str(INFRASTRUCTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(INFRASTRUCTURE_ROOT))

from scripts.workspace.catalog import (
    DEFAULT_CATALOG,
    WORKSPACE_ROOT,
    Catalog,
    Repository,
    load_catalog,
    load_workspace_lock,
)


@dataclass(frozen=True)
class CheckoutState:
    name: str
    path: str
    status: str
    expected_branch: str
    expected_revision: str
    current_branch: str | None = None
    current_revision: str | None = None
    detail: str | None = None


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def expected_remote(owner: str, repository: str) -> tuple[str, ...]:
    return (
        f"https://github.com/{owner}/{repository}.git",
        f"https://github.com/{owner}/{repository}",
        f"git@github.com:{owner}/{repository}.git",
        f"git@github.com:{owner}/{repository}",
    )


def remote_url(path: Path) -> str | None:
    result = run(["git", "-C", str(path), "remote", "get-url", "origin"])
    return result.stdout.strip() if result.returncode == 0 else None


def git_value(path: Path, *arguments: str) -> str | None:
    result = run(["git", "-C", str(path), *arguments])
    return result.stdout.strip() if result.returncode == 0 else None


def is_clean(path: Path) -> bool:
    result = run(["git", "-C", str(path), "status", "--porcelain=v1"])
    return result.returncode == 0 and not result.stdout.strip()


def plan(
    root: Path, owner: str, repositories: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """Compatibility planning helper used by diagnostics and older callers."""
    missing: list[str] = []
    conflicts: list[str] = []
    for repository in repositories:
        path = root / repository
        if not path.exists():
            missing.append(repository)
            continue
        current_remote = remote_url(path)
        if current_remote not in expected_remote(owner, repository):
            conflicts.append(
                f"{repository}: existing path is not the expected Git checkout "
                f"(origin={current_remote or 'missing'})"
            )
    return missing, conflicts


def inspect_checkout(
    workspace: Path,
    owner: str,
    repository: Repository,
    revision: str,
) -> CheckoutState:
    path = workspace / repository.name
    common = {
        "name": repository.name,
        "path": str(path),
        "expected_branch": repository.branch,
        "expected_revision": revision,
    }
    if not path.exists():
        return CheckoutState(status="missing", **common)
    if not path.is_dir():
        return CheckoutState(
            status="conflict", detail="expected a directory", **common
        )
    current_remote = remote_url(path)
    if current_remote not in expected_remote(owner, repository.name):
        return CheckoutState(
            status="conflict",
            detail=f"unexpected origin {current_remote or 'missing'}",
            **common,
        )
    branch = git_value(path, "branch", "--show-current")
    head = git_value(path, "rev-parse", "HEAD")
    if not is_clean(path):
        return CheckoutState(
            status="dirty",
            current_branch=branch,
            current_revision=head,
            detail="local changes are present; no mutation is permitted",
            **common,
        )
    if branch != repository.branch:
        return CheckoutState(
            status="wrong-branch",
            current_branch=branch,
            current_revision=head,
            detail=f"expected checked-out branch {repository.branch}",
            **common,
        )
    if head != revision:
        return CheckoutState(
            status="revision-drift",
            current_branch=branch,
            current_revision=head,
            detail="run with --update after reviewing the dry run",
            **common,
        )
    return CheckoutState(
        status="ready",
        current_branch=branch,
        current_revision=head,
        **common,
    )


def clone_locked(
    workspace: Path,
    owner: str,
    repository: Repository,
    revision: str,
) -> None:
    path = workspace / repository.name
    subprocess.run(
        [
            "gh",
            "repo",
            "clone",
            f"{owner}/{repository.name}",
            str(path),
            "--",
            "--no-checkout",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "fetch", "origin", repository.branch],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "checkout",
            "-B",
            repository.branch,
            revision,
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "branch",
            "--set-upstream-to",
            f"origin/{repository.branch}",
            repository.branch,
        ],
        check=True,
    )


def update_locked(
    path: Path, repository: Repository, expected_revision: str
) -> None:
    subprocess.run(
        ["git", "-C", str(path), "fetch", "origin", repository.branch],
        check=True,
    )
    object_result = run(
        ["git", "-C", str(path), "cat-file", "-e", f"{expected_revision}^{{commit}}"]
    )
    if object_result.returncode != 0:
        raise RuntimeError(
            f"{repository.name}: locked revision is not available from origin"
        )
    ancestor = run(
        [
            "git",
            "-C",
            str(path),
            "merge-base",
            "--is-ancestor",
            "HEAD",
            expected_revision,
        ]
    )
    if ancestor.returncode != 0:
        raise RuntimeError(
            f"{repository.name}: refusing non-fast-forward or backwards update"
        )
    subprocess.run(
        ["git", "-C", str(path), "merge", "--ff-only", expected_revision],
        check=True,
    )


def report_payload(
    workspace: Path,
    catalog: Catalog,
    lock: dict[str, dict],
) -> dict:
    states = [
        inspect_checkout(
            workspace,
            catalog.organisation,
            repository,
            lock[repository.name]["revision"],
        )
        for repository in catalog.repositories
    ]
    return {
        "schemaVersion": 1,
        "workspace": str(workspace),
        "catalog": str(DEFAULT_CATALOG),
        "lock": str(catalog.lock_path),
        "repositories": [asdict(state) for state in states],
        "summary": {
            status: sum(state.status == status for state in states)
            for status in sorted({state.status for state in states})
        },
    }


def write_report(payload: dict, output: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote workspace report to {output}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clone or fast-forward the exact locked sibling repositories. "
            "Dry run is the default and never fetches or changes a checkout."
        )
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--report", type=Path)
    mutation = parser.add_mutually_exclusive_group()
    mutation.add_argument(
        "--apply",
        action="store_true",
        help="clone only missing repositories at their locked revisions",
    )
    mutation.add_argument(
        "--update",
        action="store_true",
        help="clone missing repositories and fast-forward clean expected branches",
    )
    args = parser.parse_args()

    catalog = load_catalog(args.catalog.resolve())
    lock = load_workspace_lock(catalog)
    workspace = args.workspace.resolve()
    if workspace == INFRASTRUCTURE_ROOT or INFRASTRUCTURE_ROOT in workspace.parents:
        print("ERROR: workspace must be the parent of Infrastructure, not inside it")
        return 2
    workspace.mkdir(parents=True, exist_ok=True)

    before = report_payload(workspace, catalog, lock)
    unsafe = [
        state
        for state in before["repositories"]
        if state["status"] in {"conflict", "dirty", "wrong-branch"}
    ]
    if unsafe:
        write_report(before, args.report)
        print("ERROR: refusing to modify a workspace with unsafe checkouts")
        return 2

    if not args.apply and not args.update:
        write_report(before, args.report)
        return 0

    if run(["gh", "auth", "status"]).returncode != 0:
        print("ERROR: GitHub CLI authentication is required")
        return 2

    for repository in catalog.repositories:
        state = next(
            item for item in before["repositories"] if item["name"] == repository.name
        )
        revision = lock[repository.name]["revision"]
        if state["status"] == "missing":
            print(f"CLONE {repository.name} {revision}")
            clone_locked(workspace, catalog.organisation, repository, revision)
        elif state["status"] == "revision-drift":
            if not args.update:
                print(f"SKIP {repository.name}: requires --update")
                continue
            print(f"UPDATE {repository.name} {revision}")
            update_locked(workspace / repository.name, repository, revision)

    after = report_payload(workspace, catalog, lock)
    write_report(after, args.report)
    failures = [
        state for state in after["repositories"] if state["status"] != "ready"
    ]
    if failures:
        print("ERROR: workspace did not reach the exact lock")
        return 1
    print(f"Workspace ready: {len(after['repositories'])} locked repositories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
