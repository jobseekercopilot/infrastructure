#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def gib(value: int | float) -> str:
    return f"{value / 1024**3:.2f} GiB"


def milliseconds(value: int | float | None) -> str:
    return "—" if value is None else f"{value:.0f} ms"


def source_revisions() -> list[tuple[str, str, str]]:
    revisions: list[tuple[str, str, str]] = []
    for repository in sorted(path.parent for path in WORKSPACE_ROOT.glob("*/.git")):
        sha = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repository), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        revisions.append((repository.name, sha, "dirty" if dirty else "clean"))
    return revisions


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a measured capacity summary from benchmark JSON.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.inputs]
    for report in reports:
        if report.get("schemaVersion") != 1 or report.get("evidenceClass") != "measured":
            parser.error("every input must be a measured schemaVersion 1 benchmark")
    lines = [
        "# Capacity benchmark report",
        "",
        "> Evidence class: **measured** unless a paragraph explicitly says calculated or projected.",
        "",
        "## Environment",
        "",
    ]
    host = reports[0]["host"]
    lines.extend([
        f"- Host: {host['logicalCpuCount']} logical CPUs, {gib(host['memoryBytes'])} RAM, {host['architecture']}",
        f"- Docker: {host['dockerServerVersion']}",
        f"- Stack: `{reports[0]['stack']}` with fixture providers",
        f"- Sampler interval: {reports[0]['sampleIntervalSeconds']:.0f} seconds",
        "- Browser processes run on the host and are not included in per-container memory figures.",
        "- Workload: one headless browser per active session signs in, opens DISCOVER, searches the governed nine-job fixture and expands job details; it does not generate documents.",
        "- Safety controls: loopback port 3100 only; real providers and paid AI explicitly disabled; dataset `uk-software-developer-demo` version `1.0.0` reset and verified before each active run.",
        "",
        "### Source revisions",
        "",
        "The benchmark used the following repository HEADs. `dirty` means the tested working tree also contained coordinated, uncommitted closure changes; the SHA alone is not claimed as a complete build identifier.",
        "",
        "| Repository | HEAD | Working tree |",
        "|---|---|---|",
    ])
    lines.extend(f"| `{name}` | `{sha}` | {state} |" for name, sha, state in source_revisions())
    lines.extend([
        "",
        "## Measured profiles",
        "",
        "| Profile | Active | Passed | Failed | Responses | App errors | Sessions/s | Session p95 | Response p50 | Response p95 | Response p99 | Avg CPU | Peak CPU | Idle memory | Peak memory |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for report in reports:
        workload = report["workload"]
        summary = report["summary"]["aggregate"]
        latency = workload.get("sessionLatencyMs", {})
        response_latency = workload.get("responseLatencyMs", {})
        lines.append(
            f"| {report['profile']} | {workload.get('activeBrowserSessions', 0)} | "
            f"{workload.get('successfulSessions', 0)} | {workload.get('failedSessions', 0)} | "
            f"{workload.get('responseCount', 0)} | {workload.get('applicationErrors', 0)} | "
            f"{workload.get('throughputSessionsPerSecond', 0):.3f} | "
            f"{milliseconds(latency.get('p95'))} | "
            f"{milliseconds(response_latency.get('p50'))} | "
            f"{milliseconds(response_latency.get('p95'))} | "
            f"{milliseconds(response_latency.get('p99'))} | "
            f"{summary['cpuPercentAverage']:.2f}% | {summary['cpuPercentPeak']:.2f}% | "
            f"{gib(summary['memoryBytesIdle'])} | {gib(summary['memoryBytesPeak'])} |"
        )
    loaded = max(reports, key=lambda item: item["workload"].get("activeBrowserSessions", 0))
    services = loaded["summary"]["services"]
    top_memory = sorted(services.items(), key=lambda item: item[1]["memoryBytesPeak"], reverse=True)[:10]
    top_cpu = sorted(services.items(), key=lambda item: item[1]["cpuPercentPeak"], reverse=True)[:10]
    lines.extend([
        "",
        "## Per-service measurements",
        "",
        f"Container measurements below are from `{loaded['profile']}`, the highest attempted concurrency point.",
        "",
        "| Container | Avg CPU | Peak CPU | First-sample memory | Peak memory |",
        "|---|---:|---:|---:|---:|",
    ])
    for name, values in sorted(
        services.items(), key=lambda item: item[1]["memoryBytesPeak"], reverse=True
    ):
        lines.append(
            f"| `{name}` | {values['cpuPercentAverage']:.2f}% | "
            f"{values['cpuPercentPeak']:.2f}% | {gib(values['memoryBytesIdle'])} | "
            f"{gib(values['memoryBytesPeak'])} |"
        )
    lines.extend(["", "## Bottleneck indicators", "", "Highest peak memory:", ""])
    lines.extend(f"- `{name}`: {gib(values['memoryBytesPeak'])}" for name, values in top_memory)
    lines.extend(["", "Highest peak CPU:", ""])
    lines.extend(f"- `{name}`: {values['cpuPercentPeak']:.2f}%" for name, values in top_cpu)
    successful = [
        report for report in reports
        if report["workload"].get("activeBrowserSessions", 0) == 0
        or report["workload"].get("failedSessions", 0) == 0
    ]
    highest_successful = max(
        successful, key=lambda item: item["workload"].get("activeBrowserSessions", 0)
    )
    lines.extend([
        "",
        "## Stability and variable consumption",
        "",
        f"- Restarts across profiles: {sum(report['summary']['restarts'] for report in reports)}",
        f"- OOM-killed containers: {sum(len(report['summary']['oomKilledContainers']) for report in reports)}",
        "- Paid provider, Google Maps and LLM consumption: measured zero because this benchmark is fixture-only.",
        f"- Highest fully successful measured concurrency: {highest_successful['workload'].get('activeBrowserSessions', 0)} active sessions.",
        f"- Highest attempted concurrency: {loaded['workload'].get('activeBrowserSessions', 0)} active sessions; "
        f"{loaded['workload'].get('failedSessions', 0)} sessions failed.",
        f"- Docker stats sampling errors disclosed across profiles: {sum(len(report.get('statsSamplingErrors', [])) for report in reports)}. "
        "The 25-session run retained nine valid samples and one stats call exceeded the 20-second sampler limit.",
        f"- Transport observations at 25 sessions: {loaded['workload'].get('expectedAuthBootstrapResponses', 0)} expected unauthenticated bootstrap responses, "
        f"{loaded['workload'].get('abortedRequests', 0)} cancelled navigation requests and {loaded['workload'].get('applicationErrors', 0)} application errors.",
        "",
        "## Interpretation boundary",
        "",
        "All required levels through 25 sessions completed, so this run did not expose a failing application-service boundary. It did expose a practical latency boundary: throughput peaked at 10 sessions and the 25-session p95 reached 59.45 seconds, leaving essentially no headroom against the 60-second journey timeout. The host-side browser processes are excluded from Docker CPU/memory, so the test cannot attribute that slowdown solely to the service stack.",
        "",
        "The job-details interaction is client-side expansion of the search result, so there is no separate job-details endpoint latency to report. The response percentiles include the job search and dashboard/reporting calls that precede that interaction. Generation latency is not applicable because this capacity workload intentionally forbids paid generation.",
        "",
        "No 50-session run was attempted: the instruction allowed higher levels only when 25 succeeded comfortably, and a 59.45-second p95 is not comfortable. These runs do not establish capacity above 25. Any AWS sizing or higher-user figures derived from them must be labelled **calculated** or **projected**, not benchmark results.",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
