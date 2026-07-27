"""Controlled process environment for reproducible workspace commands."""

from __future__ import annotations

import json
import os

from scripts.workspace.catalog import INFRASTRUCTURE_ROOT

RUNTIME_ENVIRONMENT_SCHEMA = (
    INFRASTRUCTURE_ROOT / "config/runtime-environment.schema.json"
)


def controlled_environment() -> dict[str, str]:
    """Preserve tool settings but reject inherited application configuration."""
    schema = json.loads(RUNTIME_ENVIRONMENT_SCHEMA.read_text(encoding="utf-8"))
    application_variables = {
        variable["name"] for variable in schema["variables"]
    }
    return {
        name: value
        for name, value in os.environ.items()
        if name not in application_variables
    }
