import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aws" / "verify_account_email_ses.py"
SPEC = importlib.util.spec_from_file_location("verify_account_email_ses", SCRIPT)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)

REGION = "eu-west-2"
ACCOUNT = "123456789012"
CONFIGURATION_SET = "JobSeekerCopilotAccountEmails"
SOURCE_ARN = (
    f"arn:aws:ses:{REGION}:{ACCOUNT}:configuration-set/{CONFIGURATION_SET}"
)
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:jsc-public-beta-operations"
KEY_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/00000000-0000-0000-0000-000000000001"


def policy_statement(action, resource):
    return {
        "Effect": "Allow",
        "Principal": {"Service": "ses.amazonaws.com"},
        "Action": action,
        "Resource": resource,
        "Condition": {
            "StringEquals": {"aws:SourceAccount": ACCOUNT},
            "ArnLike": {"aws:SourceArn": SOURCE_ARN},
        },
    }


def live_state():
    return {
        ("sesv2", "get-account"): {
            "ProductionAccessEnabled": True,
            "SendingEnabled": True,
            "EnforcementStatus": "HEALTHY",
            "SuppressionAttributes": {"SuppressedReasons": ["COMPLAINT", "BOUNCE"]},
        },
        ("sesv2", "get-email-identity"): {
            "IdentityType": "DOMAIN",
            "VerifiedForSendingStatus": True,
            "VerificationStatus": "SUCCESS",
            "DkimAttributes": {"SigningEnabled": True, "Status": "SUCCESS"},
        },
        ("sesv2", "get-configuration-set"): {
            "ConfigurationSetName": CONFIGURATION_SET,
            "SendingOptions": {"SendingEnabled": True},
            "ReputationOptions": {"ReputationMetricsEnabled": True},
            "SuppressionOptions": {"SuppressedReasons": ["BOUNCE", "COMPLAINT"]},
        },
        ("sesv2", "get-configuration-set-event-destinations"): {
            "EventDestinations": [{
                "Name": "account-email-events",
                "Enabled": True,
                "MatchingEventTypes": sorted(VERIFIER.EXPECTED_EVENT_TYPES),
                "SnsDestination": {"TopicArn": TOPIC_ARN},
            }],
        },
        ("sns", "get-topic-attributes"): {
            "Attributes": {
                "TopicArn": TOPIC_ARN,
                "KmsMasterKeyId": KEY_ARN,
                "Policy": json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [policy_statement("sns:Publish", TOPIC_ARN)],
                }),
            },
        },
        ("sns", "list-subscriptions-by-topic"): {
            "Subscriptions": [{
                "SubscriptionArn": f"{TOPIC_ARN}:00000000-0000-0000-0000-000000000002",
                "Owner": ACCOUNT,
                "Protocol": "email",
                "Endpoint": "owner@example.invalid",
                "TopicArn": TOPIC_ARN,
            }],
        },
        ("kms", "get-key-policy"): {
            "Policy": json.dumps({
                "Version": "2012-10-17",
                "Statement": [policy_statement(
                    ["kms:GenerateDataKey*", "kms:Decrypt"], "*"
                )],
            }),
        },
    }


def reader_for(state):
    def reader(arguments):
        return copy.deepcopy(state[(arguments[0], arguments[1])])

    return reader


def verify(state):
    VERIFIER.verify_account_email_ses(
        region=REGION,
        account_id=ACCOUNT,
        identity_domain="jobseekercopilot.com",
        sender="accounts@jobseekercopilot.com",
        configuration_set=CONFIGURATION_SET,
        event_destination="account-email-events",
        topic_arn=TOPIC_ARN,
        reader=reader_for(state),
    )


