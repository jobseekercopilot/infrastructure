#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.deprecation import run_deprecated

if __name__ == "__main__":
    raise SystemExit(run_deprecated(
        "scripts.docker.rebuild_and_start_stack",
        "python scripts/rebuild_and_start_stack.py",
        "python -m scripts.docker.rebuild_and_start_stack",
    ))
