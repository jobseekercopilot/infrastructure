import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AccountEmailSesTemplateTest(unittest.TestCase):
    def test_template_keeps_account_email_resources_narrow(self):
        template = (ROOT / "aws" / "account-email-ses.yaml").read_text()

        self.assertIn("JobSeekerCopilotAccountEmails", template)
        self.assertIn("accounts@jobseekercopilot.com", template)
        self.assertIn("ses:SendEmail", template)
        self.assertIn("ses:ApiVersion: '2010-12-01'", template)
        self.assertNotIn("ses:*", template)
        self.assertNotIn("AWS::Lambda", template)
        self.assertNotIn("ses:SendRawEmail", template)
        for event_type in (
            "SEND",
            "REJECT",
            "BOUNCE",
            "COMPLAINT",
            "DELIVERY",
            "DELIVERY_DELAY",
        ):
            self.assertIn(f"- {event_type}", template)

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
