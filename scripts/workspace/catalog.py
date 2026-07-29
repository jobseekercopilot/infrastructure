"""Load and validate the authoritative Infrastructure service catalogue."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


INFRASTRUCTURE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = INFRASTRUCTURE_ROOT.parent
DEFAULT_CATALOG = INFRASTRUCTURE_ROOT / "config" / "services.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Repository:
    name: str
    kind: str
    branch: str
    build: str
    compose_services: tuple[str, ...]
    dependencies: tuple[str, ...]
    port: int | None
    health: str | None

    @property
    def path(self) -> Path:
        return WORKSPACE_ROOT / self.name


@dataclass(frozen=True)
class Profile:
    name: str
    compose_files: tuple[str, ...]
    compose_project: str
    environment_profile: str
    environment_file: Path
    secret_environment_file: Path | None
    secret_providers: tuple[str, ...]
    frontend_url: str
    services: tuple[str, ...] | str


@dataclass(frozen=True)
class Catalog:
    organisation: str
    project_title: str
    project_number: int
    infrastructure_path: str
    default_branch: str
    lock_path: Path
    environment_schema_path: Path
    repositories: tuple[Repository, ...]
    build_order: tuple[str, ...]
    profiles: tuple[Profile, ...]

    @property
    def owner(self) -> str:
        return self.organisation

    @property
    def default_ref(self) -> str:
        return self.default_branch

    @property
    def repository_names(self) -> tuple[str, ...]:
        return tuple(repository.name for repository in self.repositories)

    def repository(self, name: str) -> Repository:
        return next(repository for repository in self.repositories if repository.name == name)

    def profile(self, name: str) -> Profile:
        return next(profile for profile in self.profiles if profile.name == name)


def _required_string(raw: dict, key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _relative_file(root: Path, value: str, context: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{context} must be repository-relative")
    return root / candidate


def load_catalog(path: Path = DEFAULT_CATALOG) -> Catalog:
    infrastructure_root = path.resolve().parent.parent
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != 2:
        raise ValueError("Catalog schemaVersion must be 2")

    organisation = _required_string(raw, "organisation", "catalog")
    github_project = raw.get("githubProject")
    if not isinstance(github_project, dict):
        raise ValueError("catalog.githubProject must be an object")
    project_title = _required_string(
        github_project, "title", "catalog.githubProject"
    )
    project_number = github_project.get("number")
    if (
        not isinstance(project_number, int)
        or isinstance(project_number, bool)
        or project_number < 1
    ):
        raise ValueError("catalog.githubProject.number must be a positive integer")
    workspace = raw.get("workspace")
    if not isinstance(workspace, dict):
        raise ValueError("catalog.workspace must be an object")
    if workspace.get("layout") != "sibling-repositories":
        raise ValueError("catalog.workspace.layout must be sibling-repositories")
    infrastructure_path = _required_string(
        workspace, "infrastructurePath", "catalog.workspace"
    )
    default_branch = _required_string(workspace, "defaultBranch", "catalog.workspace")
    lock_path = _relative_file(
        infrastructure_root,
        _required_string(workspace, "lock", "catalog.workspace"),
        "catalog.workspace.lock",
    )
    environment_schema_path = _relative_file(
        infrastructure_root,
        _required_string(
            workspace, "runtimeEnvironmentSchema", "catalog.workspace"
        ),
        "catalog.workspace.runtimeEnvironmentSchema",
    )

    raw_repositories = raw.get("repositories")
    if not isinstance(raw_repositories, list) or not raw_repositories:
        raise ValueError("catalog.repositories must be a non-empty list")
    repositories: list[Repository] = []
    for index, item in enumerate(raw_repositories):
        context = f"catalog.repositories[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object")
        name = _required_string(item, "name", context)
        if not NAME.fullmatch(name):
            raise ValueError(f"{context}.name is not a safe repository name")
        compose_services = item.get("composeServices")
        dependencies = item.get("dependsOn")
        if not isinstance(compose_services, list) or any(
            not isinstance(service, str) or not service
            for service in compose_services
        ):
            raise ValueError(f"{context}.composeServices must be a string list")
        if not isinstance(dependencies, list) or any(
            not isinstance(dependency, str) or not dependency
            for dependency in dependencies
        ):
            raise ValueError(f"{context}.dependsOn must be a string list")
        port = item.get("port")
        if port is not None and (
            not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
        ):
            raise ValueError(f"{context}.port must be a valid TCP port")
        health = item.get("health")
        if health is not None and (
            not isinstance(health, str) or not health.startswith("/")
        ):
            raise ValueError(f"{context}.health must be an absolute URL path")
        repositories.append(
            Repository(
                name=name,
                kind=_required_string(item, "kind", context),
                branch=_required_string(item, "branch", context),
                build=_required_string(item, "build", context),
                compose_services=tuple(compose_services),
                dependencies=tuple(dependencies),
                port=port,
                health=health,
            )
        )

    names = tuple(repository.name for repository in repositories)
    if len(names) != len(set(names)):
        raise ValueError("catalog repository names must be unique")
    unknown_dependencies = {
        dependency
        for repository in repositories
        for dependency in repository.dependencies
        if dependency not in names
    }
    if unknown_dependencies:
        raise ValueError(
            "catalog has unknown dependencies: "
            + ", ".join(sorted(unknown_dependencies))
        )
    compose_services = [
        service
        for repository in repositories
        for service in repository.compose_services
    ]
    if len(compose_services) != len(set(compose_services)):
        raise ValueError("catalog Compose services must be uniquely owned")

    build_order = raw.get("buildOrder")
    if not isinstance(build_order, list) or tuple(build_order) != names:
        if not isinstance(build_order, list) or set(build_order) != set(names):
            raise ValueError("catalog.buildOrder must contain every repository exactly once")
    if len(build_order) != len(set(build_order)):
        raise ValueError("catalog.buildOrder must not contain duplicates")

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("catalog.profiles must be a non-empty object")
    profiles: list[Profile] = []
    known_runtime_services = set(compose_services)
    for name, item in raw_profiles.items():
        context = f"catalog.profiles.{name}"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object")
        files = item.get("composeFiles")
        services = item.get("services")
        secret_providers = item.get("secretProviders", [])
        if not isinstance(files, list) or not files:
            raise ValueError(f"{context}.composeFiles must be a non-empty list")
        if not isinstance(secret_providers, list) or any(
            not isinstance(provider, str) or not provider
            for provider in secret_providers
        ):
            raise ValueError(f"{context}.secretProviders must be a string list")
        if bool(secret_providers) != ("secretEnvironmentFile" in item):
            raise ValueError(
                f"{context}.secretProviders and secretEnvironmentFile must be configured together"
            )
        environment_file = item.get("environmentFile", f".env.{name}")
        if not isinstance(environment_file, str) or not environment_file.strip():
            raise ValueError(f"{context}.environmentFile must be a non-empty string")
        if services != "all-runtime":
            if not isinstance(services, list) or not services:
                raise ValueError(
                    f"{context}.services must be all-runtime or a non-empty list"
                )
            unknown = set(services) - known_runtime_services - {
                "authentication-postgres",
                "application-tracker-postgres",
                "document-store-postgres",
                "payment-postgres",
            }
            if unknown:
                raise ValueError(
                    f"{context} has unknown services: {', '.join(sorted(unknown))}"
                )
            services = tuple(services)
        profiles.append(
            Profile(
                name=name,
                compose_files=tuple(files),
                compose_project=_required_string(item, "composeProject", context),
                environment_profile=_required_string(
                    item, "environmentProfile", context
                ),
                environment_file=_relative_file(
                    infrastructure_root,
                    environment_file.strip(),
                    f"{context}.environmentFile",
                ),
                secret_environment_file=(
                    _relative_file(
                        infrastructure_root.parent,
                        item["secretEnvironmentFile"],
                        f"{context}.secretEnvironmentFile",
                    )
                    if "secretEnvironmentFile" in item
                    else None
                ),
                secret_providers=tuple(secret_providers),
                frontend_url=_required_string(item, "frontendUrl", context),
                services=services,
            )
        )

    return Catalog(
        organisation=organisation,
        project_title=project_title,
        project_number=project_number,
        infrastructure_path=infrastructure_path,
        default_branch=default_branch,
        lock_path=lock_path,
        environment_schema_path=environment_schema_path,
        repositories=tuple(repositories),
        build_order=tuple(build_order),
        profiles=tuple(profiles),
    )


def load_workspace_lock(catalog: Catalog, path: Path | None = None) -> dict[str, dict]:
    lock_path = path or catalog.lock_path
    raw = json.loads(lock_path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != 1:
        raise ValueError("workspace lock schemaVersion must be 1")
    entries = raw.get("repositories")
    if not isinstance(entries, list):
        raise ValueError("workspace lock repositories must be a list")
    result: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        context = f"workspace lock repositories[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{context} must be an object")
        name = _required_string(entry, "name", context)
        branch = _required_string(entry, "branch", context)
        revision = _required_string(entry, "revision", context)
        if name in result:
            raise ValueError(f"workspace lock duplicates {name}")
        if not SHA.fullmatch(revision):
            raise ValueError(f"workspace lock revision for {name} must be a full SHA")
        result[name] = {"branch": branch, "revision": revision}

    expected = set(catalog.repository_names)
    if set(result) != expected:
        missing = sorted(expected - set(result))
        extra = sorted(set(result) - expected)
        raise ValueError(
            f"workspace lock/catalog mismatch; missing={missing}, extra={extra}"
        )
    for repository in catalog.repositories:
        if result[repository.name]["branch"] != repository.branch:
            raise ValueError(
                f"workspace lock branch mismatch for {repository.name}"
            )
    return result
