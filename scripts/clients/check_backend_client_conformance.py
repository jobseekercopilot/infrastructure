#!/usr/bin/env python3
"""Check backend generated-client conformance for project-owned HTTP calls."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.project_paths import (
    BACKEND_CLIENT_CONFORMANCE_EXCLUSIONS,
    PROJECT_ROOT,
    SERVICE_DEPENDENCIES,
)


ROOT = PROJECT_ROOT
DEPENDENCIES = SERVICE_DEPENDENCIES
EXCLUSIONS = BACKEND_CLIENT_CONFORMANCE_EXCLUSIONS

HTTP_MARKERS = (
    "RestTemplate",
    "RestClient",
    "WebClient",
    "FeignClient",
    "java.net.http.HttpClient",
    "OkHttpClient",
)
CALL_MARKERS = (
    ".getForObject(",
    ".postForObject(",
    ".postForEntity(",
    ".exchange(",
    ".delete(",
    ".retrieve(",
    ".uri(",
    ".baseUrl(",
)
INTERNAL_HINTS = (
    "application-tracker-service",
    "authentication-service",
    "cv-cover-letter-service",
    "document-export-service",
    "document-store-service",
    "job-matching-service",
    "job-service",
    "payment-service",
    "postcode-io-gateway",
    "reporting-service",
    "stripe-gateway",
    "system-data-service",
    "user-profile-service",
    "/internal/",
    "/api/v1/",
    "/api/jobs",
    "services.",
)


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def service_dir(service: str) -> Path:
    return ROOT / service


def artifact_id(service: str) -> str:
    return f"{service}-client"


def expected_jar(service: str) -> str:
    return f"{service}-client-1.0.0.jar"


def path_excluded(path: Path, exclusions: dict[str, dict]) -> bool:
    return rel(path) in exclusions


def find_java_files(service: str):
    source_root = service_dir(service) / "src" / "main" / "java"
    if not source_root.exists():
        return []
    return sorted(source_root.rglob("*.java"))


def is_generated_client_config(text: str) -> bool:
    return "generated." in text and "ApiClient" in text and "@Bean" in text


def is_http_factory_config(path: Path, text: str) -> bool:
    return "/config/" in rel(path) and "@Configuration" in text and "@Bean" in text


def scan_manual_http(services: dict, exclusions: dict[str, dict]) -> list[str]:
    findings: list[str] = []
    for service, meta in services.items():
        if meta.get("type") == "frontend":
            continue
        for java_file in find_java_files(service):
            text = java_file.read_text(encoding="utf-8", errors="ignore")
            if not any(marker in text for marker in HTTP_MARKERS):
                continue
            if is_generated_client_config(text):
                continue
            if is_http_factory_config(java_file, text):
                continue
            has_call = any(marker in text for marker in CALL_MARKERS)
            has_internal_hint = any(hint in text for hint in INTERNAL_HINTS)
            suspicious_client = re.search(r"class\s+\w*(?:HttpClient|ServiceClient|GatewayClient|ApiClient|Client)\b", text)
            if has_call and (has_internal_hint or suspicious_client):
                if path_excluded(java_file, exclusions):
                    continue
                findings.append(f"manual internal HTTP candidate: {rel(java_file)}")
    return findings


def check_declared_dependencies(services: dict) -> list[str]:
    findings: list[str] = []
    for consumer, meta in services.items():
        if meta.get("type") == "frontend":
            continue
        consumer_dir = service_dir(consumer)
        pom = consumer_dir / "pom.xml"
        pom_text = pom.read_text(encoding="utf-8", errors="ignore") if pom.exists() else ""
        for producer in meta.get("dependsOn", []):
            if producer not in services:
                findings.append(f"{consumer}: unknown dependency '{producer}'")
                continue
            if services[producer].get("type") == "frontend":
                continue
            contract = ROOT / "docs" / "contracts" / f"{producer}-openapi.json"
            generated = ROOT / "generated-clients" / "backend" / producer
            jar = consumer_dir / "libs" / expected_jar(producer)
            if not contract.exists():
                findings.append(f"{consumer}: missing OpenAPI contract for {producer}: {rel(contract)}")
            if not generated.exists():
                findings.append(f"{consumer}: missing generated backend client source for {producer}: {rel(generated)}")
            if consumer_dir.exists() and not jar.exists():
                findings.append(f"{consumer}: missing installed generated JAR for {producer}: {rel(jar)}")
            if pom.exists() and artifact_id(producer) not in pom_text:
                findings.append(f"{consumer}: pom.xml missing generated dependency {artifact_id(producer)}")
    return findings


def validate_exclusions(exclusions: list[dict]) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    for item in exclusions:
        path = item.get("path")
        if not path:
            findings.append("exclusion missing path")
            continue
        if "*" in path:
            findings.append(f"broad wildcard exclusion is not allowed: {path}")
        if path in seen:
            findings.append(f"duplicate exclusion: {path}")
        seen.add(path)
        for field in ("owner", "reason", "review"):
            if not item.get(field):
                findings.append(f"exclusion {path} missing {field}")
        if not (ROOT / path).exists():
            findings.append(f"exclusion path does not exist: {path}")
    return findings


def main() -> int:
    argparse.ArgumentParser(description="Check backend generated-client conformance.").parse_args()
    config = load_json(DEPENDENCIES)
    services = config["services"]
    exclusions_raw = load_json(EXCLUSIONS)
    exclusions = {item["path"]: item for item in exclusions_raw if item.get("path")}

    findings: list[str] = []
    findings.extend(validate_exclusions(exclusions_raw))
    findings.extend(check_declared_dependencies(services))
    findings.extend(scan_manual_http(services, exclusions))

    print("Backend generated-client conformance check")
    print(f"Services inspected: {sum(1 for meta in services.values() if meta.get('type') != 'frontend')}")
    print(f"Documented exclusions: {len(exclusions)}")
    if findings:
        print("\nViolations:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("\nNo clear generated-client conformance violations found outside documented exclusions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
