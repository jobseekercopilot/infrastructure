import unittest
from unittest.mock import patch

from scripts.email.local_mailbox import (
    _redact_tokens,
    _reset_link,
    list_messages,
)


TOKEN = "A" * 43


def message(link: str = f"http://localhost:3000/reset-password#token={TOKEN}") -> dict:
    return {
        "Id": "message-1",
        "Timestamp": "2026-07-28T12:00:00Z",
        "Source": "accounts@jobseekercopilot.com",
        "Destination": {"ToAddresses": ["claimant@example.test"]},
        "Subject": "Reset your Job Seeker Copilot password",
        "Body": {
            "text_part": f"Reset your password: {link}",
            "html_part": f'<a href="{link}">Reset your password</a>',
        },
    }


class LocalEmailHelperTests(unittest.TestCase):
    def test_redacts_complete_reset_tokens(self):
        redacted = _redact_tokens(
            f"http://localhost:3000/reset-password#token={TOKEN}"
        )

        self.assertNotIn(TOKEN, redacted)
        self.assertIn("#token=[REDACTED]", redacted)

    def test_accepts_only_the_bounded_local_reset_route(self):
        self.assertEqual(
            f"http://localhost:3000/reset-password#token={TOKEN}",
            _reset_link(message()),
        )

        for unsafe in (
            f"https://app.jobseekercopilot.com/reset-password#token={TOKEN}",
            f"http://localhost:4000/reset-password#token={TOKEN}",
            f"http://localhost:3000/other#token={TOKEN}",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    _reset_link(message(unsafe))

    @patch("scripts.email.local_mailbox._messages")
    @patch("builtins.print")
    def test_list_exposes_only_safe_manual_identifiers(self, output, messages):
        messages.return_value = [message()]

        list_messages()

        rendered = " ".join(
            str(argument)
            for call in output.call_args_list
            for argument in call.args
        )
        self.assertIn("message-1", rendered)
        self.assertIn("claimant@example.test", rendered)
        self.assertNotIn(TOKEN, rendered)


if __name__ == "__main__":
    unittest.main()
