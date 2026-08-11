#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.docker.stack_config import stack_for
from scripts.lib.project_paths import INFRASTRUCTURE_ROOT, WORKSPACE_ROOT

CONFIG_PATH = INFRASTRUCTURE_ROOT / "config" / "capacity-workloads.json"
DEFAULT_RESULTS_ROOT = INFRASTRUCTURE_ROOT / "benchmark-results" / "runs"
E2E_ROOT = WORKSPACE_ROOT / "e2e"
BYTE_UNITS = {
    "B": 1,
    "kB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_size(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", value)
    if not match or match.group(2) not in BYTE_UNITS:
        raise ValueError(f"unsupported Docker size: {value}")
    return round(float(match.group(1)) * BYTE_UNITS[match.group(2)])


def parse_pair(value: str) -> tuple[int, int]:
    left, right = value.split("/", 1)
    return parse_size(left), parse_size(right)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * quantile + 0.999999) - 1))]


def run(
    command: list[str],
    *,
    cwd: Path,
    capture: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=False,
        timeout=timeout,
    )


def compose_container_ids(project: str) -> list[str]:
    result = run(
        ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.ID}}"],
        cwd=INFRASTRUCTURE_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker ps failed")
    identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not identifiers:
        raise RuntimeError(f"no running containers found for Compose project {project}")
    return identifiers


def collect_stats(container_ids: list[str]) -> list[dict[str, object]]:
    try:
        result = run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *container_ids],
            cwd=INFRASTRUCTURE_ROOT,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("docker stats exceeded the 20-second sampling limit") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker stats failed")
    samples: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        memory_used, memory_limit = parse_pair(raw["MemUsage"])
        network_rx, network_tx = parse_pair(raw["NetIO"])
        block_read, block_write = parse_pair(raw["BlockIO"])
        samples.append({
            "container": raw["Name"],
            "cpuPercent": float(raw["CPUPerc"].rstrip("%")),
            "memoryUsedBytes": memory_used,
            "memoryLimitBytes": memory_limit,
            "memoryPercent": float(raw["MemPerc"].rstrip("%")),
            "networkRxBytes": network_rx,
            "networkTxBytes": network_tx,
            "blockReadBytes": block_read,
            "blockWriteBytes": block_write,
            "pids": int(raw["PIDs"]),
        })
    return samples


def inspect_containers(container_ids: list[str]) -> list[dict[str, object]]:
    result = run(["docker", "inspect", "--size", *container_ids], cwd=INFRASTRUCTURE_ROOT)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker inspect failed")
    inspected = json.loads(result.stdout)
    return [{
        "container": item["Name"].lstrip("/"),
        "image": item["Config"]["Image"],
        "startedAt": item["State"].get("StartedAt"),
        "restartCount": item.get("RestartCount", 0),
        "oomKilled": item["State"].get("OOMKilled", False),
        "status": item["State"].get("Status"),
        "health": item["State"].get("Health", {}).get("Status"),
        "writableLayerBytes": item.get("SizeRw"),
    } for item in inspected]


def host_specification() -> dict[str, object]:
    memory_kib = 0
    with Path("/proc/meminfo").open(encoding="utf-8") as source:
        for line in source:
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
    docker = run(["docker", "version", "--format", "{{.Server.Version}}"], cwd=INFRASTRUCTURE_ROOT)
    return {
        "operatingSystem": platform.platform(),
        "architecture": platform.machine(),
        "logicalCpuCount": os.cpu_count(),
        "memoryBytes": memory_kib * 1024,
        "dockerServerVersion": docker.stdout.strip() if docker.returncode == 0 else "unavailable",
    }


