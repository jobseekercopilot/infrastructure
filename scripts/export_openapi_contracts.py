#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.deprecation import run_deprecated

if __name__ == "__main__":
    raise SystemExit(run_deprecated(
        "scripts.clients.export_openapi_contracts",
        "python scripts/export_openapi_contracts.py",
        "python -m scripts.clients.export_openapi_contracts",
    ))
