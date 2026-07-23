#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.clients.api_client_config import frontend_client_targets, load_services
from scripts.lib.project_paths import (
    CONTRACTS_DIR,
    FRONTEND_API_CLIENTS_DIR,
    FRONTEND_DIR,
    PROJECT_ROOT,
)

OUTPUT_DIR = FRONTEND_API_CLIENTS_DIR


def find_generator_command() -> str:
    for command in ["openapi-generator", "openapi-generator-cli"]:
        if shutil.which(command):
            return command

    print("ERROR: OpenAPI Generator not found")
    print()
    print("Install on Arch with:")
    print("yay -S openapi-generator")
    sys.exit(1)


def ensure_frontend_exists() -> None:
    if not FRONTEND_DIR.exists():
        print(f"ERROR: Frontend directory not found: {FRONTEND_DIR}")
        sys.exit(1)


def patch_generated_runtime(output_path: Path) -> None:
    runtime_file = output_path / "runtime.ts"

    if not runtime_file.exists():
        print(f"WARNING: runtime.ts not found at {runtime_file}")
        return

    text = runtime_file.read_text(encoding="utf-8")

    replacements = {
        "constructor(public cause: Error, msg?: string)": (
            "constructor(public override cause: Error, msg?: string)"
        ),
    }

    patched = text

    for old, new in replacements.items():
        patched = patched.replace(old, new)

    if patched != text:
        runtime_file.write_text(patched, encoding="utf-8")
        print(f"Patched TypeScript override issue in {runtime_file.relative_to(PROJECT_ROOT)}")
    else:
        print(f"No TypeScript runtime patch needed for {runtime_file.relative_to(PROJECT_ROOT)}")


def generate_client(generator_command: str, gateway_name: str) -> None:
    spec_file = CONTRACTS_DIR / f"{gateway_name}-openapi.json"

    if not spec_file.exists():
        raise FileNotFoundError(f"Missing OpenAPI contract: {spec_file}")

    output_path = OUTPUT_DIR / gateway_name

    if output_path.exists():
        shutil.rmtree(output_path)

    command = [
        generator_command,
        "generate",
        "-i",
        str(spec_file),
        "-g",
        "typescript-fetch",
        "-o",
        str(output_path),
        "--additional-properties",
        ",".join(
            [
                "supportsES6=true",
                "typescriptThreePlus=true",
                "withInterfaces=true",
                "useSingleRequestParameter=true",
            ]
        ),
    ]

    print(f"Generating frontend client for {gateway_name}")

    result = subprocess.run(command)

    if result.returncode != 0:
        raise RuntimeError(f"Failed generating frontend client for {gateway_name}")

    patch_generated_runtime(output_path)

    print(f"SUCCESS -> {output_path.relative_to(PROJECT_ROOT)}")
    print()


def main() -> int:
    argparse.ArgumentParser(description="Generate TypeScript frontend API clients from exported OpenAPI contracts.").parse_args()
    ensure_frontend_exists()

    generator_command = find_generator_command()

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    print("Generating frontend API clients")
    print(f"Generator: {generator_command}")
    print(f"Output:    {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")
    print()

    failures = 0

    for gateway in frontend_client_targets(load_services()):
        try:
            generate_client(generator_command, gateway)
        except Exception as error:
            failures += 1
            print(f"FAILED -> {gateway}")
            print(f"Reason: {error}")
            print()

    print("Frontend client generation complete")
    print(f"Failed: {failures}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
