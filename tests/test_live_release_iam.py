import importlib.util
import json
import os
import subprocess
import tempfile
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
RDS_BOUNDARY = "arn:aws:iam::123456789012:policy/jsc-public-beta-rds-monitoring-boundary"
RDS_TRUST = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "monitoring.rds.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {"aws:SourceAccount": "123456789012"},
            "ArnEquals": {
                "aws:SourceArn": "arn:aws:rds:eu-west-2:123456789012:db:jsc-public-beta-postgres"
            },
        },
    }],
}


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


def rds_plan() -> dict:
    value = plan_with_role("jsc-public-beta-rds-monitoring")
    role = value["planned_values"]["root_module"]["resources"][0]["values"]
    role["permissions_boundary"] = RDS_BOUNDARY
    role["assume_role_policy"] = json.dumps(RDS_TRUST)
    return value


def legacy_rds_role() -> dict:
    return {
        "RoleName": "jsc-public-beta-rds-monitoring",
        "PermissionsBoundary": {"PermissionsBoundaryArn": BOUNDARY},
        "AssumeRolePolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "monitoring.rds.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": "123456789012"},
                    "ArnLike": {"aws:SourceArn": "arn:aws:rds:eu-west-2:123456789012:db:*"},
                },
            }],
        },
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


def rds_boundary_reader(document: dict | None = None):
    live_document = document or VERIFIER.expected_rds_monitoring_boundary("123456789012")

    def reader(arguments: list[str]) -> dict:
        arn = arguments[arguments.index("--policy-arn") + 1]
        if arguments[1] == "get-policy":
            return {
                "Policy": {
                    "Arn": arn,
                    "PolicyName": VERIFIER.RDS_MONITORING_BOUNDARY_NAME,
                    "IsAttachable": True,
                    "DefaultVersionId": "v3",
                },
            }
        if arguments[1] == "get-policy-version":
            return {
                "PolicyVersion": {
                    "Document": live_document,
                    "VersionId": "v3",
                    "IsDefaultVersion": True,
                },
            }
        raise AssertionError(arguments)

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

    def test_exact_legacy_rds_role_is_allowed_only_for_one_way_migration(self) -> None:
        legacy = legacy_rds_role()
        listed = {"Roles": [{"RoleName": legacy["RoleName"]}]}
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "wrong permissions boundary"):
            VERIFIER.verify_roles(rds_plan(), listed, lambda _name: legacy)
        VERIFIER.verify_roles(
            rds_plan(),
            listed,
            lambda _name: legacy,
            allow_rds_monitoring_migration=True,
        )

    def test_interrupted_rds_migration_with_narrowed_trust_can_be_retried(self) -> None:
        intermediate = legacy_rds_role()
        intermediate["AssumeRolePolicyDocument"] = RDS_TRUST
        listed = {"Roles": [{"RoleName": intermediate["RoleName"]}]}
        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "wrong permissions boundary"):
            VERIFIER.verify_roles(rds_plan(), listed, lambda _name: intermediate)
        VERIFIER.verify_roles(
            rds_plan(),
            listed,
            lambda _name: intermediate,
            allow_rds_monitoring_migration=True,
        )

    def test_rds_migration_rejects_any_legacy_trust_or_boundary_variation(self) -> None:
        candidates = []
        wrong_boundary = legacy_rds_role()
        wrong_boundary["PermissionsBoundary"] = {"PermissionsBoundaryArn": "arn:aws:iam::123456789012:policy/wrong"}
        candidates.append(wrong_boundary)
        wrong_trust = legacy_rds_role()
        wrong_trust["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["ArnLike"][
            "aws:SourceArn"
        ] = "arn:aws:rds:eu-west-2:123456789012:db:other-*"
        candidates.append(wrong_trust)
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(VERIFIER.LiveIamContractError):
                    VERIFIER.verify_roles(
                        rds_plan(),
                        {"Roles": [{"RoleName": candidate["RoleName"]}]},
                        lambda _name, value=candidate: value,
                        allow_rds_monitoring_migration=True,
                    )


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


