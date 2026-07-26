#!/usr/bin/env python3
"""Render an untracked local/E2E environment with fresh least-privilege values."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "config" / "runtime-environment.schema.json"
PROFILE_TEMPLATES = {
    "local": ROOT / ".env.example",
    "e2e": ROOT / ".env.e2e.example",
    "live-provider": ROOT / ".env.live.example",
    "data-acquisition": ROOT / ".env.data-acquisition.example",
}


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    with path.open(encoding="utf-8") as source:
        schema = json.load(source)
    if schema.get("schemaVersion") != 1:
        raise ValueError("runtime environment schemaVersion must be 1")
    variables = schema.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("runtime environment schema must contain variables")
    names = [variable.get("name") for variable in variables]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("every runtime variable requires a name")
    if len(names) != len(set(names)):
        raise ValueError("runtime variable names must be unique")
    return schema


def generate_rsa_pair() -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as directory:
        private_pem_path = Path(directory) / "private.pem"
        private_path = Path(directory) / "private.der"
        public_path = Path(directory) / "public.der"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:3072",
                "-out",
                str(private_pem_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "pkcs8",
                "-topk8",
                "-nocrypt",
                "-in",
                str(private_pem_path),
                "-outform",
                "DER",
                "-out",
                str(private_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_pem_path),
                "-pubout",
                "-outform",
                "DER",
                "-out",
                str(public_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return (
            base64.b64encode(private_path.read_bytes()).decode("ascii"),
            base64.b64encode(public_path.read_bytes()).decode("ascii"),
        )


def generated_values(profile: str, schema: dict) -> dict[str, str]:
    if profile not in PROFILE_TEMPLATES:
        raise ValueError(f"unsupported profile: {profile}")
    profile_variables = [
        variable for variable in schema["variables"] if profile in variable["profiles"]
    ]
    result: dict[str, str] = {}
    rsa_names = {
        variable["name"]
        for variable in profile_variables
        if variable.get("generator") in {"rsa-private-key", "rsa-public-key"}
    }
    if rsa_names:
        private_key, public_key = generate_rsa_pair()
        if "JWT_PRIVATE_KEY_BASE64" in rsa_names:
            result["JWT_PRIVATE_KEY_BASE64"] = private_key
        if "JWT_PUBLIC_KEY_BASE64" in rsa_names:
            result["JWT_PUBLIC_KEY_BASE64"] = public_key
    for variable in profile_variables:
        if variable.get("generator") != "random":
            continue
        minimum_bytes = variable.get("minimumBytes", 32)
        result[variable["name"]] = secrets.token_urlsafe(max(minimum_bytes, 32))
    return result


def parse_template(path: Path) -> list[str]:
    if not path.is_file():
        raise ValueError(f"missing profile template: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def render(profile: str, template: Path, output: Path, force: bool = False) -> None:
    if output.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing file: {output}")
    schema = load_schema()
    generated = generated_values(profile, schema)
    rendered: list[str] = []
    replaced: set[str] = set()
    for line in parse_template(template):
        if not line or line.lstrip().startswith("#") or "=" not in line:
            rendered.append(line)
            continue
        name, current = line.split("=", 1)
        if name in generated:
            rendered.append(f"{name}={generated[name]}")
            replaced.add(name)
        else:
            rendered.append(f"{name}={current}")
    missing = sorted(set(generated) - replaced)
    if missing:
        raise ValueError(
            f"{template.name} is missing generated variables: {', '.join(missing)}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(output, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fresh untracked local, E2E, live-provider, or "
            "data-acquisition environment. External provider credentials and "
            "operator approvals remain blank."
        )
    )
    parser.add_argument(
        "--profile",
        required=True,
        choices=sorted(PROFILE_TEMPLATES),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    render(
        args.profile,
        PROFILE_TEMPLATES[args.profile],
        args.output.resolve(),
        args.force,
    )
    print(
        f"Generated {args.profile} environment at {args.output}; "
        "values were not printed. This file is untracked and mode 0600."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
