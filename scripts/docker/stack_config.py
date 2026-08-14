from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.project_paths import PROJECT_ROOT


@dataclass(frozen=True)
class StackConfig:
    name: str
    project: str
    files: tuple[str, ...]
    env_file: str
    frontend_url: str | None
    system_data_url: str | None
    validator_profile: str
    startable: bool = True
    parallel_limit: int | None = None

    def compose_command(self, env_file: str | None = None) -> list[str]:
        command = [
            "docker",
            "compose",
        ]
        if self.parallel_limit is not None:
            command.extend(("--parallel", str(self.parallel_limit)))
        command.extend([
            "-p",
            self.project,
            "--env-file",
            env_file or self.env_file,
        ])
        for compose_file in self.files:
            command.extend(["-f", compose_file])
        return command

    def validation_command(self, env_file: str | None = None) -> list[str]:
        command = [
            sys.executable,
            "scripts/security/validate_compose_runtime.py",
            "--profile",
            self.validator_profile,
            "--env-file",
            env_file or self.env_file,
        ]
        overlays = self.files
        if overlays and overlays[0] == "docker-compose.yml":
            overlays = overlays[1:]
        for compose_file in overlays:
            command.extend(["--overlay", compose_file])
        return command


STACKS = {
    "local": StackConfig(
        name="local",
        project="job-seeker-copilot-local",
        files=("docker-compose.yml",),
        env_file=".env",
        frontend_url="http://localhost:3000",
        system_data_url="http://localhost:8103",
        validator_profile="local",
    ),
    "live": StackConfig(
        name="live",
        project="job-seeker-copilot-live",
        files=("docker-compose.yml", "docker-compose.live.yml"),
        env_file=".env.live",
        frontend_url="http://localhost:3000",
        system_data_url="http://localhost:8103",
        validator_profile="live-provider",
    ),
    "e2e": StackConfig(
        name="e2e",
        project="job-seeker-copilot-e2e",
        files=(
            "docker-compose.yml",
            "docker-compose.e2e.yml",
            "docker-compose.low-memory.yml",
        ),
        env_file=".env.e2e",
        frontend_url="http://localhost:3100",
        system_data_url="http://localhost:9103",
        validator_profile="e2e",
        parallel_limit=1,
    ),
    "data-acquisition": StackConfig(
        name="data-acquisition",
        project="job-seeker-copilot-data-acquisition",
        files=("docker-compose.data-acquisition.yml",),
        env_file=".env.data-acquisition",
        frontend_url=None,
        system_data_url=None,
        validator_profile="data-acquisition",
        startable=False,
    ),
}


def stack_for(name: str) -> StackConfig:
    return STACKS[name]


def project_root() -> Path:
    return PROJECT_ROOT
