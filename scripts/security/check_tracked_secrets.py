#!/usr/bin/env python3
"""Fail when tracked environment/Compose files contain credential literals."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACKED_CONFIGURATION = (
    ROOT / ".env.example",
    ROOT / ".env.e2e.example",
    ROOT / ".env.live.example",
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.e2e.yml",
    ROOT / "docker-compose.live.yml",
)
SENSITIVE_NAME = re.compile(
    r"(?:PASSWORD|PRIVATE_KEY|SECRET|TOKEN|CALLER_KEY|ACCESS_KEY)(?:_BASE64)?$"
)
INTERPOLATION = re.compile(r"^\$\{[A-Z0-9_]+(?::[?+-].*)?\}$")


def findings(paths: tuple[Path, ...] = TRACKED_CONFIGURATION) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip().removeprefix("- ").strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip("\"'")
            if not SENSITIVE_NAME.search(name) or not value:
                continue
            if INTERPOLATION.fullmatch(value):
                continue
            failures.append(f"{path.relative_to(ROOT)}:{line_number}:{name}")
    return failures


def main() -> int:
    failures = findings()
    if failures:
        print("Tracked credential literals are forbidden:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Tracked environment and Compose files contain no credential literals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
