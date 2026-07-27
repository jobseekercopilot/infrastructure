"""Repository path constants shared by operational scripts."""

from __future__ import annotations

from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
INFRASTRUCTURE_ROOT = SCRIPTS_ROOT.parent
WORKSPACE_ROOT = INFRASTRUCTURE_ROOT.parent

# Compatibility name for Infrastructure-owned files. Service repositories are
# deliberately resolved from WORKSPACE_ROOT, never from this repository.
PROJECT_ROOT = INFRASTRUCTURE_ROOT

APP_DIR = SCRIPTS_ROOT / "app"
CLIENTS_DIR = SCRIPTS_ROOT / "clients"
CLIENT_CONFIG_DIR = CLIENTS_DIR / "config"
DATA_DIR = SCRIPTS_ROOT / "data"
DEMO_DIR = SCRIPTS_ROOT / "demo"
DOCKER_DIR = SCRIPTS_ROOT / "docker"
GIT_DIR = SCRIPTS_ROOT / "git"
TEST_DIR = SCRIPTS_ROOT / "test"

E2E_DIR = WORKSPACE_ROOT / "e2e" / "playwright-cucumber"
CONTRACTS_DIR = PROJECT_ROOT / "docs" / "contracts"
CONTRACT_LOCK = PROJECT_ROOT / "config" / "contracts-lock.json"
BACKEND_CLIENTS_DIR = INFRASTRUCTURE_ROOT / "generated-clients" / "backend"
FRONTEND_DIR = WORKSPACE_ROOT / "job-seeker-copilot-client"
FRONTEND_API_CLIENTS_DIR = FRONTEND_DIR / "src" / "generated" / "api"

BACKEND_CLIENT_CONFORMANCE_EXCLUSIONS = (
    CLIENT_CONFIG_DIR / "backend_client_conformance_exclusions.json"
)
