import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "aws" / "verify_live_release_iam.py"
SPEC = importlib.util.spec_from_file_location("verify_live_release_iam", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


TRUST = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
}
BOUNDARY = "arn:aws:iam::123456789012:policy/jsc-public-beta-workload-boundary"


def plan_with_role(name: str = "jsc-public-beta-payment-service-task") -> dict:
    return {
        "planned_values": {
            "root_module": {
                "resources": [{
                    "type": "aws_iam_role",
                    "name": "task",
                    "values": {
                        "name": name,
                        "permissions_boundary": BOUNDARY,
                        "assume_role_policy": json.dumps(TRUST),
                    },
                }],
            },
        },
    }


def live_role(name: str = "jsc-public-beta-payment-service-task") -> dict:
    return {
        "RoleName": name,
        "PermissionsBoundary": {"PermissionsBoundaryArn": BOUNDARY},
        "AssumeRolePolicyDocument": TRUST,
    }


def backup_contract() -> dict:
    return {
        "contracts": {
            name: {
                "policyArn": f"arn:aws:iam::aws:policy/{name}",
                "reviewedDefaultVersion": f"v{index}",
                "requiredSids": [f"{name}Sid"],
                "requiredActions": [f"{name}:Required"],
            }
            for index, name in enumerate(("one", "two", "three", "four"), start=1)
        },
    }


def backup_reader(contract: dict):
    by_arn = {value["policyArn"]: value for value in contract["contracts"].values()}

    def reader(arguments: list[str]) -> dict:
        arn = arguments[arguments.index("--policy-arn") + 1]
        item = by_arn[arn]
        if arguments[1] == "get-policy":
            return {"Policy": {"DefaultVersionId": item["reviewedDefaultVersion"]}}
        return {
            "PolicyVersion": {
                "Document": {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Sid": item["requiredSids"][0],
                        "Effect": "Allow",
                        "Action": item["requiredActions"],
                        "Resource": "*",
                    }],
                },
            },
        }

    return reader


class ReservedRoleContractTest(unittest.TestCase):
    def test_absent_planned_role_and_exact_existing_role_are_allowed(self) -> None:
        plan = plan_with_role()
        VERIFIER.verify_roles(plan, {"Roles": [], "IsTruncated": False})
        listed = {"Roles": [{"RoleName": live_role()["RoleName"]}], "IsTruncated": False}
        VERIFIER.verify_roles(plan, listed, lambda _name: live_role())

    def test_wrong_or_missing_boundary_is_rejected(self) -> None:
        for boundary in (None, "arn:aws:iam::123456789012:policy/wrong"):
            role = live_role()
            role["PermissionsBoundary"] = (
                None if boundary is None else {"PermissionsBoundaryArn": boundary}
            )
            with self.subTest(boundary=boundary):
                with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "wrong permissions boundary"):
                    VERIFIER.verify_roles(
                        plan_with_role(),
                        {"Roles": [{"RoleName": role["RoleName"]}]},
                        lambda _name, value=role: value,
                    )

    def test_wrong_trust_is_rejected_even_when_url_encoded_or_reordered_is_accepted(self) -> None:
        role = live_role()
        role["AssumeRolePolicyDocument"] = {
            **TRUST,
            "Statement": [{**TRUST["Statement"][0], "Principal": {"Service": "lambda.amazonaws.com"}}],
        }
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "wrong trust policy"):
            VERIFIER.verify_roles(
                plan_with_role(),
                {"Roles": [{"RoleName": role["RoleName"]}]},
                lambda _name: role,
            )

        reordered = live_role()
        reordered["AssumeRolePolicyDocument"] = json.dumps({
            "Statement": TRUST["Statement"],
            "Version": TRUST["Version"],
        }).replace(":", "%3A").replace("/", "%2F")
        VERIFIER.verify_roles(
            plan_with_role(),
            {"Roles": [{"RoleName": reordered["RoleName"]}]},
            lambda _name: reordered,
        )

    def test_get_role_must_match_the_listed_reserved_name(self) -> None:
        listed = {"Roles": [{"RoleName": live_role()["RoleName"]}]}
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "malformed or mismatched"):
            VERIFIER.verify_roles(plan_with_role(), listed, lambda _name: live_role("jsc-public-beta-other-task"))

    def test_unexpected_wildcard_passrole_collision_is_rejected(self) -> None:
        collision = live_role("jsc-public-beta-attacker-task")
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "unexpected reserved PassRole collision"):
            VERIFIER.verify_roles(plan_with_role(), {"Roles": [collision]})

    def test_incomplete_list_roles_page_is_rejected(self) -> None:
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "incomplete"):
            VERIFIER.verify_roles(plan_with_role(), {
                "Roles": [live_role()],
                "IsTruncated": True,
                "Marker": "next-page",
            })


