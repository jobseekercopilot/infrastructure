#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.clients.api_client_config import backend_services, load_services
from scripts.lib.project_paths import CONTRACTS_DIR, PROJECT_ROOT


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "jobseeker-copilot-openapi-exporter",
        },
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset)

    return json.loads(body)


def save_contract(service_name: str, contract: dict) -> Path:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = CONTRACTS_DIR / f"{service_name}-openapi.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(contract, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return output_path


def export_contract(service: dict) -> bool:
    name = service["name"]
    url = service["url"]

    print(f"Exporting {name} from {url}")

    try:
        contract = fetch_json(url)
        output_path = save_contract(name, contract)
        print(f"  OK -> {output_path.relative_to(PROJECT_ROOT)}")
        return True

    except urllib.error.URLError as error:
        print(f"  FAILED -> Could not connect to {url}")
        print(f"  Reason: {error}")
        return False

    except json.JSONDecodeError as error:
        print(f"  FAILED -> Response was not valid JSON")
        print(f"  Reason: {error}")
        return False

    except Exception as error:
        print(f"  FAILED -> Unexpected error")
        print(f"  Reason: {error}")
        return False


def main() -> int:
    argparse.ArgumentParser(description="Export OpenAPI contracts from running backend services.").parse_args()
    services = load_services()
    export_targets = [
        {
            "name": name,
            "url": f"http://localhost:{services[name]['openApiPort']}/v3/api-docs",
        }
        for name in backend_services(services)
    ]
    print("Exporting OpenAPI contracts")
    print(f"Output directory: {CONTRACTS_DIR}")
    print()

    successes = 0
    failures = 0

    for service in export_targets:
        if export_contract(service):
            successes += 1
        else:
            failures += 1

    print()
    print("Export complete")
    print(f"Successful: {successes}")
    print(f"Failed:     {failures}")

    if failures > 0:
        print()
        print("Some services failed. Make sure those services are running and the ports are correct.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
