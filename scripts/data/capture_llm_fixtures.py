#!/usr/bin/env python3
"""Fail-closed compatibility entry point for the retired live LLM capture path."""

from __future__ import annotations

import argparse
import sys


BACKLOG_URL = "https://github.com/jobseekercopilot/infrastructure/issues/29"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Live LLM fixture capture is disabled. Existing fixtures remain "
            "readable, but this command cannot make provider calls."
        )
    )
    parser.add_argument("--dataset-path")
    parser.add_argument("--llm-gateway-url")
    parser.add_argument("--job-id")
    parser.add_argument("--yes", action="store_true")
    parser.parse_args()
    print(
        "Live LLM fixture capture is disabled by the INFRA-11 mode boundary. "
        "A separately approved, cost-bounded quarantine workflow is tracked at "
        f"{BACKLOG_URL}. No provider call was made.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
