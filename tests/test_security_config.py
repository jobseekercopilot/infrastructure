from __future__ import annotations

import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.security.check_tracked_secrets import ROOT, findings
from scripts.security.generate_profile_env import (
    PROFILE_TEMPLATES,
    generate_rsa_pair,
    generated_values,
    load_schema,
    render,
)


class RuntimeEnvironmentSchemaTests(unittest.TestCase):
    def test_document_identity_variables_have_explicit_owners_and_consumers(self) -> None:
        schema = load_schema()
        variables = {variable["name"]: variable for variable in schema["variables"]}
        required = {
            "APPLICATION_TRACKER_DATABASE_PASSWORD",
            "AUTH_SERVICE_TOKEN",
            "ENVIRONMENT_DATA_TOKEN",
            "APPLICATION_TRACKER_PRODUCER_TOKEN",
            "APPLICATION_TRACKER_READER_TOKEN",
            "DOCUMENT_STORE_PRODUCER_TOKEN",
            "DOCUMENT_STORE_READER_TOKEN",
            "DOCUMENT_EXPORT_GATEWAY_TOKEN",
            "CV_COVER_LETTER_GATEWAY_TOKEN",
            "CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN",
            "BFF_TO_PAYMENT_GATEWAY_TOKEN",
            "PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
            "PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN",
            "STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN",
        }
        self.assertTrue(required.issubset(variables))
        for name in required:
            variable = variables[name]
            self.assertEqual(variable["classification"], "secret")
            self.assertGreaterEqual(variable["minimumBytes"], 32)
            self.assertTrue(variable["owner"])
            self.assertTrue(variable["consumers"])

    def test_live_provider_credentials_have_single_gateway_ownership(self) -> None:
        variables = {
            variable["name"]: variable for variable in load_schema()["variables"]
        }
        expected = {
            "REED_API_KEY": "reed-gateway",
            "ADZUNA_APP_ID": "adzuna-gateway",
            "ADZUNA_APP_KEY": "adzuna-gateway",
            "JSEARCH_API_KEY": "jsearch-gateway",
        }
        for name, consumer in expected.items():
            self.assertEqual(variables[name]["classification"], "secret")
            self.assertEqual(variables[name]["consumers"], [consumer])
            self.assertEqual(
                variables[name]["profiles"],
                ["live-provider", "data-acquisition"],
            )

    def test_every_generated_variable_is_blank_in_each_tracked_template(self) -> None:
        schema = load_schema()
        for profile, template in PROFILE_TEMPLATES.items():
            generated_names = {
                variable["name"]
                for variable in schema["variables"]
                if variable.get("generator") and profile in variable["profiles"]
            }
            values = {}
            for line in template.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.split("=", 1)
                    values[name] = value
            self.assertTrue(
                generated_names.issubset(values),
                f"{profile} template is missing generated variables",
            )
            for name in generated_names:
                self.assertEqual(values[name], "", f"{profile}:{name} must be blank")

    def test_generated_credentials_are_distinct_and_sufficiently_long(self) -> None:
        schema = load_schema()
        with patch(
            "scripts.security.generate_profile_env.generate_rsa_pair",
            return_value=("private-key", "public-key"),
        ):
            values = generated_values("e2e", schema)
        random_names = [
            variable["name"]
            for variable in schema["variables"]
            if variable.get("generator") == "random"
        ]
        random_values = [values[name] for name in random_names]
        self.assertEqual(len(random_values), len(set(random_values)))
        self.assertTrue(all(len(value.encode("utf-8")) >= 32 for value in random_values))

    def test_generated_rsa_pair_uses_java_compatible_der_encodings(self) -> None:
        private_key, public_key = generate_rsa_pair()
        with tempfile.TemporaryDirectory() as directory:
            private_path = Path(directory) / "private.der"
            public_path = Path(directory) / "public.der"
            private_path.write_bytes(base64.b64decode(private_key))
            public_path.write_bytes(base64.b64decode(public_key))
            subprocess.run(
                [
                    "openssl",
                    "pkcs8",
                    "-inform",
                    "DER",
                    "-in",
                    str(private_path),
                    "-nocrypt",
                    "-out",
                    "/dev/null",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-inform",
                    "DER",
                    "-in",
                    str(public_path),
                    "-noout",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def test_render_refuses_overwrite_and_uses_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".env.e2e"
            with patch(
                "scripts.security.generate_profile_env.generate_rsa_pair",
                return_value=("private-key", "public-key"),
            ):
                render("e2e", PROFILE_TEMPLATES["e2e"], output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                render("e2e", PROFILE_TEMPLATES["e2e"], output)


class TrackedSecretPolicyTests(unittest.TestCase):
    def test_tracked_configuration_contains_no_credential_literal(self) -> None:
        self.assertEqual(findings(), [])

    def test_literal_secret_is_reported_but_interpolation_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "compose.env"
            path.write_text(
                "AUTH_SERVICE_TOKEN=literal-value\n"
                "DOCUMENT_STORE_READER_TOKEN=${DOCUMENT_STORE_READER_TOKEN:?required}\n"
                "ADZUNA_APP_KEY: literal-value\n"
                "JSEARCH_API_KEY: ${JSEARCH_API_KEY:-}\n",
                encoding="utf-8",
            )
            result = findings((path,))
        self.assertEqual(len(result), 2)
        self.assertIn("AUTH_SERVICE_TOKEN", result[0])
        self.assertIn("ADZUNA_APP_KEY", result[1])


if __name__ == "__main__":
    unittest.main()