def summarise(samples: list[dict[str, object]], final_inspection: list[dict[str, object]]) -> dict[str, object]:
    by_container: dict[str, list[dict[str, object]]] = {}
    for sample in samples:
        for container in sample["containers"]:
            by_container.setdefault(container["container"], []).append(container)
    services = {}
    for name, observations in sorted(by_container.items()):
        cpu = [float(item["cpuPercent"]) for item in observations]
        memory = [int(item["memoryUsedBytes"]) for item in observations]
        services[name] = {
            "samples": len(observations),
            "cpuPercentAverage": mean(cpu),
            "cpuPercentPeak": max(cpu),
            "memoryBytesAverage": round(mean(memory)),
            "memoryBytesPeak": max(memory),
            "memoryBytesIdle": memory[0],
            "networkRxBytesEnd": observations[-1]["networkRxBytes"],
            "networkTxBytesEnd": observations[-1]["networkTxBytes"],
            "blockReadBytesEnd": observations[-1]["blockReadBytes"],
            "blockWriteBytesEnd": observations[-1]["blockWriteBytes"],
        }
    aggregate_memory = [sum(int(item["memoryUsedBytes"]) for item in sample["containers"]) for sample in samples]
    aggregate_cpu = [sum(float(item["cpuPercent"]) for item in sample["containers"]) for sample in samples]
    return {
        "sampleCount": len(samples),
        "aggregate": {
            "cpuPercentAverage": mean(aggregate_cpu) if aggregate_cpu else 0,
            "cpuPercentPeak": max(aggregate_cpu, default=0),
            "memoryBytesAverage": round(mean(aggregate_memory)) if aggregate_memory else 0,
            "memoryBytesPeak": max(aggregate_memory, default=0),
            "memoryBytesIdle": aggregate_memory[0] if aggregate_memory else 0,
        },
        "services": services,
        "restarts": sum(int(item["restartCount"]) for item in final_inspection),
        "oomKilledContainers": [item["container"] for item in final_inspection if item["oomKilled"]],
        "unhealthyContainers": [
            item["container"] for item in final_inspection
            if item["status"] != "running" or item["health"] not in (None, "healthy")
        ],
    }


def load_profiles() -> dict[str, dict[str, object]]:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1:
        raise RuntimeError("capacity workload schemaVersion must be 1")
    return document["profiles"]


