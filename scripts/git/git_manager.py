#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.project_paths import PROJECT_ROOT, WORKSPACE_ROOT
from scripts.workspace.catalog import DEFAULT_CATALOG, load_catalog


CONFIG_PATH = DEFAULT_CATALOG
EXPECTED_STATUSES = ("Ideas", "Backlog", "Ready", "In Progress", "Review", "Bugs", "Done")
READY_STATUSES = ("Ready", "Backlog")
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "": 99, None: 99}


class GitManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoConfig:
    name: str
    path: Path
    test_command: str | None = None


@dataclass(frozen=True)
class GitHubConfig:
    owner: str
    project_title: str
    project_number: int


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    github: GitHubConfig
    repositories: dict[str, RepoConfig]


@dataclass
class ProjectItem:
    id: str
    title: str
    status: str = ""
    priority: str = ""
    body: str = ""
    number: int | None = None
    repo: str = ""
    url: str = ""
    labels: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    content_id: str = ""
    content_type: str = ""

    @property
    def display_priority(self) -> str:
        return self.priority or "-"


def run(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )


def run_shell(command: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        check=check,
        text=True,
        capture_output=True,
    )


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        raise GitManagerError(f"Config file not found: {path}")

    raw = json.loads(path.read_text())
    catalog = load_catalog(path)
    root_dir = WORKSPACE_ROOT

    github_raw = {
        "owner": catalog.owner,
        "project_title": catalog.project_title,
        "project_number": catalog.project_number,
    }
    repositories = {
        catalog.infrastructure_path: RepoConfig(
            name=catalog.infrastructure_path,
            path=root_dir / catalog.infrastructure_path,
            test_command="python3 -m unittest discover -s tests",
        )
    }
    for repository in catalog.repositories:
        test_command = (
            "mvn test"
            if repository.build == "maven"
            else "npm test -- --watch=false"
            if repository.build == "npm"
            else None
        )
        repositories[repository.name] = RepoConfig(
            name=repository.name,
            path=root_dir / repository.name,
            test_command=test_command,
        )

    return AppConfig(
        root_dir=root_dir,
        github=GitHubConfig(
            owner=str(github_raw["owner"]),
            project_title=str(github_raw["project_title"]),
            project_number=int(github_raw["project_number"]),
        ),
        repositories=repositories,
    )


def discover_repositories(root_dir: Path) -> dict[str, RepoConfig]:
    repositories: dict[str, RepoConfig] = {}
    for git_dir in sorted(root_dir.glob("*/.git")):
        repo_path = git_dir.parent
        repositories[repo_path.name] = RepoConfig(name=repo_path.name, path=repo_path)
    if (root_dir / ".git").exists():
        repositories.setdefault(root_dir.name, RepoConfig(name=root_dir.name, path=root_dir))
    return repositories


