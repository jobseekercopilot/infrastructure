import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AccountEmailSesTemplateTest(unittest.TestCase):
    @staticmethod
    def bootstrap_resources():
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def construct_intrinsic(loader, _suffix, node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml")
            .read_text(encoding="utf-8"),
            Loader=CloudFormationLoader,
        )
        return template["Resources"]

    def test_public_beta_terraform_is_the_single_account_email_resource_owner(self):
        self.assertFalse((ROOT / "aws" / "account-email-ses.yaml").exists())
        terraform = (ROOT / "aws" / "public-beta" / "account-email.tf").read_text()

        self.assertIn('resource "aws_sesv2_configuration_set" "account_email"', terraform)
        self.assertIn(
            'resource "aws_sesv2_configuration_set_event_destination" "account_email"',
            terraform,
        )
        self.assertIn('configuration_set_name = var.ses_configuration_set', terraform)
        self.assertIn('event_destination_name = "account-email-events"', terraform)
        self.assertIn('topic_arn = var.foundation_operations_topic_arn', terraform)
        self.assertEqual(terraform.count("prevent_destroy = true"), 2)
        self.assertIn('suppressed_reasons = ["BOUNCE", "COMPLAINT"]', terraform)
        self.assertIn("reputation_metrics_enabled = true", terraform)
        self.assertIn("sending_enabled = true", terraform)
        for event_type in (
            "SEND", "REJECT", "BOUNCE", "COMPLAINT", "DELIVERY", "DELIVERY_DELAY",
        ):
            self.assertIn(f'"{event_type}"', terraform)
        self.assertNotIn('"OPEN"', terraform)
        self.assertNotIn('"CLICK"', terraform)

    def test_runtime_send_grant_is_exact_and_boundary_capped(self):
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text()
        policy = compute.split('data "aws_iam_policy_document" "account_email" {', 1)[1].split(
            'data "aws_iam_policy_document" "ecs_exec" {', 1
        )[0]
        self.assertIn('actions = ["ses:SendEmail"]', policy)
        self.assertIn('variable = "ses:FromAddress"', policy)
        self.assertIn('variable = "ses:ApiVersion"', policy)
        self.assertIn('values   = ["2010-12-01"]', policy)
        self.assertIn('variable = "aws:SecureTransport"', policy)
        self.assertIn('role   = aws_iam_role.task["authentication-service"].id', policy)
        self.assertIn('count = var.enabled_integrations.account_email ? 1 : 0', policy)
        self.assertNotIn("ses:SendRawEmail", policy)
        self.assertNotIn("ses:SendBulkEmail", policy)

        resources = self.bootstrap_resources()
        boundary = resources["WorkloadPermissionsBoundary"]["Properties"]["PolicyDocument"]["Statement"]
        capped = {statement["Sid"]: statement for statement in boundary}[
            "SendOnlyAuthenticationAccountEmail"
        ]
        self.assertEqual(capped["Action"], "ses:SendEmail")
        self.assertEqual(
            set(capped["Resource"]),
            {
                "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/jobseekercopilot.com",
                "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:configuration-set/JobSeekerCopilotAccountEmails",
            },
        )
        self.assertEqual(
            capped["Condition"],
            {
                "StringEquals": {
                    "ses:FromAddress": "accounts@jobseekercopilot.com",
                    "ses:ApiVersion": "2010-12-01",
                },
                "Bool": {"aws:SecureTransport": "true"},
            },
        )

    def test_bootstrap_publisher_and_apply_permissions_are_exact(self):
        resources = self.bootstrap_resources()
        expected_source = (
            "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:"
            "configuration-set/JobSeekerCopilotAccountEmails"
        )
        topic_policy = resources["OperationsTopicPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        topic_statement = {statement["Sid"]: statement for statement in topic_policy}[
            "ExactAccountEmailEventPublisher"
        ]
        self.assertEqual(topic_statement["Principal"], {"Service": "ses.amazonaws.com"})
        self.assertEqual(topic_statement["Action"], "sns:Publish")
        self.assertEqual(topic_statement["Resource"], "OperationsTopic")
        self.assertEqual(topic_statement["Condition"]["ArnLike"]["aws:SourceArn"], expected_source)

        key_policy = resources["NotificationKey"]["Properties"]["KeyPolicy"]["Statement"]
        key_statement = {statement["Sid"]: statement for statement in key_policy}[
            "EncryptExactAccountEmailEvents"
        ]
        self.assertEqual(set(key_statement["Action"]), {"kms:Decrypt", "kms:GenerateDataKey*"})
        self.assertEqual(key_statement["Condition"]["ArnLike"]["aws:SourceArn"], expected_source)

        apply_policy = resources["ApplyObservabilityPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        by_sid = {statement["Sid"]: statement for statement in apply_policy}
        create = by_sid["CreateOnlyTaggedAccountEmailConfigurationSet"]
        tag = by_sid["TagOnlyExactAccountEmailConfigurationSet"]
        manage = by_sid["ManageOnlyTaggedAccountEmailConfiguration"]
        required_create_tags = {
            "aws:RequestTag/Application": "Job Seeker Copilot",
            "aws:RequestTag/Environment": "public-beta",
            "aws:RequestTag/ManagedBy": "Terraform",
            "ses:ApiVersion": "2",
        }
        self.assertEqual(create["Action"], "ses:CreateConfigurationSet")
        self.assertEqual(create["Resource"], "*")
        self.assertEqual(create["Condition"]["StringEquals"], required_create_tags)
        self.assertEqual(tag["Action"], "ses:TagResource")
        self.assertEqual(tag["Resource"], expected_source)
        self.assertEqual(tag["Condition"]["StringEquals"], required_create_tags)
        self.assertEqual(manage["Condition"]["StringEquals"]["ses:ApiVersion"], "2")
        actions = {create["Action"], tag["Action"]} | set(manage["Action"])
        self.assertNotIn("ses:SendEmail", actions)
        self.assertNotIn("ses:DeleteConfigurationSet", actions)
        self.assertNotIn("ses:DeleteConfigurationSetEventDestination", actions)

    def test_local_and_e2e_compose_force_fixture_delivery(self):
        local = (ROOT / "docker-compose.yml").read_text()
        e2e = (ROOT / "docker-compose.e2e.yml").read_text()

        self.assertIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=fixture", local)
        self.assertIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=fixture", e2e)
        self.assertNotIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=ses", local)
        self.assertNotIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=ses", e2e)

    def test_local_ses_overlay_is_bounded_and_uses_the_production_adapter(self):
        overlay = (ROOT / "docker-compose.local-ses.yml").read_text()
        initialiser = (
            ROOT / "localstack" / "init" / "ready.d"
            / "10-account-email-ses.sh"
        ).read_text()

        self.assertIn("localstack/localstack:4.14.0", overlay)
        self.assertIn('"127.0.0.1:4566:4566"', overlay)
        self.assertIn("SERVICES=ses", overlay)
        self.assertIn("PERSISTENCE=0", overlay)
        self.assertIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=local-ses", overlay)
        self.assertIn("AUTH_ACCOUNT_EMAIL_SES_ENDPOINT=http://localstack:4566", overlay)
        self.assertIn("AWS_ACCESS_KEY_ID=test", overlay)
        self.assertIn("AWS_SECRET_ACCESS_KEY=test", overlay)
        self.assertNotIn("AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=ses", overlay)
        self.assertIn("verify-email-identity", initialiser)
        self.assertIn("create-configuration-set", initialiser)
        self.assertIn("get-identity-verification-attributes", initialiser)
        self.assertNotIn("amazonaws.com", overlay)
        self.assertNotIn("amazonaws.com", initialiser)
