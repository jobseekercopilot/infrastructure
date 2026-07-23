from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.lib.project_paths import PROJECT_ROOT


@dataclass(frozen=True)
class StackConfig:
    name: str
    project: str
    files: tuple[str, ...]
    env_file: str
    frontend_url: str
    system_data_url: str

    def compose_command(self) -> list[str]:
        command = ["docker", "compose", "-p", self.project, "--env-file", self.env_file]
        for compose_file in self.files:
            command.extend(["-f", compose_file])
        return command


STACKS = {
    "live": StackConfig(
        name="live",
        project="job-seeker-copilot-live",
        files=("docker-compose.yml", "docker-compose.live.yml"),
        env_file=".env.live",
        frontend_url="http://localhost:3000",
        system_data_url="http://localhost:8103",
    ),
    "e2e": StackConfig(
        name="e2e",
        project="job-seeker-copilot-e2e",
        files=("docker-compose.yml", "docker-compose.e2e.yml"),
        env_file=".env.e2e",
        frontend_url="http://localhost:3100",
        system_data_url="http://localhost:9103",
    ),
    "data-acquisition": StackConfig(
        name="data-acquisition",
        project="job-seeker-copilot-e2e",
        files=("docker-compose.yml", "docker-compose.e2e.yml", "docker-compose.data-acquisition.yml"),
        env_file=".env.e2e",
        frontend_url="http://localhost:3100",
        system_data_url="http://localhost:9103",
    ),
}


def stack_for(name: str) -> StackConfig:
    return STACKS[name]


def project_root() -> Path:
    return PROJECT_ROOT