class GitHubProjectClient:
    def __init__(self, config: GitHubConfig) -> None:
        self.config = config
        self._project_cache: dict[str, Any] | None = None

    def require_gh(self) -> None:
        if not shutil.which("gh"):
            raise GitManagerError(
                "GitHub CLI is not installed.\n"
                "Install it from https://cli.github.com/ and run: gh auth login"
            )

    def auth_status(self) -> bool:
        if not shutil.which("gh"):
            return False
        return run(["gh", "auth", "status"], check=False).returncode == 0

    def gh_json(self, args: list[str]) -> Any:
        self.require_gh()
        completed = run(["gh", *args])
        output = completed.stdout.strip()
        return json.loads(output) if output else {}

    def gh_text(self, args: list[str], check: bool = True) -> str:
        self.require_gh()
        return run(["gh", *args], check=check).stdout.strip()

    def graphql(self, query: str, fields: dict[str, str]) -> Any:
        args = ["api", "graphql", "-f", f"query={query}"]
        for key, value in fields.items():
            flag = "-F" if key == "number" else "-f"
            args.extend([flag, f"{key}={value}"])
        return self.gh_json(args)

    def project(self) -> dict[str, Any]:
        if self._project_cache is not None:
            return self._project_cache

        query = """
        query($login: String!, $number: Int!) {
          user(login: $login) {
            projectV2(number: $number) {
              id
              title
              fields(first: 50) {
                nodes {
                  __typename
                  ... on ProjectV2FieldCommon { id name }
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    options { id name }
                  }
                }
              }
            }
          }
          organization(login: $login) {
            projectV2(number: $number) {
              id
              title
              fields(first: 50) {
                nodes {
                  __typename
                  ... on ProjectV2FieldCommon { id name }
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    options { id name }
                  }
                }
              }
            }
          }
        }
        """
        data = self.graphql(
            query,
            {"login": self.config.owner, "number": str(self.config.project_number)},
        )
        project = (data.get("data", {}).get("user") or {}).get("projectV2")
        project = project or (data.get("data", {}).get("organization") or {}).get("projectV2")
        if not project:
            raise GitManagerError(
                f"Could not read project {self.config.owner}/{self.config.project_number}. "
                "Run `gh auth login` and confirm your token has project access."
            )
        self._project_cache = project
        return project

    def statuses(self) -> list[str]:
        status_field = self.single_select_field("Status")
        return [option["name"] for option in status_field.get("options", [])]

    def single_select_field(self, name: str) -> dict[str, Any]:
        for field_node in self.project().get("fields", {}).get("nodes", []):
            if field_node and field_node.get("name", "").lower() == name.lower():
                return field_node
        raise GitManagerError(f"Project field not found: {name}")

    def items(self) -> list[ProjectItem]:
        raw = self.gh_json(
            [
                "project",
                "item-list",
                str(self.config.project_number),
                "--owner",
                self.config.owner,
                "--format",
                "json",
                "--limit",
                "500",
            ]
        )
        raw_items = raw.get("items", raw if isinstance(raw, list) else [])
        items = [self._parse_item(item) for item in raw_items]
        return items

    def _parse_item(self, raw: dict[str, Any]) -> ProjectItem:
        content = raw.get("content") or {}
        labels_raw = raw.get("labels") or content.get("labels") or []
        labels = [label.get("name", str(label)) if isinstance(label, dict) else str(label) for label in labels_raw]
        repo = repo_name(content.get("repository") or raw.get("repository") or "")
        body = content.get("body") or raw.get("body") or ""
        title = raw.get("title") or content.get("title") or ""
        priority = raw.get("priority") or raw.get("Priority") or field_value(raw, "Priority")
        status = raw.get("status") or raw.get("Status") or field_value(raw, "Status")
        return ProjectItem(
            id=str(raw.get("id") or ""),
            title=title,
            status=str(status or ""),
            priority=str(priority or ""),
            body=body,
            number=as_int(content.get("number") or raw.get("number")),
            repo=repo,
            url=content.get("url") or raw.get("url") or "",
            labels=labels,
            repositories=parse_repositories(body, repo),
            content_id=str(content.get("id") or raw.get("contentId") or ""),
            content_type=content.get("type") or raw.get("type") or "",
        )

    def move_item(self, item: ProjectItem, status: str) -> None:
        self.set_single_select(item, "Status", status)

    def set_single_select(self, item: ProjectItem, field_name: str, value: str) -> None:
        select_field = self.single_select_field(field_name)
        option = next((option for option in select_field.get("options", []) if option["name"] == value), None)
        if not option:
            raise GitManagerError(f"{field_name} option not found on board: {value}")
        query = """
        mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
          updateProjectV2ItemFieldValue(input: {
            projectId: $project,
            itemId: $item,
            fieldId: $field,
            value: { singleSelectOptionId: $option }
          }) {
            projectV2Item { id }
          }
        }
        """
        self.graphql(
            query,
            {
                "project": self.project()["id"],
                "item": item.id,
                "field": select_field["id"],
                "option": option["id"],
            },
        )

    def create_draft_item(self, title: str, body: str) -> str:
        query = """
        mutation($project: ID!, $title: String!, $body: String!) {
          addProjectV2DraftIssue(input: { projectId: $project, title: $title, body: $body }) {
            projectItem { id }
          }
        }
        """
        data = self.graphql(query, {"project": self.project()["id"], "title": title, "body": body})
        return data["data"]["addProjectV2DraftIssue"]["projectItem"]["id"]

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        args = ["issue", "create", "--repo", f"{self.config.owner}/{repo}", "--title", title, "--body", body]
        for label in labels:
            args.extend(["--label", label])
        return self.gh_text(args)

    def add_issue_url_to_project(self, issue_url: str) -> str:
        issue = self.gh_json(["issue", "view", issue_url, "--json", "id"])
        query = """
        mutation($project: ID!, $content: ID!) {
          addProjectV2ItemById(input: { projectId: $project, contentId: $content }) {
            item { id }
          }
        }
        """
        data = self.graphql(query, {"project": self.project()["id"], "content": issue["id"]})
        return data["data"]["addProjectV2ItemById"]["item"]["id"]

    def comment_on_issue(self, item: ProjectItem, body: str) -> None:
        if not item.repo or not item.number:
            print("Skipping issue comment: item is not linked to a repository issue.")
            return
        self.gh_text(
            ["issue", "comment", str(item.number), "--repo", f"{self.config.owner}/{item.repo}", "--body", body]
        )


