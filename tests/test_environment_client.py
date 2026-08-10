from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from scripts.data.environment_client import request_json
from scripts.data.reset_and_seed_environment import enforce_e2e_target


class EnvironmentClientTests(unittest.TestCase):
    def test_test_profile_is_accepted_only_on_the_bounded_e2e_url(self) -> None:
        status = {
            "activeEnvironment": "test",
            "environmentManagementEnabled": True,
        }
        enforce_e2e_target("http://localhost:9103", status)
        with self.assertRaisesRegex(RuntimeError, "unknown system-data-service URL"):
            enforce_e2e_target("http://localhost:9203", status)

    def test_internal_caller_key_is_required_before_any_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "scripts.data.environment_client.urlopen"
        ) as urlopen:
            with self.assertRaisesRegex(RuntimeError, "SYSTEM_DATA_INTERNAL_CALLER_KEY"):
                request_json("GET", "http://localhost:9103", "/internal/environments/status")
            urlopen.assert_not_called()

    def test_internal_caller_key_is_sent_without_being_logged(self) -> None:
        response = MagicMock()
        response.read.return_value = b'{"status":"SUCCESS"}'
        response.__enter__.return_value = response
        caller_key = "bounded-test-caller-key-1234567890"
        with patch.dict(
            os.environ,
            {"SYSTEM_DATA_INTERNAL_CALLER_KEY": caller_key},
            clear=True,
        ), patch(
            "scripts.data.environment_client.urlopen",
            return_value=response,
        ) as urlopen:
            result = request_json(
                "GET",
                "http://localhost:9103",
                "/internal/environments/status",
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(caller_key, request.get_header("X-system-data-key"))
        self.assertEqual({"status": "SUCCESS"}, result)


if __name__ == "__main__":
    unittest.main()