class RdsMonitoringPolicyContractTest(unittest.TestCase):
    def test_exact_bootstrap_boundary_default_document_is_accepted(self) -> None:
        VERIFIER.verify_rds_monitoring_boundary(rds_plan(), rds_boundary_reader())

    def test_missing_bootstrap_boundary_fails_closed(self) -> None:
        def missing(_arguments: list[str]) -> dict:
            raise VERIFIER.LiveIamContractError("NoSuchEntity")

        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "NoSuchEntity"):
            VERIFIER.verify_rds_monitoring_boundary(rds_plan(), missing)

    def test_broadened_bootstrap_boundary_document_is_rejected(self) -> None:
        documents = []
        extra_action = VERIFIER.expected_rds_monitoring_boundary("123456789012")
        extra_action["Statement"][0]["Action"].append("logs:DeleteLogGroup")
        documents.append(extra_action)
        broad_resource = VERIFIER.expected_rds_monitoring_boundary("123456789012")
        broad_resource["Statement"][1]["Resource"] = "*"
        documents.append(broad_resource)
        for document in documents:
            with self.subTest(document=document):
                with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "document drifted"):
                    VERIFIER.verify_rds_monitoring_boundary(
                        rds_plan(),
                        rds_boundary_reader(document),
                    )

    def test_bootstrap_boundary_metadata_must_be_exact(self) -> None:
        base_reader = rds_boundary_reader()

        def wrong_metadata(arguments: list[str]) -> dict:
            value = base_reader(arguments)
            if arguments[1] == "get-policy":
                value["Policy"]["IsAttachable"] = False
            return value

        with self.assertRaisesRegex(VERIFIER.LiveIamContractError, "metadata is not exact"):
            VERIFIER.verify_rds_monitoring_boundary(rds_plan(), wrong_metadata)

    def test_exact_managed_policy_without_inline_policies_is_accepted(self) -> None:
        VERIFIER.verify_rds_monitoring_policies(
            {"AttachedPolicies": [{"PolicyArn": VERIFIER.RDS_MONITORING_POLICY_ARN}]},
            {"PolicyNames": []},
        )

    def test_missing_extra_or_inline_policy_is_rejected(self) -> None:
        candidates = (
            ({"AttachedPolicies": []}, {"PolicyNames": []}),
            ({"AttachedPolicies": [
                {"PolicyArn": VERIFIER.RDS_MONITORING_POLICY_ARN},
                {"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"},
            ]}, {"PolicyNames": []}),
            ({"AttachedPolicies": [{"PolicyArn": VERIFIER.RDS_MONITORING_POLICY_ARN}]},
             {"PolicyNames": ["unexpected"]}),
        )
        for attached, inline in candidates:
            with self.subTest(attached=attached, inline=inline):
                with self.assertRaises(VERIFIER.LiveIamContractError):
                    VERIFIER.verify_rds_monitoring_policies(attached, inline)

