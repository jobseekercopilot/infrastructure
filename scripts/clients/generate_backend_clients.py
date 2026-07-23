#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.clients.api_client_config import backend_client_targets, load_services
from scripts.lib.project_paths import BACKEND_CLIENTS_DIR, CONTRACTS_DIR, PROJECT_ROOT

OUTPUT_DIR = BACKEND_CLIENTS_DIR

def artifact_id_for(service_name: str) -> str:
    return f"{service_name}-client"


def ensure_openapi_generator():
    if shutil.which("openapi-generator") is None:
        print("ERROR: openapi-generator not found")
        print()
        print("Install with:")
        print("yay -S openapi-generator")
        sys.exit(1)


def patch_spring_61_compatibility(output_path: Path) -> None:
    api_client = next(output_path.glob("src/main/java/**/client/ApiClient.java"), None)
    if api_client is None:
        raise FileNotFoundError(f"Generated ApiClient.java not found under {output_path}")

    text = api_client.read_text(encoding="utf-8")
    patched = text.replace("headers.headerSet()", "headers.entrySet()")
    if patched != text:
        api_client.write_text(patched, encoding="utf-8")
        print(f"Patched Spring 6.1 HttpHeaders compatibility in {api_client}")


def generate_client(service_name: str):
    spec_file = CONTRACTS_DIR / f"{service_name}-openapi.json"

    if not spec_file.exists():
        raise FileNotFoundError(f"Missing OpenAPI contract: {spec_file}")

    output_path = OUTPUT_DIR / service_name

    if output_path.exists():
        shutil.rmtree(output_path)

    command = [
        "openapi-generator",
        "generate",
        "-i",
        str(spec_file),
        "-g",
        "java",
        "-o",
        str(output_path),
        "--additional-properties",
    (
        "library=resttemplate,"
        "useJakartaEe=true,"
        "serializationLibrary=jackson,"
        "dateLibrary=java8-localdatetime,"
        "hideGenerationTimestamp=true,"
        "groupId=com.jobseekercopilot.generated,"
        f"artifactId={artifact_id_for(service_name)},"
        "artifactVersion=1.0.0,"
        f"apiPackage=com.jobseekercopilot.generated.{service_name.replace('-', '')}.api,"
        f"modelPackage=com.jobseekercopilot.generated.{service_name.replace('-', '')}.model,"
        f"invokerPackage=com.jobseekercopilot.generated.{service_name.replace('-', '')}.client"
    ),
    ]

    print(f"Generating client for {service_name}")

    result = subprocess.run(command)

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed generating client for {service_name}"
        )

    patch_spring_61_compatibility(output_path)

    print(f"SUCCESS -> {output_path}")
    print()


def main():
    argparse.ArgumentParser(description="Generate Java backend API clients from exported OpenAPI contracts.").parse_args()
    ensure_openapi_generator()

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    print("Generating backend API clients")
    print()

    for service in backend_client_targets(load_services()):
        generate_client(service)

    print("Finished")


if __name__ == "__main__":
    main()
