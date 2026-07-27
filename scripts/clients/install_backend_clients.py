#!/usr/bin/env python3

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def main() -> int:
    print(
        "ERROR: copied client JAR installation is retired.\n"
        "Use ./scripts/build-all.sh; it reconstructs locked producer-owned "
        "clients from Git into the workspace-local .cache/m2 repository.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
