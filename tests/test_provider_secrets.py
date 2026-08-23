import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.security.provider_secrets import (
    parse_secret_file,
    secret_files_inside_repositories,
    set_secret,
    validate_store,
)


class ProviderSecretStoreTests(unittest.TestCase):
    def test_store_requires_exact_path_without_reading_an_alternative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            alternative = Path(directory) / ".secrets.env"
            alternative.write_text("REED_API_KEY=secret\n", encoding="utf-8")
            alternative.chmod(0o600)

            failures = validate_store(("REED",), alternative)

        self.assertEqual(1, len(failures))
        self.assertIn("must be", failures[0])
        self.assertNotIn("not-a-real-secret", failures[0])

    def test_missing_reed_reports_replacement_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / ".secrets.env"
            store.write_text("REED_API_KEY=\n", encoding="utf-8")
            store.chmod(0o600)
            with patch(
                "scripts.security.provider_secrets.SECRET_FILE",
                store,
            ):
                failures = validate_store(("REED",), store)

        self.assertEqual(
            ["REED_API_KEY is MISSING — REPLACEMENT REQUIRED"],
            failures,
        )

    def test_repository_scan_rejects_nonempty_provider_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repository = workspace / "service"
            (repository / ".git").mkdir(parents=True)
            environment = repository / ".env.local"
            environment.write_text(
                "ADZUNA_APP_ID=not-a-real-secret\n",
                encoding="utf-8",
            )

            findings = secret_files_inside_repositories(workspace)

        self.assertEqual([environment], findings)

    def test_repository_scan_allows_empty_examples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            repository = workspace / "service"
            (repository / ".git").mkdir(parents=True)
            (repository / ".env.example").write_text(
                "JSEARCH_API_KEY=example-placeholder\n",
                encoding="utf-8",
            )

            findings = secret_files_inside_repositories(workspace)

        self.assertEqual([], findings)

    def test_openai_validation_requires_the_complete_live_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / ".secrets.env"
            store.write_text(
                "OPENAI_API_KEY=not-a-real-secret\n",
                encoding="utf-8",
            )
            store.chmod(0o600)
            with patch(
                "scripts.security.provider_secrets.SECRET_FILE",
                store,
            ):
                failures = validate_store(("OPENAI",), store)

        self.assertNotIn("OPENAI_ORGANIZATION_ID is MISSING", failures)
        self.assertNotIn("OPENAI_PROJECT_ID is MISSING", failures)
        self.assertIn("OPENAI_PRIVACY_DECISION_ID is MISSING", failures)
        self.assertIn("OPENAI_PRIVACY_REVIEWED_ON is MISSING", failures)
        self.assertIn("OPENAI_PRIVACY_REVIEW_DUE_ON is MISSING", failures)
        self.assertNotIn("OPENAI_PRIVACY_REVIEW_ON", "\n".join(failures))
        self.assertNotIn("not-a-real-secret", "\n".join(failures))

    def test_google_validation_requires_only_the_gateway_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / ".secrets.env"
            store.write_text("GOOGLE_MAPS_API_KEY=not-a-real-secret\n", encoding="utf-8")
            store.chmod(0o600)
            with patch("scripts.security.provider_secrets.SECRET_FILE", store):
                failures = validate_store(("GOOGLE",), store)

        self.assertEqual([], failures)

    def test_set_secret_updates_atomically_and_preserves_other_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / ".secrets.env"
            store.write_text(
                "# external credentials\nREED_API_KEY=keep-me\n"
                "GOOGLE_MAPS_API_KEY=replace-me\n",
                encoding="utf-8",
            )
            with patch("scripts.security.provider_secrets.SECRET_FILE", store):
                set_secret("GOOGLE_MAPS_API_KEY", "new-secret", store)

            values = parse_secret_file(store)
            self.assertEqual("keep-me", values["REED_API_KEY"])
            self.assertEqual("new-secret", values["GOOGLE_MAPS_API_KEY"])
            self.assertEqual(0o600, store.stat().st_mode & 0o777)
            self.assertEqual(
                1,
                store.read_text(encoding="utf-8").count("GOOGLE_MAPS_API_KEY="),
            )
