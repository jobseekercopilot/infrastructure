#!/usr/bin/env python3

from scripts.workspace.catalog import load_catalog


def load_services() -> dict[str, dict]:
    """Compatibility view for legacy read-only tooling.

    New workspace operations consume the catalogue directly. Keeping this
    adapter prevents a second dependency manifest from drifting.
    """
    catalog = load_catalog()
    services = {
        repository.name: {
            "type": repository.kind,
            "openApiPort": repository.port,
            "dependsOn": list(repository.dependencies),
            "enabled": bool(repository.compose_services),
            "frontendFacing": repository.kind == "frontend",
        }
        for repository in catalog.repositories
        if repository.kind != "test"
    }
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
