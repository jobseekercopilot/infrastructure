import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "aws" / "verify_live_rds_monitoring.py"
SPEC = importlib.util.spec_from_file_location("verify_live_rds_monitoring", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)

DB = "jsc-public-beta-postgres"
ROLE = "arn:aws:iam::123456789012:role/jsc-public-beta-rds-monitoring"
START = datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc)


def instance(interval=60, role=ROLE):
    return {
        "DBInstances": [{
            "DBInstanceIdentifier": DB,
            "DBInstanceArn": "arn:aws:rds:eu-west-2:123456789012:db:jsc-public-beta-postgres",
            "MonitoringInterval": interval,
            "MonitoringRoleArn": role,
        }],
    }


def events(message=None, occurred_at="2026-08-23T01:00:01Z"):
    values = [] if message is None else [{
        "SourceIdentifier": DB,
        "SourceType": "db-instance",
        "Date": occurred_at,
        "Message": message,
    }]
    return {"Events": values}


class SequenceReader:
    def __init__(self, instances, event_values=None):
        self.instances = iter(instances)
        self.event_values = iter(event_values or [])
        self.last_events = events()

    def __call__(self, arguments):
        if arguments[1] == "describe-events":
            try:
                self.last_events = next(self.event_values)
            except StopIteration:
                pass
            return self.last_events
        if arguments[1] == "describe-db-instances":
            return next(self.instances)
        raise AssertionError(arguments)


class LiveRdsMonitoringTest(unittest.TestCase):
    def test_six_consecutive_exact_samples_are_required(self):
        sleeps = []
        VERIFIER.verify_stable(
            SequenceReader([instance()] * 6),
            sleeps.append,
            "eu-west-2",
            DB,
            ROLE,
            START,
        )
        self.assertEqual(sleeps, [10] * 5)

    def test_transient_success_followed_by_interval_reversion_fails_closed(self):
        with self.assertRaisesRegex(VERIFIER.LiveRdsMonitoringError, "MonitoringInterval is 0"):
            VERIFIER.verify_stable(
                SequenceReader([instance(), instance(), instance(0), instance(0)]),
                lambda _seconds: None,
                "eu-west-2",
                DB,
                ROLE,
                START,
                required_consecutive=3,
                maximum_attempts=4,
                poll_seconds=0,
            )

    def test_post_apply_enhanced_monitoring_failure_event_is_terminal(self):
        reader = SequenceReader(
            [instance()],
            [events(
                "Amazon RDS has been unable to configure Enhanced Monitoring on your instance: "
                "jsc-public-beta-postgres and this feature has been disabled."
            )],
        )
        with self.assertRaisesRegex(VERIFIER.LiveRdsMonitoringError, "failure recurred"):
            VERIFIER.verify_stable(
                reader,
                lambda _seconds: None,
                "eu-west-2",
                DB,
                ROLE,
                START,
                required_consecutive=1,
                maximum_attempts=1,
                poll_seconds=0,
            )

    def test_credentials_failure_event_is_also_terminal(self):
        with self.assertRaisesRegex(VERIFIER.LiveRdsMonitoringError, "failure recurred"):
            VERIFIER.verify_events(
                events(
                    "Amazon RDS has been unable to create credentials for enhanced monitoring "
                    "and this feature has been disabled."
                ),
                DB,
                START,
            )

    def test_wrong_role_never_satisfies_the_stability_window(self):
        with self.assertRaisesRegex(VERIFIER.LiveRdsMonitoringError, "MonitoringRoleArn"):
            VERIFIER.verify_stable(
                SequenceReader([instance(role="arn:aws:iam::123456789012:role/wrong")] * 2),
                lambda _seconds: None,
                "eu-west-2",
                DB,
                ROLE,
                START,
                required_consecutive=1,
                maximum_attempts=2,
                poll_seconds=0,
            )

    def test_malformed_or_cross_instance_events_are_rejected(self):
        for value in (
            {"Marker": "next", "Events": []},
            {"Events": [{
                "SourceIdentifier": "other",
                "SourceType": "db-instance",
                "Date": "2026-08-23T01:00:01Z",
                "Message": "normal",
            }]},
            {"Events": ["malformed"]},
        ):
            with self.subTest(value=value):
                with self.assertRaises(VERIFIER.LiveRdsMonitoringError):
                    VERIFIER.verify_events(value, DB, START)

    def test_matching_failure_before_apply_does_not_count_as_a_recurrence(self):
        VERIFIER.verify_events(
            events("Unable to configure Enhanced Monitoring", "2026-08-23T00:59:59Z"),
            DB,
            START,
        )

    def test_not_before_requires_an_absolute_timestamp(self):
        self.assertEqual(
            VERIFIER.parse_utc_timestamp("2026-08-23T02:00:00+01:00"),
            START,
        )
        with self.assertRaisesRegex(VERIFIER.LiveRdsMonitoringError, "timezone"):
            VERIFIER.parse_utc_timestamp("2026-08-23T01:00:00")


if __name__ == "__main__":
    unittest.main()
