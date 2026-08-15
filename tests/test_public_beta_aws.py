import json
import importlib.util
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

    def test_release_mode_rejects_placeholder_image_manifest(self) -> None:
        result = self.run_validator("--release")
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

    def test_duplicate_manifest_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            result = self.run_validator("--image-manifest", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate object key", result.stderr)

    def test_waf_has_narrow_upload_override_and_full_crs_elsewhere(self) -> None:
        edge = (ROOT / "aws" / "public-beta" / "edge.tf").read_text(encoding="utf-8")
        self.assertEqual(edge.count("AWSManagedRulesCommonRuleSet"), 2)
        self.assertIn('name = "SizeRestrictions_BODY"', edge)
        self.assertIn("action_to_use {", edge)
        self.assertIn("document-uploads$", edge)
        self.assertIn("replace$", edge)
        self.assertEqual(edge.count('search_string         = "POST"'), 2)

    def test_privileged_actions_are_immutable_and_manually_gated(self) -> None:
        for name, environment in (
            ("aws-public-beta-build.yml", "production-build"),
            ("aws-public-beta-release.yml", "production-aws"),
        ):
            workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("github.ref == 'refs/heads/main'", workflow)
            self.assertIn(f"environment: {environment}", workflow)
            self.assertIn("role-duration-seconds: 10800", workflow)
            references = re.findall(r"^\s*uses:\s*[^\s#]+@([^\s#]+)", workflow, flags=re.MULTILINE)
            self.assertTrue(references)
            self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references))
        release = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        self.assertIn("gh attestation verify", release)
        self.assertIn("workspaceLockSha256", release)
        self.assertIn('git merge-base --is-ancestor "$build_sha" "$GITHUB_SHA"', release)
        self.assertIn('git show "$build_sha:config/workspace-lock.json"', release)
        self.assertIn('if [ "$RELEASE_ACTION" = rollback ]; then', release)
        self.assertNotIn('"$RELEASE_ACTION" = rollback ] || [ "$RELEASE_ACTION" = activate', release)
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
        self.assertIn("for_each = var.high_availability ? local.raw_services : {}", compute)
        self.assertIn("deployment_maximum_percent         = 100", compute)
        self.assertIn("deployment_minimum_healthy_percent = 0", compute)
        self.assertNotIn("deployment_maximum_percent         = var.high_availability ? 200", compute)
        self.assertIn('{ containerPath = "/var/log/clamav", size = 64', compute)
        self.assertIn("steady_state_task_slots = length(local.raw_services) + 2", locals_source)
        self.assertIn("release_task_slots = (length(local.raw_services) + 1) * local.deployment_copy_multiplier + 1", locals_source)
        self.assertIn("condition     = local.release_reserved_cpu + local.os_reserved_cpu", locals_source)
        self.assertIn("condition     = local.release_reserved_memory + local.os_reserved_memory", locals_source)
        self.assertIn("filesha256(local.approval_manifest_path)", locals_source)
        self.assertIn("reserved_cpu_units               = local.release_reserved_cpu", outputs)
        self.assertIn("task_slots=$(jq -er '.task_slots'", release)

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
        self.assertIn("--min-capacity 0", emergency)
        self.assertIn("DynamicScalingOutSuspended=true", emergency)
        self.assertIn("all application/scanner tasks are stopped", emergency)
        self.assertIn("expected_services+=(clamav)", emergency)
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
                    "revision": "91857140c71bfda8b807c535272f918fe7741263",
                    "openApiSha256": "cd74fbf278c710a2782bbbe6473f9f708a19b6dd9329f42927ce302bb53f5f6b",
                },
                "locationGateway": {
                    "revision": "777ec7e8885fcb07368e05ad2543181e4ef7a891",
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
                "document-generation-gateway",
                "payment-service",
                "payment-gateway",
                "stripe-gateway",
                "system-data-service",
                "job-seeker-copilot-client",
                "e2e",
            )},
            {
                "authentication-service": "5c67f6ef36478ffa6a4d2fcbb76c210478229651",
                "user-management-gateway": "1c3ad16acbe7c4c6f18ea52493a14ffbfe614760",
                "document-generation-gateway": "d0d0f37780d9f8fa0db1e9ea45e37c9bdccd5cb1",
                "payment-service": "4caa12969f058b96f02ebce10ce2f562039cac0c",
                "payment-gateway": "c2c53e7faaea61f169e04663893a3a692d2e8135",
                "stripe-gateway": "7d2cc958bc06ea05234868b3b34e943e68bc9785",
                "system-data-service": "99e0e5984c7b68199a178df707804e0d7f0aeb18",
                "job-seeker-copilot-client": "3092e46157105a3d8702221c53623184f276a896",
                "e2e": "caec5576b016c0c34c36900f1a733bc60a4126c4",
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
                "revision": "5dc8aa1e7afb9492a96d3dedde847c530b6209b0",
                "openApiSha256": "dde3349e015f2cd7ef7bf9bc810681bebe98fca1ed1510005aa0b1a8b0e6d08e",
                "authSnapshotSha256": "95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0",
            },
            "documentGenerationGateway": {
                "revision": "cd9b71a3d4dbfbe41d6784f3eeeb7b1b113f5218",
                "openApiSha256": "864ba3c36b2ba4bcd1749edc597ed903a21e7dfa515bb2809d3bc9b9cf878f42",
            },
            "paymentService": {
                "revision": "63a2f3f2c6e29bb2d2744124c4b1ebe3a3b895ff",
                "openApiSha256": "40aa59f62a4ad4d956c2324c9c8d9fa154e4b04b49c029cbda0d80cc2c5dcdc9",
            },
            "paymentGateway": {
                "revision": "c49f9dc7441d146e58b428793a9c1a833c24aec5",
                "openApiSha256": "addd12e77307194d1635e49da9195dfe616a7e7653662492592764dd9092a4ec",
            },
            "stripeGateway": {
                "revision": "0e84d1bd97a00194809322307682c557069f30d4",
                "openApiSha256": "9fff5cff738ab51c24be85e989dcb6b9fe01bd2397289695660deff2c83a6ef7",
            },
        })
        self.assertEqual(images["dependencyEvidence"]["paymentFixtureAcceptance"], {
            "systemDataServiceRevision": "ca4bafeafbfe41b25a8507f6f08d97490ef71a28",
            "e2eRevision": "1541d92f34a3068bb160e1638834a06af6a60796",
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
                "revision": "3092e46157105a3d8702221c53623184f276a896",
                "artifactContractSha256": "801fab5beb7ea81798677086ef00a94759294a1e85915f74da843632de2c6f75",
                "packaging": "OCI_SSR_BFF",
            },
            "landing": {
                "revision": "743e42475319330be70e4d6d8f47000f913626f9",
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
        template = yaml.load(
            (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(encoding="utf-8"),
            Loader=CloudFormationLoader,
        )
        self.assertEqual(template["AWSTemplateFormatVersion"], "2010-09-09")
        resources = template["Resources"]
        for name in ("StateKey", "StateBucket", "StateBucketPolicy", "PlanRole", "BuildRole", "ApplyRole"):
            self.assertIn(name, resources)
        self.assertEqual(resources["StateBucket"]["DeletionPolicy"], "Retain")
        self.assertEqual(resources["StateKey"]["DeletionPolicy"], "Retain")

        backend = (ROOT / "aws" / "public-beta" / "backend.hcl.example").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "aws-public-beta-release.yml").read_text(encoding="utf-8")
        bootstrap = (ROOT / "aws" / "public-beta" / "bootstrap" / "state-and-oidc.yaml").read_text(encoding="utf-8")
        for source in (backend, workflow, bootstrap):
            self.assertIn("public-beta/terraform.tfstate", source)


if __name__ == "__main__":
    unittest.main()
