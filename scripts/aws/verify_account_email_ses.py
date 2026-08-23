#!/usr/bin/env python3
"""Verify the live account-email SES boundary without sending an email."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any


class AccountEmailSesError(ValueError):
    """Live SES/SNS/KMS state does not match the reviewed release contract."""


JsonObject = dict[str, Any]
AwsReader = Callable[[list[str]], JsonObject]

EXPECTED_EVENT_TYPES = {
    "BOUNCE",
    "COMPLAINT",
    "DELIVERY",
    "DELIVERY_DELAY",
    "REJECT",
    "SEND",
}


def aws_json(arguments: list[str]) -> JsonObject:
    result = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or "AWS CLI returned no diagnostic"
        raise AccountEmailSesError(f"AWS read failed: {diagnostic}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AccountEmailSesError("AWS read returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AccountEmailSesError("AWS read returned a non-object")
    return value


def string_set(value: Any, label: str) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    raise AccountEmailSesError(f"{label} is malformed")


def policy_document(value: Any, label: str) -> JsonObject:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AccountEmailSesError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AccountEmailSesError(f"{label} is not an object")
    return value


def policy_statements(document: JsonObject, label: str) -> list[JsonObject]:
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not all(isinstance(item, dict) for item in statements):
        raise AccountEmailSesError(f"{label} statements are malformed")
    return statements


def service_principals(statement: JsonObject) -> set[str]:
    principal = statement.get("Principal")
    if not isinstance(principal, dict) or "Service" not in principal:
        return set()
    return string_set(principal["Service"], "policy service principal")


def source_conditions_match(statement: JsonObject, account_id: str, source_arn: str) -> bool:
    conditions = statement.get("Condition")
    if not isinstance(conditions, dict):
        return False
    string_equals = conditions.get("StringEquals")
    arn_like = conditions.get("ArnLike")
    return (
        isinstance(string_equals, dict)
        and string_equals.get("aws:SourceAccount") == account_id
        and isinstance(arn_like, dict)
        and arn_like.get("aws:SourceArn") == source_arn
    )


def verify_publish_policies(
    topic: JsonObject,
    key: JsonObject,
    *,
    account_id: str,
    source_arn: str,
    topic_arn: str,
) -> None:
    attributes = topic.get("Attributes")
    if not isinstance(attributes, dict) or attributes.get("TopicArn") != topic_arn:
        raise AccountEmailSesError("operations topic ARN does not match the release contract")
    key_id = attributes.get("KmsMasterKeyId")
    if not isinstance(key_id, str) or not key_id or key_id == "alias/aws/sns":
        raise AccountEmailSesError("operations topic must use the retained customer-managed notification key")

    topic_policy = policy_document(attributes.get("Policy"), "operations topic policy")
    topic_allows = any(
        statement.get("Effect") == "Allow"
        and "ses.amazonaws.com" in service_principals(statement)
        and "sns:Publish" in string_set(statement.get("Action"), "topic policy action")
        and topic_arn in string_set(statement.get("Resource"), "topic policy resource")
        and source_conditions_match(statement, account_id, source_arn)
        for statement in policy_statements(topic_policy, "operations topic policy")
    )
    if not topic_allows:
        raise AccountEmailSesError("operations topic does not allow the exact SES configuration set to publish")

    key_policy = policy_document(key.get("Policy"), "notification key policy")
    key_allows = any(
        statement.get("Effect") == "Allow"
        and "ses.amazonaws.com" in service_principals(statement)
        and {"kms:Decrypt", "kms:GenerateDataKey*"}.issubset(
            string_set(statement.get("Action"), "key policy action")
        )
        and "*" in string_set(statement.get("Resource"), "key policy resource")
        and source_conditions_match(statement, account_id, source_arn)
        for statement in policy_statements(key_policy, "notification key policy")
    )
    if not key_allows:
        raise AccountEmailSesError("notification key does not allow the exact SES configuration set")


def verify_confirmed_operations_subscription(value: Any, topic_arn: str) -> None:
    subscriptions = value.get("Subscriptions") if isinstance(value, dict) else None
    if not isinstance(subscriptions, list) or len(subscriptions) != 1:
        raise AccountEmailSesError("operations topic must have exactly one confirmed email subscription")
    subscription = subscriptions[0]
    if not isinstance(subscription, dict):
        raise AccountEmailSesError("operations topic subscription is malformed")
    subscription_arn = subscription.get("SubscriptionArn")
    endpoint = subscription.get("Endpoint")
    if (
        subscription.get("TopicArn") != topic_arn
        or subscription.get("Protocol") != "email"
        or not isinstance(subscription_arn, str)
        or not subscription_arn.startswith(f"{topic_arn}:")
        or subscription_arn in {"PendingConfirmation", "Deleted"}
        or not isinstance(endpoint, str)
        or not endpoint.strip()
    ):
        raise AccountEmailSesError("operations topic email subscription is not confirmed")


def verify_account_email_ses(
    *,
    region: str,
    account_id: str,
    identity_domain: str,
    sender: str,
    configuration_set: str,
    event_destination: str,
    topic_arn: str,
    reader: AwsReader = aws_json,
) -> None:
    if region != "eu-west-2" or not account_id.isdigit() or len(account_id) != 12:
        raise AccountEmailSesError("account-email verification is limited to the exact eu-west-2 account")
    if identity_domain != "jobseekercopilot.com":
        raise AccountEmailSesError("unexpected SES identity domain")
    if sender != "accounts@jobseekercopilot.com":
        raise AccountEmailSesError("unexpected account-email sender")
    if configuration_set != "JobSeekerCopilotAccountEmails":
        raise AccountEmailSesError("unexpected account-email configuration set")
    if event_destination != "account-email-events":
        raise AccountEmailSesError("unexpected account-email event destination")
    expected_topic_arn = f"arn:aws:sns:{region}:{account_id}:jsc-public-beta-operations"
    if topic_arn != expected_topic_arn:
        raise AccountEmailSesError("unexpected account-email operations topic")

    account = reader(["sesv2", "get-account", "--region", region])
    if account.get("ProductionAccessEnabled") is not True:
        raise AccountEmailSesError("SES production access is not enabled")
    if account.get("SendingEnabled") is not True:
        raise AccountEmailSesError("SES account sending is not enabled")
    if account.get("EnforcementStatus") != "HEALTHY":
        raise AccountEmailSesError("SES enforcement status is not HEALTHY")
    account_suppression = account.get("SuppressionAttributes")
    if not isinstance(account_suppression, dict) or string_set(
        account_suppression.get("SuppressedReasons"), "account suppression reasons"
    ) != {"BOUNCE", "COMPLAINT"}:
        raise AccountEmailSesError("SES account suppression must cover bounce and complaint")

    identity = reader([
        "sesv2", "get-email-identity",
        "--email-identity", identity_domain,
        "--region", region,
    ])
    dkim = identity.get("DkimAttributes")
    if (
        identity.get("IdentityType") != "DOMAIN"
        or identity.get("VerifiedForSendingStatus") is not True
        or identity.get("VerificationStatus") != "SUCCESS"
        or not isinstance(dkim, dict)
        or dkim.get("SigningEnabled") is not True
        or dkim.get("Status") != "SUCCESS"
    ):
        raise AccountEmailSesError("SES domain identity or DKIM is not successfully verified")

    configuration = reader([
        "sesv2", "get-configuration-set",
        "--configuration-set-name", configuration_set,
        "--region", region,
    ])
    if configuration.get("ConfigurationSetName") != configuration_set:
        raise AccountEmailSesError("SES configuration-set name does not match")
    if configuration.get("SendingOptions", {}).get("SendingEnabled") is not True:
        raise AccountEmailSesError("account-email configuration-set sending is disabled")
    if configuration.get("ReputationOptions", {}).get("ReputationMetricsEnabled") is not True:
        raise AccountEmailSesError("account-email reputation metrics are disabled")
    if string_set(
        configuration.get("SuppressionOptions", {}).get("SuppressedReasons"),
        "configuration-set suppression reasons",
    ) != {"BOUNCE", "COMPLAINT"}:
        raise AccountEmailSesError("account-email suppression must cover bounce and complaint")

    destinations = reader([
        "sesv2", "get-configuration-set-event-destinations",
        "--configuration-set-name", configuration_set,
        "--region", region,
    ]).get("EventDestinations")
    if not isinstance(destinations, list) or len(destinations) != 1 or not isinstance(destinations[0], dict):
        raise AccountEmailSesError("account-email must have exactly one event destination")
    destination = destinations[0]
    if (
        destination.get("Name") != event_destination
        or destination.get("Enabled") is not True
        or string_set(destination.get("MatchingEventTypes"), "SES event types") != EXPECTED_EVENT_TYPES
        or destination.get("SnsDestination", {}).get("TopicArn") != topic_arn
    ):
        raise AccountEmailSesError("account-email event destination does not match the release contract")

    topic = reader(["sns", "get-topic-attributes", "--topic-arn", topic_arn, "--region", region])
    attributes = topic.get("Attributes")
    key_id = attributes.get("KmsMasterKeyId") if isinstance(attributes, dict) else None
    if not isinstance(key_id, str) or not key_id:
        raise AccountEmailSesError("operations topic omits its notification key")
    key = reader([
        "kms", "get-key-policy",
        "--key-id", key_id,
        "--policy-name", "default",
        "--region", region,
    ])
    source_arn = (
        f"arn:aws:ses:{region}:{account_id}:configuration-set/{configuration_set}"
    )
    verify_publish_policies(
        topic,
        key,
        account_id=account_id,
        source_arn=source_arn,
        topic_arn=topic_arn,
    )
    subscriptions = reader([
        "sns", "list-subscriptions-by-topic",
        "--topic-arn", topic_arn,
        "--region", region,
    ])
    verify_confirmed_operations_subscription(subscriptions, topic_arn)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--identity-domain", required=True)
    parser.add_argument("--sender", required=True)
    parser.add_argument("--configuration-set", required=True)
    parser.add_argument("--event-destination", required=True)
    parser.add_argument("--topic-arn", required=True)
    args = parser.parse_args()
    try:
        verify_account_email_ses(
            region=args.region,
            account_id=args.account_id,
            identity_domain=args.identity_domain,
            sender=args.sender,
            configuration_set=args.configuration_set,
            event_destination=args.event_destination,
            topic_arn=args.topic_arn,
        )
    except (AccountEmailSesError, OSError) as exc:
        print(f"Account-email SES verification failed: {exc}", file=sys.stderr)
        return 3
    print(
        "Verified production SES, DKIM, suppression, exact encrypted account-email events "
        "and a confirmed operations subscription without sending email."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