def field_value(raw: dict[str, Any], name: str) -> str:
    for field_data in raw.get("fieldValues", []) or raw.get("fields", []):
        if isinstance(field_data, dict) and field_data.get("name", "").lower() == name.lower():
            return str(field_data.get("value") or field_data.get("text") or field_data.get("name") or "")
    return ""


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def repo_name(repository: Any) -> str:
    if isinstance(repository, dict):
        return str(repository.get("name") or repository.get("nameWithOwner", "").split("/")[-1])
    text = str(repository or "")
    return text.split("/")[-1] if text else ""


def parse_repositories(body: str, fallback_repo: str = "") -> list[str]:
    repos: list[str] = []
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if re.match(r"^repositories\s*:\s*$", stripped, flags=re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if not stripped:
                continue
            if re.match(r"^[A-Za-z][\w -]+:\s*$", stripped):
                break
            match = re.match(r"^[-*]\s+(.+)$", stripped)
            if match:
                repos.append(match.group(1).strip())
            else:
                break
    if not repos and fallback_repo:
        repos.append(fallback_repo)
    return unique(repos)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def find_item(client: GitHubProjectClient, query: str) -> ProjectItem:
    items = client.items()
    lowered = query.lower()
    matches = [
        item
        for item in items
        if item.title.lower() == lowered
        or lowered in item.title.lower()
        or (item.number is not None and str(item.number) == query.lstrip("#"))
    ]
    if not matches:
        raise GitManagerError(f"No project item matched: {query}")
    if len(matches) > 1:
        print("Multiple project items matched:")
        for item in matches:
            number = f"#{item.number} " if item.number else ""
            print(f"- {number}{item.title} [{item.status}]")
        raise GitManagerError("Please use a more specific title or issue number.")
    return matches[0]


def branch_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"feature/{slug or 'work-item'}"


def priority_key(item: ProjectItem) -> tuple[int, str]:
    return (PRIORITY_ORDER.get(item.priority, 50), item.title.lower())


def print_item(item: ProjectItem) -> None:
    labels = f" Labels: {', '.join(item.labels)}" if item.labels else ""
    repo_text = ", ".join(item.repositories) if item.repositories else "-"
    print(f"[{item.display_priority}] {item.title}{labels}")
    print(f"Repos: {repo_text}")
    if item.url:
        print(item.url)
    print()


def validate_statuses(client: GitHubProjectClient) -> None:
    actual = client.statuses()
    unknown = [status for status in actual if status not in EXPECTED_STATUSES]
    missing = [status for status in EXPECTED_STATUSES if status not in actual]
    if unknown:
        print("Warning: board has unexpected statuses: " + ", ".join(unknown))
    if missing:
        print("Warning: expected statuses missing from board: " + ", ".join(missing))


def command_board(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    validate_statuses(client)
    items = client.items()
    print(config.github.project_title)
    print("=" * len(config.github.project_title))
    statuses = client.statuses() or list(EXPECTED_STATUSES)
    by_status = {status: [] for status in statuses}
    for item in items:
        by_status.setdefault(item.status or "No Status", []).append(item)
    for status, status_items in by_status.items():
        print()
        print(status.upper())
        if not status_items:
            print("(empty)")
            continue
        for item in sorted(status_items, key=priority_key):
            print_item(item)


def command_next(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    items = [item for item in client.items() if item.status in READY_STATUSES]
    for status in READY_STATUSES:
        print(status.upper())
        status_items = sorted([item for item in items if item.status == status], key=priority_key)
        if not status_items:
            print("(empty)\n")
            continue
        for item in status_items:
            print_item(item)


def resolve_repos(config: AppConfig, item: ProjectItem, requested: list[str] | None) -> list[RepoConfig]:
    names = requested or item.repositories
    if not names:
        print("Affected repositories are unknown.")
        available = sorted(config.repositories)
        for index, repo in enumerate(available, start=1):
            print(f"{index}. {repo}")
        chosen = input("Choose repos by number or name, separated by spaces: ").strip().split()
        names = [available[int(value) - 1] if value.isdigit() else value for value in chosen]
    missing = [name for name in names if name not in config.repositories]
    if missing:
        raise GitManagerError("Unknown local repositories: " + ", ".join(missing))
    return [config.repositories[name] for name in unique(names)]


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def command_start(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    item = find_item(client, args.item)
    repos = resolve_repos(config, item, args.repos)
    branch = branch_name(item.title)

    print(f"Work item: {item.title}")
    print("Repositories: " + ", ".join(repo.name for repo in repos))
    print(f"Branch: {branch}")
    if ask_yes_no("Move board item to In Progress?", default=True):
        client.move_item(item, "In Progress")
        print("Moved board item to In Progress.")
    if ask_yes_no("Create/switch to this branch in affected repos?", default=False):
        for repo in repos:
            ensure_git_repo(repo)
            run(["git", "switch", "-c", branch], cwd=repo.path, check=False)
            current = run(["git", "branch", "--show-current"], cwd=repo.path).stdout.strip()
            if current != branch:
                run(["git", "switch", branch], cwd=repo.path)
            print(f"{repo.name}: {branch}")


def ensure_git_repo(repo: RepoConfig) -> None:
    if not (repo.path / ".git").exists():
        raise GitManagerError(f"Not a git repository: {repo.path}")


def git_status(repo: RepoConfig) -> tuple[bool, bool, str]:
    ensure_git_repo(repo)
    status = run(["git", "status", "--short"], cwd=repo.path).stdout.strip()
    uncommitted = bool(status)
    upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=repo.path, check=False)
    unpushed = False
    if upstream.returncode == 0:
        count = run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=repo.path).stdout.strip()
        unpushed = int(count or "0") > 0
    return uncommitted, unpushed, status


def command_finish(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    item = find_item(client, args.item)
    repos = resolve_repos(config, item, args.repos)
    target_status = args.status
    blocked = False

    for repo in repos:
        uncommitted, unpushed, status = git_status(repo)
        print(f"{repo.name}:")
        print(status or "clean")
        if uncommitted:
            print("Blocked: uncommitted changes present.")
            blocked = True
        if unpushed:
            print("Blocked: unpushed commits present.")
            blocked = True
        if args.run_tests:
            if not repo.test_command:
                print("No test_command configured.")
            else:
                print(f"Running: {repo.test_command}")
                result = run_shell(repo.test_command, repo.path, check=False)
                print(result.stdout.strip())
                if result.returncode != 0:
                    print(result.stderr.strip())
                    print("Blocked: test/build command failed.")
                    blocked = True
        print()

    if target_status == "Done" and blocked:
        raise GitManagerError("Refusing to move item to Done until safety checks pass.")

    if not ask_yes_no(f"Move board item to {target_status}?", default=target_status == "Review"):
        print("Board item not moved.")
        return
    client.move_item(item, target_status)
    print(f"Moved board item to {target_status}.")

    if args.comment:
        summary = input("Issue comment summary: ").strip()
        if summary:
            client.comment_on_issue(item, summary)
            print("Posted issue comment.")


def command_move(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    item = find_item(client, args.item)
    if args.status == "Done":
        repos = resolve_repos(config, item, args.repos)
        for repo in repos:
            uncommitted, unpushed, _ = git_status(repo)
            if uncommitted or unpushed:
                raise GitManagerError("Refusing to move to Done while affected repos are dirty or unpushed.")
    client.move_item(item, args.status)
    print(f"Moved {item.title} to {args.status}.")


def command_create(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    repos = args.repos or ([args.repo] if args.repo else [])
    body = args.body or ""
    if repos:
        body = body.rstrip() + "\n\nRepositories:\n" + "\n".join(f"- {repo}" for repo in repos) + "\n"
    labels = args.label or []
    if args.repo:
        issue_url = client.create_issue(args.repo, args.title, body, labels)
        print(f"Created issue: {issue_url}")
        item_id = client.add_issue_url_to_project(issue_url)
        print("Added issue to project.")
        item = ProjectItem(id=item_id, title=args.title)
    else:
        item_id = client.create_draft_item(args.title, body)
        print("Created draft project item.")
        item = ProjectItem(id=item_id, title=args.title)
    if args.priority:
        try:
            client.set_single_select(item, "Priority", args.priority)
            print(f"Set priority to {args.priority}.")
        except GitManagerError as exc:
            print(f"Warning: {exc}")
    if args.status:
        client.move_item(item, args.status)
        print(f"Moved item to {args.status}.")


def command_doctor(args: argparse.Namespace) -> None:
    config = load_config()
    client = GitHubProjectClient(config.github)
    checks: list[tuple[str, bool, str]] = []
    checks.append(("git installed", bool(shutil.which("git")), "Install git."))
    checks.append(("gh installed", bool(shutil.which("gh")), "Install GitHub CLI: https://cli.github.com/"))
    checks.append(("gh authenticated", client.auth_status(), "Run: gh auth login"))
    checks.append(("root directory exists", config.root_dir.exists(), str(config.root_dir)))
    checks.append(("repositories found", bool(config.repositories), "No nested git repositories found."))
    for repo in sorted(config.repositories.values(), key=lambda value: value.name):
        remote = run(["git", "remote"], cwd=repo.path, check=False)
        checks.append((f"{repo.name} remotes exist", bool(remote.stdout.strip()), "Run: git remote add origin ..."))
    project_ok = False
    statuses_ok = False
    try:
        project = client.project()
        project_ok = bool(project)
        statuses = client.statuses()
        statuses_ok = bool(statuses)
    except Exception as exc:
        checks.append(("GitHub project can be read", False, str(exc)))
    else:
        checks.append(("GitHub project can be read", project_ok, project.get("title", "")))
        checks.append(("project statuses found", statuses_ok, ", ".join(statuses)))

    failed = False
    for label, ok, detail in checks:
        marker = "OK" if ok else "FAIL"
        print(f"{marker:4} {label}")
        if detail and not ok:
            print(f"     {detail}")
        failed = failed or not ok
    if project_ok and statuses_ok:
        validate_statuses(client)
    if failed:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gm", description="Manage Job Seeker Copilot repos and GitHub Project work.")
    sub = parser.add_subparsers(dest="command", required=True)

    board = sub.add_parser("board", help="Show the GitHub Project board.")
    board.set_defaults(func=command_board)

    next_parser = sub.add_parser("next", help="Show Ready and Backlog work.")
    next_parser.set_defaults(func=command_next)

    start = sub.add_parser("start", help="Start work on a project item.")
    start.add_argument("item")
    start.add_argument("--repos", nargs="+")
    start.set_defaults(func=command_start)

    finish = sub.add_parser("finish", help="Finish work on a project item.")
    finish.add_argument("item")
    finish.add_argument("--repos", nargs="+")
    finish.add_argument("--run-tests", action="store_true")
    finish.add_argument("--status", choices=["Review", "Done"], default="Review")
    finish.add_argument("--comment", action="store_true")
    finish.set_defaults(func=command_finish)

    move = sub.add_parser("move", help="Move a project item to a status.")
    move.add_argument("item")
    move.add_argument("status", choices=EXPECTED_STATUSES)
    move.add_argument("--repos", nargs="+")
    move.set_defaults(func=command_move)

    create = sub.add_parser("create", help="Create an issue or draft project item.")
    create.add_argument("title")
    create.add_argument("--repo")
    create.add_argument("--repos", nargs="+")
    create.add_argument("--label", action="append")
    create.add_argument("--priority", choices=["Critical", "High", "Medium", "Low"])
    create.add_argument("--status", choices=EXPECTED_STATUSES, default="Backlog")
    create.add_argument("--body")
    create.set_defaults(func=command_create)

    doctor = sub.add_parser("doctor", help="Check local and GitHub setup.")
    doctor.set_defaults(func=command_doctor)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        detail = stderr or stdout or str(exc)
        raise SystemExit(f"Error: {detail}") from exc
    except GitManagerError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
