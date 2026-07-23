#!/usr/bin/env python3

import json
from pathlib import Path

from scripts.lib.project_paths import PROJECT_ROOT, SERVICE_DEPENDENCIES

DEPENDENCY_MAP = SERVICE_DEPENDENCIES


def load_services() -> dict[str, dict]:
    with DEPENDENCY_MAP.open(encoding="utf-8") as file:
        services = json.load(file)["services"]

    unknown_dependencies = {
        dependency
        for service in services.values()
        for dependency in service.get("dependsOn", [])
        if dependency not in services
    }
    if unknown_dependencies:
        names = ", ".join(sorted(unknown_dependencies))
        raise ValueError(f"Unknown services in dependency map: {names}")

    return services


def is_enabled(config: dict) -> bool:
    return config.get("enabled", True)


def backend_services(services: dict[str, dict]) -> list[str]:
    return [
        name
        for name, config in services.items()
        if config["type"] != "frontend" and is_enabled(config)
    ]


def backend_client_targets(services: dict[str, dict]) -> list[str]:
    targets = {
        dependency
        for config in services.values()
        if config["type"] != "frontend"
        and (is_enabled(config) or config.get("generateClients", False))
        for dependency in config.get("dependsOn", [])
    }
    return [name for name in services if name in targets]


def frontend_client_targets(services: dict[str, dict]) -> list[str]:
    targets: list[str] = []
    for config in services.values():
        if config["type"] != "frontend" or not is_enabled(config):
            continue
        targets.extend(
            dependency
            for dependency in config.get("dependsOn", [])
            if is_enabled(services[dependency])
            and services[dependency].get("frontendFacing", False)
        )
    return list(dict.fromkeys(targets))


def backend_consumers(services: dict[str, dict], dependency: str) -> list[str]:
    return [
        name
        for name, config in services.items()
        if config["type"] != "frontend"
        and (is_enabled(config) or config.get("generateClients", False))
        and dependency in config.get("dependsOn", [])
    ]
