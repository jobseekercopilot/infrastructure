"""Load and validate the Infrastructure repository catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "config" / "services.json"


@dataclass(frozen=True)
class Catalog:
    owner: str
    default_ref: str
    repositories: tuple[str, ...]


def load_catalog(path: Path = DEFAULT_CATALOG) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != 1:
        raise ValueError("Unsupported catalog schemaVersion")

    owner = raw.get("owner")
    default_ref = raw.get("defaultRef")
    repositories = raw.get("repositories")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("Catalog owner must be a non-empty string")
    if not isinstance(default_ref, str) or not default_ref.strip():
        raise ValueError("Catalog defaultRef must be a non-empty string")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("Catalog repositories must be a non-empty list")
    if any(not isinstance(name, str) or not name.strip() for name in repositories):
        raise ValueError("Every repository name must be a non-empty string")
    if len(repositories) != len(set(repositories)):
        raise ValueError("Catalog repository names must be unique")

    return Catalog(owner.strip(), default_ref.strip(), tuple(repositories))