class ReleaseScriptOrderingTest(unittest.TestCase):
    def run_state_machine_schema_helper(
        self, terraform_json: str, aws_result: str = '{"result":"OK"}'
    ) -> subprocess.CompletedProcess[str]:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(
            encoding="utf-8"
        )
        start = script.index("validate_state_machine_definitions_from_json() {")
        end = script.index("\n}\n\nvalidate_planned_state_machine_definitions()", start) + 2
        validator = script[start:end]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            terraform_path = root / "terraform.json"
            terraform_path.write_text(terraform_json, encoding="utf-8")
            fake_aws = root / "aws"
            fake_aws.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$FAKE_AWS_RESULT\"\n",
                encoding="utf-8",
            )
            fake_aws.chmod(0o700)
            harness = f'''set -euo pipefail
umask 077
region=eu-west-2
temporary_release_files=()
trap 'rm -f -- "${{temporary_release_files[@]}}"' EXIT
{validator}
validate_state_machine_definitions_from_json "$1" planned
'''
            environment = os.environ.copy()
            environment["PATH"] = f"{root}:{environment['PATH']}"
            environment["FAKE_AWS_RESULT"] = aws_result
            return subprocess.run(
                ["bash", "-c", harness, "validator-test", str(terraform_path)],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )

    def test_every_apply_uses_a_verified_saved_plan_and_every_operator_is_prechecked(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        self.assertIn("umask 077", script)
        self.assertIn("trap cleanup_release_files EXIT", script)
        self.assertNotIn("-auto-approve", script)

        for function_name in ("plan_and_apply", "targeted_plan_and_apply"):
            body = script.split(f"{function_name}() {{", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
            self.assertLess(body.index("verify_live_release_iam"), body.index("terraform -chdir=\"$module\" apply"))
            self.assertIn('apply -input=false "$plan"', body)

        full_apply = script.split("plan_and_apply() {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        apply_index = full_apply.index('apply -input=false "$plan"')
        self.assertGreater(full_apply.index('verify_live_release_iam "$plan"', apply_index), apply_index)
        self.assertGreater(full_apply.index("verify_live_rds_monitoring", apply_index), apply_index)
        self.assertIn('if [[ "$label" == foundation ]]', full_apply)

        verifier = script.split("verify_live_release_iam() {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        self.assertLess(
            verifier.index("validate_planned_state_machine_definitions"),
            verifier.index("verify_saved_release_plan.py"),
        )
        self.assertLess(
            verifier.index("validate_deployed_state_machine_definitions"),
            verifier.index("verify_saved_release_plan.py"),
        )
        self.assertLess(verifier.index("verify_saved_release_plan.py"), verifier.index("verify_live_release_iam.py"))

        lines = script.splitlines()
        operator_lines = [index for index, line in enumerate(lines) if "run_release_operator.sh" in line]
        self.assertEqual(len(operator_lines), 8)
        for index in operator_lines:
            self.assertIn("verify_current_iam_contract", lines[index - 1])

    def test_live_verifier_is_bound_to_reviewed_contract_and_plan_json(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        verifier = script.split("verify_live_release_iam() {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        self.assertIn('terraform -chdir="$module" show -json "$plan"', verifier)
        self.assertIn("verify_live_release_iam.py", verifier)
        self.assertIn('--backup-contract "$backup_policy_contract"', verifier)

    def test_state_machine_definitions_are_schema_checked_by_aws_before_apply(self) -> None:
        script = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        validator = script.split("validate_state_machine_definitions_from_json() {", maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        self.assertIn('select(.mode == "managed" and .type == "aws_sfn_state_machine")', validator)
        self.assertIn('select(.values.definition | type == "string")', validator)
        self.assertIn("aws stepfunctions validate-state-machine-definition", validator)
        self.assertIn('--definition "file://$definition_file"', validator)
        self.assertIn('--type "$machine_type"', validator)
        self.assertIn("--severity ERROR", validator)
        self.assertIn("--max-results 100", validator)
        self.assertIn(".result == \"OK\"", validator)
        self.assertIn('if ! state_machine_count=$(jq -er', validator)
        self.assertIn('if ! jq -r', validator)
        self.assertIn('>"$definitions_file"', validator)
        self.assertIn('done <"$definitions_file"', validator)
        self.assertIn("validated != state_machine_count", validator)
        self.assertIn("only $validated fully rendered definition", validator)
        self.assertNotIn("cat \"$definition_file\"", validator)

        planned = script.split("validate_planned_state_machine_definitions() {", maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        self.assertNotIn("deferred", planned)
        self.assertIn('validate_state_machine_definitions_from_json "$plan_json" planned', planned)

        deployed = script.split("validate_deployed_state_machine_definitions() {", maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        self.assertIn('terraform -chdir="$module" show -json', deployed)
        self.assertIn('validate_state_machine_definitions_from_json "$state_json" deployed', deployed)
        self.assertIn('rm -f -- "$state_json"', deployed)

        targeted = script.split("targeted_plan_and_apply() {", maxsplit=1)[1].split(
            "\n}", maxsplit=1
        )[0]
        self.assertGreater(
            targeted.index("validate_deployed_state_machine_definitions"),
            targeted.index('terraform -chdir="$module" apply'),
        )

    def test_state_machine_schema_helper_fails_closed_on_unknown_or_invalid_json(self) -> None:
        definition = json.dumps({
            "StartAt": "Complete",
            "States": {"Complete": {"Type": "Succeed"}},
        })
        resource = {
            "address": "aws_sfn_state_machine.example",
            "mode": "managed",
            "type": "aws_sfn_state_machine",
            "values": {"definition": definition, "type": "STANDARD"},
        }
        plan = {"planned_values": {"root_module": {"resources": [resource]}}}
        accepted = self.run_state_machine_schema_helper(json.dumps(plan))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("passed for 1 planned definition", accepted.stdout)

        rejected = self.run_state_machine_schema_helper(
            json.dumps(plan),
            '{"result":"FAIL","diagnostics":[{"severity":"ERROR","message":"bad schema"}]}',
        )
        self.assertEqual(rejected.returncode, 3)
        self.assertIn("AWS rejected", rejected.stderr)
        self.assertIn("ERROR: bad schema", rejected.stderr)

        resource["values"]["definition"] = None
        unknown = self.run_state_machine_schema_helper(json.dumps(plan))
        self.assertEqual(unknown.returncode, 3)
        self.assertIn("only 0 fully rendered definition", unknown.stderr)

        malformed = self.run_state_machine_schema_helper("{")
        self.assertEqual(malformed.returncode, 3)
        self.assertIn("Could not enumerate", malformed.stderr)

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
