import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEEDER = ROOT / "scripts" / "aws" / "seed-runtime-secrets.sh"


class RuntimeSecretSeedingTests(unittest.TestCase):
    def _generate_pem_pair(self, directory: Path, stem: str = "jwt") -> tuple[Path, Path]:
        private_key = directory / f"{stem}-private.pem"
        public_key = directory / f"{stem}-public.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return private_key, public_key

    def _run_seeder(self, directory: Path, core: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], dict]:
        fake_bin = directory / "bin"
        fake_bin.mkdir()
        core_input = directory / "core-input.json"
        core_output = directory / "core-output.json"
        core_input.write_text(json.dumps(core), encoding="utf-8")
        core_input.chmod(0o600)
        fake_aws = fake_bin / "aws"
        fake_aws.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "secretsmanager" ]] || exit 2
operation=$2
shift 2
secret_id=""
secret_string=""
while (($#)); do
  case "$1" in
    --secret-id) secret_id=$2; shift 2 ;;
    --secret-string) secret_string=$2; shift 2 ;;
    *) shift ;;
  esac
done
case "$operation" in
  list-secret-version-ids)
    [[ "$secret_id" == "jsc-public-beta/runtime/core" ]] && printf '1\n' || printf '0\n'
    ;;
  get-secret-value)
    [[ "$secret_id" == "jsc-public-beta/runtime/core" ]] || exit 2
    cat "$FAKE_AWS_CORE_INPUT"
    ;;
  put-secret-value)
    if [[ "$secret_id" == "jsc-public-beta/runtime/core" ]]; then
      cp "${secret_string#file://}" "$FAKE_AWS_CORE_OUTPUT"
    fi
    printf 'fake-version\n'
    ;;
  *) exit 2 ;;
esac
""",
            encoding="utf-8",
        )
        fake_aws.chmod(0o700)
        environment = {
            **os.environ,
            "AWS_REGION": "eu-west-2",
            "FAKE_AWS_CORE_INPUT": str(core_input),
            "FAKE_AWS_CORE_OUTPUT": str(core_output),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        }
        result = subprocess.run(
            ["bash", str(SEEDER), "public-beta"],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        rendered = json.loads(core_output.read_text(encoding="utf-8")) if core_output.exists() else {}
        return result, rendered

    def _assert_java_compatible_der_pair(self, directory: Path, rendered: dict[str, str]) -> bytes:
        private_der = directory / "rendered-private.der"
        public_der = directory / "rendered-public.der"
        derived_public = directory / "derived-public.der"
        private_der.write_bytes(base64.b64decode(rendered["JWT_PRIVATE_KEY_BASE64"], validate=True))
        public_der.write_bytes(base64.b64decode(rendered["JWT_PUBLIC_KEY_BASE64"], validate=True))
        self.assertFalse(private_der.read_bytes().startswith(b"-----BEGIN"))
        self.assertFalse(public_der.read_bytes().startswith(b"-----BEGIN"))
        subprocess.run(
            [
                "openssl",
                "pkcs8",
                "-inform",
                "DER",
                "-in",
                str(private_der),
                "-nocrypt",
                "-out",
                os.devnull,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-inform",
                "DER",
                "-in",
                str(private_der),
                "-pubout",
                "-outform",
                "DER",
                "-out",
                str(derived_public),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.assertEqual(public_der.read_bytes(), derived_public.read_bytes())
        return public_der.read_bytes()

    def test_existing_pem_pair_is_normalized_to_der_without_rotating_key_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            private_pem, public_pem = self._generate_pem_pair(directory)
            core = {
                "JWT_PRIVATE_KEY_BASE64": base64.b64encode(private_pem.read_bytes()).decode("ascii"),
                "JWT_PUBLIC_KEY_BASE64": base64.b64encode(public_pem.read_bytes()).decode("ascii"),
            }

            result, rendered = self._run_seeder(directory, core)

            self.assertEqual(result.returncode, 0, result.stderr)
            normalized_public = self._assert_java_compatible_der_pair(directory, rendered)
            original_public_der = directory / "original-public.der"
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-in",
                    str(public_pem),
                    "-outform",
                    "DER",
                    "-out",
                    str(original_public_der),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertEqual(original_public_der.read_bytes(), normalized_public)
            self.assertIn("without rotating existing values", result.stdout)

            with tempfile.TemporaryDirectory() as second_temporary_directory:
                second_result, second_rendered = self._run_seeder(
                    Path(second_temporary_directory), rendered
                )
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(second_rendered, {})
            self.assertIn("Validated existing complete secret", second_result.stdout)

    def test_new_pair_is_seeded_as_java_compatible_der(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)

            result, rendered = self._run_seeder(directory, {})

            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_java_compatible_der_pair(directory, rendered)


if __name__ == "__main__":
    unittest.main()
