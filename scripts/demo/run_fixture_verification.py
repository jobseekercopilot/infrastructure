#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.project_paths import PROJECT_ROOT


ROOT = PROJECT_ROOT


def run(name, args):
    print(f"\n== {name} ==")
    result = subprocess.run([sys.executable, *args], cwd=ROOT)
    if result.returncode != 0:
        print(f"{name} failed with exit code {result.returncode}")
        return False
    return True


def main():
    argparse.ArgumentParser(description="Run fixture-mode verification checks.").parse_args()
    checks = [
        ("provider modes", ["-m", "scripts.demo.check_fixture_modes"]),
        ("fixture dataset", ["-m", "scripts.demo.validate_fixture_dataset"]),
        ("gateway smoke", ["-m", "scripts.demo.smoke_test_fixtures"]),
    ]
    ok = True
    for name, args in checks:
        ok = run(name, args) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
