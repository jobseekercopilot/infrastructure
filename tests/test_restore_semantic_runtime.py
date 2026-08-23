import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPERATOR_TF = ROOT / "aws" / "public-beta" / "operator.tf"
NETWORK_TF = ROOT / "aws" / "public-beta" / "network.tf"
BROKER = ROOT / "aws" / "public-beta" / "operator" / "run-restore-semantic-broker.sh"
VERIFIER = ROOT / "aws" / "public-beta" / "operator" / "verify-restored-semantics.sh"
CLONER = ROOT / "aws" / "public-beta" / "operator" / "clone-restored-document-store.sh"
SOURCE = ROOT / "aws" / "public-beta" / "operator" / "prepare-restore-source-canary.sh"
OBSERVER = ROOT / "scripts" / "aws" / "run_restore_semantic_verification.sh"


def resource_block(text: str, kind: str, name: str) -> str:
    marker = f'{kind} "{name}"'
    start = text.index(marker)
    brace = text.index("{", start)
    depth = 0
    quoted = False
    escaped = False
    for offset in range(brace, len(text)):
        char = text[offset]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    raise AssertionError(f"unterminated {marker}")


class RestoreSemanticRuntimeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.operator = OPERATOR_TF.read_text()
        cls.network = NETWORK_TF.read_text()
        cls.broker = BROKER.read_text()
        cls.verifier = VERIFIER.read_text()
        cls.cloner = CLONER.read_text()
        cls.source = SOURCE.read_text()
        cls.observer = OBSERVER.read_text()

    def test_all_runtime_scripts_have_posix_shell_syntax(self) -> None:
        for script in (BROKER, VERIFIER, CLONER, SOURCE):
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["sh", "-n", str(script)], capture_output=True, text=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_semantic_tasks_never_receive_the_production_core_secret(self) -> None:
        app_policy = resource_block(
            self.operator,
            'data "aws_iam_policy_document"',
            "restore_semantic_document_store_secrets",
        )
        verifier_policy = resource_block(
            self.operator,
            'data "aws_iam_policy_document"',
            "restore_semantic_verifier_secrets",
        )
        app_task = resource_block(
            self.operator, 'resource "aws_ecs_task_definition"', "restore_semantic_document_store"
        )
        verifier_task = resource_block(
            self.operator, 'resource "aws_ecs_task_definition"', "restore_semantic_verifier"
        )
        for block in (app_policy, verifier_policy, app_task, verifier_task):
            self.assertNotIn("aws_secretsmanager_secret.core", block)
        self.assertIn('name      = "DOCUMENT_STORE_DATABASE_PASSWORD"', app_task)
        self.assertIn("secrets = [for key, secret in aws_secretsmanager_secret.database", verifier_task)
        self.assertIn("invalid-restore-semantic-admin-token-0000", self.operator)
        self.assertIn("invalid-restore-semantic-admin-token-0000", verifier_task)

    def test_semantic_app_disables_unrelated_background_mutators(self) -> None:
        self.assertRegex(
            self.operator, r'DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED\s*= "false"'
        )
        self.assertRegex(self.operator, r'DOCUMENT_STORE_UPLOAD_CLEANUP_ENABLED\s*= "false"')
        runtime = json.loads(
            (ROOT / "aws" / "public-beta" / "config" / "runtime-services.json").read_text()
        )["services"]["document-store-service"]["environment"]
        self.assertEqual(runtime["DOCUMENT_STORE_RECONCILIATION_RUN_ON_STARTUP"], "false")
        for delay in (
            "DOCUMENT_STORE_RECONCILIATION_INITIAL_DELAY_MS",
            "DOCUMENT_STORE_RECONCILIATION_FIXED_DELAY_MS",
            "DOCUMENT_STORE_PERMANENT_ERASURE_FIXED_DELAY_MS",
            "DOCUMENT_STORE_RETENTION_FIXED_DELAY_MS",
        ):
            self.assertRegex(self.operator, rf'{delay}\s*= "28800000"')
            self.assertRegex(self.broker, rf'\$env\.{delay} == "28800000"')
        for disabled in (
            "DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED",
            "DOCUMENT_STORE_UPLOAD_CLEANUP_ENABLED",
        ):
            self.assertIn(f'$env.{disabled} == "false"', self.broker)

    def test_semantic_journal_policy_matches_production_modulo_reserved_prefix(self) -> None:
        compute = (ROOT / "aws" / "public-beta" / "compute.tf").read_text()
        production = resource_block(
            compute, 'data "aws_iam_policy_document"', "document_store_journal"
        )
        semantic = resource_block(
            self.operator,
            'data "aws_iam_policy_document"',
            "restore_semantic_document_store_journal",
        )

        def normalise(value: str) -> str:
            value = re.sub(r"#.*", "", value)
            value = value.replace("restore_semantic_document_store_journal", "document_store_journal")
            value = value.replace("permanent-erasures/v1/7e57c0de-*", "permanent-erasures/v1/*")
            return re.sub(r"\s+", "", value)

        self.assertEqual(normalise(semantic), normalise(production))

    def test_broker_derives_distinct_synthetic_values_and_bounds_all_overrides(self) -> None:
        labels = (
            "retention-admin",
            "erasure-fingerprint",
            "document-producer",
            "document-reader",
            "tracker-producer",
            "tracker-reader",
            "environment-data",
        )
        for label in labels:
            self.assertIn(f"derive_synthetic_value {label}", self.broker)
        self.assertIn('(unique | length) == 7', self.broker)
        self.assertIn('[ "$bytes" -le 8192 ]', self.broker)
        self.assertIn('assert_override_size clone', self.broker)
        self.assertIn('assert_override_size "document-store-${target_database}"', self.broker)
        self.assertIn('assert_override_size verifier', self.broker)
        self.assertNotIn("aws_secretsmanager_secret.core", self.broker)

    def test_replay_database_uses_48_nonconstant_seed_bits(self) -> None:
        expected = 'replay_database="restore_replay_$(printf \'%s\' "$seed" | cut -c1-12)"'
        self.assertIn(expected, self.broker)
        self.assertIn(
            'replay_database_seed=$(printf \'%s:%s:%s\' "$drill_id" "$release_id" "$source_marker_sha"',
            self.verifier,
        )
        self.assertNotIn("operation_hex", self.verifier)

    def test_marker_is_durable_attempt_bound_and_cleanup_never_deletes_it(self) -> None:
        self.assertIn("jsc-public-beta-restore-semantic-start-marker.v2", self.broker)
        self.assertIn("another execution or input already owns this drill marker", self.broker)
        self.assertIn("durable drill retry limit is exhausted", self.broker)
        self.assertIn("recorded ARNs alone are not a complete redrive containment proof", self.broker)
        self.assertRegex(
            self.broker,
            r'if \[ "\$marker_exists" = true \]; then[\s\S]*?contain_children \|\| fail '
            r'"prior attempt children could not be contained before redrive"',
        )
        self.assertIn(":attempt-%s:clone:", self.broker)
        self.assertIn(":attempt-%s:source:", self.broker)
        self.assertIn(":attempt-%s:replay:", self.broker)
        self.assertIn(":attempt-%s:verifier:", self.broker)
        self.assertNotIn("delete-parameter", self.broker)
        self.assertIn("ssm list-tags-for-resource", self.broker)
        self.assertIn("durable marker ownership tags are missing or drifted", self.broker)
        broker_policy = resource_block(
            self.operator, 'data "aws_iam_policy_document"', "restore_semantic_broker_task"
        )
        self.assertIn('"ssm:ListTagsForResource"', broker_policy)

    def test_redrive_reuses_only_the_exact_canonical_operation_and_replay(self) -> None:
        for name in (
            "RESTORE_ATTEMPT",
            "RESTORE_ERASURE_OPERATION_ID",
            "RESTORE_ERASURE_REPLAY_ID",
        ):
            self.assertIn(f'{{name:"{name}",value:', self.broker)
        self.assertIn("attempt must be 1, 2 or 3", self.cloner)
        self.assertIn("first attempt found a pre-existing replay operation", self.cloner)
        self.assertIn("replay operation exists without its exact source operation", self.cloner)
        self.assertIn("source retry operation is not the exact immutable-journal state", self.cloner)
        self.assertIn("replay retry operation is not the exact reconstructed state", self.cloner)
        self.assertIn("replay retry journal contract differs from the source operation", self.cloner)
        self.assertIn("pre-attempt erasure operations are extra, mismatched or replay-only", self.verifier)
        self.assertIn("pre-existing replay journal contract differs from the source operation", self.verifier)
        self.assertIn("sourceOperationPreexistingBeforeAttempt:$sourcePreexisting", self.verifier)
        self.assertIn("replayOperationPreexistingBeforeAttempt:$replayPreexisting", self.verifier)
        source_pre = self.verifier.index("preexisting_source_row_snapshot=$(psql_value_database")
        source_call = self.verifier.index(
            'http_json PUT "${source_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}"'
        )
        source_first_guard = self.verifier.index(
            "first redrive source retry mutated its pre-existing canonical row"
        )
        source_second_guard = self.verifier.index(
            "second redrive source retry mutated its pre-existing canonical row"
        )
        replay_pre = self.verifier.index("preexisting_replay_row_snapshot=$(psql_value_database")
        replay_call = self.verifier.index(
            'http_json PUT "${replay_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}'
        )
        replay_first_guard = self.verifier.index(
            "first redrive replay retry mutated its pre-existing canonical row"
        )
        replay_second_guard = self.verifier.index(
            "second redrive replay retry mutated its pre-existing canonical row"
        )
        self.assertLess(source_pre, source_call)
        self.assertLess(source_call, source_first_guard)
        self.assertLess(source_first_guard, source_second_guard)
        self.assertLess(replay_pre, replay_call)
        self.assertLess(replay_call, replay_first_guard)
        self.assertLess(replay_first_guard, replay_second_guard)
        for guard in (
            "first redrive source retry changed immutable journal history",
            "source retry changed immutable journal history",
            "first replay call changed immutable journal history",
            "replay retry changed immutable journal history",
        ):
            self.assertIn(guard, self.verifier)
        self.assertNotIn("DROP DATABASE", self.cloner)

    def test_worst_case_completed_marker_fits_ssm_standard_parameter(self) -> None:
        account = "123456789012"
        drill = "d" * 32
        task_arn = f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/" + "a" * 32
        role = lambda suffix: f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-{suffix}"
        task_definition = (
            f"arn:aws:ecs:eu-west-2:{account}:task-definition/"
            "jsc-public-beta-restore-semantic-broker:999999"
        )
        execution = (
            f"arn:aws:states:eu-west-2:{account}:execution:"
            "jsc-public-beta-restore-semantic:" + "x" * 80
        )
        network_tuple = {
            "eniId": "eni-" + "a" * 17,
            "privateIp": "10.42.47.255",
            "subnetId": "subnet-" + "a" * 17,
            "securityGroupId": "sg-" + "a" * 17,
        }
        marker = {
            "schemaVersion": "jsc-public-beta-restore-semantic-start-marker.v2",
            "phase": "COMPLETED",
            "attempt": 3,
            "childTasks": {
                key: task_arn
                for key in ("clone", "sourceApplication", "replayApplication", "verifier")
            },
            "executionArn": execution,
            "inputBindingSha256": "a" * 64,
            "drillId": drill,
            "operationId": "7e57c0de-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "restoreReplayId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "replayDatabase": "restore_replay_aaaaaaaaaaaa",
            "createdAt": "2026-08-23T12:34:56Z",
            "lastAttemptStartedAt": "2026-08-23T12:34:56Z",
            "completedAt": "2026-08-23T12:34:56Z",
            "verifierLogStream": "restore-semantic-verifier/restore-semantic-verifier/" + "a" * 32,
            "runtimeBinding": {
                "stateMachineArn": (
                    f"arn:aws:states:eu-west-2:{account}:stateMachine:"
                    "jsc-public-beta-restore-semantic"
                ),
                "executionArn": execution,
                "broker": {
                    "taskArn": task_arn,
                    "taskDefinitionArn": task_definition,
                    "imageDigest": "sha256:" + "a" * 64,
                    "executionRoleArn": role("broker-execution"),
                    "taskRoleArn": role("broker-task"),
                    **network_tuple,
                    "injectedSecretCount": 0,
                },
                "privateSubnetIds": ["subnet-" + "a" * 17, "subnet-" + "b" * 17],
                "childNetwork": {
                    key: network_tuple
                    for key in ("clone", "sourceApplication", "replayApplication", "verifier")
                },
            },
            "network": {
                "vpcId": "vpc-" + "a" * 17,
                "restoreDatabaseSecurityGroupId": "sg-" + "a" * 17,
                "semanticSecurityGroupId": "sg-" + "b" * 17,
                "brokerSecurityGroupId": "sg-" + "c" * 17,
                "childStaticRuleCount": 7,
                "brokerStaticRuleCount": 3,
                "semanticEniCountBeforeStart": 0,
                "semanticEniCountAfterContainment": 0,
                "restoredDatabaseArn": (
                    f"arn:aws:rds:eu-west-2:{account}:db:jsc-public-beta-restore-{drill}"
                ),
                "restoredDatabaseEndpoint": (
                    f"jsc-public-beta-restore-{drill}.abcdefghijkl.eu-west-2.rds.amazonaws.com"
                ),
            },
            "publicSafety": {
                "publicEntrypointFixed503": True,
                "applicationDesiredCount": 0,
                "runningPublicApplicationTaskCount": 0,
                "pendingClusterTaskCountAfterContainment": 0,
                "semanticTasksNotAttachedToPublicFleet": True,
            },
        }
        encoded = json.dumps(marker, separators=(",", ":"), sort_keys=True).encode()
        self.assertLessEqual(len(encoded), 4096)
        self.assertIn("completed durable marker exceeds the SSM Standard 4096-byte limit", self.broker)

    def test_containment_waits_for_stopped_and_zero_semantic_enis(self) -> None:
        self.assertIn("marker-recorded child with missing/drifted tags", self.broker)
        self.assertIn("contained discoverable children but the durable marker remains malformed", self.broker)
        self.assertIn("recorded_tasks=$(printf '%s' \"$marker\" | jq -r '(.childTasks // {})[]?')", self.broker)
        self.assertNotIn("then .childTasks[]? else error", self.broker)
        self.assertIn("containment timed out waiting for STOPPED", self.broker)
        self.assertIn("containment left $eni_count semantic ENI(s)", self.broker)
        self.assertIn('--desired-status PENDING', self.broker)
        self.assertIn('--desired-status RUNNING', self.broker)
        self.assertNotIn("aws ecs wait tasks-stopped", self.broker)
        self.assertIn("semantic_eni_count_after_containment", self.broker)
        self.assertIn("trap on_exit EXIT", self.broker)
        self.assertIn("trap 'exit 143' TERM", self.broker)
        self.assertNotIn("trap on_exit EXIT HUP INT TERM", self.broker)

    def test_static_network_is_aws_enforced_and_semantic_has_no_public_https(self) -> None:
        for name in (
            "restore_database_from_semantic_verifier",
            "restore_semantic_verifier_database",
            "restore_semantic_verifier_self",
            "restore_semantic_verifier_s3",
            "restore_semantic_verifier_dns_tcp",
            "restore_semantic_verifier_dns_udp",
        ):
            self.assertIn(f'"{name}"', self.network)
        semantic_group = resource_block(
            self.network, 'resource "aws_security_group"', "restore_semantic_verifier"
        )
        self.assertNotIn("ingress {", semantic_group)
        self.assertNotIn("egress {", semantic_group)
        self.assertNotIn('cidr_ipv4         = "0.0.0.0/0"', semantic_group)
        self.assertEqual(self.network.count('description       = "Regional AWS control-plane APIs through'), 1)
        self.assertEqual(self.network.count('description       = "S3 gateway and regional SSM API HTTPS"'), 1)
        self.assertNotRegex(
            self.operator,
            r"AuthorizeSecurityGroup(?:Ingress|Egress)|RevokeSecurityGroup(?:Ingress|Egress)",
        )

    def test_state_machine_hard_codes_secret_free_broker(self) -> None:
        task = resource_block(
            self.operator, 'resource "aws_ecs_task_definition"', "restore_semantic_broker"
        )
        machine = resource_block(
            self.operator, 'resource "aws_sfn_state_machine"', "restore_semantic"
        )
        self.assertNotIn("secrets =", task)
        self.assertNotIn("RESTORE_BROKER_TASK_DEFINITION_ARN", task)
        self.assertIn(".taskDefinition.containerDefinitions[0].environment | from_entries", self.broker)
        self.assertIn("RESTORE_PRIVATE_SUBNET_IDS_JSON:$privateSubnets", self.broker)
        self.assertIn("environment | length) == 25", self.broker)
        self.assertIn("environment[].name] | unique | length) == 25", self.broker)
        self.assertIn('SourceCommit:$operatorCommit', self.broker)
        self.assertIn('Command     = ["/opt/jsc/run-restore-semantic-broker.sh", "start"]', machine)
        self.assertIn("NetworkConfiguration = local.restore_semantic_broker_network", machine)
        self.assertIn("ExecutionRoleArn = aws_iam_role.restore_semantic_broker_execution.arn", machine)
        self.assertIn("TaskRoleArn      = aws_iam_role.restore_semantic_broker_task.arn", machine)
        self.assertRegex(machine, r'Group\s+= "jsc-restore-semantic-broker"')
        self.assertRegex(machine, r'Group\s+= "jsc-restore-semantic-contain"')
        self.assertNotRegex(machine, r"\b(?:Count|StartedBy)\s*=")
        self.assertNotIn('"Overrides.$"', machine)
        self.assertIn("state machine did not apply the exact broker ownership tags", self.broker)
        self.assertIn(".tasks[0].overrides.containerOverrides[0].environment | from_entries", self.broker)
        self.assertIn("STATE_MACHINE_EXECUTION_ARN:$execution", self.broker)
        self.assertIn('.tasks[0].group == "jsc-restore-semantic-broker"', self.broker)
        self.assertIn('.tasks[0].startedBy == "AWS Step Functions"', self.broker)
        self.assertGreaterEqual(self.observer.count("jsc-restore-semantic-broker"), 3)
        self.assertGreaterEqual(self.observer.count("jsc-restore-semantic-contain"), 3)
        self.assertIn('expected_group="family:${family}"', self.observer)
        self.assertIn("expected_started_by=$started_by", self.observer)
        self.assertIn("expected_group=jsc-restore-semantic-broker", self.observer)
        self.assertIn('expected_started_by="AWS Step Functions"', self.observer)
        self.assertIn(
            '.tasks[0].group == $group and .tasks[0].startedBy == $started',
            self.observer,
        )
        self.assertLess(
            self.observer.index('started_by="jsc-rs-'),
            self.observer.index("describe_exact_task()"),
        )
        self.assertIn('values   = ["RestoreSemanticBroker"]', self.operator)
        self.assertIn('values   = ["RestoreSemanticVerification"]', self.operator)

    def test_broker_revalidates_exact_restore_destination_controls(self) -> None:
        broker = self.broker
        self.assertIn('test("^vpc-[0-9a-f]{8,17}$")', broker)
        self.assertIn('all($ids[1:]; test("^sg-[0-9a-f]{8,17}$"))', broker)
        self.assertIn(
            'key/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            broker,
        )
        self.assertNotIn('vpc-[0-9a-f]*|sg-[0-9a-f]*', broker)
        self.assertIn('.taskDefinition.requiresCompatibilities == ["EC2"]', broker)
        self.assertIn("([$environment[].name] | unique | length) == ($environment | length)", broker)
        self.assertIn("([$secrets[].name] | unique | length) == ($secrets | length)", broker)
        for command in (
            "get-bucket-location",
            "get-bucket-ownership-controls",
            "get-bucket-encryption",
            "get-bucket-policy",
            "get-bucket-policy-status",
            "get-public-access-block",
            "get-bucket-versioning",
        ):
            self.assertIn(command, broker)
        for field in (
            "BucketKeyEnabled:true",
            "BucketOwnerEnforced",
            "(.Statement | sort_by(.Sid)) == ([",
            ".KmsKeyId == $kms",
            ".DBSubnetGroup.DBSubnetGroupName == $subnetGroup",
            ".DBParameterGroups == [{DBParameterGroupName:$parameterGroup,ParameterApplyStatus:\"in-sync\"}]",
            ".Engine == \"postgres\"",
        ):
            self.assertIn(field, broker)
        bucket_policy = resource_block(
            self.operator, 'data "aws_iam_policy_document"', "restore_semantic_broker_task"
        )
        for action in (
            "s3:GetBucketLocation",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPolicy",
            "s3:GetBucketPolicyStatus",
            "s3:GetEncryptionConfiguration",
        ):
            self.assertIn(action, bucket_policy)

    def test_source_and_destination_version_inspection_is_exact(self) -> None:
        self.assertGreaterEqual(self.source.count(".BucketKeyEnabled == true"), 1)
        self.assertIn(".bucketKey == true", self.source)
        self.assertGreaterEqual(self.source.count("all(.Versions[]?; .Key == $key)"), 2)
        self.assertGreaterEqual(self.verifier.count("all(.Versions[]?; .Key == $key)"), 3)
        source_policy = resource_block(
            self.operator,
            'data "aws_iam_policy_document"',
            "operator_restore_canary",
        )
        self.assertIn('"s3:GetBucketVersioning"', source_policy)
        self.assertIn('$until <= (now + (($days + 1) * 86400))', self.verifier)
        for script in (self.broker, self.verifier):
            self.assertIn('keys == ["generation","sha256","sizeBytes","versionId"]', script)
            self.assertIn('.document.versions[0].versionId != .document.versions[1].versionId', script)

    def test_clone_and_verifier_bind_pre_application_schema_fingerprint(self) -> None:
        self.assertIn("document_schema_fingerprint", self.cloner)
        self.assertIn("clone_schema_fingerprint", self.cloner)
        self.assertIn("jsc-restore-replay-v2", self.cloner)
        self.assertIn("source database is not quiescent during replay-clone reuse", self.cloner)
        self.assertIn("pre_application_schema_fingerprint", self.verifier)
        self.assertIn("candidate startup changed or repaired restored schema/Flyway state", self.verifier)

    def test_empty_bootstrap_integrity_covers_every_domain_table(self) -> None:
        for table in (
            "account_deletion_operation",
            "registration_legal_acceptance",
            "evidence_snapshot_selection",
            "user_profile_workplace_arrangements",
            "saved_job_snapshots",
            "generation_operations",
            "document_storage_reconciliation_cursors",
            "document_tombstone_associations",
            "application_document_reconciliations",
            "document_availability_projections",
            "payment_provider_events",
        ):
            self.assertIn(table, self.verifier)
        self.assertIn("emptyBootstrapDomainInvariantsVerified:true", self.verifier)

    def test_raw_verifier_output_has_no_final_orchestration_claim(self) -> None:
        self.assertIn("jsc-public-beta-restore-semantic-raw.v1", self.verifier)
        self.assertIn("JSC_RESTORE_SEMANTIC_RAW_EVIDENCE_B64=", self.verifier)
        self.assertNotIn("jsc-public-beta-restore-semantic-observation.v1", self.verifier)
        self.assertNotIn('status:"VERIFIED"', self.verifier)
        self.assertIn("AGGREGATE_DOCUMENT_STORAGE_HEALTH_NOT_CLAIMED", self.verifier)
        self.assertIn("CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED", self.verifier)
        self.assertIn('^vpc-[0-9a-f]{8,17}$', self.verifier)
        self.assertIn('^sg-[0-9a-f]{8,17}$', self.verifier)
        self.assertIn('key/[0-9a-f]{8}-[0-9a-f]{4}-', self.verifier)


if __name__ == "__main__":
    unittest.main()
