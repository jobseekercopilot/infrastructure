import json
import hashlib
import importlib.util
import os
import copy
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "aws" / "validate_public_beta.py"
IMAGE_TEMPLATE = ROOT / "aws" / "public-beta" / "config" / "image-manifest.json"
LANDING_BUILDER = ROOT / "scripts" / "aws" / "build_landing_artifact.py"


class PublicBetaAwsContractTest(unittest.TestCase):
    def _load_bootstrap_template(self):
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def construct_intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
        return yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(
                encoding="utf-8"
            ),
            Loader=CloudFormationLoader,
        )

    def run_validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(VALIDATOR), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_checked_in_dark_template_is_valid_without_aws(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no AWS calls", result.stdout)
        offline_plan = (ROOT / "scripts" / "aws" / "offline_terraform_plan.sh").read_text(encoding="utf-8")
        self.assertIn('cp "$module/.terraform.lock.hcl"', offline_plan)
        self.assertIn("-lockfile=readonly", offline_plan)
        self.assertIn("PENDING Landing hashes correctly block release readiness", offline_plan)
        self.assertIn("generated Landing hashes satisfy release readiness", offline_plan)
        self.assertIn("Checked-in PENDING approvals/images correctly block", offline_plan)
        self.assertIn("-var=application_desired_count=1", offline_plan)
        self.assertIn("-var=public_entrypoint_enabled=true", offline_plan)
        self.assertIn("fully approved activation topology passed", offline_plan)
        offline_verifier = (ROOT / "scripts" / "aws" / "verify_offline_activation_plan.py").read_text(
            encoding="utf-8"
        )
        for semantic_role in (
            "jsc-public-beta-restore-semantic-broker-task",
            "jsc-public-beta-restore-semantic-state-machine",
        ):
            self.assertIn(
                f'"{semantic_role}": "arn:aws:iam::000000000000:policy/'
                'jsc-public-beta-restore-semantic-broker-boundary"',
                offline_verifier,
            )
        for journal_policy_owner in (
            "aws_iam_role_policy.document_store",
            "aws_iam_role_policy.restore_semantic_document_store_journal",
            "aws_iam_role_policy.restore_semantic_verifier",
        ):
            self.assertIn(f'"{journal_policy_owner}"', offline_verifier)
        self.assertIn("permanent-erasures/v1/7e57c0de-*", offline_verifier)
        self.assertIn("erasure-journal data-plane IAM owner set differs", offline_verifier)

    def test_offline_activation_harness_cannot_run_on_main_with_live_credentials_or_backend(self) -> None:
        harness = ROOT / "scripts" / "aws" / "offline_terraform_plan.sh"
        base_environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("AWS_") and key not in {"GITHUB_REF"}
        }
        protected = subprocess.run(
            ["bash", str(harness)],
            cwd=ROOT,
            env={**base_environment, "GITHUB_REF": "refs/heads/main"},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(protected.returncode, 2)
        self.assertIn("protected main or a release tag", protected.stderr)

        credentialed = subprocess.run(
            ["bash", str(harness)],
            cwd=ROOT,
            env={**base_environment, "AWS_ACCESS_KEY_ID": "real-session-must-not-be-used"},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(credentialed.returncode, 2)
        self.assertIn("AWS_ACCESS_KEY_ID is set", credentialed.stderr)

        script = harness.read_text(encoding="utf-8")
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        self.assertIn('[[ ! -e "$validation_root/backend.tf" ]]', script)
        self.assertIn('startswith(abspath(path.root), "/tmp/jsc-public-beta-offline.")', locals_source)
        self.assertIn('var.aws_account_id == "000000000000"', locals_source)
        self.assertIn('-var=offline_validation=false', release)

    def test_frontend_release_readiness_separates_invariants_from_generated_hashes(self) -> None:
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        frontend_block = locals_source.split("frontend_release_ready = (", maxsplit=1)[1].split(
            "\n  )", maxsplit=1
        )[0]
        self.assertNotIn("PENDING", frontend_block)
        self.assertIn("staticArtifactSha256", frontend_block)
        self.assertIn("runtimeConfigSha256", frontend_block)
        self.assertIn("selectedSamTemplateSha256", frontend_block)
        self.assertIn('regex("^[0-9a-f]{64}$", digest)', frontend_block)
        self.assertIn("local.frontend_release_ready", locals_source)
        expanded_cost_block = locals_source.split("local.expanded_cost_shape &&", maxsplit=1)[1].split(
            "var.monthly_budget_usd > 750", maxsplit=1
        )[0]
        self.assertIn("local.release_placeholder_pattern", expanded_cost_block)
        self.assertIn("expanded_capacity_approval_reference", expanded_cost_block)

    def test_release_mode_rejects_placeholder_image_manifest(self) -> None:
        manifest = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        erasure_evidence = manifest["dependencyEvidence"]["documentStorePermanentErasure"]
        erasure_evidence["revision"] = "8" * 40
        erasure_evidence["openApiSha256"] = "9" * 64
        erasure_evidence["restoreReplayRunbookSha256"] = hashlib.sha256(
            (ROOT / erasure_evidence["restoreReplayRunbook"]).read_bytes()
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_validator("--release", "--image-manifest", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sourceBranch must be main", result.stderr)

    def test_static_aws_credentials_are_rejected(self) -> None:
        manifest = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        manifest["images"]["document-store-service"]["digest"] = "sha256:" + "f" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_validator("--image-manifest", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checked-in image digests must remain placeholders", result.stderr)

    def test_document_bucket_rejects_missing_or_wrong_sse_kms_headers(self) -> None:
        data_source = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        document_policy = data_source.split('data "aws_iam_policy_document" "documents" {', maxsplit=1)[1].split(
            'resource "aws_s3_bucket_policy" "documents"', maxsplit=1
        )[0]
        for sid in (
            "DenyMissingObjectEncryption",
            "DenyWrongObjectEncryptionAlgorithm",
            "DenyMissingObjectKmsKey",
            "DenyWrongObjectKmsKey",
        ):
            self.assertIn(f'sid     = "{sid}"', document_policy)
        self.assertEqual(document_policy.count('actions = ["s3:PutObject"]'), 4)
        self.assertIn('variable = "s3:x-amz-server-side-encryption"', document_policy)
        self.assertIn('values   = ["aws:kms"]', document_policy)
        self.assertIn('variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"', document_policy)
        self.assertIn("values   = [var.foundation_data_kms_key_arn]", document_policy)

    def test_duplicate_manifest_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            result = self.run_validator("--image-manifest", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate object key", result.stderr)

    def test_waf_has_three_exact_post_body_overrides_and_full_crs_elsewhere(self) -> None:
        edge = (ROOT / "aws" / "public-beta" / "edge.tf").read_text(encoding="utf-8")
        path_set = edge.split(
            'resource "aws_wafv2_regex_pattern_set" "authenticated_document_uploads" {',
            maxsplit=1,
        )[1].split('resource "aws_wafv2_web_acl" "app" {', maxsplit=1)[0]
        self.assertEqual(edge.count("AWSManagedRulesCommonRuleSet"), 2)
        self.assertEqual(edge.count('vendor_name = "AWS"'), 3)
        self.assertNotIn("ip_set_reference_statement", edge)
        self.assertNotIn("rule_group_reference_statement", edge)
        self.assertEqual(edge.count('name = "SizeRestrictions_BODY"'), 1)
        self.assertIn("action_to_use {", edge)
        self.assertEqual(path_set.count("regular_expression {"), 3)
        for exact_path in (
            '^/api/v1/document-generation/applications/[0-9a-fA-F-]{36}/document-uploads$',
            '^/api/v1/document-generation/applications/[0-9a-fA-F-]{36}/replace$',
            '^/api/jobs/saved$',
        ):
            self.assertIn(f'regex_string = "{exact_path}"', path_set)
        self.assertEqual(edge.count('search_string         = "POST"'), 2)

    def test_dark_target_group_associations_are_non_ingress_and_ordered(self) -> None:
        edge = (ROOT / "aws" / "public-beta" / "edge.tf").read_text(encoding="utf-8")
        network = (ROOT / "aws" / "public-beta" / "network.tf").read_text(encoding="utf-8")
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")

        association_listener = edge.split(
            'resource "aws_lb_listener" "dark_target_group_association" {', maxsplit=1
        )[1].split('resource "aws_lb_listener_rule" "dark_frontend_association" {', maxsplit=1)[0]
        self.assertIn("port              = 65535", association_listener)
        self.assertIn('protocol          = "HTTP"', association_listener)
        self.assertIn('type = "fixed-response"', association_listener)
        self.assertIn('status_code  = "503"', association_listener)

        association_contracts = (
            (
                "dark_frontend_association",
                'resource "aws_lb_listener_rule" "dark_stripe_association" {',
                "frontend",
                "frontend",
            ),
            ("dark_stripe_association", 'resource "aws_lb_listener" "http" {', "stripe", "stripe"),
        )
        for resource_name, next_marker, target_group_name, host_prefix in association_contracts:
            rule = edge.split(
                f'resource "aws_lb_listener_rule" "{resource_name}" {{', maxsplit=1
            )[1].split(next_marker, maxsplit=1)[0]
            self.assertIn(
                "listener_arn = aws_lb_listener.dark_target_group_association.arn", rule
            )
            self.assertIn(f"target_group_arn = aws_lb_target_group.{target_group_name}.arn", rule)
            self.assertIn('source_ip { values = ["192.0.2.0/24"] }', rule)
            self.assertIn(
                f'host_header {{ values = ["{host_prefix}.dark-association.invalid"] }}', rule
            )

        alb_security_group = network.split(
            'resource "aws_security_group" "alb" {', maxsplit=1
        )[1].split('resource "aws_security_group" "ecs_hosts" {', maxsplit=1)[0]
        ingress_ports = {int(port) for port in re.findall(r"from_port\s+=\s+(\d+)", alb_security_group)}
        self.assertEqual(ingress_ports, {80, 443})
        self.assertNotIn("65535", alb_security_group)

        https_listener = edge.split('resource "aws_lb_listener" "https" {', maxsplit=1)[1].split(
            'resource "aws_lb_listener_rule" "stripe_webhook" {', maxsplit=1
        )[0]
        self.assertIn("for_each = var.public_entrypoint_enabled ? [1] : []", https_listener)
        self.assertIn("target_group_arn = aws_lb_target_group.frontend.arn", https_listener)
        self.assertIn("for_each = var.public_entrypoint_enabled ? [] : [1]", https_listener)
        self.assertIn('status_code  = "503"', https_listener)
        self.assertIn(
            "count = local.has_tls_configuration && var.public_entrypoint_enabled && var.enabled_integrations.stripe ? 1 : 0",
            edge,
        )

        application_service = compute.split('resource "aws_ecs_service" "service" {', maxsplit=1)[1]
        application_dependencies = application_service.rsplit("depends_on = [", maxsplit=1)[1].split(
            "]", maxsplit=1
        )[0]
        self.assertIn("aws_lb_listener_rule.dark_frontend_association", application_dependencies)
        self.assertIn("aws_lb_listener_rule.dark_stripe_association", application_dependencies)
        self.assertEqual(
            len(re.findall(r'availability_zone_rebalancing\s+=\s+"DISABLED"', compute)), 2
        )
        self.assertNotRegex(compute, r'availability_zone_rebalancing\s+=\s+"ENABLED"')

    def test_privileged_actions_are_immutable_and_manually_gated(self) -> None:
        for name, environment in (
            ("aws-public-beta-build.yml", "production-build"),
            ("aws-public-beta-release.yml", "production-aws"),
        ):
            workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("github.ref == 'refs/heads/main'", workflow)
            self.assertIn(f"environment: {environment}", workflow)
            if name == "aws-public-beta-release.yml":
                self.assertIn("inputs.action == 'prepare-restore-source' && 21600 || 10800", workflow)
            else:
                self.assertIn("role-duration-seconds: 10800", workflow)
            references = re.findall(r"^\s*uses:\s*[^\s#]+@([^\s#]+)", workflow, flags=re.MULTILINE)
            self.assertTrue(references)
            self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references))
        release = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            release.count(
                "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
            ),
            2,
        )
        self.assertGreaterEqual(release.count("digest-mismatch: error"), 2)
        self.assertNotIn("gh attestation verify", release)
        self.assertIn("workspaceLockSha256", release)
        self.assertIn('git merge-base --is-ancestor "$build_sha" "$GITHUB_SHA"', release)
        self.assertIn('git show "$build_sha:config/workspace-lock.json"', release)
        self.assertIn('if [ "$RELEASE_ACTION" = rollback ]; then', release)
        self.assertNotIn('"$RELEASE_ACTION" = rollback ] || [ "$RELEASE_ACTION" = activate', release)

    def test_github_environment_guard_fails_closed_for_owner_actor_and_branch_policy(self) -> None:
        guard = ROOT / "scripts" / "aws" / "verify_github_environment_protection.sh"
        with tempfile.TemporaryDirectory() as directory:
            fake_bin = Path(directory)
            fake_gh = fake_bin / "gh"
            fake_gh.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "key = 'BRANCH_POLICY_JSON' if 'deployment-branch-policies' in sys.argv[-1] else 'ENVIRONMENT_JSON'\n"
                "print(os.environ[key])\n",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)
            environment = {
                "name": "production-build",
                "can_admins_bypass": False,
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
                "protection_rules": [{"type": "branch_policy"}],
            }
            branch_policy = {
                "total_count": 1,
                "branch_policies": [{"name": "main", "type": "branch"}],
            }
            command_environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "ENVIRONMENT_JSON": json.dumps(environment),
                "BRANCH_POLICY_JSON": json.dumps(branch_policy),
            }
            command = [
                "bash", str(guard), "jobseekercopilot/infrastructure", "production-build",
                "jobseekercopilot", "jobseekercopilot",
            ]
            valid = subprocess.run(command, env=command_environment, check=False, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)

            environment["name"] = "production-aws-restore-observe"
            command_environment["ENVIRONMENT_JSON"] = json.dumps(environment)
            observe_allowed = subprocess.run(
                [
                    "bash", str(guard), "jobseekercopilot/infrastructure",
                    "production-aws-restore-observe", "jobseekercopilot", "jobseekercopilot",
                ],
                env=command_environment, check=False, capture_output=True, text=True,
            )
            self.assertEqual(observe_allowed.returncode, 0, observe_allowed.stderr)
            environment["name"] = "production-build"
            command_environment["ENVIRONMENT_JSON"] = json.dumps(environment)

            wrong_actor = subprocess.run(
                [*command[:-1], "another-user"],
                env=command_environment, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(wrong_actor.returncode, 0)
            self.assertIn("only repository owner jobseekercopilot", wrong_actor.stderr)

            environment["can_admins_bypass"] = True
            command_environment["ENVIRONMENT_JSON"] = json.dumps(environment)
            admin_bypass = subprocess.run(
                command, env=command_environment, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(admin_bypass.returncode, 0)
            self.assertIn("disable administrator bypass", admin_bypass.stderr)

            environment["can_admins_bypass"] = False
            branch_policy["branch_policies"][0]["name"] = "develop"
            command_environment["ENVIRONMENT_JSON"] = json.dumps(environment)
            command_environment["BRANCH_POLICY_JSON"] = json.dumps(branch_policy)
            develop_allowed = subprocess.run(
                command, env=command_environment, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(develop_allowed.returncode, 0)
            self.assertIn("exact main branch", develop_allowed.stderr)

        guard_source = guard.read_text(encoding="utf-8")
        self.assertIn("can_admins_bypass == false", guard_source)
        self.assertIn('"$actor_login" != "$operator_login"', guard_source)
        approvals = json.loads((ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text())
        github_evidence = approvals["githubEnvironmentProtection"]
        self.assertFalse(github_evidence["reviewed"])
        self.assertFalse(github_evidence["administratorBypassDisabled"])

        for workflow_name, environment_name in (
            ("aws-public-beta-build.yml", "production-build"),
            ("aws-public-beta-release.yml", "production-aws-plan"),
            ("aws-public-beta-release.yml", "production-aws"),
            ("aws-public-beta-restore-drill.yml", "production-aws-restore"),
            ("aws-public-beta-restore-drill.yml", "production-aws-restore-cleanup"),
            ("aws-public-beta-restore-semantic.yml", "production-aws-restore"),
            ("aws-public-beta-restore-semantic.yml", "production-aws-restore-observe"),
            ("aws-public-beta-restore-semantic.yml", "production-aws-restore-cleanup"),
        ):
            workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
            self.assertIn(
                f'verify_github_environment_protection.sh "$GITHUB_REPOSITORY" {environment_name} '
                '"$GITHUB_REPOSITORY_OWNER" "$GITHUB_ACTOR"',
                workflow,
            )
        build = (ROOT / ".github" / "workflows" / "aws-public-beta-build.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(build.count("actions: read"), 2)
        guard_source = guard.read_text(encoding="utf-8")
        self.assertIn("aws-restore|aws-restore-cleanup|aws-restore-observe", guard_source)

        restore_drill = (ROOT / ".github" / "workflows" / "aws-public-beta-restore-drill.yml").read_text(
            encoding="utf-8"
        )
        restore_semantic = (
            ROOT / ".github" / "workflows" / "aws-public-beta-restore-semantic.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("group: jsc-public-beta-aws-mutation", restore_drill)
        self.assertIn("group: jsc-public-beta-aws-mutation", restore_semantic)
        publish_job = build.split("\n  publish:\n", maxsplit=1)[1].split("\n  promote:\n", maxsplit=1)[0]
        self.assertIn("group: jsc-public-beta-aws-mutation", publish_job)
        self.assertNotIn("group: jsc-public-beta-restore-drill", restore_drill)
        self.assertNotIn("group: jsc-public-beta-restore-semantic", restore_semantic)

    def test_bootstrap_apply_role_cannot_escalate_or_mutate_unrelated_resources(self) -> None:
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def construct_intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(encoding="utf-8"),
            Loader=CloudFormationLoader,
        )
        for parameter_name, parameter in template["Parameters"].items():
            if parameter["Type"] not in {"String", "CommaDelimitedList"}:
                for string_only_constraint in ("AllowedPattern", "MinLength", "MaxLength"):
                    self.assertNotIn(
                        string_only_constraint,
                        parameter,
                        f"{parameter_name} uses a String-only CloudFormation constraint",
                    )
        self.assertEqual(template["Parameters"]["EcsAmiId"]["Type"], "AWS::EC2::Image::Id")
        resources = template["Resources"]
        self.assertIn("WorkloadPermissionsBoundary", resources)
        self.assertEqual(
            template["Outputs"]["WorkloadPermissionsBoundaryArn"]["Value"],
            "WorkloadPermissionsBoundary",
        )
        managed_policy_names = [
            "ApplyDiscoveryPolicy",
            "ApplyEc2NetworkPolicy",
            "ApplyNetworkEdgePolicy",
            "ApplyComputePolicy",
            "ApplyComputeLaunchPolicy",
            "ApplyDataPolicy",
            "ApplyObservabilityPolicy",
            "ApplyReleaseOperationsPolicy",
            "ApplyIamPolicy",
            "ApplyTagAndStateGuardPolicy",
        ]
        apply_role = resources["ApplyRole"]["Properties"]
        self.assertEqual(apply_role["MaxSessionDuration"], 21600)
        self.assertEqual(set(apply_role["ManagedPolicyArns"]), set(managed_policy_names))
        self.assertLessEqual(len(apply_role["ManagedPolicyArns"]), 10)
        self.assertEqual(
            {policy["PolicyName"] for policy in apply_role["Policies"]},
            {"TerraformState", "NonRemovableApplyGuardrails"},
        )
        inline_size = sum(
            len(json.dumps(policy["PolicyDocument"], separators=(",", ":")))
            for policy in apply_role["Policies"]
        )
        self.assertLessEqual(inline_size, 10240)

        rendered_values = {
            "AWS::Partition": "aws",
            "AWS::Region": "eu-west-2",
            "AWS::AccountId": "123456789012",
            "AppDomainName": "app.example.co.uk",
            "EcsAmiId": "ami-0123456789abcdef0",
            "Route53HostedZoneArn": "arn:aws:route53:::hostedzone/Z0123456789ABCDEF",
            "StateKey.Arn": "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000001",
            "StateBucket.Arn": "arn:aws:s3:::jsc-public-beta-state-123456789012",
            "ApplicationDataKey.Arn": "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000002",
            "ErasureJournalKey.Arn": "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000003",
            "ErasureJournalBucket.Arn": "arn:aws:s3:::jsc-public-beta-erasure-journal-123456789012",
            "CustomerDataBackupVault.BackupVaultArn": (
                "arn:aws:backup:eu-west-2:123456789012:backup-vault:jsc-public-beta-customer-data"
            ),
            "CustomerDataBackupPlan.BackupPlanArn": (
                "arn:aws:backup:eu-west-2:123456789012:backup-plan:00000000-0000-0000-0000-000000000000"
            ),
            "WorkloadPermissionsBoundary": (
                "arn:aws:iam::123456789012:policy/jsc-public-beta-workload-boundary"
            ),
            "RdsMonitoringPermissionsBoundary": (
                "arn:aws:iam::123456789012:policy/jsc-public-beta-rds-monitoring-boundary"
            ),
            "BackupWorkloadBoundary": (
                "arn:aws:iam::123456789012:policy/jsc-public-beta-backup-boundary"
            ),
            "BackupRestoreWorkloadBoundary": (
                "arn:aws:iam::123456789012:policy/jsc-public-beta-backup-restore-boundary"
            ),
            "RestoreSemanticBrokerPermissionsBoundary": (
                "arn:aws:iam::123456789012:policy/jsc-public-beta-restore-semantic-broker-boundary"
            ),
        }

        def render_policy_value(value):
            if isinstance(value, dict):
                return {key: render_policy_value(item) for key, item in value.items()}
            if isinstance(value, list):
                return [render_policy_value(item) for item in value]
            if isinstance(value, str):
                if value in rendered_values:
                    return rendered_values[value]
                for key, rendered in rendered_values.items():
                    value = value.replace("${" + key + "}", rendered)
                return value
            return value

        rendered_inline_size = sum(
            len(json.dumps(render_policy_value(policy["PolicyDocument"]), separators=(",", ":")))
            for policy in apply_role["Policies"]
        )
        self.assertLessEqual(rendered_inline_size, 10240)

        statements = [
            statement
            for policy in apply_role["Policies"]
            for statement in policy["PolicyDocument"]["Statement"]
        ]
        for policy_name in managed_policy_names:
            policy = resources[policy_name]
            self.assertEqual(policy["Type"], "AWS::IAM::ManagedPolicy")
            document = policy["Properties"]["PolicyDocument"]
            self.assertLessEqual(
                len(json.dumps(render_policy_value(document), separators=(",", ":"))),
                6144,
                f"{policy_name} exceeds the IAM managed-policy document quota after realistic ARN rendering",
            )
            statements.extend(document["Statement"])
        for boundary_name in (
            "WorkloadPermissionsBoundary", "RdsMonitoringPermissionsBoundary",
            "BackupWorkloadBoundary", "BackupRestoreWorkloadBoundary",
            "RestoreSemanticBrokerPermissionsBoundary",
        ):
            document = resources[boundary_name]["Properties"]["PolicyDocument"]
            self.assertLessEqual(
                len(json.dumps(render_policy_value(document), separators=(",", ":"))),
                6144,
                f"{boundary_name} exceeds the IAM managed-policy document quota after realistic ARN rendering",
            )
        by_sid = {statement["Sid"]: statement for statement in statements}
        serialized = json.dumps(statements)
        for forbidden in (
            "iam:CreatePolicy",
            "iam:CreatePolicyVersion",
            "iam:DeletePolicy",
            "iam:DeletePolicyVersion",
            "iam:SetDefaultPolicyVersion",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("role/jsc-public-beta-*\"", serialized)

        create_role = by_sid["CreateCommonBoundaryConstrainedRoles"]
        self.assertEqual(create_role["Action"], "iam:CreateRole")
        self.assertEqual(
            create_role["Condition"]["StringEquals"]["iam:PermissionsBoundary"],
            "WorkloadPermissionsBoundary",
        )
        self.assertEqual(create_role["Condition"]["StringEquals"]["aws:RequestTag/Environment"], "public-beta")
        self.assertTrue(all("github" not in arn for arn in create_role["Resource"]))
        self.assertNotIn("rds-monitoring", json.dumps(create_role["Resource"]))
        create_monitoring_role = by_sid["CreateRdsMonitoringBoundaryConstrainedRole"]
        self.assertEqual(
            create_monitoring_role["Condition"]["StringEquals"]["iam:PermissionsBoundary"],
            "RdsMonitoringPermissionsBoundary",
        )
        manage_monitoring_role = by_sid["ManageOnlyRdsMonitoringBoundaryConstrainedRole"]
        self.assertEqual(
            set(manage_monitoring_role["Condition"]["StringEquals"]["iam:PermissionsBoundary"]),
            {"WorkloadPermissionsBoundary", "RdsMonitoringPermissionsBoundary"},
        )
        self.assertEqual(
            set(manage_monitoring_role["Action"]),
            {"iam:DeleteRole", "iam:UpdateAssumeRolePolicy", "iam:UpdateRoleDescription"},
        )
        repair_monitoring_role = by_sid["RepairOnlyRdsMonitoringWorkloadBoundary"]
        self.assertEqual(
            repair_monitoring_role["Condition"]["StringEquals"]["iam:PermissionsBoundary"],
            "RdsMonitoringPermissionsBoundary",
        )

        tagged_create = by_sid["CreateOnlyTaggedNetworkResources"]
        self.assertNotEqual(tagged_create["Resource"], "*")
        self.assertTrue(all(arn.startswith("arn:${AWS::Partition}:ec2:") for arn in tagged_create["Resource"]))
        self.assertEqual(tagged_create["Condition"]["StringEquals"]["aws:RequestTag/ManagedBy"], "Terraform")
        tagged_parents = by_sid["UseOnlyTaggedVpcParentsDuringCreate"]
        self.assertEqual(
            tagged_parents["Condition"]["StringEquals"]["aws:ResourceTag/ManagedBy"],
            "Terraform",
        )
        for action in (
            "ec2:CreateFlowLogs",
            "ec2:CreateNatGateway",
            "ec2:CreateRouteTable",
            "ec2:CreateSecurityGroup",
            "ec2:CreateSubnet",
            "ec2:CreateVpcEndpoint",
        ):
            self.assertIn(action, tagged_create["Action"])
            self.assertIn(action, tagged_parents["Action"])
        # Negative simulations: an untagged create and a wrong boundary cannot
        # satisfy the only applicable Allow statements.
        untagged_request = {}
        self.assertFalse(all(
            untagged_request.get(key) == value
            for key, value in tagged_create["Condition"]["StringEquals"].items()
        ))
        self.assertNotEqual(
            "arn:aws:iam::123456789012:policy/AdministratorAccess",
            create_role["Condition"]["StringEquals"]["iam:PermissionsBoundary"],
        )

        image_run = by_sid["RunOnlyReviewedEcsAmiFromLaunchTemplate"]
        self.assertIn("::image/${EcsAmiId}", image_run["Resource"])
        image_conditions = json.dumps(image_run["Condition"])
        for unsupported_on_image in (
            "ec2:InstanceType", "ec2:MetadataHttpTokens", "ec2:AssociatePublicIpAddress",
            "ec2:VolumeType", "ec2:Encrypted",
        ):
            self.assertNotIn(unsupported_on_image, image_conditions)
        self.assertEqual(
            by_sid["CreateOnlyTaggedPublicBetaInstances"]["Condition"]["StringEquals"]["ec2:InstanceType"],
            "m7i.2xlarge",
        )
        self.assertEqual(
            by_sid["CreateOnlyTaggedPublicBetaInstances"]["Condition"]["StringEquals"][
                "ec2:MetadataHttpTokens"
            ],
            "required",
        )
        self.assertEqual(
            by_sid["CreateOnlyPrivateNetworkInterfacesFromReviewedTemplate"]["Condition"]["BoolIfExists"][
                "ec2:AssociatePublicIpAddress"
            ],
            "false",
        )
        self.assertEqual(
            by_sid["CreateOnlyTaggedEncryptedGp3Volumes"]["Condition"]["StringEquals"]["ec2:VolumeType"],
            "gp3",
        )
        self.assertEqual(
            by_sid["CreateOnlyTaggedEncryptedGp3Volumes"]["Condition"]["Bool"]["ec2:Encrypted"],
            "true",
        )
        for sid in (
            "RunOnlyReviewedEcsAmiFromLaunchTemplate", "RunOnlyFromTaggedPublicBetaTemplateResources",
            "CreateOnlyTaggedPublicBetaInstances",
            "CreateOnlyTaggedEncryptedGp3Volumes",
        ):
            self.assertEqual(by_sid[sid]["Condition"]["Bool"]["ec2:IsLaunchTemplateResource"], "true")
        # The ASG supplies vpc_zone_identifier outside the launch template.
        # AWS therefore evaluates the selected subnet with
        # ec2:IsLaunchTemplateResource=false during its RunInstances dry run.
        asg_subnet = by_sid["RunOnlyInTaggedPublicBetaSubnets"]
        self.assertNotIn("Bool", asg_subnet["Condition"])
        self.assertEqual(
            asg_subnet["Condition"]["StringEquals"]["ec2:ResourceTag/ManagedBy"],
            "Terraform",
        )
        self.assertIn("ec2:LaunchTemplate", asg_subnet["Condition"]["ArnLike"])
        asg_eni = by_sid["CreateOnlyPrivateNetworkInterfacesFromReviewedTemplate"]
        self.assertNotIn("Bool", asg_eni["Condition"])
        self.assertEqual(
            asg_eni["Condition"]["StringEqualsIfExists"]["aws:RequestTag/ManagedBy"],
            "Terraform",
        )
        self.assertEqual(
            set(asg_eni["Condition"]["ArnLike"]),
            {"ec2:LaunchTemplate", "ec2:Subnet", "ec2:Vpc"},
        )

        create_database = by_sid["CreateOnlyReviewedPublicBetaDatabase"]
        self.assertIn(":db:jsc-public-beta-postgres", create_database["Resource"])
        self.assertNotIn(":pg:", create_database["Resource"])
        self.assertNotIn(":subgrp:", create_database["Resource"])
        self.assertEqual(create_database["Condition"]["StringEquals"]["rds:DatabaseClass"], "db.t4g.medium")
        database_parents = by_sid["UseOnlyTaggedPublicBetaDatabaseParentsDuringCreate"]
        self.assertTrue(all(":pg:" in resource or ":subgrp:" in resource for resource in database_parents["Resource"]))
        expected_parameter_group = (
            "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:"
            "pg:jsc-public-beta-postgres15-*"
        )
        self.assertIn(expected_parameter_group, database_parents["Resource"])
        self.assertIn(expected_parameter_group, by_sid["CreateOnlyTaggedDataResources"]["Resource"])
        self.assertNotIn(
            "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:pg:jsc-public-beta-postgres-*",
            database_parents["Resource"] + by_sid["CreateOnlyTaggedDataResources"]["Resource"],
        )
        data_source = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        self.assertIn('name_prefix = "${local.name_prefix}-postgres15-"', data_source)
        self.assertEqual(
            database_parents["Condition"]["StringEquals"]["aws:ResourceTag/ManagedBy"],
            "Terraform",
        )
        parent_conditions = json.dumps(database_parents["Condition"])
        for db_only_condition in (
            "rds:DatabaseClass", "rds:DatabaseEngine", "rds:MultiAz",
            "rds:PubliclyAccessible", "rds:StorageEncrypted", "rds:StorageSize",
        ):
            self.assertNotIn(db_only_condition, parent_conditions)

        exact_pass_pairs = {
            "PassOnlyEcsInstanceRoleToEc2": "ec2.amazonaws.com",
            "PassOnlyMonitoringRoleToRdsMonitoring": "rds.amazonaws.com",
            "PassOnlyFlowRoleToVpcFlowLogs": "vpc-flow-logs.amazonaws.com",
            "PassOnlyBackupRolesToBackup": "backup.amazonaws.com",
            "PassOnlyTaskRolesToEcsTasks": "ecs-tasks.amazonaws.com",
        }
        for sid, service in exact_pass_pairs.items():
            statement = by_sid[sid]
            self.assertEqual(statement["Condition"]["StringEquals"]["iam:PassedToService"], service)
            self.assertNotIn("github", json.dumps(statement["Resource"]))
        self.assertNotIn("application-autoscaling.amazonaws.com", serialized)

        exact_attachment_pairs = {
            "AttachOnlyEcsInstancePolicies": (
                "role/jsc-public-beta-ecs-instance", "WorkloadPermissionsBoundary",
            ),
            "AttachOnlyRdsMonitoringPolicy": (
                "role/jsc-public-beta-rds-monitoring", "RdsMonitoringPermissionsBoundary",
            ),
            "AttachOnlyBackupPolicies": (
                "role/jsc-public-beta-backup", "BackupWorkloadBoundary",
            ),
            "AttachOnlyBackupRestorePolicies": (
                "role/jsc-public-beta-backup-restore", "BackupRestoreWorkloadBoundary",
            ),
            "AttachOnlyExecutionRolePolicy": (
                "role/jsc-public-beta-*-execution", "WorkloadPermissionsBoundary",
            ),
        }
        for sid, (expected_role, expected_boundary) in exact_attachment_pairs.items():
            statement = by_sid[sid]
            self.assertIn(expected_role, statement["Resource"])
            self.assertNotIn("AdministratorAccess", json.dumps(statement))
            arn_equals = statement["Condition"]["ArnEquals"]
            self.assertIn("iam:PolicyARN", arn_equals)
            self.assertEqual(arn_equals["iam:PermissionsBoundary"], expected_boundary)

        # ACM certificate IDs are not name-derived and DeleteCertificate does
        # not support a resource-tag condition, so the apply role must not own
        # ACM writes at all. It consumes an independently reviewed exact ARN.
        for forbidden in (
            "acm:RequestCertificate",
            "acm:DeleteCertificate",
            "acm:AddTagsToCertificate",
            "acm:RemoveTagsFromCertificate",
        ):
            self.assertNotIn(forbidden, serialized)

        # Opaque-ID resources are foundation-owned or absent from the lean
        # stack. The routine apply identity cannot use a request-tag call to
        # claim an unrelated resource and then delete/update it.
        allowed_actions = {
            action
            for statement in statements
            if statement["Effect"] == "Allow"
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
        }
        for forbidden in (
            "application-autoscaling:RegisterScalableTarget",
            "application-autoscaling:TagResource",
            "backup:CreateBackupPlan",
            "backup:DeleteBackupPlan",
            "backup:TagResource",
            "ce:CreateAnomalyMonitor",
            "ce:CreateAnomalySubscription",
            "ce:DeleteAnomalyMonitor",
            "ce:DeleteAnomalySubscription",
            "ce:TagResource",
            "kms:CreateKey",
            "kms:PutKeyPolicy",
            "kms:ScheduleKeyDeletion",
            "kms:TagResource",
        ):
            self.assertNotIn(forbidden, allowed_actions)
        self.assertIn("servicediscovery:TagResource", allowed_actions)
        for forbidden in (
            "servicediscovery:DeleteNamespace",
            "servicediscovery:DeleteService",
            "servicediscovery:UpdatePrivateDnsNamespace",
            "servicediscovery:UpdateService",
        ):
            self.assertNotIn(forbidden, allowed_actions)

        backup_selection = by_sid["ManageSelectionOnExactFoundationBackupPlan"]
        self.assertEqual(backup_selection["Resource"], "CustomerDataBackupPlan.BackupPlanArn")
        self.assertEqual(
            backup_selection["Condition"]["StringEquals"]["aws:ResourceTag/ManagedBy"],
            "CloudFormation-bootstrap",
        )
        account_setting = by_sid["RequiredEcsAccountSetting"]
        self.assertEqual(account_setting["Condition"]["StringEquals"]["ecs:account-setting"], "awsvpcTrunking")

        create_asg = by_sid["CreateOnlyExactTaggedAutoScalingGroup"]
        self.assertIn("autoScalingGroupName/jsc-public-beta-ecs-*", create_asg["Resource"])
        self.assertEqual(
            create_asg["Condition"]["Bool"]["autoscaling:LaunchTemplateVersionSpecified"],
            "true",
        )
        self.assertNotIn("iam:DeleteRolePermissionsBoundary", {
            action
            for statement in statements
            if statement["Effect"] == "Allow"
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
        })
        self.assertEqual(by_sid["DenyWorkloadBoundaryRemoval"]["Effect"], "Deny")

        state_deny = by_sid["DenyBootstrapStateControlPlaneMutation"]
        self.assertEqual(state_deny["Effect"], "Deny")
        self.assertIn("kms:ScheduleKeyDeletion", state_deny["Action"])
        self.assertIn("s3:DeleteBucket", state_deny["Action"])
        self.assertIn("StateKey.Arn", state_deny["Resource"])
        self.assertIn("StateBucket.Arn", state_deny["Resource"])

        application_buckets = by_sid["PublicBetaApplicationBucketsOnly"]["Resource"]
        self.assertTrue(all(
            "jsc-public-beta-access-logs-${AWS::AccountId}" in arn
            or "jsc-public-beta-documents-${AWS::AccountId}" in arn
            for arn in application_buckets
        ))
        self.assertNotIn("jsc-public-beta-*", application_buckets)
        self.assertIn(
            "(?!jsc-public-beta-(access-logs|documents|erasure-journal)-)",
            template["Parameters"]["StateBucketName"]["AllowedPattern"],
        )

        boundary_statements = resources["WorkloadPermissionsBoundary"]["Properties"]["PolicyDocument"]["Statement"]
        boundary_by_sid = {statement["Sid"]: statement for statement in boundary_statements}
        self.assertEqual(
            boundary_by_sid["FoundationDataKey"]["Resource"],
            "ApplicationDataKey.Arn",
        )
        self.assertTrue(all(
            "jsc-public-beta-access-logs-${AWS::AccountId}" in arn
            or "jsc-public-beta-documents-${AWS::AccountId}" in arn
            for arn in boundary_by_sid["PublicBetaBucketsOnly"]["Resource"]
        ))
        self.assertIn("s3:GetBucketVersioning", boundary_by_sid["PublicBetaBucketsOnly"]["Action"])
        self.assertEqual(
            boundary_by_sid["ImmutableJournalWrite"]["Action"],
            "s3:PutObject",
        )
        self.assertIn(
            "/permanent-erasures/v1/*",
            boundary_by_sid["ImmutableJournalWrite"]["Resource"],
        )
        self.assertEqual(
            set(boundary_by_sid["BoundJournalRead"]["Action"]),
            {"s3:GetObject", "s3:GetObjectVersion"},
        )
        self.assertEqual(
            set(boundary_by_sid["JournalKmsThroughS3"]["Action"]),
            {"kms:Decrypt", "kms:GenerateDataKey"},
        )
        self.assertEqual(
            boundary_by_sid["JournalKmsThroughS3"]["Resource"],
            "ErasureJournalKey.Arn",
        )
        for foundation_name in (
            "ApplicationDataKey",
            "NotificationKey",
            "OperationsTopic",
            "CustomerDataBackupVault",
            "CustomerDataBackupPlan",
            "MonthlyCostAlertBudget",
            "MonthlyCostCeilingBudget",
            "MonthlyCostCriticalForecastBudget",
            "ServiceCostAnomalyMonitor",
            "DailyCostAnomalySubscription",
            "StateBucketPolicy",
            "ErasureJournalBucketPolicy",
            "OperationsTopicPolicy",
            "WorkloadPermissionsBoundary",
            "RdsMonitoringPermissionsBoundary",
            "BackupWorkloadBoundary",
            "BackupRestoreWorkloadBoundary",
        ):
            self.assertEqual(resources[foundation_name].get("DeletionPolicy"), "Retain")
            self.assertEqual(resources[foundation_name].get("UpdateReplacePolicy"), "Retain")
        self.assertEqual(template["Outputs"]["ApplicationDataKeyArn"]["Value"], "ApplicationDataKey.Arn")
        self.assertEqual(template["Outputs"]["OperationsTopicArn"]["Value"], "OperationsTopic")
        variables = (ROOT / "aws" / "public-beta" / "variables.tf").read_text(encoding="utf-8")
        certificate_switch = variables.split('variable "manage_certificate" {', maxsplit=1)[1].split(
            '\n}', maxsplit=1
        )[0]
        self.assertIn("default     = false", certificate_switch)
        self.assertIn("condition     = !var.manage_certificate", certificate_switch)

        terraform_source = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "aws" / "public-beta").glob("*.tf")
        )
        for foundation_resource in (
            'resource "aws_kms_key"',
            'resource "aws_backup_plan"',
            'resource "aws_backup_vault"',
            'resource "aws_budgets_budget"',
            'resource "aws_ce_anomaly_',
            'resource "aws_sns_topic"',
            'resource "aws_appautoscaling_',
        ):
            self.assertNotIn(foundation_resource, terraform_source)
        self.assertIn("var.foundation_data_kms_key_arn", terraform_source)
        self.assertIn("var.foundation_backup_plan_id", terraform_source)
        role_boundaries = {}
        for role_name, role_body in re.findall(
            r'^resource "aws_iam_role" "([^"]+)" \{(.*?)(?=^resource |\Z)',
            terraform_source,
            flags=re.MULTILINE | re.DOTALL,
        ):
            boundary_match = re.search(r'permissions_boundary\s*=\s*"([^"]+)"', role_body)
            self.assertIsNotNone(boundary_match, f"{role_name} has no permissions boundary")
            role_boundaries[role_name] = boundary_match.group(1)
        exceptional_boundaries = {
            "backup": "jsc-public-beta-backup-boundary",
            "backup_restore": "jsc-public-beta-backup-restore-boundary",
            "rds_monitoring": "jsc-public-beta-rds-monitoring-boundary",
            "restore_semantic_broker_task": "jsc-public-beta-restore-semantic-broker-boundary",
            "restore_semantic_state_machine": "jsc-public-beta-restore-semantic-broker-boundary",
        }
        self.assertEqual(
            {
                name: boundary.rsplit("/", maxsplit=1)[-1]
                for name, boundary in role_boundaries.items()
                if not boundary.endswith("/jsc-public-beta-workload-boundary")
            },
            exceptional_boundaries,
        )
        self.assertTrue(
            all(
                boundary.endswith("/jsc-public-beta-workload-boundary")
                for name, boundary in role_boundaries.items()
                if name not in exceptional_boundaries
            )
        )
        self.assertEqual(terraform_source.count("jsc-public-beta-rds-monitoring-boundary"), 1)
        self.assertEqual(terraform_source.count("jsc-public-beta-backup-boundary"), 1)
        self.assertEqual(terraform_source.count("jsc-public-beta-backup-restore-boundary"), 1)
        self.assertEqual(terraform_source.count("jsc-public-beta-restore-semantic-broker-boundary"), 2)
        self.assertNotIn("jsc-public-beta-erasure-journal-read-boundary", terraform_source)
        release = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        self.assertEqual(release.count("group: jsc-public-beta-aws-mutation"), 1)
        mutate_job = release.split("\n  mutate:\n", maxsplit=1)[1]
        self.assertIn(
            "    concurrency:\n      group: jsc-public-beta-aws-mutation\n      cancel-in-progress: false",
            mutate_job,
        )
        self.assertIn('test "$build_sha" = "$GITHUB_SHA"', release)
        self.assertEqual(release.count("Validate release contract before assuming AWS"), 2)
        self.assertEqual(release.count("verify_frontend_release_artifact.sh"), 2)

        build = (ROOT / ".github" / "workflows" / "aws-public-beta-build.yml").read_text(encoding="utf-8")
        build_script = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        publish_script = (ROOT / "scripts" / "aws" / "publish_release_images.sh").read_text(encoding="utf-8")
        self.assertIn("job-seeker-copilot-landing", build)
        self.assertIn("LANDING_RUNTIME_ENV_B64", build)
        self.assertIn("LAUNCH_APPROVALS_FILE", build)
        self.assertIn("build_landing_artifact.py", build_script)
        self.assertIn("--landing-only", build_script)
        self.assertIn("verify_frontend_release_artifact.sh", publish_script)
        self.assertIn("frontendArtifacts", build_script)
        self.assertIn("paymentFixtureAcceptance", build_script)
        self.assertIn("system-data-service", build_script)
        self.assertIn("[e2e]=", build_script)
        self.assertIn("Infrastructure does not contain the reviewed isolated payment fixture overlay", build_script)
        self.assertNotIn("aws ecr", build_script)
        self.assertIn("Refusing to execute source builds while AWS credentials are present", build_script)
        self.assertIn(
            "clamav/clamav:1.4.5@sha256:4de20bd9ab45a4b763c5412b769217ef5082572ebc8a63aff1a77943419e5dd8",
            build_script,
        )
        self.assertNotIn("1.4.5_base", build_script)
        self.assertIn("clamav_health_command=", build_script)
        self.assertIn("clamdscan --reload", build_script)
        self.assertIn("exit 42", build_script)
        self.assertIn("clamav_reload_observed=true", build_script)
        self.assertEqual(build_script.count('docker exec "$clamav_probe" /bin/sh -c "$clamav_health_command"'), 2)
        self.assertIn("uid=100,gid=101,mode=0750", build_script)
        self.assertNotIn("--tmpfs /var/lib/clamav", build_script)
        self.assertIn('push_image clamav "$clamav_image" 1.4.5', publish_script)
        self.assertIn('${GITHUB_REF:-}', build_script)
        self.assertNotIn('${GITHUB_REF:-refs/heads/main}', build_script)
        landing_builder = LANDING_BUILDER.read_text(encoding="utf-8")
        self.assertIn('build_environment.pop("AMPLIFY_RELEASE_AUTHORISED", None)', landing_builder)
        self.assertIn("aws ecr get-login-password", publish_script)
        self.assertIn("load_prepared_release_images.sh", build)
        prepare_job = build.split("\n  publish:\n", maxsplit=1)[0]
        self.assertNotIn("id-token: write", prepare_job)
        self.assertLess(build.index("Build and verify release artifacts without AWS credentials"), build.index("Configure build-only AWS role"))

    def test_release_runtime_dockerfiles_pin_fixed_alpine_openssl_packages(self) -> None:
        vulnerable_base = (
            "eclipse-temurin:17-jre-alpine@"
            "sha256:02320dd4ce20e243dfb915c686089cf9315c763084fafbb12d5c9993aee18b57"
        )
        pinned_base = (
            "eclipse-temurin:17-jre-alpine@"
            "sha256:90b7615cb81e3a75f69124fb480e48981c7d56dbc9f32c614d789d3a1c3e32fe"
        )
        expected_prefix = f"""FROM {pinned_base}
# Refresh the pinned runtime's OpenSSL packages to the CVE-2026-14456 fixed build.
RUN apk add --no-cache --upgrade \\
    libcrypto3=3.5.8-r0 \\
    libssl3=3.5.8-r0 \\
    openssl=3.5.8-r0
"""
        for service in (
            "adzuna-gateway",
            "document-generation-gateway",
            "jsearch-gateway",
            "reed-gateway",
        ):
            dockerfile = (ROOT / "docker" / f"{service}.runtime.Dockerfile").read_text(encoding="utf-8")
            self.assertNotIn(vulnerable_base, dockerfile, service)
            self.assertTrue(dockerfile.startswith(expected_prefix), service)
            self.assertEqual(dockerfile.count("FROM "), 1, service)
            self.assertNotIn("3.5.7-r0", dockerfile, service)
            for package in ("libcrypto3", "libssl3", "openssl"):
                self.assertEqual(dockerfile.count(f"{package}=3.5.8-r0"), 1, service)
            remainder = dockerfile.removeprefix(expected_prefix)
            self.assertNotRegex(remainder, r"\b(?:apk|apt-get)\b", service)

    def test_release_operator_pins_fixed_alpine_openssl_libraries(self) -> None:
        dockerfile = (ROOT / "aws" / "public-beta" / "operator" / "Dockerfile").read_text(encoding="utf-8")
        fixed_install = """RUN apk add --no-cache --upgrade \\
    libcrypto3=3.5.8-r0 \\
    libssl3=3.5.8-r0 \\
    aws-cli ca-certificates curl jq"""
        self.assertEqual(dockerfile.count("apk add"), 1)
        self.assertIn(fixed_install, dockerfile)
        self.assertNotIn("3.5.7-r0", dockerfile)
        self.assertEqual(dockerfile.count("libcrypto3=3.5.8-r0"), 1)
        self.assertEqual(dockerfile.count("libssl3=3.5.8-r0"), 1)

    def test_landing_static_tar_is_deterministic_and_rejects_links(self) -> None:
        spec = importlib.util.spec_from_file_location("build_landing_artifact", LANDING_BUILDER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "browser"
            (source / "config").mkdir(parents=True)
            (source / "index.html").write_text("<html></html>\n", encoding="utf-8")
            (source / "config" / "app-config.json").write_text('{"publicBetaEnabled":false}\n', encoding="utf-8")
            first = root / "first.tar"
            second = root / "second.tar"
            module.create_deterministic_tar(source, first)
            module.create_deterministic_tar(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                members = archive.getmembers()
                self.assertEqual([member.name for member in members], sorted(member.name for member in members))
                self.assertTrue(all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in members))

            (source / "linked-config").symlink_to(source / "config" / "app-config.json")
            with self.assertRaises(module.ReleaseInputError):
                module.create_deterministic_tar(source, root / "linked.tar")

        with self.assertRaisesRegex(ValueError, "duplicate key"):
            module.reject_duplicates([("PUBLIC_BETA_ENABLED", "false"), ("PUBLIC_BETA_ENABLED", "true")])

    def test_frontend_release_evidence_verifier_detects_substitution(self) -> None:
        spec = importlib.util.spec_from_file_location("build_landing_artifact_verify", LANDING_BUILDER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = root / "browser"
            (browser / "config").mkdir(parents=True)
            runtime_config = browser / "config" / "app-config.json"
            runtime_config.write_text('{"publicBetaEnabled":false}\n', encoding="utf-8")
            archive = root / "landing-static.tar"
            module.create_deterministic_tar(browser, archive)
            sam = root / "landing-waitlist-backend-template.yaml"
            sam.write_text("AWSTemplateFormatVersion: '2010-09-09'\n", encoding="utf-8")
            metadata = {
                "schemaVersion": 1,
                "repository": "jobseekercopilot/job-seeker-copilot-landing",
                "revision": "a" * 40,
                "artifactContractSha256": "b" * 64,
                "staticArtifactSha256": module.sha256(archive),
                "runtimeConfigSha256": module.sha256(runtime_config),
                "selectedSamTemplate": "infrastructure/waitlist-backend/template.yaml",
                "selectedSamTemplateSha256": module.sha256(sam),
                "deploymentStatus": "NOT_DEPLOYED",
            }
            metadata_path = root / "landing-artifact.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            client = {
                "revision": "c" * 40,
                "artifactContractSha256": "d" * 64,
                "imageDigest": "sha256:" + "e" * 64,
            }
            manifest = {
                "capabilities": {"frontendArtifactsVerified": True},
                "dependencyEvidence": {
                    "frontendArtifacts": {
                        "client": {
                            "revision": client["revision"],
                            "artifactContractSha256": client["artifactContractSha256"],
                            "packaging": "OCI_SSR_BFF",
                        },
                        "landing": {
                            key: value
                            for key, value in metadata.items()
                            if key not in {"schemaVersion", "repository"}
                        },
                    }
                },
                "images": {"job-seeker-copilot-client": {"digest": client["imageDigest"]}},
            }
            manifest_path = root / "image-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance_path = root / "provenance.json"
            provenance_path.write_text(
                json.dumps({"frontendArtifacts": {"client": client, "landing": metadata}}), encoding="utf-8"
            )
            command = [
                "bash",
                str(ROOT / "scripts" / "aws" / "verify_frontend_release_artifact.sh"),
                str(manifest_path),
                str(provenance_path),
                str(archive),
                str(metadata_path),
                str(sam),
            ]
            valid = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            sam.write_text("substituted: true\n", encoding="utf-8")
            substituted = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertNotEqual(substituted.returncode, 0)
            self.assertIn("SAM template checksum mismatch", substituted.stderr)

    def test_landing_runtime_legal_identity_must_match_protected_approval(self) -> None:
        spec = importlib.util.spec_from_file_location("validate_public_beta_landing", VALIDATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        legal = {
            "reviewed": True,
            "effectiveOn": "2026-08-15",
            "legalVersion": "uk-legal-1",
            "legalEntityType": "SOLE_TRADER",
            "taxStatus": "NOT_VAT_REGISTERED",
            "legalEntityName": "Reviewed Owner",
            "tradingName": "Job Seeker Copilot",
            "businessAddress": "Reviewed business address",
            "privacyEmail": "privacy@jobseekercopilot.com",
            "supportEmail": "support@jobseekercopilot.com",
            "icoRegistrationStatus": "NOT_REQUIRED_CONFIRMED",
            "icoRegistrationReference": "",
            "accountDeletionCompletionDays": 35,
            "documentDeletionCompletionDays": 35,
            "securityLogRetentionDays": 90,
            "supportRecordRetentionDays": 365,
            "financialRecordRetentionYears": 7,
            "termsUrl": "https://app.jobseekercopilot.com/terms",
            "privacyNoticeUrl": "https://app.jobseekercopilot.com/privacy",
        }
        config = dict.fromkeys(module.LANDING_RUNTIME_FIELDS, "")
        config.update(
            {
                "environmentName": "production",
                "publicWebsiteUrl": "https://www.jobseekercopilot.com",
                "minimumUserAge": 18,
                "enableLiveSubmissions": False,
                "publicBetaEnabled": False,
                "searchIndexingEnabled": False,
                "analyticsEnabled": False,
                "legalDocumentsReviewed": True,
                "mainApplicationUrl": "https://app.jobseekercopilot.com",
                "registrationUrl": "https://app.jobseekercopilot.com/register",
                "signInUrl": "https://app.jobseekercopilot.com/sign-in",
                "pricingUrl": "https://app.jobseekercopilot.com/payment",
                **{
                    runtime_name: legal[approval_name]
                    for runtime_name, approval_name in {
                        "legalEffectiveDate": "effectiveOn",
                        "legalVersion": "legalVersion",
                        "legalEntityType": "legalEntityType",
                        "taxStatus": "taxStatus",
                        "legalEntityName": "legalEntityName",
                        "tradingName": "tradingName",
                        "businessAddress": "businessAddress",
                        "privacyEmail": "privacyEmail",
                        "supportEmail": "supportEmail",
                        "icoRegistrationStatus": "icoRegistrationStatus",
                        "icoRegistrationReference": "icoRegistrationReference",
                        "accountDeletionCompletionDays": "accountDeletionCompletionDays",
                        "documentDeletionCompletionDays": "documentDeletionCompletionDays",
                        "securityLogRetentionDays": "securityLogRetentionDays",
                        "supportRecordRetentionDays": "supportRecordRetentionDays",
                        "financialRecordRetentionYears": "financialRecordRetentionYears",
                    }.items()
                },
            }
        )
        module.validate_landing_runtime_config(config, {"publicLegal": legal})
        config["taxStatus"] = "VAT_REGISTERED"
        with self.assertRaisesRegex(module.ContractError, "differ from protected launch approval"):
            module.validate_landing_runtime_config(config, {"publicLegal": legal})

    def test_rds_ca_is_checksum_bound_into_exact_database_images(self) -> None:
        build = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        self.assertIn('git -C "$checkout" merge-base --is-ancestor "$revision" origin/main', build)
        self.assertIn('scripts/test-all.sh" --profile full-fixture', build)
        self.assertIn("docker compose", build)
        self.assertIn('build "${runtime_services[@]}"', build)
        self.assertIn("for service in adzuna-gateway jsearch-gateway", build)
        self.assertIn("curl --fail --show-error --silent --location", build)
        self.assertIn("COPY --chmod=0444 global-bundle.pem /etc/jsc/rds/global-bundle.pem", build)
        self.assertIn("uk.jobseekercopilot.rds-ca-sha256", build)
        self.assertIn("USER 10001:10001", build)

    def test_release_build_reclaims_only_unused_cache_before_clamav(self) -> None:
        build = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        retained_inspection = 'docker image inspect "${retained_release_images[@]}" >/dev/null'
        self.assertIn("mapfile -t retained_release_images", build)
        self.assertIn('retained_release_images+=("$operator_image")', build)
        self.assertEqual(build.count(retained_inspection), 2)
        cache_reclaim = "docker builder prune --all --force >/dev/null"
        self.assertEqual(build.count(cache_reclaim), 1)
        self.assertNotIn("docker system prune", build)
        self.assertNotIn("docker image prune", build)
        self.assertNotIn("docker container prune", build)
        self.assertLess(build.index("operator_image=jsc-release-release-operator"), build.index(retained_inspection))
        self.assertLess(build.index(retained_inspection), build.index(cache_reclaim))
        self.assertLess(build.index(cache_reclaim), build.rindex(retained_inspection))
        self.assertLess(build.rindex(retained_inspection), build.index('docker pull "$clamav_image"'))

    def test_exact_locked_contract_hashes_reject_mutated_descendants(self) -> None:
        verifier_path = ROOT / "scripts" / "aws" / "verify_release_contract_hashes.py"
        spec = importlib.util.spec_from_file_location("verify_release_contract_hashes", verifier_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        manifest: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for index, (json_path, relative_file) in enumerate(module.CONTRACT_FILES.items()):
                source = workspace / relative_file
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"exact exported contract {index}\n".encode())
                cursor = manifest
                for component in json_path[:-1]:
                    cursor = cursor.setdefault(component, {})
                cursor[json_path[-1]] = hashlib.sha256(source.read_bytes()).hexdigest()

            module.verify_hashes(workspace, manifest)
            first_file = workspace / next(iter(module.CONTRACT_FILES.values()))
            first_file.write_bytes(first_file.read_bytes() + b"mutated descendant\n")
            with self.assertRaisesRegex(module.ContractHashError, "exact-checkout"):
                module.verify_hashes(workspace, manifest)

            first_file.write_bytes(b"exact exported contract 0\n")
            manifest["dependencyEvidence"]["unmapped"] = {"openApiSha256": "a" * 64}
            with self.assertRaisesRegex(module.ContractHashError, "unmapped"):
                module.verify_hashes(workspace, manifest)

        build = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        self.assertLess(
            build.index('scripts/test-all.sh" --profile full-fixture'),
            build.index("verify_release_contract_hashes.py"),
        )
        self.assertLess(
            build.index("verify_release_contract_hashes.py"),
            build.index('scripts/build-all.sh" --profile full-fixture'),
        )
        self.assertLess(
            build.index("verify_release_contract_hashes.py"),
            build.index(".capabilities.paymentV2ProductionContractVerified=true"),
        )

    def test_stripe_fixture_code_is_proven_dormant_in_the_exact_production_image(self) -> None:
        manifest = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        evidence = manifest["dependencyEvidence"]["stripeFixtureProductionIsolation"]
        self.assertEqual(evidence["profile"], "production")
        self.assertEqual(evidence["providerMode"], "DISABLED")
        self.assertTrue(evidence["fixtureModeStartupRejected"])
        self.assertEqual(evidence["fixturePaymentControlRouteStatus"], 404)
        self.assertEqual(len(evidence["conditionalBeansAbsent"]), 4)
        self.assertFalse(manifest["capabilities"]["stripeFixtureProductionIsolationVerified"])

        build = (ROOT / "scripts" / "aws" / "build_release_images.sh").read_text(encoding="utf-8")
        self.assertIn("did not reject production-profile FIXTURE startup", build)
        self.assertIn('stripe_fixture_logs=$(docker logs "$stripe_probe" 2>&1)', build)
        self.assertIn(
            "grep -Fq 'cannot start in FIXTURE mode with a production profile' <<<\"$stripe_fixture_logs\"",
            build,
        )
        self.assertNotIn('docker logs "$stripe_probe" 2>&1 | grep -Fq', build)
        self.assertIn("fixture payment-control route was present", build)
        self.assertIn("mode-conditional fixture control/provider bean was active", build)
        self.assertIn(".capabilities.stripeFixtureProductionIsolationVerified=true", build)
        runtime = (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        self.assertNotIn("STRIPE_FIXTURE_PAYMENT_CONTROL", runtime)
        self.assertNotIn("STRIPE_FIXTURE_WEBHOOK", runtime)

    def test_database_logging_suppresses_statements_and_bind_values(self) -> None:
        data = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        parameter_group = data.split('resource "aws_db_parameter_group" "postgres" {', maxsplit=1)[1].split(
            'resource "aws_iam_role" "rds_monitoring"', maxsplit=1
        )[0]
        for name, value in (
            ("log_min_duration_statement", "-1"),
            ("log_statement", "none"),
            ("log_duration", "0"),
            ("log_min_error_statement", "panic"),
            ("log_parameter_max_length", "0"),
            ("log_parameter_max_length_on_error", "0"),
            ("log_error_verbosity", "terse"),
            ("log_connections", "1"),
            ("log_disconnections", "1"),
        ):
            self.assertRegex(
                parameter_group,
                rf'name\s+=\s+"{re.escape(name)}"[\s\S]*?value\s+=\s+"{re.escape(value)}"',
            )
        self.assertNotIn('value        = "1000"', parameter_group)

    def test_rds_enhanced_monitoring_is_exactly_scoped_and_fail_closed(self) -> None:
        data = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        role = data.split('resource "aws_iam_role" "rds_monitoring" {', maxsplit=1)[1].split(
            'resource "aws_iam_role_policy_attachment" "rds_monitoring"', maxsplit=1
        )[0]
        self.assertIn("jsc-public-beta-rds-monitoring-boundary", role)
        self.assertIn(
            '"aws:SourceArn" = "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:db:${local.name_prefix}-postgres"',
            role,
        )
        self.assertNotIn('db:*', role)
        database = data.split('resource "aws_db_instance" "postgres" {', maxsplit=1)[1]
        self.assertIn("monitoring_interval             = 60", database)
        self.assertIn("monitoring_role_arn             = aws_iam_role.rds_monitoring.arn", database)

        template = self._load_bootstrap_template()
        resources = template["Resources"]
        boundary = resources["RdsMonitoringPermissionsBoundary"]
        self.assertEqual(boundary["DeletionPolicy"], "Retain")
        self.assertEqual(boundary["UpdateReplacePolicy"], "Retain")
        statements = boundary["Properties"]["PolicyDocument"]["Statement"]
        self.assertEqual(
            {statement["Resource"] for statement in statements},
            {
                "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:RDSOSMetrics",
                "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:RDSOSMetrics:log-stream:*",
            },
        )
        self.assertNotIn("/jsc/public-beta/", json.dumps(boundary))
        self.assertNotIn("*", statements[0]["Resource"])

        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        self.assertIn("verify_live_rds_monitoring.py", release)
        self.assertIn("--allow-rds-monitoring-migration", release)

    def test_public_security_log_retention_matches_every_diagnostic_store(self) -> None:
        data = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        observability = (ROOT / "aws" / "public-beta" / "observability.tf").read_text(encoding="utf-8")
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        self.assertIn('Retention = "${var.log_retention_days}-days"', data)
        self.assertIn("expiration { days = var.log_retention_days }", data)
        self.assertNotRegex(compute, r"retention_in_days\s*=\s*[0-9]+")
        self.assertNotRegex(observability, r"retention_in_days\s*=\s*[0-9]+")
        self.assertIn(
            "try(local.public_legal_contract.securityLogRetentionDays, 0) == var.log_retention_days",
            locals_source,
        )

    def test_clamav_is_a_no_task_role_service_with_scoped_scanner_network(self) -> None:
        network = (ROOT / "aws" / "public-beta" / "network.tf").read_text(encoding="utf-8")
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        self.assertNotIn("self        = true", network)
        self.assertNotIn("from_port   = 0\n    to_port     = 0", network)
        public_egress = network.split("service_public_https_egress", maxsplit=1)[1].split("]))", maxsplit=1)[0]
        self.assertNotIn('"document-store-service"', public_egress)
        self.assertIn('for_each = local.service_dependencies', network)
        self.assertIn('resource "aws_security_group" "clamav"', network)
        self.assertIn('resource "aws_vpc_security_group_ingress_rule" "clamav_from_document_store"', network)
        self.assertIn('resource "aws_vpc_security_group_egress_rule" "document_store_clamav"', network)
        clamav_task = compute.split('resource "aws_ecs_task_definition" "clamav" {', maxsplit=1)[1].split(
            'resource "aws_ecs_service" "clamav" {', maxsplit=1
        )[0]
        self.assertNotIn("task_role_arn", clamav_task)
        self.assertIn("execution_role_arn       = aws_iam_role.clamav_execution.arn", clamav_task)
        self.assertIn("memory = 4096", clamav_task)
        self.assertIn("172800", clamav_task)
        self.assertIn("clamdscan --reload", clamav_task)
        self.assertNotIn('containerPath = "/var/lib/clamav"', clamav_task)
        self.assertIn('"uid=100", "gid=101", "mode=0750"', clamav_task)

    def test_lean_autoscaling_cannot_request_a_second_node(self) -> None:
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        outputs = (ROOT / "aws" / "public-beta" / "outputs.tf").read_text(encoding="utf-8")
        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        self.assertIn("max_size = local.node_count", compute)
        self.assertIn("version = aws_launch_template.ecs.latest_version", compute)
        self.assertNotIn('version = "$Latest"', compute)
        self.assertIn("min_healthy_percentage       = var.high_availability ? 50 : 0", compute)
        self.assertIn("max_healthy_percentage       = 100", compute)
        self.assertIn('scale_in_protected_instances = "Refresh"', compute)
        self.assertIn('standby_instances            = "Terminate"', compute)
        self.assertIn("skip_matching                = true", compute)
        self.assertIn("auto_rollback                = true", compute)
        self.assertIn("target_capacity           = 100", compute)
        self.assertNotIn('resource "aws_appautoscaling_', compute)
        self.assertIn("deployment_maximum_percent         = 100", compute)
        self.assertIn("deployment_minimum_healthy_percent = 0", compute)
        self.assertNotIn("deployment_maximum_percent         = var.high_availability ? 200", compute)
        self.assertIn('{ containerPath = "/var/log/clamav", size = 64', compute)
        self.assertIn("steady_state_task_slots = length(local.raw_services) + 2", locals_source)
        self.assertIn("release_task_slots = (length(local.raw_services) + 1) * local.deployment_copy_multiplier + 1", locals_source)
        self.assertIn('"m7i.2xlarge" = { cpu = 8192, memory = 32768, awsvpc_tasks_per_instance = 40 }', locals_source)
        self.assertIn('"m7i.4xlarge" = { cpu = 16384, memory = 65536, awsvpc_tasks_per_instance = 60 }', locals_source)
        self.assertIn("condition     = local.release_reserved_cpu + local.os_reserved_cpu", locals_source)
        self.assertIn("condition     = local.release_reserved_memory + local.os_reserved_memory", locals_source)
        self.assertIn("filesha256(local.approval_manifest_path)", locals_source)
        self.assertIn("reserved_cpu_units               = local.release_reserved_cpu", outputs)
        self.assertIn("awsvpc_tasks_per_instance        = local.instance_capacity[var.instance_type].awsvpc_tasks_per_instance", outputs)
        self.assertIn("awsvpc_task_limit                = local.instance_capacity[var.instance_type].awsvpc_tasks_per_instance * local.node_count", outputs)
        self.assertIn("task_slots=$(jq -er '.task_slots'", release)
        self.assertIn("awsvpc_task_limit=$(jq -er '.awsvpc_task_limit'", release)
        self.assertIn('.name == "ecs.instance-type" and .value == $expected_instance_type', release)
        self.assertIn('.type == "ElasticNetworkInterface" and .status == "ATTACHED"', release)
        self.assertIn("remaining_awsvpc_tasks=$((awsvpc_task_limit - active_tasks))", release)
        self.assertNotIn('select(.name == "ENI")', release)

    def test_private_service_discovery_is_protected_from_provider_forcenew_drift(self) -> None:
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        self.assertNotIn("health_check_custom_config {}", compute)
        self.assertNotIn("health_check_custom_config {", compute)
        self.assertEqual(compute.count("prevent_destroy = true"), 3)

    def test_activation_requires_exact_prepared_release_markers(self) -> None:
        release = (ROOT / "scripts" / "aws" / "public_beta_release.sh").read_text(encoding="utf-8")
        activate = release.split("  activate)", maxsplit=1)[1]
        self.assertIn("assert_exact_prepared_release", activate)
        self.assertIn('run_release_operator.sh" release-preflight', activate)
        self.assertIn("assert_marker database-bootstrap", release)
        self.assertIn("assert_marker preflight", release)
        self.assertLess(activate.index("assert_exact_prepared_release"), activate.index("plan_and_apply 1 true activate"))
        self.assertNotIn("  darken)", release)
        self.assertIn('--landing-archive "$landing_archive"', release)

    def test_database_bootstrap_uses_rds_permitted_role_alteration_and_fails_closed(self) -> None:
        bootstrap = (
            ROOT / "aws" / "public-beta" / "operator" / "bootstrap-databases.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("FROM pg_auth_members m WHERE m.member = r.oid", bootstrap)
        self.assertIn('"false:false:false:false:false:0"', bootstrap)
        self.assertIn("privileged role or membership detected", bootstrap)
        self.assertIn(
            "ALTER ROLE %I LOGIN PASSWORD %L NOINHERIT CONNECTION LIMIT 14",
            bootstrap,
        )
        alter_role = re.search(r"SELECT format\('ALTER ROLE [^']+'", bootstrap)
        self.assertIsNotNone(alter_role)
        for rds_forbidden_attribute in (
            "NOSUPERUSER",
            "NOCREATEDB",
            "NOCREATEROLE",
            "NOREPLICATION",
            "NOBYPASSRLS",
        ):
            self.assertNotIn(rds_forbidden_attribute, alter_role.group(0))
        self.assertIn("ALTER SCHEMA public OWNER TO %I", bootstrap)
        self.assertIn("GRANT USAGE, CREATE ON SCHEMA public TO %I", bootstrap)
        self.assertIn("SELECT pg_get_userbyid(nspowner)", bootstrap)
        self.assertIn('"$username:true:true:true:true"', bootstrap)
        app_verification = bootstrap.split('schema_state="', maxsplit=1)[1]
        self.assertNotIn("ALTER SCHEMA", app_verification)
        self.assertNotIn("GRANT USAGE", app_verification)
        self.assertNotIn("REVOKE CREATE", app_verification)

    def test_emergency_darken_is_approval_independent_and_closes_every_public_route_first(self) -> None:
        emergency = (ROOT / "scripts" / "aws" / "emergency_darken.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        outputs = (ROOT / "aws" / "public-beta" / "outputs.tf").read_text(encoding="utf-8")
        self.assertIn('current_release_id=$(jq -er .release_id', emergency)
        self.assertIn('[[ "$current_release_id" == "$release_id" ]]', emergency)
        self.assertNotIn("terraform -chdir=\"$module\" plan", emergency)
        self.assertNotIn("validate_public_beta.py", emergency)
        self.assertNotIn("APPROVAL_MANIFEST", emergency)
        self.assertLess(emergency.index("aws elbv2 modify-rule"), emergency.index("aws elbv2 modify-listener"))
        self.assertLess(emergency.index("aws elbv2 modify-listener"), emergency.index("aws ecs update-service"))
        self.assertNotIn("register-scalable-target", emergency)
        self.assertNotIn("DynamicScalingOutSuspended", emergency)
        self.assertIn("--desired-count 0", emergency)
        self.assertIn("all application/scanner/operator tasks are stopped", emergency)
        self.assertIn("expected_services+=(clamav)", emergency)
        self.assertIn("aws ecs list-tags-for-resource", emergency)
        self.assertIn('$tags.Purpose == "ReleaseOperator"', emergency)
        self.assertIn("aws ecs stop-task", emergency)
        self.assertLess(
            emergency.index("aws ecs stop-task"),
            emergency.index("tagged operators were stopped, but"),
        )
        self.assertIn('if: inputs.action != \'foundation\' && inputs.action != \'darken\'', workflow)
        self.assertIn("Execute approval-independent emergency containment", workflow)
        self.assertIn('EXPECTED_RELEASE_ID: ${{ inputs.release_id }}', workflow)
        self.assertIn('scripts/aws/emergency_darken.sh "$EXPECTED_RELEASE_ID"', workflow)
        self.assertIn('output "emergency_darken_contract"', outputs)
        self.assertIn("stripe_webhook_rule_arn", outputs)

    def test_payment_and_stripe_templates_fail_closed(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        stripe_runtime_block = locals_source.split("stripe_commercial_environment = {", maxsplit=1)[1].split(
            "\n  }", maxsplit=1
        )[0]
        self.assertIn(
            'EXTERNAL_PROVIDER_MODE         = var.enabled_integrations.stripe ? "LIVE" : "DISABLED"',
            stripe_runtime_block,
        )
        self.assertNotIn('"FIXTURE"', stripe_runtime_block)
        payment = runtime["payment-service"]["environment"]
        stripe = runtime["stripe-gateway"]["environment"]
        self.assertEqual(payment["PAYMENT_CHECKOUT_ENABLED"], "false")
        self.assertEqual(payment["PAYMENT_CHECKOUT_RELEASE_AUTHORISED"], "false")
        self.assertEqual(payment["PAYMENT_TAX_STATUS"], "NOT_CONFIGURED")
        self.assertEqual(payment["PAYMENT_LEGAL_ENTITY_TYPE"], "NOT_CONFIGURED")
        self.assertEqual(payment["PAYMENT_LEGAL_ENTITY_REVIEWED"], "false")
        self.assertEqual(payment["PAYMENT_FOUNDING_PROMOTION_ENABLED"], "false")
        self.assertEqual(payment["PAYMENT_CHECKOUT_ORDER_TTL"], "PT1H")
        self.assertEqual(stripe["EXTERNAL_PROVIDER_MODE"], "DISABLED")
        self.assertEqual(stripe["STRIPE_LIVE_RELEASE_AUTHORISED"], "false")
        self.assertEqual(stripe["STRIPE_PRICE_STARTER"], "UNAPPROVED")
        self.assertEqual(stripe["STRIPE_PRICE_ACTIVE"], "UNAPPROVED")
        self.assertEqual(stripe["STRIPE_PRICE_POWER"], "UNAPPROVED")
        self.assertNotIn("?", stripe["STRIPE_SUCCESS_URL"])
        self.assertNotIn("?", stripe["STRIPE_CANCEL_URL"])

    def test_google_billing_quota_gate_is_external_and_fail_closed(self) -> None:
        approvals = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text(encoding="utf-8")
        )["integrations"]["google_maps"]
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        self.assertFalse(approvals["approved"])
        self.assertFalse(approvals["googleBillingQuotasVerified"])
        self.assertEqual(approvals["gcpBudgetAlertThresholdPercents"], [50, 75, 90, 100])
        self.assertEqual(runtime["google-maps-gateway"]["environment"]["GOOGLE_MAPS_ENABLED"], "{{google_enabled}}")

    def test_bedrock_runtime_contract_matches_available_account_evidence(self) -> None:
        approvals = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text(encoding="utf-8")
        )["integrations"]["bedrock"]
        environment = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]["llm-gateway"]["environment"]

        self.assertEqual(environment["EXTERNAL_PROVIDER_MODE"], "{{bedrock_mode}}")
        self.assertEqual(environment["BEDROCK_MODEL_ID"], "anthropic.claude-3-7-sonnet-20250219-v1:0")
        self.assertEqual(environment["BEDROCK_REGION"], "{{region}}")
        self.assertEqual(environment["GENERATION_MODEL_ID"], environment["BEDROCK_MODEL_ID"])
        self.assertEqual(
            environment["GENERATION_MODEL_DEPLOYMENT_VERSION"],
            "document-generation-bedrock-claude-3-7-sonnet-20250219",
        )
        for forbidden in ("OPENAI_ENDPOINT", "OPENAI_MODEL", "OPENAI_API_KEY"):
            self.assertNotIn(forbidden, environment)
        self.assertIn("modelId", approvals)
        self.assertIn("awsRegion", approvals)
        self.assertIn("dataProcessingOwner", approvals)
        self.assertIn("dataProcessingReviewedOn", approvals)

    def test_client_and_registration_legal_contracts_fail_closed(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        approvals = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text(encoding="utf-8")
        )
        client = runtime["job-seeker-copilot-client"]["environment"]
        auth = runtime["authentication-service"]["environment"]
        self.assertEqual(client["BFF_SESSION_COOKIE_PROFILE"], "production")
        self.assertEqual(client["COMMUTE_ROUTING_MODE"], "DISTANCE_ONLY")
        self.assertEqual(client["LEGAL_DOCUMENTS_REVIEWED"], "false")
        self.assertEqual(client["LEGAL_ENTITY_TYPE"], "NOT_CONFIGURED")
        self.assertEqual(client["TAX_STATUS"], "NOT_CONFIGURED")
        self.assertEqual(auth["AUTH_LEGAL_DOCUMENTS_REVIEWED"], "false")
        self.assertEqual(auth["AUTH_LEGAL_CURRENT_VERSION"], "NOT_CONFIGURED")
        self.assertFalse(approvals["publicLegal"]["reviewed"])
        self.assertEqual(approvals["publicLegal"]["legalEntityType"], "NOT_CONFIGURED")

    def test_user_management_gateway_has_exact_production_browser_origin(self) -> None:
        environment = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]["user-management-gateway"]["environment"]

        self.assertEqual(
            environment["GATEWAY_ALLOWED_ORIGINS"],
            "https://app.jobseekercopilot.com",
        )

    def test_document_store_journal_is_machine_written_immutable_and_release_gated(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]["document-store-service"]
        environment = runtime["environment"]
        self.assertEqual(environment["DOCUMENT_STORE_ERASURE_JOURNAL_PROVIDER"], "s3")
        self.assertEqual(environment["DOCUMENT_STORE_ERASURE_JOURNAL_REGION"], "{{region}}")
        self.assertEqual(
            environment["DOCUMENT_STORE_ERASURE_JOURNAL_BUCKET"], "{{erasure_journal_bucket}}"
        )
        self.assertEqual(
            environment["DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID"], "{{erasure_journal_kms_key_arn}}"
        )
        self.assertEqual(environment["DOCUMENT_STORE_ERASURE_JOURNAL_CREDENTIALS_PROVIDER"], "task-role")
        self.assertEqual(environment["DOCUMENT_STORE_ERASURE_JOURNAL_OBJECT_LOCK_ENABLED"], "true")
        self.assertEqual(
            environment["DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION"], "UNAPPROVED"
        )
        self.assertEqual(environment["TZ"], "UTC")
        approvals = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text(encoding="utf-8")
        )["documentStorePermanentErasure"]
        self.assertEqual(approvals["journalRetentionPolicyVersion"], "NOT_CONFIGURED")
        image_manifest = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        erasure_evidence = image_manifest["dependencyEvidence"]["documentStorePermanentErasure"]
        self.assertEqual(
            erasure_evidence["revision"],
            "159f75701654d5e0a951f0546cf1583e993a9b47",
        )
        self.assertEqual(
            erasure_evidence["openApiSha256"],
            "e43ef6ea262553eb5fd5752b984d6cf027a538b930a1dff7288091e7a3ee1242",
        )
        self.assertEqual(
            erasure_evidence["restoreReplayRunbookSha256"],
            hashlib.sha256(
                (ROOT / erasure_evidence["restoreReplayRunbook"]).read_bytes()
            ).hexdigest(),
        )
        self.assertFalse(image_manifest["capabilities"]["documentStorePermanentErasureVerified"])
        partially_pinned = copy.deepcopy(image_manifest)
        partially_pinned["dependencyEvidence"]["documentStorePermanentErasure"]["openApiSha256"] = "PENDING"
        with tempfile.TemporaryDirectory() as directory:
            partial_path = Path(directory) / "partial-image-manifest.json"
            partial_path.write_text(json.dumps(partially_pinned), encoding="utf-8")
            partial_result = self.run_validator("--image-manifest", str(partial_path))
        self.assertNotEqual(partial_result.returncode, 0)
        self.assertIn("wholly PENDING or reviewed", partial_result.stderr)

        locals_source = (ROOT / "aws" / "public-beta" / "locals.tf").read_text(encoding="utf-8")
        erasure_ready = locals_source.split(
            "document_store_permanent_erasure_image_ready = (", maxsplit=1
        )[1].split("\n  )", maxsplit=1)[0]
        self.assertIn('regex("^[0-9a-f]{40}$"', erasure_ready)
        self.assertIn('regex("^[0-9a-f]{64}$"', erasure_ready)
        self.assertNotIn("PENDING", erasure_ready)
        self.assertIn("initial_beta_recovery_exception_active", locals_source)
        self.assertIn('timeadd(local.initial_beta_recovery_exception.approvedAt, "168h")', locals_source)
        self.assertIn("document_store_erasure_release_authorised", locals_source)
        self.assertIn("maximumApplicationDesiredCount", locals_source)

        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        journal_policy = compute.split(
            'sid     = "WriteOnlyImmutableErasureJournalRecords"', maxsplit=1
        )[1].split('data "aws_iam_policy_document" "document_store"', maxsplit=1)[0]
        self.assertIn("permanent-erasures/v1/*", journal_policy)
        for action in ("s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "kms:GenerateDataKey", "kms:Decrypt"):
            self.assertIn(action, journal_policy)
        for forbidden in (
            "s3:ListBucket", "s3:ListBucketVersions", "s3:DeleteObject", "s3:DeleteObjectVersion",
            "s3:HeadObject", "s3:BypassGovernanceRetention",
        ):
            self.assertNotIn(forbidden, journal_policy)
        self.assertNotRegex(journal_policy, r'actions\s*=\s*\[[^]]*"kms:(Encrypt|DescribeKey)"')
        self.assertNotIn("s3:x-amz-server-side-encryption-bucket-key-enabled", journal_policy)
        self.assertIn('variable = "s3:x-amz-server-side-encryption"', journal_policy)
        self.assertIn('variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"', journal_policy)
        self.assertIn('variable = "kms:ViaService"', journal_policy)
        self.assertIn('variable = "kms:EncryptionContext:aws:s3:arn"', journal_policy)

        preflight = (ROOT / "aws" / "public-beta" / "operator" / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn('document-permanent-erasure-readiness.v3', preflight)
        self.assertIn(".recoveryDays == 30", preflight)
        self.assertNotIn(".recoveryDays == 35", preflight)
        for pending_count in (
            "recoveryJournalWritePending", "recoveryJournalEvidenceMissing",
            "liveErasureReconciliationPending", "restoreJournalReadPending",
            "restoreReplayPending", "backupRetentionOverdue",
        ):
            self.assertIn(f".{pending_count} == 0", preflight)
        self.assertIn(".backupRetentionPending >= 0", preflight)
        self.assertNotIn(".backupRetentionPending == 0", preflight)

    def test_release_approval_rejects_placeholders_zero_hashes_and_incoherent_provenance(self) -> None:
        spec = importlib.util.spec_from_file_location("validate_public_beta_approvals", VALIDATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        reviewed_at = module.datetime.datetime.now(module.datetime.timezone.utc).replace(microsecond=0)
        today = reviewed_at.date()
        approvals = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "launch-approvals.json").read_text(encoding="utf-8")
        )
        approvals["reviewedAt"] = reviewed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        approvals["githubEnvironmentProtection"].update({
            "reviewed": True,
            "reviewedBy": "Bernard McGeever, sole operator",
            "reviewedOn": today.isoformat(),
            "evidenceReference": "github-environment-protection-review-2026-08-15",
            "ownerOnlyWorkflowActorVerified": True,
            "soloOperatorSelfApprovalAuthorised": True,
            "exactMainBranchVerified": True,
            "administratorBypassDisabled": True,
        })
        approvals["documentStorePermanentErasure"].update({
            "reviewed": True,
            "reviewedBy": "Independent privacy and recovery reviewer",
            "reviewedOn": today.isoformat(),
            "evidenceReference": "document-erasure-recovery-review-2026-08-15",
            "retentionPolicyVersion": "document-retention-2026-08-15",
            "backupRetentionPolicyVersion": "aws-backup-35-days-2026-08-15",
            "journalRetentionPolicyVersion": "immutable-erasure-journal-2026-08-15",
            "maximumBackupRetentionDays": 35,
            "journalRetentionDays": 90,
            "externalDeletionJournalVerified": True,
            "isolatedRestoreReplayVerified": True,
            "restoreDrillEvidenceSha256": "3" * 64,
        })
        legal_hash = "1" * 64
        approvals["publicLegal"].update({
            "reviewed": True,
            "reviewedBy": "Independent legal reviewer",
            "evidenceReference": "legal-review-record-2026-08-15",
            "legalVersion": "uk-consumer-terms-2026-08-15",
            "effectiveOn": today.isoformat(),
            "legalEntityType": "SOLE_TRADER",
            "taxStatus": "NOT_VAT_REGISTERED",
            "legalEntityName": "Reviewed Owner Name",
            "tradingName": "Job Seeker Copilot",
            "businessAddress": "Reviewed United Kingdom service address",
            "privacyEmail": "privacy@jobseekercopilot.com",
            "supportEmail": "support@jobseekercopilot.com",
            "icoRegistrationStatus": "NOT_REQUIRED_CONFIRMED",
            "icoRegistrationReference": "",
            "accountDeletionCompletionDays": 35,
            "documentDeletionCompletionDays": 35,
            "securityLogRetentionDays": 90,
            "supportRecordRetentionDays": 365,
            "financialRecordRetentionYears": 7,
            "termsUrl": "https://app.jobseekercopilot.com/terms",
            "privacyNoticeUrl": "https://app.jobseekercopilot.com/privacy",
            "clientLegalArtifactSha256": legal_hash,
            "landingLegalArtifactSha256": "2" * 64,
        })
        stripe = approvals["integrations"]["stripe"]
        stripe.update({
            "legalEntityType": "SOLE_TRADER",
            "legalEntityConfigurationVersion": "uk-consumer-terms-2026-08-15",
            "taxStatus": "NOT_VAT_REGISTERED",
            "consumerTermsVersion": "uk-consumer-terms-2026-08-15",
            "consumerTermsEffectiveOn": today.isoformat(),
            "consumerTermsUrl": "https://app.jobseekercopilot.com/terms",
            "consumerTermsContentSha256": legal_hash,
            "financialRecordRetentionYears": 7,
        })
        module.validate_approvals(approvals, True)

        pending_restore_candidate = copy.deepcopy(approvals)
        pending_restore_candidate["documentStorePermanentErasure"].update({
            "isolatedRestoreReplayVerified": False,
            "restoreDrillEvidenceSha256": "",
        })
        module.validate_approvals(pending_restore_candidate, True, restore_candidate=True)
        with self.assertRaisesRegex(module.ContractError, "isolated-restore replay evidence"):
            module.validate_approvals(pending_restore_candidate, True)

        exception_release = copy.deepcopy(pending_restore_candidate)
        exception_release["documentStorePermanentErasure"]["initialPublicBetaRecoveryException"].update({
            "approved": True,
            "id": "initial-public-beta-recovery-2026-08-23",
            "approvedBy": "Bernard McGeever, product owner",
            "approvedAt": reviewed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiresAt": (reviewed_at + module.datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "trackingReference": "https://github.com/jobseekercopilot/infrastructure/issues/999",
            "justification": "Low-traffic initial public beta with the full recovery drill due within seven days.",
            "compensatingControl": "Encrypted versioned storage, automated backups, fixed scaling ceilings and emergency darkening remain enabled.",
            "maximumApplicationDesiredCount": 1,
        })
        module.validate_approvals(exception_release, True)

        expired_exception = copy.deepcopy(exception_release)
        expired_exception["documentStorePermanentErasure"]["initialPublicBetaRecoveryException"].update({
            "approvedAt": (reviewed_at - module.datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiresAt": (reviewed_at - module.datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        with self.assertRaisesRegex(module.ContractError, "exception is expired"):
            module.validate_approvals(expired_exception, True)

        overlong_exception = copy.deepcopy(exception_release)
        overlong_exception["documentStorePermanentErasure"]["initialPublicBetaRecoveryException"]["expiresAt"] = (
            reviewed_at + module.datetime.timedelta(days=8)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaisesRegex(module.ContractError, "exceeds seven days"):
            module.validate_approvals(overlong_exception, True)

        completed_with_exception = copy.deepcopy(exception_release)
        completed_with_exception["documentStorePermanentErasure"].update({
            "isolatedRestoreReplayVerified": True,
            "restoreDrillEvidenceSha256": "3" * 64,
        })
        with self.assertRaisesRegex(module.ContractError, "requires removal"):
            module.validate_approvals(completed_with_exception, True)

        mutations = (
            (("publicLegal", "reviewedBy"), "TBD"),
            (("publicLegal", "evidenceReference"), "PLACEHOLDER"),
            (("publicLegal", "legalVersion"), "PLACEHOLDER"),
            (("publicLegal", "privacyEmail"), "placeholder@example.com"),
            (("publicLegal", "clientLegalArtifactSha256"), "0" * 64),
            (("publicLegal", "landingLegalArtifactSha256"), "0" * 64),
            (("documentStorePermanentErasure", "reviewedBy"), "TBD"),
            (("documentStorePermanentErasure", "evidenceReference"), "PLACEHOLDER"),
            (("documentStorePermanentErasure", "retentionPolicyVersion"), "NOT_CONFIGURED"),
            (("documentStorePermanentErasure", "backupRetentionPolicyVersion"), "TBD"),
            (("documentStorePermanentErasure", "journalRetentionPolicyVersion"), "UNAPPROVED"),
            (("documentStorePermanentErasure", "externalDeletionJournalVerified"), False),
            (("documentStorePermanentErasure", "isolatedRestoreReplayVerified"), False),
            (("documentStorePermanentErasure", "restoreDrillEvidenceSha256"), "0" * 64),
        )
        for path, value in mutations:
            candidate = copy.deepcopy(approvals)
            candidate[path[0]][path[1]] = value
            with self.assertRaises(module.ContractError, msg=".".join(path)):
                module.validate_approvals(candidate, True)

        under_retained_journal = copy.deepcopy(approvals)
        under_retained_journal["publicLegal"]["documentDeletionCompletionDays"] = 365
        with self.assertRaisesRegex(module.ContractError, "journal retention"):
            module.validate_approvals(under_retained_journal, True)

        future = copy.deepcopy(approvals)
        future["reviewedAt"] = (reviewed_at + module.datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaisesRegex(module.ContractError, "future"):
            module.validate_approvals(future, True)

        def approve_common(candidate: dict[str, object], name: str) -> dict[str, object]:
            approval = candidate["integrations"][name]
            approval.update({
                "approved": True,
                "approvalReference": f"provider-approval-record-{name}",
                "approvedBy": "Release compliance owner",
                "termsReviewedOn": today.isoformat(),
                "expiresOn": (today + module.datetime.timedelta(days=30)).isoformat(),
                "monthlyRequestLimit": 1000,
                "monthlyCostCeilingGbp": 100,
                "attributionRequirement": "Reviewed provider attribution and display obligation",
            })
            return approval

        common_placeholder = copy.deepcopy(approvals)
        approved = approve_common(common_placeholder, "nhs_jobs")
        approved["approvalReference"] = "TBD"
        with self.assertRaisesRegex(module.ContractError, "approvalReference"):
            module.validate_approvals(common_placeholder, True)

        google_placeholder = copy.deepcopy(approvals)
        google = approve_common(google_placeholder, "google_maps")
        google.update({
            "googleBillingQuotasVerified": True,
            "billingQuotaEvidenceReference": "google-quota-review-record",
            "gcpProjectId": "job-seeker-copilot-production",
            "placesQuotaId": "places-daily-requests",
            "placesDailyQuota": 100,
            "routeMatrixEssentialsQuotaId": "route-matrix-essential-elements",
            "routeMatrixEssentialsDailyElementQuota": 100,
            "routeMatrixProQuotaId": "route-matrix-pro-elements",
            "routeMatrixProDailyElementQuota": 100,
            "gcpBudgetAlertGbp": 50,
            "emergencyDisableOwner": "Platform release owner",
            "emergencyDisableRunbookReference": "google-emergency-disable-runbook",
        })
        google["billingQuotaEvidenceReference"] = "PLACEHOLDER"
        with self.assertRaisesRegex(module.ContractError, "billingQuotaEvidenceReference"):
            module.validate_approvals(google_placeholder, True)

        bedrock_placeholder = copy.deepcopy(approvals)
        bedrock = approve_common(bedrock_placeholder, "bedrock")
        bedrock.update({
            "modelId": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            "awsRegion": "eu-west-2",
            "dataProcessingOwner": "Data protection owner",
            "dataProcessingReviewedOn": today.isoformat(),
        })
        future_reviewed_bedrock = copy.deepcopy(bedrock_placeholder)
        future_reviewed_bedrock["integrations"]["bedrock"]["dataProcessingReviewedOn"] = (
            today + module.datetime.timedelta(days=1)
        ).isoformat()
        with self.assertRaisesRegex(module.ContractError, "follows reviewedAt provenance"):
            module.validate_approvals(future_reviewed_bedrock, True)

        bad_region_bedrock = copy.deepcopy(bedrock_placeholder)
        bad_region_bedrock["integrations"]["bedrock"]["awsRegion"] = "not-a-region"
        with self.assertRaisesRegex(module.ContractError, "valid AWS region"):
            module.validate_approvals(bad_region_bedrock, True)

        bedrock["modelId"] = "TBD"
        with self.assertRaisesRegex(module.ContractError, "modelId"):
            module.validate_approvals(bedrock_placeholder, True)

        stripe_placeholder = copy.deepcopy(approvals)
        live_stripe = approve_common(stripe_placeholder, "stripe")
        live_stripe.update({
            "paymentReadinessStatus": "PASS",
            "refundRunbookReference": "stripe-refund-runbook-record",
            "reconciliationRunbookReference": "stripe-reconciliation-runbook-record",
            "legalEntityReviewed": True,
            "legalEntityEvidenceReference": "reviewed-seller-identity-record",
            "merchantTermsTraderDisclosureVerified": True,
            "liveStripeCatalog": [
                {"id": "starter", "productId": "prod_liveStarter", "priceId": "price_liveStarter499"},
                {"id": "active", "productId": "prod_liveActive", "priceId": "price_liveActive1199"},
                {"id": "power", "productId": "prod_livePower", "priceId": "price_livePower1999"},
            ],
        })
        live_stripe["refundRunbookReference"] = "TBD"
        with self.assertRaisesRegex(module.ContractError, "refundRunbookReference"):
            module.validate_approvals(stripe_placeholder, True)

    def test_postcodes_northern_ireland_is_release_gated(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        images = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(
            runtime["postcode-io-gateway"]["environment"]["POSTCODES_IO_NORTHERN_IRELAND_ENABLED"],
            "false",
        )
        self.assertEqual(
            images["dependencyEvidence"]["postcodesNorthernIrelandCoverageChain"],
            {
                "postcodeIoGateway": {
                    "revision": "f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb",
                    "openApiSha256": "8321009c305d2d22986224e366df6f0b451c1b5587d05dd0ec4876441e09d7ff",
                },
                "locationService": {
                    "revision": "4d8d09a79018c3f281cfead84348d14ed84be851",
                    "openApiSha256": "0cd7a877836dfbf1a42b5f71e0a807ec8dc99f88d69a695d7c5734e320cdef27",
                },
                "locationGateway": {
                    "revision": "86b2805c8430ede14a53a7320b87f0eeb2797b17",
                    "openApiSha256": "30d71d6b2508c7cbd452b522c30c26bfa7a571e1f1ebcda979008422db469cfc",
                },
            },
        )
        self.assertFalse(images["capabilities"]["postcodesNorthernIrelandCoverageChainVerified"])

    def test_final_payment_and_isolated_fixture_evidence_are_pinned_but_release_stays_dark(self) -> None:
        images = json.loads(IMAGE_TEMPLATE.read_text(encoding="utf-8"))
        workspace_lock = json.loads((ROOT / "config" / "workspace-lock.json").read_text(encoding="utf-8"))
        locked_revisions = {entry["name"]: entry["revision"] for entry in workspace_lock["repositories"]}
        self.assertEqual(
            {name: locked_revisions[name] for name in (
                "authentication-service",
                "user-management-gateway",
                "location-gateway",
                "location-service",
                "llm-gateway",
                "document-store-service",
                "document-generation-gateway",
                "payment-service",
                "payment-gateway",
                "stripe-gateway",
                "system-data-service",
                "job-seeker-copilot-client",
                "e2e",
            )},
            {
                "authentication-service": "a3ca5efed33a379f748d82b5e70949e5aa765b41",
                "user-management-gateway": "121d77471b0ba72f3cf08cb662dc2500c9fb4289",
                "location-gateway": "63e3f07bf6efb2d2f067e98bc6d6e16ea03cd809",
                "location-service": "70fda950c6dc794571d4c34a568f49f6f6992b4c",
                "llm-gateway": "1efee28560fb685871b0069d8d21a4851f69f6d0",
                "document-store-service": "30f2ab6c94db2ab4e6d53e584a8ab3d162eef63f",
                "document-generation-gateway": "e15784c7098d327835e2a7d14dd257c1b95b08bd",
                "payment-service": "d4858f4af367062cf62c1eb142209f4236c38e95",
                "payment-gateway": "7c7ef4774739f0818f375a08e3b68f1d3a3c6d72",
                "stripe-gateway": "9d991b6c1111d06073f0f40d9fb5d2430a103983",
                "system-data-service": "f6b28693dbb174e0317a5e3396c831e13134c21e",
                "job-seeker-copilot-client": "5f4aca3aa6528a883506a8a5dc31566187c5e3ae",
                "e2e": "16f586b80ea3bd822f9931fffdb75d523d5541b1",
            },
        )
        self.assertFalse(images["capabilities"]["paymentV2ProductionContractVerified"])
        self.assertFalse(images["capabilities"]["paymentFixtureAcceptanceVerified"])
        self.assertEqual(images["launchApprovalManifestSha256"], "PENDING")
        self.assertEqual(images["dependencyEvidence"]["paymentV2ProductionContract"], {
            "authenticationService": {
                "revision": "d447addae21714f51267c0ab073377c24e3cfe81",
                "openApiSha256": "8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884",
            },
            "userManagementGateway": {
                "revision": "15e6bed692352f92daccc295c3987319e18ef720",
                "openApiSha256": "ebb1332f8927cdb69dd659db444627e59c4f5d8f4330e04d95ed17164fb8bcf7",
                "authSnapshotSha256": "95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0",
            },
            "documentGenerationGateway": {
                "revision": "e15784c7098d327835e2a7d14dd257c1b95b08bd",
                "openApiSha256": "930d8612d035c72a18107a7ea0afe3c1af52b2f86240c61b27c096c388dce895",
            },
            "paymentService": {
                "revision": "baeec9aa8da1285a2406900c9550773ac3841af7",
                "openApiSha256": "77186ce39bd32be4d8aed80b496df5873cf9e16c9ea911d7bc9b364d8a7b46e3",
            },
            "paymentGateway": {
                "revision": "99ee685a6809a254305a4cbb4dd92ba0fa7751bc",
                "openApiSha256": "9da54edec5a264e541433bf16dbc3826d8e0aa813ceb8e91fcdafab05f324b0b",
            },
            "stripeGateway": {
                "revision": "04dd9fa7c095f65120afd37cfc11380176756216",
                "openApiSha256": "4fc3c82918d2c062c56a5326b783dfabcf2c3fd68dfdeb56626cca260fa225a7",
            },
        })
        self.assertEqual(images["dependencyEvidence"]["paymentFixtureAcceptance"], {
            "systemDataServiceRevision": "ca4bafeafbfe41b25a8507f6f08d97490ef71a28",
            "e2eRevision": "cfa1a70a0028f11f8019c889b9057ba8124ff8f5",
            "infrastructureRevision": "412566a750ead55740e0b2b4b81cebe29d3e0ad9",
            "profile": "test",
            "providerMode": "FIXTURE",
            "healthyServiceCount": 36,
            "scenarioCount": 4,
            "stepCount": 33,
        })
        runtime_path = ROOT / "aws" / "public-beta" / "config" / "runtime-services.json"
        runtime_names = set(json.loads(runtime_path.read_text(encoding="utf-8"))["services"])
        self.assertNotIn("system-data-service", runtime_names)
        self.assertNotIn("e2e", runtime_names)
        self.assertFalse(images["capabilities"]["frontendArtifactsVerified"])
        self.assertEqual(images["dependencyEvidence"]["frontendArtifacts"], {
            "client": {
                "revision": "5f4aca3aa6528a883506a8a5dc31566187c5e3ae",
                "artifactContractSha256": "801fab5beb7ea81798677086ef00a94759294a1e85915f74da843632de2c6f75",
                "packaging": "OCI_SSR_BFF",
            },
            "landing": {
                "revision": "ce2a2a45aa32c838f12b3a8ff692ac5c1a0cdee7",
                "artifactContractSha256": "9682372ef2d909de3b2b49c6d0fed232565b61e1b1fe0ac666ace58bfdb0804f",
                "staticArtifactSha256": "PENDING",
                "runtimeConfigSha256": "PENDING",
                "selectedSamTemplate": "infrastructure/waitlist-backend/template.yaml",
                "selectedSamTemplateSha256": "PENDING",
                "deploymentStatus": "NOT_DEPLOYED",
            },
        })

    def test_account_lifecycle_uses_distinct_receiver_tokens(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        for token, receiver in (
            ("ACCOUNT_LIFECYCLE_TO_PAYMENT_SERVICE_TOKEN", "payment-service"),
            ("PAYMENT_SERVICE_TO_STRIPE_GATEWAY_LIFECYCLE_TOKEN", "stripe-gateway"),
        ):
            binding = f"core:{token}"
            sender = "authentication-service" if receiver == "payment-service" else "payment-service"
            self.assertEqual(runtime[sender]["secrets"][token], binding)
            self.assertEqual(runtime[receiver]["secrets"][token], binding)
        self.assertNotIn("STRIPE_GATEWAY_URL", runtime["authentication-service"]["environment"])

    def test_jwt_consumers_use_namespace_qualified_authentication_jwks(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        expected_consumers = {
            "application-tracker-service",
            "document-generation-gateway",
            "document-store-service",
            "job-finder-gateway",
            "job-service",
            "reporting-gateway",
            "user-profile-service",
        }
        qualified_uri = "http://authentication-service.{{namespace}}:8084/.well-known/jwks.json"
        actual_consumers = {
            name
            for name, service in runtime.items()
            if "AUTH_JWKS_URI" in service["environment"]
        }
        self.assertEqual(expected_consumers, actual_consumers)
        for name in expected_consumers:
            self.assertEqual(qualified_uri, runtime[name]["environment"]["AUTH_JWKS_URI"])

    def test_real_provider_deadlines_cover_the_bounded_jsearch_request(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        job_service = runtime["job-service"]["environment"]
        job_finder = runtime["job-finder-gateway"]["environment"]
        client = runtime["job-seeker-copilot-client"]["environment"]

        provider_timeout = int(job_service["JOB_SEARCH_PROVIDER_TIMEOUT_MS"])
        matching_timeout = int(job_service["JOB_SEARCH_MATCHING_TIMEOUT_MS"])
        request_timeout = int(job_service["JOB_SEARCH_REQUEST_TIMEOUT_MS"])
        finder_response_timeout = int(job_finder["JOB_FINDER_RESPONSE_TIMEOUT_MS"])
        finder_deadline = int(job_finder["JOB_FINDER_REQUEST_DEADLINE_MS"])
        bff_timeout = int(client["BFF_DOWNSTREAM_TIMEOUT_MS"])

        self.assertEqual("1", job_service["JSEARCH_MAX_CURSOR_PAGES"])
        self.assertEqual(15_000, provider_timeout)
        self.assertEqual(3_000, matching_timeout)
        self.assertEqual(20_000, request_timeout)
        self.assertGreaterEqual(request_timeout, provider_timeout + matching_timeout)
        self.assertEqual(23_000, finder_response_timeout)
        self.assertEqual(finder_response_timeout, finder_deadline)
        self.assertGreater(finder_deadline, request_timeout)
        self.assertEqual(25_000, bff_timeout)
        self.assertGreater(bff_timeout, finder_deadline)

    def test_apprenticeship_response_buffer_covers_a_full_detail_page(self) -> None:
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text(encoding="utf-8")
        )["services"]
        apprenticeships = runtime["apprenticeships-gateway"]["environment"]

        self.assertEqual("100", apprenticeships["APPRENTICESHIPS_SYNC_PAGE_SIZE"])
        self.assertEqual(
            2 * 1024 * 1024,
            int(apprenticeships["APPRENTICESHIPS_MAX_IN_MEMORY_RESPONSE_BYTES"]),
        )

    def test_public_beta_hotfix_sources_are_pinned_to_protected_main(self) -> None:
        workspace_lock = json.loads(
            (ROOT / "config" / "workspace-lock.json").read_text(encoding="utf-8")
        )
        revisions = {
            entry["name"]: entry["revision"]
            for entry in workspace_lock["repositories"]
        }

        self.assertEqual(
            {
                "apprenticeships-gateway": "23344e50f2688f2148dc3d478440a705c7d822f1",
                "job-service": "c38f84efa65005af5c1f387c9b98d2e58426d1e0",
                "stripe-gateway": "9d991b6c1111d06073f0f40d9fb5d2430a103983",
                "job-seeker-copilot-client": "5f4aca3aa6528a883506a8a5dc31566187c5e3ae",
            },
            {
                name: revisions[name]
                for name in (
                    "apprenticeships-gateway",
                    "job-service",
                    "stripe-gateway",
                    "job-seeker-copilot-client",
                )
            },
        )

    def test_manual_bootstrap_template_is_syntactically_complete(self) -> None:
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def construct_intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
        bootstrap_path = ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml"
        bootstrap_bytes = bootstrap_path.read_bytes()
        template = yaml.load(bootstrap_bytes.decode("utf-8"), Loader=CloudFormationLoader)

        def assert_string_mapping_keys(value, path="template"):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIsInstance(
                        key,
                        str,
                        f"{path} contains a non-string mapping key; quote YAML keywords used as CloudFormation keys",
                    )
                    assert_string_mapping_keys(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    assert_string_mapping_keys(item, f"{path}[{index}]")

        assert_string_mapping_keys(template)
        self.assertEqual(template["AWSTemplateFormatVersion"], "2010-09-09")
        resources = template["Resources"]
        for name in ("StateKey", "StateBucket", "StateBucketPolicy", "PlanRole", "BuildRole", "ApplyRole"):
            self.assertIn(name, resources)
        self.assertEqual(resources["StateBucket"]["DeletionPolicy"], "Retain")
        self.assertEqual(resources["StateKey"]["DeletionPolicy"], "Retain")

        expected_oidc_subjects = {
            "PlanRole": "repo:${GitHubOrganisation}@${GitHubOrganisationId}/${GitHubRepository}@${GitHubRepositoryId}:environment:${PlanEnvironmentName}",
            "BuildRole": "repo:${GitHubOrganisation}@${GitHubOrganisationId}/${GitHubRepository}@${GitHubRepositoryId}:environment:${BuildEnvironmentName}",
            "ApplyRole": "repo:${GitHubOrganisation}@${GitHubOrganisationId}/${GitHubRepository}@${GitHubRepositoryId}:environment:${ApplyEnvironmentName}",
        }
        for role_name, expected_subject in expected_oidc_subjects.items():
            trust = resources[role_name]["Properties"]["AssumeRolePolicyDocument"]
            condition = trust["Statement"][0]["Condition"]["StringEquals"]
            self.assertEqual(condition["token.actions.githubusercontent.com:sub"], expected_subject)
        self.assertEqual(template["Parameters"]["GitHubOrganisationId"]["AllowedPattern"], "^[0-9]+$")
        self.assertEqual(template["Parameters"]["GitHubRepositoryId"]["AllowedPattern"], "^[0-9]+$")

        # The foundation deliberately exceeds CloudFormation's inline
        # TemplateBody limit, but stays well inside the versioned TemplateURL
        # limit. The operator runbook must therefore use a checksum-pinned S3
        # object and acknowledge named IAM resources.
        self.assertGreater(len(bootstrap_bytes), 51_200)
        self.assertLess(len(bootstrap_bytes), 1_000_000)
        bootstrap_readme = (
            ROOT / "aws" / "public-beta" / "bootstrap" / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("TemplateURL", bootstrap_readme)
        self.assertIn("CAPABILITY_NAMED_IAM", bootstrap_readme)
        self.assertIn("sha256", bootstrap_readme.lower())

        for retained in (
            "StateKeyAlias",
            "ApplicationDataKeyAlias",
            "ErasureJournalKeyAlias",
            "NotificationKeyAlias",
            "StateBucketPolicy",
            "ErasureJournalBucketPolicy",
            "OperationsTopicPolicy",
            "WorkloadPermissionsBoundary",
        ):
            self.assertEqual(resources[retained].get("DeletionPolicy"), "Retain")
            self.assertEqual(resources[retained].get("UpdateReplacePolicy"), "Retain")

        topic_statements = resources["OperationsTopicPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        topic_by_sid = {statement["Sid"]: statement for statement in topic_statements}
        self.assertEqual(
            set(topic_by_sid["OwnerAdministration"]["Action"]),
            {
                "sns:AddPermission",
                "sns:DeleteTopic",
                "sns:GetTopicAttributes",
                "sns:ListSubscriptionsByTopic",
                "sns:Publish",
                "sns:RemovePermission",
                "sns:SetTopicAttributes",
                "sns:Subscribe",
            },
        )
        self.assertNotIn("sns:*", topic_by_sid["OwnerAdministration"]["Action"])

        state_policy = resources["StateBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        state_by_sid = {statement["Sid"]: statement for statement in state_policy}
        self.assertEqual(
            state_by_sid["DenyWrongStateKmsKey"]["Condition"]["StringNotEquals"][
                "s3:x-amz-server-side-encryption-aws-kms-key-id"
            ],
            "StateKey.Arn",
        )
        journal_policy = resources["ErasureJournalBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        journal_by_sid = {statement["Sid"]: statement for statement in journal_policy}
        self.assertEqual(
            journal_by_sid["DenyWrongJournalKey"]["Condition"]["StringNotEquals"][
                "s3:x-amz-server-side-encryption-aws-kms-key-id"
            ],
            "ErasureJournalKey.Arn",
        )
        self.assertNotIn(
            "s3:x-amz-server-side-encryption-bucket-key-enabled",
            bootstrap_bytes.decode("utf-8"),
        )

        application_key_policy = resources["ApplicationDataKey"]["Properties"]["KeyPolicy"]["Statement"]
        application_key_by_sid = {statement["Sid"]: statement for statement in application_key_policy}
        autoscaling_principal = (
            "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/aws-service-role/"
            "autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
        )
        self.assertEqual(
            application_key_by_sid["AllowAutoScalingServiceLinkedRoleUse"]["Principal"]["AWS"],
            autoscaling_principal,
        )
        autoscaling_grant = application_key_by_sid["AllowAutoScalingServiceLinkedRoleGrant"]
        self.assertEqual(autoscaling_grant["Principal"]["AWS"], autoscaling_principal)
        self.assertEqual(autoscaling_grant["Condition"]["Bool"]["kms:GrantIsForAWSResource"], "true")

        discovery_statements = resources["ApplyDiscoveryPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        discovery_actions = {
            action
            for statement in discovery_statements
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
        }
        self.assertIn("s3:GetAccelerateConfiguration", discovery_actions)
        self.assertIn("s3:GetReplicationConfiguration", discovery_actions)
        self.assertIn("ec2:GetSecurityGroupsForVpc", discovery_actions)
        self.assertNotIn("ec2:Get*", discovery_actions)

        plan_read_policy = next(
            policy
            for policy in resources["PlanRole"]["Properties"]["Policies"]
            if policy["PolicyName"] == "PublicBetaReadOnlyPlan"
        )
        plan_read_actions = {
            action
            for statement in plan_read_policy["PolicyDocument"]["Statement"]
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
        }
        self.assertIn("s3:GetAccelerateConfiguration", plan_read_actions)
        self.assertFalse(
            any(action.startswith(("s3:Put", "s3:Delete")) for action in plan_read_actions),
            "the refresh-only plan policy must not gain S3 write permissions",
        )

        compute_statements = resources["ApplyComputePolicy"]["Properties"]["PolicyDocument"]["Statement"]
        compute_by_sid = {statement["Sid"]: statement for statement in compute_statements}
        tagged_compute = compute_by_sid["ManageOnlyTaggedComputeResources"]
        deregister = compute_by_sid["DeregisterTaskDefinitionsInRegion"]
        self.assertNotIn("ecs:DeregisterTaskDefinition", tagged_compute["Action"])
        self.assertFalse(any("task-definition/" in resource for resource in tagged_compute["Resource"]))
        self.assertEqual(deregister["Action"], "ecs:DeregisterTaskDefinition")
        self.assertEqual(deregister["Resource"], "*")
        self.assertEqual(
            deregister["Condition"],
            {"StringEquals": {"aws:RequestedRegion": "AWS::Region"}},
        )
        self.assertEqual(
            [
                statement["Sid"]
                for statement in compute_statements
                if statement["Resource"] == "*"
                and any(
                    action.startswith("ecs:")
                    for action in (
                        statement["Action"]
                        if isinstance(statement["Action"], list)
                        else [statement["Action"]]
                    )
                )
            ],
            [
                "DeregisterTaskDefinitionsInRegion",
                "RequiredEcsAccountSetting",
            ],
        )
        private_zone = compute_by_sid["CreateHostedZoneRequiredByPrivateDnsNamespace"]
        self.assertEqual(private_zone["Action"], "route53:CreateHostedZone")
        self.assertNotIn("Condition", private_zone)
        private_zone_read = compute_by_sid["ReadHostedZoneRequiredByPrivateDnsNamespace"]
        self.assertEqual(
            set(private_zone_read["Action"]),
            {"route53:GetHostedZone", "route53:ListHostedZonesByName"},
        )
        route53_actions = {
            action
            for statement in compute_statements
            for action in (
                statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            )
            if action.startswith("route53:")
        }
        self.assertEqual(
            route53_actions,
            {"route53:CreateHostedZone", "route53:GetHostedZone", "route53:ListHostedZonesByName"},
        )
        self.assertEqual(
            resources["ApplyComputeLaunchPolicy"]["Properties"]["Description"],
            "Launch only the reviewed ECS AMI through the tagged public-beta launch template.",
        )
        compute_launch_statements = resources["ApplyComputeLaunchPolicy"]["Properties"]["PolicyDocument"][
            "Statement"
        ]
        compute_launch_by_sid = {statement["Sid"]: statement for statement in compute_launch_statements}
        ecs_managed_tag = compute_launch_by_sid["AllowEcsManagedTagOnReviewedAutoScalingGroup"]
        self.assertEqual(ecs_managed_tag["Effect"], "Allow")
        self.assertEqual(ecs_managed_tag["Action"], "autoscaling:CreateOrUpdateTags")
        self.assertEqual(
            ecs_managed_tag["Resource"],
            "arn:${AWS::Partition}:autoscaling:${AWS::Region}:${AWS::AccountId}:"
            "autoScalingGroup:*:autoScalingGroupName/jsc-public-beta-ecs-*",
        )
        self.assertEqual(
            ecs_managed_tag["Condition"]["StringEquals"],
            {
                "aws:ResourceTag/Application": "Job Seeker Copilot",
                "aws:ResourceTag/Environment": "public-beta",
                "aws:ResourceTag/ManagedBy": "Terraform",
            },
        )
        self.assertEqual(
            ecs_managed_tag["Condition"]["ForAllValues:StringEquals"]["aws:TagKeys"],
            ["AmazonECSManaged"],
        )
        self.assertEqual(
            ecs_managed_tag["Condition"]["Null"]["aws:RequestTag/AmazonECSManaged"],
            "false",
        )

        self.assertEqual(
            resources["ApplyObservabilityPolicy"]["Properties"]["Description"],
            (
                "Named and tagged public-beta alarms, dashboards and WAF lifecycle; "
                "billing controls stay in the manual foundation."
            ),
        )
        observability_statements = resources["ApplyObservabilityPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        observability_by_sid = {statement["Sid"]: statement for statement in observability_statements}
        managed_waf = observability_by_sid["ReferenceOnlyAwsManagedWafRuleSets"]
        self.assertEqual(set(managed_waf["Action"]), {"wafv2:CreateWebACL", "wafv2:UpdateWebACL"})
        self.assertTrue(managed_waf["Resource"].endswith(":regional/managedruleset/*/*"))
        tagged_waf = observability_by_sid["ManageOnlyTaggedWafResources"]
        self.assertIn("wafv2:CreateWebACL", tagged_waf["Action"])
        self.assertTrue(
            any(":regional/regexpatternset/jsc-public-beta-*/*" in arn for arn in tagged_waf["Resource"])
        )
        waf_alb = observability_by_sid["AssociateWafOnlyWithTaggedPublicBetaAlb"]
        self.assertEqual(
            set(waf_alb["Action"]),
            {
                "elasticloadbalancing:CreateWebACLAssociation",
                "elasticloadbalancing:DeleteWebACLAssociation",
                "elasticloadbalancing:GetLoadBalancerWebACL",
            },
        )
        self.assertTrue(waf_alb["Resource"].endswith("loadbalancer/app/jsc-public-beta-*/*"))
        delegated_set_web_acl = observability_by_sid["AllowWafDelegatedSetWebAcl"]
        self.assertEqual(delegated_set_web_acl["Effect"], "Allow")
        self.assertEqual(delegated_set_web_acl["Action"], "elasticloadbalancing:SetWebACL")
        self.assertEqual(delegated_set_web_acl["Resource"], "*")
        self.assertNotIn("Condition", delegated_set_web_acl)
        self.assertEqual(
            sum(
                action == "elasticloadbalancing:SetWebACL"
                for statement in observability_statements
                for action in (
                    statement["Action"]
                    if isinstance(statement["Action"], list)
                    else [statement["Action"]]
                )
            ),
            1,
        )
        self.assertNotIn(
            "elasticloadbalancing:*",
            {
                action
                for statement in observability_statements
                for action in (
                    statement["Action"]
                    if isinstance(statement["Action"], list)
                    else [statement["Action"]]
                )
            },
        )

        iam_statements = resources["ApplyReleaseOperationsPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        iam_by_sid = {statement["Sid"]: statement for statement in iam_statements}
        self.assertEqual(
            iam_by_sid["PassOnlyMonitoringRoleToRdsMonitoring"]["Condition"]["StringEquals"][
                "iam:PassedToService"
            ],
            "rds.amazonaws.com",
        )

        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        clamav = compute.split('resource "aws_ecs_task_definition" "clamav" {', maxsplit=1)[1].split(
            'resource "aws_ecs_service" "clamav"', maxsplit=1
        )[0]
        self.assertIn("startPeriod = 300", clamav)
        self.assertNotIn("startPeriod = 600", clamav)
        for statement in journal_policy:
            if statement["Sid"] != "DenyInsecureTransport":
                self.assertIn("/permanent-erasures/v1/*", statement["Resource"])
        for budget_name in (
            "MonthlyCostAlertBudget",
            "MonthlyCostCeilingBudget",
            "MonthlyCostCriticalForecastBudget",
        ):
            budget = resources[budget_name]
            self.assertEqual(budget["DependsOn"], "OperationsTopicPolicy")
            self.assertEqual(budget["DeletionPolicy"], "Retain")
            self.assertEqual(budget["UpdateReplacePolicy"], "Retain")
            self.assertNotIn("CostFilters", budget["Properties"]["Budget"])

        def notifications(name: str) -> set[tuple[str, int]]:
            entries = resources[name]["Properties"]["NotificationsWithSubscribers"]
            self.assertTrue(
                all(entry["Notification"]["ThresholdType"] == "ABSOLUTE_VALUE" for entry in entries)
            )
            return {
                (entry["Notification"]["NotificationType"], entry["Notification"]["Threshold"])
                for entry in entries
            }

        self.assertEqual(
            notifications("MonthlyCostAlertBudget"),
            {("ACTUAL", value) for value in (350, 500, 560, 650, 700)},
        )
        self.assertEqual(
            notifications("MonthlyCostCeilingBudget"),
            {("ACTUAL", 750)} | {("FORECASTED", value) for value in (350, 500, 560, 650)},
        )
        self.assertEqual(
            notifications("MonthlyCostCriticalForecastBudget"),
            {("FORECASTED", 700), ("FORECASTED", 750)},
        )
        subscription = resources["OperationsEmailSubscription"]["Properties"]
        self.assertEqual(subscription["TopicArn"], "OperationsTopic")
        self.assertEqual(subscription["Protocol"], "email")
        self.assertEqual(subscription["Endpoint"], "OperationsNotificationEmail")
        self.assertEqual(resources["ServiceCostAnomalyMonitor"]["Condition"], "CreateCostAnomalyMonitor")
        self.assertIn("ExistingCostAnomalyMonitorArn", template["Parameters"])
        self.assertEqual(template["Parameters"]["MonthlyBudgetUsd"]["Default"], 750)

        data_source = (ROOT / "aws" / "public-beta" / "data.tf").read_text(encoding="utf-8")
        self.assertIn('bucket        = "${local.name_prefix}-access-logs-${var.aws_account_id}"', data_source)
        self.assertIn('bucket        = "${local.name_prefix}-documents-${var.aws_account_id}"', data_source)
        self.assertNotIn('bucket_prefix = "${local.name_prefix}-documents-"', data_source)

        compute_source = (ROOT / "aws" / "public-beta" / "compute.tf").read_text(encoding="utf-8")
        asg = compute_source.split('resource "aws_autoscaling_group" "ecs" {', maxsplit=1)[1].split(
            'resource "aws_ecs_capacity_provider"', maxsplit=1
        )[0]
        for key, value in (
            ("Application", "Job Seeker Copilot"),
            ("Environment", "public-beta"),
            ("ManagedBy", "Terraform"),
        ):
            self.assertRegex(asg, rf'key\s+= "{re.escape(key)}"\s+value\s+= "{re.escape(value)}"')
        self.assertEqual(asg.count("propagate_at_launch = true"), 5)

        bootstrap_source = bootstrap_bytes.decode("utf-8")
        self.assertNotIn("targetgroup/jsc-public-beta-*/*", bootstrap_source)
        self.assertIn("targetgroup/jscweb*/*", bootstrap_source)
        self.assertIn("targetgroup/jscpay*/*", bootstrap_source)
        self.assertIn("tag:GetResources", bootstrap_source)

        backend = (ROOT / "aws" / "public-beta" / "backend.hcl.example").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        bootstrap = bootstrap_bytes.decode("utf-8")
        for source in (backend, workflow, bootstrap):
            self.assertIn("public-beta/terraform.tfstate", source)

    def test_backup_managed_policy_contract_survives_permissions_boundaries(self) -> None:
        class CloudFormationLoader(yaml.SafeLoader):
            pass

        def construct_intrinsic(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            return loader.construct_mapping(node)

        CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(
                encoding="utf-8"
            ),
            Loader=CloudFormationLoader,
        )
        contract = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "aws-backup-managed-policy-contract.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(contract["schemaVersion"], 1)
        self.assertEqual(contract["region"], "eu-west-2")

        boundary_actions: dict[str, set[str]] = {}
        boundary_statements: dict[str, list[dict]] = {}
        for boundary_name in ("BackupWorkloadBoundary", "BackupRestoreWorkloadBoundary"):
            actions: set[str] = set()
            statements = template["Resources"][boundary_name]["Properties"]["PolicyDocument"]["Statement"]
            for statement in statements:
                if statement["Effect"] != "Allow":
                    continue
                value = statement["Action"]
                actions.update(value if isinstance(value, list) else [value])
            boundary_actions[boundary_name] = actions
            boundary_statements[boundary_name] = statements

        backup_source = (ROOT / "aws" / "public-beta" / "backup.tf").read_text(encoding="utf-8")
        expected_versions = {
            "rdsBackup": "v30",
            "s3Backup": "v5",
            "rdsRestore": "v35",
            "s3Restore": "v2",
        }
        for name, entry in contract["contracts"].items():
            self.assertEqual(entry["reviewedDefaultVersion"], expected_versions[name])
            self.assertRegex(entry["officialReference"], r"^https://docs\.aws\.amazon\.com/")
            self.assertIn(entry["policyArn"], backup_source)
            missing = set(entry["requiredActions"]) - boundary_actions[entry["boundary"]]
            self.assertFalse(
                missing,
                f"{entry['boundary']} removes required actions from {name}: {sorted(missing)}",
            )
            for action in entry["unconditionalBoundaryActions"]:
                matching = []
                for statement in boundary_statements[entry["boundary"]]:
                    value = statement["Action"]
                    actions = value if isinstance(value, list) else [value]
                    if statement["Effect"] == "Allow" and action in actions:
                        matching.append(statement)
                self.assertTrue(matching, f"{entry['boundary']} has no Allow for {action}")
                self.assertTrue(
                    any("Condition" not in statement for statement in matching),
                    f"{entry['boundary']} makes direct {action} narrower than the managed-policy contract",
                )

        backup_actions = boundary_actions["BackupWorkloadBoundary"]
        restore_actions = boundary_actions["BackupRestoreWorkloadBoundary"]
        bucket_tag_reads = [
            statement
            for statement in boundary_statements["BackupWorkloadBoundary"]
            if "s3:ListTagsForResource" in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
        ]
        self.assertEqual(len(bucket_tag_reads), 1)
        self.assertEqual(
            bucket_tag_reads[0]["Resource"],
            "arn:${AWS::Partition}:s3:::jsc-public-beta-documents-${AWS::AccountId}",
        )
        self.assertNotIn("s3:DeleteObject", backup_actions)
        self.assertTrue(contract["contracts"]["s3Restore"]["precreatedDestinationRequired"])
        self.assertNotIn("s3:CreateBucket", restore_actions)
        self.assertNotIn("s3:DeleteBucket", restore_actions)
        self.assertNotIn("backup:DeleteRecoveryPoint", backup_actions | restore_actions)
        self.assertNotIn("rds:RestoreDBInstanceToPointInTime", restore_actions)
        for boundary_name, grant_sid in (
            ("BackupWorkloadBoundary", "GrantFoundationDataKeyOnlyToBackupResources"),
            ("BackupRestoreWorkloadBoundary", "GrantFoundationDataKeyOnlyToRestoreResources"),
        ):
            statements = {
                statement["Sid"]: statement for statement in boundary_statements[boundary_name]
            }
            grant = statements[grant_sid]
            self.assertEqual(grant["Action"], "kms:CreateGrant")
            self.assertEqual(grant["Resource"], "ApplicationDataKey.Arn")
            self.assertEqual(grant["Condition"]["Bool"]["kms:GrantIsForAWSResource"], "true")

        restore_by_sid = {
            statement["Sid"]: statement
            for statement in boundary_statements["BackupRestoreWorkloadBoundary"]
        }
        snapshot_target = restore_by_sid["ExactPrivateIsolatedRdsSnapshotRestoreTarget"]
        self.assertEqual(snapshot_target["Action"], "rds:RestoreDBInstanceFromDBSnapshot")
        self.assertEqual(
            snapshot_target["Resource"],
            "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:db:jsc-public-beta-restore-*",
        )
        self.assertEqual(snapshot_target["Condition"]["Bool"]["rds:PubliclyAccessible"], "false")
        snapshot_restore = restore_by_sid["ExactIsolatedRdsSnapshotRestoreInputs"]
        self.assertEqual(snapshot_restore["Action"], "rds:RestoreDBInstanceFromDBSnapshot")
        self.assertNotIn("Condition", snapshot_restore)
        self.assertEqual(
            set(snapshot_restore["Resource"]),
            {
                "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:snapshot:awsbackup:*",
                "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:pg:jsc-public-beta-postgres15-*",
                "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:subgrp:jsc-public-beta-postgres",
                "arn:${AWS::Partition}:rds:${AWS::Region}:${AWS::AccountId}:og:default:postgres-15",
            },
        )
        self.assertNotIn("pg:*", json.dumps(snapshot_restore))
        self.assertNotIn("subgrp:*", json.dumps(snapshot_restore))


if __name__ == "__main__":
    unittest.main()