class AccountEmailLiveVerifierTest(unittest.TestCase):
    def test_accepts_exact_healthy_read_only_contract(self):
        verify(live_state())

    def test_rejects_account_identity_configuration_and_destination_drift(self):
        mutations = (
            (("sesv2", "get-account"), "ProductionAccessEnabled", False, "production access"),
            (("sesv2", "get-account"), "EnforcementStatus", "PROBATION", "HEALTHY"),
            (("sesv2", "get-email-identity"), "VerificationStatus", "FAILED", "identity or DKIM"),
            (("sesv2", "get-configuration-set"), "ConfigurationSetName", "Other", "name does not match"),
        )
        for key, field, value, message in mutations:
            state = live_state()
            state[key][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(VERIFIER.AccountEmailSesError, message):
                    verify(state)

        state = live_state()
        state[("sesv2", "get-configuration-set-event-destinations")]["EventDestinations"][0][
            "MatchingEventTypes"
        ].append("OPEN")
        with self.assertRaisesRegex(VERIFIER.AccountEmailSesError, "event destination"):
            verify(state)

    def test_rejects_unscoped_or_unencrypted_event_publication(self):
        state = live_state()
        state[("sns", "get-topic-attributes")]["Attributes"]["KmsMasterKeyId"] = "alias/aws/sns"
        with self.assertRaisesRegex(VERIFIER.AccountEmailSesError, "customer-managed"):
            verify(state)

        for service in ("sns", "kms"):
            state = live_state()
            key = (service, "get-topic-attributes" if service == "sns" else "get-key-policy")
            document_field = "Policy" if service == "kms" else "Policy"
            if service == "sns":
                container = state[key]["Attributes"]
            else:
                container = state[key]
            policy = json.loads(container[document_field])
            policy["Statement"][0]["Condition"]["ArnLike"]["aws:SourceArn"] = (
                f"arn:aws:ses:{REGION}:{ACCOUNT}:configuration-set/*"
            )
            container[document_field] = json.dumps(policy)
            with self.subTest(service=service):
                with self.assertRaisesRegex(VERIFIER.AccountEmailSesError, "does not allow"):
                    verify(state)

    def test_requires_exactly_one_confirmed_email_subscription_without_exposing_endpoint(self):
        mutations = (
            ([], "exactly one confirmed"),
            ([
                *live_state()[("sns", "list-subscriptions-by-topic")]["Subscriptions"],
                {
                    "SubscriptionArn": f"{TOPIC_ARN}:00000000-0000-0000-0000-000000000003",
                    "Owner": ACCOUNT,
                    "Protocol": "email",
                    "Endpoint": "second@example.invalid",
                    "TopicArn": TOPIC_ARN,
                },
            ], "exactly one confirmed"),
        )
        for subscriptions, message in mutations:
            state = live_state()
            state[("sns", "list-subscriptions-by-topic")]["Subscriptions"] = subscriptions
            with self.subTest(count=len(subscriptions)):
                with self.assertRaisesRegex(VERIFIER.AccountEmailSesError, message):
                    verify(state)

        for field, value in (
            ("SubscriptionArn", "PendingConfirmation"),
            ("Protocol", "https"),
            ("Endpoint", ""),
            ("TopicArn", "arn:aws:sns:eu-west-2:123456789012:other"),
        ):
            state = live_state()
            state[("sns", "list-subscriptions-by-topic")]["Subscriptions"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    VERIFIER.AccountEmailSesError, "subscription is not confirmed"
                ) as raised:
                    verify(state)
                self.assertNotIn("example.invalid", str(raised.exception))

    def test_release_script_verifies_without_any_send_command(self):
        verifier_source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('"send-email"', verifier_source)
        self.assertNotIn('"send-raw-email"', verifier_source)

        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(
            encoding="utf-8"
        )
        foundation = release.split("  foundation)", 1)[1].split("    ;;", 1)[0]
        self.assertLess(foundation.index("plan_and_apply 0 false foundation"), foundation.index(
            "verify_account_email_ses"
        ))
        prepare = release.split("prepare_private_fleet() {", 1)[1].split("\n}", 1)[0]
        self.assertLess(prepare.index('plan_and_apply 0 false "${verb,,}-dark"'), prepare.index(
            "verify_account_email_ses"
        ))
        self.assertLess(prepare.index("verify_account_email_ses"), prepare.index("seed-runtime-secrets.sh"))
        activate = release.split("  activate)", 1)[1].split("    ;;", 1)[0]
        self.assertLess(activate.index("verify_account_email_ses"), activate.index("plan_and_apply 1 true activate"))


if __name__ == "__main__":
    unittest.main()
