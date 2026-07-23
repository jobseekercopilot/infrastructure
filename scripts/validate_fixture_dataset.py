#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.deprecation import run_deprecated

if __name__ == "__main__":
    raise SystemExit(run_deprecated(
        "scripts.demo.validate_fixture_dataset",
        "python scripts/validate_fixture_dataset.py",
        "python -m scripts.demo.validate_fixture_dataset",
    ))
