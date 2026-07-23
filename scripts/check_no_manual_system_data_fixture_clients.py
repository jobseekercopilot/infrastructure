#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.deprecation import run_deprecated

if __name__ == "__main__":
    raise SystemExit(run_deprecated(
        "scripts.clients.check_no_manual_system_data_fixture_clients",
        "python scripts/check_no_manual_system_data_fixture_clients.py",
        "python -m scripts.clients.check_no_manual_system_data_fixture_clients",
    ))
