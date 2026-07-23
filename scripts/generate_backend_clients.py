#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.deprecation import run_deprecated

if __name__ == "__main__":
    raise SystemExit(run_deprecated(
        "scripts.clients.generate_backend_clients",
        "python scripts/generate_backend_clients.py",
        "python -m scripts.clients.generate_backend_clients",
    ))
