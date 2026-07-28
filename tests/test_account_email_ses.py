import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AccountEmailSesTemplateTest(unittest.TestCase):
    def test_template_keeps_account_email_resources_narrow(self):
        template = (ROOT / "aws" / "account-email-ses.yaml").read_text()

        self.assertIn("JobSeekerCopilotAccountEmails", template)
        self.assertIn("accounts@jobseekercopilot.com", template)
        self.assertIn("ses:SendEmail", template)
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
