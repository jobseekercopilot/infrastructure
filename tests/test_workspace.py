from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.workspace.bootstrap import expected_remote, plan
from scripts.workspace.catalog import load_catalog


class CatalogTests(unittest.TestCase):
    def test_repository_names_are_unique(self) -> None:
        catalog = load_catalog()
        self.assertEqual(len(catalog.repositories), len(set(catalog.repositories)))
        self.assertIn("job-matching-service", catalog.repositories)
        self.assertIn("e2e", catalog.repositories)

    def test_invalid_catalog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "owner": "jobseekercopilot",
                        "defaultRef": "develop",
                        "repositories": ["duplicate", "duplicate"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unique"):
                load_catalog(path)


class BootstrapPlanTests(unittest.TestCase):
    def test_missing_checkout_is_planned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing, conflicts = plan(Path(directory), "owner", ("service",))
        self.assertEqual(missing, ["service"])
        self.assertEqual(conflicts, [])

    def test_unexpected_existing_checkout_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "service").mkdir()
            with patch(
                "scripts.workspace.bootstrap.remote_url",
                return_value="https://github.com/someone-else/service.git",
            ):
                missing, conflicts = plan(Path(directory), "owner", ("service",))
        self.assertEqual(missing, [])
        self.assertEqual(len(conflicts), 1)

    def test_https_and_ssh_remotes_are_accepted(self) -> None:
        self.assertEqual(
            expected_remote("owner", "service"),
            (
                "https://github.com/owner/service.git",
                "git@github.com:owner/service.git",
            ),
        )


if __name__ == "__main__":
    unittest.main()
