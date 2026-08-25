import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEEDER_PATH = ROOT / "scripts" / "aws" / "seed-approved-job-provider-secrets.py"
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "aws-public-beta-provider-secrets.yml"
)
SPEC = importlib.util.spec_from_file_location("provider_secret_seeder", SEEDER_PATH)
assert SPEC and SPEC.loader
SEEDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEEDER)


class ApprovedProviderSecretSeedingTests(unittest.TestCase):
    def _write_store(self, directory: Path) -> tuple[Path, dict[str, str]]:
        values = {
            "REED_API_KEY": "reed-value-for-test",
            "ADZUNA_APP_ID": "adzuna-id-for-test",
            "ADZUNA_APP_KEY": "adzuna-key-for-test",
            "JSEARCH_API_KEY": "jsearch-value-for-test",
            "APPRENTICESHIPS_API_KEY": "apprenticeships-value-for-test",
        }
        path = directory / ".secrets.env"
        path.write_text(
            "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path, values

    def test_owner_only_store_maps_to_exact_provider_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path, values = self._write_store(Path(directory_name))

            payloads = SEEDER.provider_payloads(path)

        self.assertEqual(
            {
                "reed": {"api_key": values["REED_API_KEY"]},
                "adzuna": {
                    "app_id": values["ADZUNA_APP_ID"],
                    "app_key": values["ADZUNA_APP_KEY"],
                },
                "jsearch": {"api_key": values["JSEARCH_API_KEY"]},
                "apprenticeships": {
                    "api_key": values["APPRENTICESHIPS_API_KEY"]
                },
            },
            payloads,
        )

    def test_store_rejects_weak_permissions_and_missing_fields_without_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path, _ = self._write_store(Path(directory_name))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "mode 0600"):
                SEEDER.provider_payloads(path)
            path.chmod(0o600)
            path.write_text("REED_API_KEY=short\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "REED_API_KEY") as context:
                SEEDER.provider_payloads(path)

        self.assertNotIn("short", str(context.exception))

    def test_seed_verifies_unique_current_version_and_schema_without_argument_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            path, values = self._write_store(directory)
            put_script = directory / "put-external-secret.sh"
            put_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            put_script.chmod(0o700)
            commands: list[list[str]] = []

            def fake_runner(command, **_kwargs):
                commands.append(command)
                if command[0] == "aws" and command[2] == "list-secret-version-ids":
                    return subprocess.CompletedProcess(command, 0, "1\n", "")
                if command[0] == "aws" and command[2] == "get-secret-value":
                    secret_id = command[command.index("--secret-id") + 1]
                    provider = secret_id.rsplit("/", maxsplit=1)[-1]
                    payload = {
                        "reed": {"api_key": values["REED_API_KEY"]},
                        "adzuna": {
                            "app_id": values["ADZUNA_APP_ID"],
                            "app_key": values["ADZUNA_APP_KEY"],
                        },
                        "jsearch": {"api_key": values["JSEARCH_API_KEY"]},
                        "apprenticeships": {
                            "api_key": values["APPRENTICESHIPS_API_KEY"]
                        },
                    }[provider]
                    return subprocess.CompletedProcess(
                        command, 0, json.dumps(payload), ""
                    )
                return subprocess.CompletedProcess(command, 0, "", "")

            SEEDER.seed_and_verify(path, put_script=put_script, runner=fake_runner)

        flattened_arguments = "\n".join(
            argument for command in commands for argument in command
        )
        for value in values.values():
            self.assertNotIn(value, flattened_arguments)
        self.assertEqual(
            4,
            sum(command[0] == str(put_script) for command in commands),
        )
        self.assertEqual(
            4,
            sum("list-secret-version-ids" in command for command in commands),
        )
        self.assertEqual(
            4,
            sum("get-secret-value" in command for command in commands),
        )

    def test_protected_workflow_is_main_only_oidc_and_output_free(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("CONFIRMATION: ${{ inputs.confirmation }}", workflow)
        self.assertIn(
            'run: test "$CONFIRMATION" = '
            "'SEED APPROVED JOB PROVIDER SECRETS public-beta'",
            workflow,
        )
        self.assertNotIn("run: ${{ inputs.confirmation }}", workflow)
        self.assertIn("environment: production-aws", workflow)
        self.assertIn("group: jsc-public-beta-aws-mutation", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn(
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
            workflow,
        )
        self.assertIn(
            "aws-actions/configure-aws-credentials@"
            "61815dcd50bd041e203e49132bacad1fd04d2708",
            workflow,
        )
        self.assertIn("verify_github_environment_protection.sh", workflow)
        self.assertIn("umask 077", workflow)
        self.assertIn("seed-approved-job-provider-secrets.py", workflow)
        for name in (
            "REED_API_KEY",
            "ADZUNA_APP_ID",
            "ADZUNA_APP_KEY",
            "JSEARCH_API_KEY",
            "APPRENTICESHIPS_API_KEY",
        ):
            self.assertIn(f"${{{{ secrets.{name} }}}}", workflow)
            self.assertNotIn(f'echo "${name}"', workflow)
        self.assertNotIn("set -x", workflow)
        self.assertIn(
            'secret_file="${RUNNER_TEMP}/approved-job-provider-secrets.env"',
            workflow,
        )
        self.assertIn("chmod 0600 \"$secret_file\"", workflow)
        self.assertIn("trap cleanup EXIT HUP INT TERM", workflow)


if __name__ == "__main__":
    unittest.main()