def main() -> int:
    profiles = load_profiles()
    parser = argparse.ArgumentParser(description="Measure the isolated fixture stack during a repeatable workload.")
    parser.add_argument("--profile", choices=sorted(profiles), required=True)
    parser.add_argument("--sample-interval", type=float, default=2.0)
    parser.add_argument("--duration", type=int, help="Override idle duration in seconds.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start-stack", action="store_true")
    parser.add_argument("--allow-high-concurrency", action="store_true")
    args = parser.parse_args()
    if args.sample_interval < 1 or args.sample_interval > 30:
        parser.error("--sample-interval must be from 1 to 30 seconds")

    profile = profiles[args.profile]
    if profile.get("requiresHighConcurrencyApproval") and not args.allow_high_concurrency:
        parser.error("this profile requires --allow-high-concurrency after checking host headroom")
    stack = stack_for("e2e")
    if args.start_stack:
        start = run([sys.executable, "-m", "scripts.docker.start_stack", "e2e"], cwd=INFRASTRUCTURE_ROOT, capture=False)
        if start.returncode != 0:
            return start.returncode
    wait = run([sys.executable, "-m", "scripts.docker.wait_for_stack", "e2e"], cwd=INFRASTRUCTURE_ROOT, capture=False)
    if wait.returncode != 0:
        return wait.returncode
    fixture = run([sys.executable, "-m", "scripts.demo.check_fixture_modes"], cwd=INFRASTRUCTURE_ROOT, capture=False)
    if fixture.returncode != 0:
        raise RuntimeError("fixture-mode preflight failed; no benchmark was run")
    if profile["kind"] != "idle":
        prepare = run(
            [
                sys.executable,
                "-m",
                "scripts.demo.prepare_demo",
                "--skip-start",
                "--skip-smoke",
            ],
            cwd=INFRASTRUCTURE_ROOT,
            capture=False,
        )
        if prepare.returncode != 0:
            raise RuntimeError("deterministic DEMO_READY preparation failed; no workload was run")

    container_ids = compose_container_ids(stack.project)
    before = inspect_containers(container_ids)
    samples: list[dict[str, object]] = []
    stop = threading.Event()
    collector_errors: list[dict[str, str]] = []

    def collect() -> None:
        while not stop.is_set():
            try:
                samples.append({"capturedAt": utc_now(), "containers": collect_stats(container_ids)})
            except Exception as exc:  # preserve measured samples and disclose transient sampler failures
                collector_errors.append({"capturedAt": utc_now(), "error": str(exc)})
            stop.wait(args.sample_interval)

    output = args.output or DEFAULT_RESULTS_ROOT / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{args.profile}.json"
    output = output.resolve()
    allowed = (INFRASTRUCTURE_ROOT / "benchmark-results").resolve()
    if output != allowed and allowed not in output.parents:
        parser.error("--output must remain under infrastructure/benchmark-results/")
    output.parent.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    workload: dict[str, object]
    try:
        if profile["kind"] == "idle":
            duration = args.duration or int(profile["durationSeconds"])
            time.sleep(duration)
            workload = {"kind": "idle", "durationSeconds": duration}
        else:
            workload_path = E2E_ROOT / "test-results" / "capacity" / "benchmark" / f"{output.stem}-workload.json"
            workload_path.parent.mkdir(parents=True, exist_ok=True)
            environment = {
                **os.environ,
                "E2E_BASE_URL": stack.frontend_url,
                "ALLOW_CAPACITY_E2E": "true",
                "CAPACITY_FIXTURE_CONFIRMED": "true",
                "ALLOW_REAL_PROVIDER_E2E": "false",
                "ALLOW_AI_GENERATION": "false",
                "SKIP_DEMO_PREP": "true",
            }
            command = [
                "node", "scripts/run-capacity-workload.js",
                "--users", str(profile["concurrency"]),
                "--iterations", str(profile["iterations"]),
                "--output", str(workload_path.relative_to(E2E_ROOT)),
            ]
            completed = subprocess.run(command, cwd=E2E_ROOT, env=environment, text=True, capture_output=True)
            if workload_path.exists():
                workload = json.loads(workload_path.read_text(encoding="utf-8"))
            else:
                workload = {"kind": "browser", "exitCode": completed.returncode}
            workload["runnerExitCode"] = completed.returncode
            if completed.returncode != 0:
                workload["runnerError"] = (completed.stderr or completed.stdout)[-2000:]
    finally:
        stop.set()
        thread.join(timeout=25)
    if thread.is_alive():
        collector_errors.append({
            "capturedAt": utc_now(),
            "error": "stats collector did not stop within 25 seconds",
        })
    if not samples:
        try:
            samples.append({"capturedAt": utc_now(), "containers": collect_stats(container_ids)})
        except Exception as exc:
            collector_errors.append({"capturedAt": utc_now(), "error": str(exc)})
            raise RuntimeError("no Docker resource samples were captured") from exc
    after = inspect_containers(container_ids)
    report = {
        "schemaVersion": 1,
        "evidenceClass": "measured",
        "profile": args.profile,
        "stack": stack.project,
        "providerMode": "fixture",
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "sampleIntervalSeconds": args.sample_interval,
        "statsSamplingErrors": collector_errors,
        "host": host_specification(),
        "containerStateBefore": before,
        "containerStateAfter": after,
        "workload": workload,
        "externalConsumption": {
            "mode": "fixture",
            "llmRequests": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "paidJobProviderRequests": 0,
            "googleMapsRequests": 0,
            "note": "Fixture workload; these are measured as zero paid external calls, not estimates of live usage."
        },
        "summary": summarise(samples, after),
        "samples": samples,
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    print(output)
    if workload.get("runnerExitCode", 0) != 0 or report["summary"]["oomKilledContainers"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
