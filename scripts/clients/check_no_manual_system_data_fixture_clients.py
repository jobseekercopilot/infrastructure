#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.project_paths import PROJECT_ROOT

SOURCE_ROOTS = [
    "adzuna-gateway/src/main/java",
    "jsearch-gateway/src/main/java",
    "reed-gateway/src/main/java",
    "postcode-io-gateway/src/main/java",
    "llm-gateway/src/main/java",
    "stripe-gateway/src/main/java",
]

FORBIDDEN = [
    "/internal/fixtures",
    "UriComponentsBuilder.fromHttpUrl(fixtureProperties.getSystemDataServiceUrl())",
    "new RestTemplate()",
    "RestTemplate restTemplate",
    "Map<?, ?> body",
    "Map<String, Object> payload",
]

ALLOWED_FILES = {
    "config/SystemDataServiceApiConfig.java",
}


def main() -> int:
    argparse.ArgumentParser(description="Check fixture providers do not use manual system-data HTTP clients.").parse_args()
    failures: list[str] = []
    for root in SOURCE_ROOTS:
        source_root = PROJECT_ROOT / root
        if not source_root.exists():
            continue
        for path in source_root.rglob("Fixture*ProviderClient.java"):
            relative_to_source = str(path.relative_to(source_root))
            if relative_to_source in ALLOWED_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN:
                if pattern in text:
                    failures.append(f"{path.relative_to(PROJECT_ROOT)} contains forbidden pattern: {pattern}")

    if failures:
        print("Manual system-data-service fixture clients are not allowed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("OK: no manual system-data-service fixture HTTP clients found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