class BackupManagedPolicyContractTest(unittest.TestCase):
    def test_reviewed_versions_sids_and_actions_are_accepted(self) -> None:
        contract = backup_contract()
        VERIFIER.verify_backup_policies(contract, backup_reader(contract))

    def test_default_version_drift_is_rejected(self) -> None:
        contract = backup_contract()
        base_reader = backup_reader(contract)

        def reader(arguments: list[str]) -> dict:
            value = base_reader(arguments)
            if arguments[1] == "get-policy":
                value["Policy"]["DefaultVersionId"] = "v999"
            return value

        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "default version drifted"):
            VERIFIER.verify_backup_policies(contract, reader)

    def test_missing_required_sid_or_action_is_rejected(self) -> None:
        contract = backup_contract()
        for missing_field in ("Sid", "Action"):
            base_reader = backup_reader(contract)

            def reader(arguments: list[str], field: str = missing_field) -> dict:
                value = base_reader(arguments)
                if arguments[1] == "get-policy-version":
                    statement = value["PolicyVersion"]["Document"]["Statement"][0]
                    statement[field] = [] if field == "Action" else "DifferentSid"
                return value

            with self.subTest(missing=missing_field):
                with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "document drifted"):
                    VERIFIER.verify_backup_policies(contract, reader)


class ReleaseScriptOrderingTest(unittest.TestCase):
    def test_every_apply_uses_a_verified_saved_plan_and_every_operator_is_prechecked(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        self.assertIn("umask 077", script)
        self.assertIn("trap cleanup_release_files EXIT", script)
        self.assertNotIn("-auto-approve", script)

        for function_name in ("plan_and_apply", "targeted_plan_and_apply"):
            body = script.split(f"{function_name}() {{", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
            self.assertLess(body.index("verify_live_release_iam"), body.index("terraform -chdir=\"$module\" apply"))
            self.assertIn('apply -input=false "$plan"', body)

        lines = script.splitlines()
        operator_lines = [index for index, line in enumerate(lines) if "run_release_operator.sh" in line]
        self.assertEqual(len(operator_lines), 4)
        for index in operator_lines:
            self.assertIn("verify_current_iam_contract", lines[index - 1])

    def test_live_verifier_is_bound_to_reviewed_contract_and_plan_json(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        verifier = script.split("verify_live_release_iam() {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        self.assertIn('terraform -chdir="$module" show -json "$plan"', verifier)
        self.assertIn("verify_live_release_iam.py", verifier)
        self.assertIn('--backup-contract "$backup_policy_contract"', verifier)

    def test_foundation_preflights_auto_scaling_launch_template_authorization(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        preflight = script.split("verify_existing_launch_template_authorization() {", maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        self.assertIn("aws ec2 run-instances", preflight)
        self.assertIn("--dry-run", preflight)
        self.assertIn("--subnet-id", preflight)
        self.assertIn("--count 1", preflight)
        self.assertIn('for subnet_id in "${subnet_ids[@]}"', preflight)
        self.assertIn('"DryRunOperation"', preflight)
        foundation = script.split("foundation)", maxsplit=1)[1].split(";;", maxsplit=1)[0]
        self.assertLess(
            foundation.index("verify_existing_launch_template_authorization"),
            foundation.index("plan_and_apply 0 false foundation"),
        )


if __name__ == "__main__":
    unittest.main()
