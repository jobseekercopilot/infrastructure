#!/usr/bin/env python3
"""Prove that production RDS Enhanced Monitoring stays enabled after apply.

Terraform can report a successful asynchronous DB modification before Amazon
RDS later rejects the monitoring role and reverts ``MonitoringInterval`` to
zero. This verifier observes multiple consecutive live samples and scans the
DB-instance events emitted since the corresponding saved-plan apply began. A
release cannot pass on a transient value or after a recurring role failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable


class LiveRdsMonitoringError(ValueError):
    """The live RDS monitoring state is malformed or violates the contract."""


class MonitoringNotReady(LiveRdsMonitoringError):
    """The eventual RDS monitoring state has not reached the contract yet."""


JsonObject = dict[str, Any]
AwsReader = Callable[[list[str]], JsonObject]
Sleeper = Callable[[float], None]

EXPECTED_DB_IDENTIFIER = "jsc-public-beta-postgres"
EXPECTED_MONITORING_INTERVAL = 60
FAILURE_MESSAGES = (
    # RDS-EVENT-0079: RDS could not create the service-role credentials.
    re.compile(
        r"\bunable\s+to\s+create\s+credentials\s+for\s+enhanced\s+monitoring\b",
        re.IGNORECASE,
    ),
    # RDS-EVENT-0080: the role or its permissions boundary is unusable.
    re.compile(
        r"\bunable\s+to\s+configure\s+enhanced\s+monitoring\b",
        re.IGNORECASE,
    ),
)


def parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveRdsMonitoringError("--not-before must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise LiveRdsMonitoringError("--not-before must include a timezone")
    return parsed.astimezone(timezone.utc)


def aws_json(arguments: list[str]) -> JsonObject:
    result = subprocess.run(
        ["aws", *arguments, "--no-cli-pager", "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or "AWS CLI returned no diagnostic"
        raise LiveRdsMonitoringError(f"AWS RDS monitoring read failed: {diagnostic}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LiveRdsMonitoringError("AWS RDS monitoring read returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LiveRdsMonitoringError("AWS RDS monitoring read returned a non-object")
    return value


def verify_events(events: JsonObject, db_identifier: str, not_before: datetime) -> None:
    if events.get("Marker"):
        raise LiveRdsMonitoringError("RDS event response is incomplete")
    values = events.get("Events")
    if not isinstance(values, list):
        raise LiveRdsMonitoringError("RDS event response omits Events")
    for event in values:
        if not isinstance(event, dict):
            raise LiveRdsMonitoringError("RDS event response contains a malformed event")
        source = event.get("SourceIdentifier")
        source_type = event.get("SourceType")
        message = event.get("Message")
        occurred_at = event.get("Date")
        if source != db_identifier or source_type != "db-instance":
            raise LiveRdsMonitoringError("RDS returned an event for an unexpected DB instance")
        if not isinstance(message, str) or not isinstance(occurred_at, str):
            raise LiveRdsMonitoringError("RDS event omits its message or timestamp")
        event_time = parse_utc_timestamp(occurred_at)
        if event_time >= not_before and any(
            pattern.search(message) for pattern in FAILURE_MESSAGES
        ):
            raise LiveRdsMonitoringError(
                "RDS Enhanced Monitoring configuration failure recurred after apply"
            )


def verify_instance(
    response: JsonObject,
    db_identifier: str,
    monitoring_role_arn: str,
) -> None:
    instances = response.get("DBInstances")
    if not isinstance(instances, list) or len(instances) != 1 or not isinstance(instances[0], dict):
        raise LiveRdsMonitoringError("RDS response must contain exactly one DB instance")
    instance = instances[0]
    if instance.get("DBInstanceIdentifier") != db_identifier:
        raise LiveRdsMonitoringError("RDS returned an unexpected DB instance")
    interval = instance.get("MonitoringInterval")
    role_arn = instance.get("MonitoringRoleArn")
    db_arn = instance.get("DBInstanceArn")
    role_match = re.fullmatch(
        r"arn:aws:iam::([0-9]{12}):role/jsc-public-beta-rds-monitoring",
        monitoring_role_arn,
    )
    if role_match is None or db_arn != (
        f"arn:aws:rds:eu-west-2:{role_match.group(1)}:db:{db_identifier}"
    ):
        raise LiveRdsMonitoringError("RDS instance and monitoring role are not in the exact reviewed account")
    if interval != EXPECTED_MONITORING_INTERVAL:
        raise MonitoringNotReady(
            f"RDS MonitoringInterval is {interval!r}, expected {EXPECTED_MONITORING_INTERVAL}"
        )
    if role_arn != monitoring_role_arn:
        raise MonitoringNotReady("RDS MonitoringRoleArn is not the exact reviewed service role")


def read_sample(
    reader: AwsReader,
    region: str,
    db_identifier: str,
    monitoring_role_arn: str,
    not_before: datetime,
) -> None:
    events = reader([
        "rds", "describe-events",
        "--region", region,
        "--source-type", "db-instance",
        "--source-identifier", db_identifier,
        "--start-time", not_before.isoformat().replace("+00:00", "Z"),
    ])
    # Check failure events before considering a transiently-correct instance
    # value; a recurrence is terminal even if RDS has not reverted yet.
    verify_events(events, db_identifier, not_before)
    instance = reader([
        "rds", "describe-db-instances",
        "--region", region,
        "--db-instance-identifier", db_identifier,
    ])
    verify_instance(instance, db_identifier, monitoring_role_arn)


def verify_stable(
    reader: AwsReader,
    sleeper: Sleeper,
    region: str,
    db_identifier: str,
    monitoring_role_arn: str,
    not_before: datetime,
    required_consecutive: int = 6,
    maximum_attempts: int = 18,
    poll_seconds: float = 10,
) -> None:
    if required_consecutive < 1 or maximum_attempts < required_consecutive or poll_seconds < 0:
        raise LiveRdsMonitoringError("invalid RDS monitoring stability-window configuration")
    consecutive = 0
    last_not_ready: MonitoringNotReady | None = None
    for attempt in range(maximum_attempts):
        try:
            read_sample(reader, region, db_identifier, monitoring_role_arn, not_before)
        except MonitoringNotReady as exc:
            consecutive = 0
            last_not_ready = exc
        else:
            consecutive += 1
            if consecutive >= required_consecutive:
                return
        if attempt + 1 < maximum_attempts:
            sleeper(poll_seconds)
    detail = str(last_not_ready) if last_not_ready is not None else "stable samples were not observed"
    raise LiveRdsMonitoringError(
        f"RDS Enhanced Monitoring did not remain healthy for {required_consecutive} consecutive samples: {detail}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--db-instance-identifier", required=True)
    parser.add_argument("--monitoring-role-arn", required=True)
    parser.add_argument("--not-before", required=True)
    args = parser.parse_args()
    try:
        if args.region != "eu-west-2":
            raise LiveRdsMonitoringError("RDS monitoring verification is restricted to eu-west-2")
        if args.db_instance_identifier != EXPECTED_DB_IDENTIFIER:
            raise LiveRdsMonitoringError("unexpected production DB instance identifier")
        expected_role = re.fullmatch(
            r"arn:aws:iam::[0-9]{12}:role/jsc-public-beta-rds-monitoring",
            args.monitoring_role_arn,
        )
        if expected_role is None:
            raise LiveRdsMonitoringError("unexpected RDS monitoring role ARN")
        verify_stable(
            aws_json,
            time.sleep,
            args.region,
            args.db_instance_identifier,
            args.monitoring_role_arn,
            parse_utc_timestamp(args.not_before),
        )
    except (OSError, LiveRdsMonitoringError) as exc:
        print(f"Live RDS Enhanced Monitoring verification failed: {exc}", file=sys.stderr)
        return 3
    print("Verified RDS Enhanced Monitoring at 60 seconds with no post-apply failure recurrence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
