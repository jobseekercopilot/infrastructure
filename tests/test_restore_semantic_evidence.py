import base64
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "aws" / "validate_restore_semantic_evidence.py"
ACCOUNT = "123456789012"
DRILL = "beta-20260823"
RELEASE = "20260823T030000Z-222222222222"
SOURCE_MARKER_SHA = "9" * 64
SEED = hashlib.sha256(
    f"{DRILL}:{RELEASE}:{'9' * 64}".encode("utf-8")
).hexdigest()
REPLAY_SEED = hashlib.sha256(
    f"replay:{DRILL}:{RELEASE}:{SOURCE_MARKER_SHA}".encode("utf-8")
).hexdigest()
OPERATION = f"7e57c0de-{SEED[:4]}-4{SEED[4:7]}-8{SEED[7:10]}-{SEED[10:22]}"
REPLAY = f"{REPLAY_SEED[:8]}-{REPLAY_SEED[8:12]}-4{REPLAY_SEED[12:15]}-8{REPLAY_SEED[15:18]}-{REPLAY_SEED[18:30]}"
REPLAY_DATABASE = "restore_replay_" + SEED[:12]
DATABASES = [
    "authentication",
    "user_profile",
    "job_service",
    "document_generation",
    "document_store",
    "application_tracker",
    "payment",
]

SPEC = importlib.util.spec_from_file_location("restore_semantic_validator", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR_MODULE)


class RestoreSemanticEvidenceTest(unittest.TestCase):
    def iam_fixture(self) -> tuple[dict, dict]:
        account = ACCOUNT
        prefix = f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-"
        roles = {
            "stateMachine": prefix + "state-machine",
            "brokerExecution": prefix + "broker-execution",
            "brokerTask": prefix + "broker-task",
            "cloneExecution": prefix + "clone-execution",
            "applicationExecution": prefix + "document-store-execution",
            "applicationTask": prefix + "document-store-task",
            "verifierExecution": prefix + "verifier-execution",
            "verifierTask": prefix + "verifier-task",
        }
        definition_prefix = f"arn:aws:ecs:eu-west-2:{account}:task-definition/jsc-public-beta-restore-semantic-"
        context = {
            "accountId": account,
            "region": "eu-west-2",
            "stateMachineArn": f"arn:aws:states:eu-west-2:{account}:stateMachine:jsc-public-beta-restore-semantic",
            "clusterArn": f"arn:aws:ecs:eu-west-2:{account}:cluster/jsc-public-beta",
            "roles": roles,
            "definitions": {
                "broker": definition_prefix + "broker:10",
                "clone": definition_prefix + "clone:11",
                "application": definition_prefix + "document-store:12",
                "verifier": definition_prefix + "verifier:13",
            },
            "workloadBoundaryArn": f"arn:aws:iam::{account}:policy/jsc-public-beta-workload-boundary",
            "brokerBoundaryArn": f"arn:aws:iam::{account}:policy/jsc-public-beta-restore-semantic-broker-boundary",
            "dataKmsKeyArn": f"arn:aws:kms:eu-west-2:{account}:key/11111111-2222-3333-4444-555555555555",
            "erasureJournalKmsKeyArn": f"arn:aws:kms:eu-west-2:{account}:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "erasureJournalBucket": f"jsc-public-beta-erasure-journal-{account}",
            "rdsMasterSecretArn": f"arn:aws:secretsmanager:eu-west-2:{account}:secret:rds!db-AbCdEf",
            "documentStoreSecretArn": f"arn:aws:secretsmanager:eu-west-2:{account}:secret:jsc-public-beta/database/document_store-AbCd12",
            "databaseSecretArns": [
                f"arn:aws:secretsmanager:eu-west-2:{account}:secret:jsc-public-beta/database/{database}-AbCd12"
                for database in DATABASES
            ],
            "managedExecutionPolicyArn": "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        }
        expected_inline = VALIDATOR_MODULE._expected_iam_inline_documents(context)
        task_trust = {
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Action": "sts:AssumeRole",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:ecs:eu-west-2:{account}:*"},
                },
            }],
        }
        state_trust = {
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Action": "sts:AssumeRole",
                "Principal": {"Service": "states.amazonaws.com"},
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnEquals": {"aws:SourceArn": context["stateMachineArn"]},
                },
            }],
        }
        execution_kinds = {"brokerExecution", "cloneExecution", "applicationExecution", "verifierExecution"}
        broker_boundary_kinds = {"stateMachine", "brokerTask"}
        role_documents = {}
        for kind, role_arn in roles.items():
            boundary = (
                context["brokerBoundaryArn"] if kind in broker_boundary_kinds
                else context["workloadBoundaryArn"]
            )
            role_documents[kind] = {
                "getRole": {"Role": {
                    "Arn": role_arn, "RoleName": role_arn.rsplit("/", 1)[-1],
                    "PermissionsBoundary": {
                        "PermissionsBoundaryType": "Policy", "PermissionsBoundaryArn": boundary,
                    },
                    "AssumeRolePolicyDocument": copy.deepcopy(
                        state_trust if kind == "stateMachine" else task_trust
                    ),
                }},
                "inlinePolicyNames": sorted(expected_inline[kind]),
                "attachedPolicies": (
                    [context["managedExecutionPolicyArn"]] if kind in execution_kinds else []
                ),
                "inlineDocuments": copy.deepcopy(expected_inline[kind]),
            }
        managed_document = {
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Action": [
                    "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage",
                    "logs:CreateLogStream", "logs:PutLogEvents",
                ], "Resource": "*",
            }],
        }
        documents = {
            "roles": role_documents,
            "managedExecutionPolicy": {
                "metadata": {"Policy": {
                    "Arn": context["managedExecutionPolicyArn"], "DefaultVersionId": "v1",
                }},
                "version": {"PolicyVersion": {"VersionId": "v1", "Document": managed_document}},
            },
        }
        return documents, context

    def run_task_fixture(self, *, prior_verifier_placement_failure: bool = False) -> tuple[list[dict], dict, dict]:
        account = ACCOUNT
        definition_prefix = f"arn:aws:ecs:eu-west-2:{account}:task-definition/jsc-public-beta-restore-semantic-"
        definitions = {
            "clone": definition_prefix + "clone:11",
            "source": definition_prefix + "document-store:12",
            "replay": definition_prefix + "document-store:12",
            "verifier": definition_prefix + "verifier:13",
        }
        current_tasks = {
            stage: f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/{number:032x}"
            for number, stage in enumerate(("clone", "source", "replay", "verifier"), start=1)
        }
        prior_clone = f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/{10:032x}"
        prior_source = f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/{11:032x}"
        prior_replay = f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/{12:032x}"
        prior_tasks = {"clone": prior_clone}
        if prior_verifier_placement_failure:
            prior_tasks |= {"source": prior_source, "replay": prior_replay}
        marker_broker = f"arn:aws:ecs:eu-west-2:{account}:task/jsc-public-beta/{20:032x}"
        marker_bytes = b'{"schemaVersion":"fixture-source-marker.v1"}'
        state_machine_role = f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-state-machine"
        broker_execution_role = f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-broker-execution"
        broker_task_role = f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-broker-task"
        broker_definition = definition_prefix + "broker:10"
        execution_arn = f"arn:aws:states:eu-west-2:{account}:execution:jsc-public-beta-restore-semantic:fixture"
        state_input = {
            "drillId": DRILL, "releaseId": RELEASE, "releaseAttestationId": "6" * 64,
            "sourceCanaryId": DRILL, "sourceEvidenceSha256": "b" * 64,
            "sourceMarkerSha256": hashlib.sha256(marker_bytes).hexdigest(),
            "restoreStartEvidenceSha256": "c" * 64, "rdsRestoreJobId": "rds-job-12345678",
            "s3RestoreJobId": "s3-job-12345678",
            "rdsRecoveryPointArn": f"arn:aws:rds:eu-west-2:{account}:snapshot:awsbackup:job-rds",
            "s3RecoveryPointArn": f"arn:aws:backup:eu-west-2:{account}:recovery-point:s3",
            "restoreRoleArn": f"arn:aws:iam::{account}:role/jsc-public-beta-backup-restore",
        }
        context = {
            "accountId": account,
            "region": "eu-west-2",
            "drillId": DRILL,
            "attempt": 2,
            "lastAttemptStartedAt": "2026-08-23T02:00:00Z",
            "brokerRoleArn": f"arn:aws:iam::{account}:role/jsc-public-beta-restore-semantic-broker-task",
            "stateMachineRoleArn": state_machine_role,
            "clusterArn": f"arn:aws:ecs:eu-west-2:{account}:cluster/jsc-public-beta",
            "startedBy": "jsc-rs-12345678901234567890",
            "inputBindingSha256": "a" * 64,
            "definitions": definitions,
            "currentTasks": current_tasks,
            "privateSubnetIds": ["subnet-0123456789abcdef0", "subnet-1123456789abcdef0"],
            "semanticSecurityGroupId": "sg-1123456789abcdef0",
            "databaseHost": f"jsc-public-beta-restore-{DRILL}.abc123.eu-west-2.rds.amazonaws.com",
            "releaseId": RELEASE,
            "sourceCanaryId": DRILL,
            "sourceMarkerSha256": hashlib.sha256(marker_bytes).hexdigest(),
            "sourceEvidenceSha256": "b" * 64,
            "replayDatabase": REPLAY_DATABASE,
            "bucket": f"jsc-public-beta-restore-{account}-{DRILL}",
            "operationId": OPERATION,
            "restoreReplayId": REPLAY,
            "documentStoreImageDigest": "sha256:" + "4" * 64,
            "releaseOperatorImageDigest": "sha256:" + "5" * 64,
            "vpcId": "vpc-0123456789abcdef0",
            "databaseSecurityGroupId": "sg-0123456789abcdef0",
            "restoredDatabaseArn": f"arn:aws:rds:eu-west-2:{account}:db:jsc-public-beta-restore-{DRILL}",
            "brokerDefinitionArn": broker_definition,
            "brokerExecutionRoleArn": broker_execution_role,
            "brokerTaskRoleArn": broker_task_role,
            "brokerSecurityGroupId": "sg-2123456789abcdef0",
            "executionArn": execution_arn,
            "stateInput": state_input,
            "markerBrokerTaskArn": marker_broker,
        }
        task_tags = [
            {"key": "Application", "value": "Job Seeker Copilot"},
            {"key": "Environment", "value": "public-beta"},
            {"key": "ManagedBy", "value": "RestoreSemanticVerification"},
            {"key": "RestoreDrillId", "value": DRILL},
        ]
        task_stage = {task: stage for stage, task in current_tasks.items()}
        task_stage[prior_clone] = "clone"
        if prior_verifier_placement_failure:
            task_stage[prior_source] = "source"
            task_stage[prior_replay] = "replay"
        task_stage[marker_broker] = "broker"
        task_ips = {
            task: f"10.42.1.{index + 10}"
            for index, task in enumerate(task_stage)
        }

        def task_fact(task_arn: str, stage: str) -> dict:
            digest = (
                context["documentStoreImageDigest"]
                if stage in {"source", "replay"} else context["releaseOperatorImageDigest"]
            )
            family_stage = "document-store" if stage in {"source", "replay"} else stage
            tags = copy.deepcopy(task_tags)
            if stage == "broker":
                tags[2]["value"] = "RestoreSemanticBroker"
            group = (
                "jsc-restore-semantic-broker"
                if stage == "broker"
                else f"family:jsc-public-beta-restore-semantic-{family_stage}"
            )
            started_by = "AWS Step Functions" if stage == "broker" else context["startedBy"]
            return {
                "taskArn": task_arn,
                "taskDefinitionArn": (
                    context["brokerDefinitionArn"] if stage == "broker" else definitions[stage]
                ),
                "group": group,
                "startedBy": started_by,
                "lastStatus": "STOPPED",
                "containers": [{"imageDigest": digest}],
                "tags": tags,
                "attachments": [{"type": "ElasticNetworkInterface", "details": [
                    {"name": "networkInterfaceId", "value": f"eni-{task_arn[-17:]}"},
                    {"name": "privateIPv4Address", "value": task_ips[task_arn]},
                    {"name": "subnetId", "value": context["privateSubnetIds"][0]},
                ]}],
            }

        tasks_response = {
            "tasks": [task_fact(task, stage) for task, stage in task_stage.items()],
            "failures": [],
        }
        facts_for_environment = {
            task["taskArn"]: {
                "privateIp": task["attachments"][0]["details"][1]["value"]
            }
            for task in tasks_response["tasks"]
        }

        def event(
            attempt: int, stage: str, task_arn: str | None, *,
            failed: bool = False, placement_failure: bool = False,
        ) -> dict:
            attempt_tasks = current_tasks if attempt == 2 else prior_tasks
            environment = VALIDATOR_MODULE._expected_child_environment(
                context, attempt, stage, attempt_tasks, facts_for_environment
            )
            if stage == "verifier":
                environment["RESTORE_SOURCE_MARKER_B64"] = base64.b64encode(marker_bytes).decode("ascii")
            token = VALIDATOR_MODULE._run_task_token(
                context["inputBindingSha256"], attempt, stage, definitions[stage]
            )
            response = (
                None if failed else
                {"failures": [{"arn": "", "reason": "RESOURCE:MEMORY"}], "tasks": []}
                if placement_failure else
                {"failures": [], "tasks": [{"taskArn": task_arn}]}
            )
            stage_second = {"clone": 0, "source": 1, "replay": 1, "verifier": 2}[stage]
            value = {
                "eventSource": "ecs.amazonaws.com",
                "eventName": "RunTask",
                "eventTime": (
                    f"2026-08-23T01:00:0{stage_second}Z" if attempt == 1
                    else f"2026-08-23T03:00:0{stage_second}Z"
                ),
                "awsRegion": "eu-west-2",
                "recipientAccountId": account,
                "userIdentity": {
                    "type": "AssumedRole",
                    "accountId": account,
                    "sessionContext": {"sessionIssuer": {
                        "type": "Role", "accountId": account,
                        "arn": context["brokerRoleArn"],
                        "userName": "jsc-public-beta-restore-semantic-broker-task",
                    }},
                },
                "requestParameters": {
                    "clientToken": token,
                    "cluster": context["clusterArn"],
                    "count": 1,
                    "launchType": "EC2",
                    "networkConfiguration": {"awsvpcConfiguration": {
                        "assignPublicIp": "DISABLED",
                        "securityGroups": [context["semanticSecurityGroupId"]],
                        "subnets": context["privateSubnetIds"],
                    }},
                    "overrides": {"containerOverrides": [{
                        "name": (
                            "restore-semantic-document-store"
                            if stage in {"source", "replay"} else f"restore-semantic-{stage}"
                        ),
                        "environment": [
                            {"name": name, "value": value}
                            for name, value in environment.items()
                        ],
                    }]},
                    "startedBy": context["startedBy"],
                    "tags": copy.deepcopy(task_tags),
                    "taskDefinition": definitions[stage],
                },
                "responseElements": response,
            }
            if failed:
                value["errorCode"] = "ClientException"
                value["errorMessage"] = "fixture exact failed SDK call"
            return value

        if prior_verifier_placement_failure:
            prior_events = [
                event(1, "clone", prior_clone), event(1, "source", prior_source),
                event(1, "replay", prior_replay),
                event(1, "verifier", None, placement_failure=True),
            ]
        else:
            prior_events = [
                event(1, "clone", prior_clone), event(1, "source", None, failed=True),
                event(1, "replay", None, placement_failure=True),
            ]
        events = [
            *prior_events,
            *[event(2, stage, current_tasks[stage]) for stage in ("clone", "source", "replay", "verifier")],
        ]
        broker_environment = {
            "RESTORE_BROKER_TASK_DEFINITION_ARN": broker_definition,
            "RESTORE_BROKER_EXECUTION_ROLE_ARN": broker_execution_role,
            "RESTORE_BROKER_TASK_ROLE_ARN": broker_task_role,
            "RESTORE_DRILL_ID": state_input["drillId"],
            "RELEASE_ID": state_input["releaseId"],
            "RELEASE_ATTESTATION_ID": state_input["releaseAttestationId"],
            "RESTORE_SOURCE_CANARY_ID": state_input["sourceCanaryId"],
            "RESTORE_SOURCE_EVIDENCE_SHA256": state_input["sourceEvidenceSha256"],
            "RESTORE_SOURCE_MARKER_SHA256": state_input["sourceMarkerSha256"],
            "RESTORE_START_EVIDENCE_SHA256": state_input["restoreStartEvidenceSha256"],
            "RDS_RESTORE_JOB_ID": state_input["rdsRestoreJobId"],
            "S3_RESTORE_JOB_ID": state_input["s3RestoreJobId"],
            "RDS_RECOVERY_POINT_ARN": state_input["rdsRecoveryPointArn"],
            "S3_RECOVERY_POINT_ARN": state_input["s3RecoveryPointArn"],
            "RESTORE_ROLE_ARN": state_input["restoreRoleArn"],
            "STATE_MACHINE_EXECUTION_ARN": execution_arn,
        }
        broker_tags = copy.deepcopy(task_tags)
        broker_tags[2]["value"] = "RestoreSemanticBroker"
        state_event = {
            "eventSource": "ecs.amazonaws.com", "eventName": "RunTask",
            "eventTime": "2026-08-23T00:59:00Z", "awsRegion": "eu-west-2",
            "recipientAccountId": account,
            "userIdentity": {
                "type": "AssumedRole", "accountId": account,
                "sessionContext": {"sessionIssuer": {
                    "type": "Role", "accountId": account, "arn": state_machine_role,
                    "userName": "jsc-public-beta-restore-semantic-state-machine",
                }},
            },
            "requestParameters": {
                "clientToken": "state-token-fixture-1", "cluster": context["clusterArn"],
                "count": 1, "enableECSManagedTags": False, "launchType": "EC2",
                "group": "jsc-restore-semantic-broker",
                "networkConfiguration": {"awsvpcConfiguration": {
                    "assignPublicIp": "DISABLED", "securityGroups": [context["brokerSecurityGroupId"]],
                    "subnets": context["privateSubnetIds"],
                }},
                "overrides": {
                    "executionRoleArn": broker_execution_role, "taskRoleArn": broker_task_role,
                    "containerOverrides": [{
                        "name": "restore-semantic-broker",
                        "command": ["/opt/jsc/run-restore-semantic-broker.sh", "start"],
                        "environment": [
                            {"name": name, "value": value} for name, value in broker_environment.items()
                        ],
                    }],
                },
                "startedBy": "AWS Step Functions", "tags": broker_tags,
                "taskDefinition": broker_definition,
            },
            "responseElements": {"failures": [], "tasks": [{"taskArn": marker_broker}]},
        }
        events.insert(0, state_event)
        return events, tasks_response, context

    def readiness(self) -> dict:
        return {
            "schemaVersion": "document-permanent-erasure-readiness.v3",
            "enabled": True,
            "ready": True,
            "status": "READY",
            "policyVersion": "public-beta-retention-v1",
            "backupRetentionPolicyVersion": "public-beta-backup-retention-v1",
            "recoveryDays": 30,
            "maximumBackupRetentionDays": 35,
            "backupExpiryEvidenceRequired": True,
            "recoveryJournalWritePending": 0,
            "recoveryJournalEvidenceMissing": 0,
            "liveErasureReconciliationPending": 0,
            "restoreJournalReadPending": 0,
            "restoreReplayPending": 0,
            "backupRetentionPending": 1,
            "backupRetentionOverdue": 0,
        }

    def generation(self, number: int, version: str, digest_character: str) -> dict:
        return {
            "generation": number,
            "versionId": version,
            "sourceSha256": digest_character * 64,
            "sizeBytes": 128 + number,
            "bucketKeyEnabled": True,
            "exactSourceMetadataVerified": True,
            "payloadSha256Verified": True,
        }

    def evidence(self) -> dict:
        vpc = "vpc-0123456789abcdef0"
        database_sg = "sg-0123456789abcdef0"
        semantic_sg = "sg-1123456789abcdef0"
        runtime = {
            "cloneTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'1' * 32}",
            "sourceApplicationTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'2' * 32}",
            "replayApplicationTaskArn": f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'3' * 32}",
            "cloneTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-clone:17"
            ),
            "applicationTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-document-store:18"
            ),
            "verifierTaskDefinitionArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                "jsc-public-beta-restore-semantic-verifier:19"
            ),
            "documentStoreImageDigest": "sha256:" + "4" * 64,
            "releaseOperatorImageDigest": "sha256:" + "5" * 64,
            "vpcId": vpc,
            "restoreDatabaseSecurityGroupId": database_sg,
            "semanticSecurityGroupId": semantic_sg,
            "restoredDatabaseArn": (
                f"arn:aws:rds:eu-west-2:{ACCOUNT}:db:jsc-public-beta-restore-{DRILL}"
            ),
            "restoredDatabaseEndpoint": (
                f"jsc-public-beta-restore-{DRILL}.abc123.eu-west-2.rds.amazonaws.com"
            ),
            "applicationTasksUseDedicatedJournalOnlyRole": True,
            "verifierHasNoJournalPut": True,
            "cloneHasNoTaskRole": True,
            "actualTaskImageDigestsVerified": True,
            "securityCriticalTaskDefinitionContractsVerified": True,
            "exactTaskTagsVerified": True,
            "exactTaskLifecycleVerified": True,
        }
        return {
            "schemaVersion": "jsc-public-beta-restore-semantic-observation.v1",
            "status": "VERIFIED",
            "environment": "public-beta",
            "drillId": DRILL,
            "startedAt": "2026-08-23T04:00:00Z",
            "completedAt": "2026-08-23T04:30:00Z",
            "verifierTaskArn": (
                f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'6' * 32}"
            ),
            "releaseCandidate": {
                "releaseId": RELEASE,
                "releaseAttestationId": "7" * 64,
            },
            "orchestrationBinding": {
                "stateMachineArn": (
                    f"arn:aws:states:eu-west-2:{ACCOUNT}:stateMachine:"
                    "jsc-public-beta-restore-semantic"
                ),
                "executionArn": (
                    f"arn:aws:states:eu-west-2:{ACCOUNT}:execution:"
                    "jsc-public-beta-restore-semantic:jsc-rs-beta-20260823"
                ),
                "executionStatus": "SUCCEEDED",
                "stateMachineType": "STANDARD",
                "stateMachineRoleArn": (
                    f"arn:aws:iam::{ACCOUNT}:role/jsc-public-beta-restore-semantic-state-machine"
                ),
                "brokerTaskArn": (
                    f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{'7' * 32}"
                ),
                "brokerTaskDefinitionArn": (
                    f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task-definition/"
                    "jsc-public-beta-restore-semantic-broker:20"
                ),
                "brokerExecutionRoleArn": (
                    f"arn:aws:iam::{ACCOUNT}:role/jsc-public-beta-restore-semantic-broker-execution"
                ),
                "brokerTaskRoleArn": (
                    f"arn:aws:iam::{ACCOUNT}:role/jsc-public-beta-restore-semantic-broker-task"
                ),
                "brokerImageDigest": "sha256:" + "5" * 64,
                "brokerInjectedSecretCount": 0,
                "brokerTaskStoppedSuccessfully": True,
                "securityCriticalStateMachineContractVerified": True,
                "brokerRuntimeBindingsVerified": True,
                "expectedIamBoundaryBindingsVerified": True,
                "expectedInlinePolicyNamesAndActionsVerified": True,
                "noDangerousIamActionsVerified": True,
                "durableMarkerName": f"/jsc/public-beta/restore-semantic/{DRILL}/start",
                "durableMarkerSchemaVersion": "jsc-public-beta-restore-semantic-start-marker.v2",
                "durableMarkerSha256": "e" * 64,
                "durableMarkerRetained": True,
                "markerPhase": "COMPLETED",
                "markerAttempt": 1,
                "inputBindingSha256": "f" * 64,
                "operationId": OPERATION,
                "restoreReplayId": REPLAY,
                "replayDatabase": REPLAY_DATABASE,
            },
            "runtimeBinding": runtime,
            "networkIsolation": {
                "vpcId": vpc,
                "restoreDatabaseSecurityGroupId": database_sg,
                "semanticSecurityGroupId": semantic_sg,
                "brokerSecurityGroupId": "sg-2123456789abcdef0",
                "privateSubnetIds": ["subnet-0123456789abcdef0", "subnet-1123456789abcdef0"],
                "staticRulesTerraformOwned": True,
                "exactReviewedRuleTuplesVerified": True,
                "securityGroupRuleCount": 10,
                "semanticDatabaseSecurityGroupRuleCount": 7,
                "brokerSecurityGroupRuleCount": 3,
                "restoreDatabaseIngressRuleCount": 1,
                "restoreDatabaseEgressRuleCount": 0,
                "semanticIngressRuleCount": 1,
                "semanticEgressRuleCount": 5,
                "restoreDatabasePublicIngressRuleCount": 0,
                "semanticEniCountBeforeStart": 0,
                "semanticEniCountAfterContainment": 0,
                "brokerEniCountAfterCompletion": 0,
                "restoredDatabasePubliclyAccessible": False,
                "restoredDatabaseUsesOnlyRestoreSecurityGroup": True,
                "semanticTasksUseOnlySemanticSecurityGroup": True,
                "brokerTaskUsesOnlyBrokerSecurityGroup": True,
                "taskPrivateSubnetBindingsVerified": True,
            },
            "publicSafety": {
                "publicEntrypointFixed503": True,
                "applicationDesiredCount": 0,
                "runningApplicationTaskCount": 0,
                "pendingApplicationTaskCount": 0,
                "semanticTasksNotAttachedToPublicFleet": True,
            },
            "restoreControlPlane": {
                "restoreJobsExactBindingsVerified": True,
                "restoredDatabaseExactControlsVerified": True,
                "restoredBucketExactControlsVerified": True,
                "restoreOwnershipTagsVerified": True,
            },
            "restoreSource": {
                "canaryId": "launch-20260823",
                "sourceEvidenceSha256": "8" * 64,
                "sourceMarkerSha256": "9" * 64,
            },
            "databaseVerification": {
                "logicalDatabases": DATABASES,
                "exactCanaryRowCounts": {
                    name: 1 for name in (
                        "authentication", "userProfile", "jobService", "documentGeneration",
                        "documentStore", "applicationTracker", "payment", "replayClone",
                    )
                },
                "exactCanaryRowsVerified": True,
                "preOperationReplayCloneVerified": True,
                "preApplicationSchemaFingerprint": "1" * 64,
                "schemaAndFlywayFingerprintUnchangedAfterCandidateStartup": True,
                "nonPrivilegedRolesVerified": True,
                "tlsConnectionsVerified": True,
                "flywayHistoriesVerified": True,
                "emptyBootstrapDomainInvariantsVerified": True,
                "paymentLedgerSeedAndEmptyStateReconciled": True,
            },
            "documentVerification": {
                "mappingType": "NON_CUSTOMER_RESTORE_CANARY",
                "bucket": f"jsc-public-beta-restore-{ACCOUNT}-{DRILL}",
                "key": "restore-canary/v1/launch-20260823/document.json",
                "destinationVersionCount": 2,
                "deleteMarkerCount": 0,
                "generations": [
                    self.generation(1, "destination-version-one", "a"),
                    self.generation(2, "destination-version-two", "b"),
                ],
                "newDestinationVersionIdsVerified": True,
                "customerGeneratedDocumentMappingClaimed": False,
            },
            "erasureReplayVerification": {
                "attempt": 1,
                "sourceOperationPreexistingBeforeAttempt": False,
                "replayOperationPreexistingBeforeAttempt": False,
                "operationId": OPERATION,
                "restoreReplayId": REPLAY,
                "syntheticOwnerSha256": "c" * 64,
                "documentCount": 0,
                "objectScopeCount": 0,
                "sourceCanonicalResponseSha256": "2" * 64,
                "replayCanonicalResponseSha256": "3" * 64,
                "sourceCanonicalRowSha256": "4" * 64,
                "replayCanonicalRowSha256": "5" * 64,
                "journalContractSha256": "6" * 64,
                "sourceCanonicalRetryVerified": True,
                "replayCanonicalRetryVerified": True,
                "sourceReplayJournalContractEqual": True,
                "journal": {
                    "bucket": f"jsc-public-beta-erasure-journal-{ACCOUNT}",
                    "key": f"permanent-erasures/v1/{OPERATION}.json",
                    "versionId": "journal-version-one",
                    "versionCount": 1,
                    "deleteMarkerCount": 0,
                    "contentSha256": "d" * 64,
                    "sizeBytes": 512,
                    "objectLockMode": "GOVERNANCE",
                    "minimumRetentionDays": 36,
                    "bucketKeyEnabled": True,
                    "contentSha256MetadataVerified": True,
                    "unchangedAfterSourceAndReplayRetries": True,
                    "writeByCandidateApplicationVerified": True,
                    "exactVersionReadBySeparateVerifierVerified": True,
                },
                "externalJournalWriteVerified": True,
                "externalJournalReadVerified": True,
                "absentOperationReconstructed": True,
                "exactReplayVerified": True,
                "restoreReplayEvidenceRecorded": True,
                "restoreReplayObjectErasedAtVerified": True,
                "sourceReadiness": self.readiness(),
                "replayReadiness": self.readiness(),
            },
            "scopeLimitations": [
                "SYNTHETIC_NON_CUSTOMER_EMPTY_SCOPE",
                "JOURNAL_WRITE_READ_RETRY_AND_ABSENT_OPERATION_RECONSTRUCTION_PROVEN",
                "CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED",
                "CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED",
                "RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY",
                "LIVENESS_AND_FLYWAY_STARTUP_ONLY",
                "AGGREGATE_DOCUMENT_STORAGE_HEALTH_NOT_CLAIMED",
            ],
        }

    def run_validator(self, evidence: dict, *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic-evidence.json"
            path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
            return subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(path), *extra],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

    def assert_invalid(self, evidence: dict, message: str) -> None:
        result = self.run_validator(evidence)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(message, result.stderr)

    def test_accepts_exact_offline_observation_and_expected_bindings(self) -> None:
        evidence = self.evidence()
        runtime_sha = hashlib.sha256(json.dumps(
            evidence["runtimeBinding"], sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        result = self.run_validator(
            evidence,
            "--expected-account-id", ACCOUNT,
            "--expected-drill-id", DRILL,
            "--expected-release-id", RELEASE,
            "--expected-release-attestation-id", "7" * 64,
            "--expected-source-evidence-sha256", "8" * 64,
            "--expected-source-marker-sha256", "9" * 64,
            "--expected-document-store-image-digest", "sha256:" + "4" * 64,
            "--expected-release-operator-image-digest", "sha256:" + "5" * 64,
            "--expected-verifier-task-arn", evidence["verifierTaskArn"],
            "--expected-execution-arn", evidence["orchestrationBinding"]["executionArn"],
            "--expected-marker-sha256", "e" * 64,
            "--expected-runtime-binding-sha256", runtime_sha,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline validation; no live verification claim", result.stdout)

        wrong_binding = self.run_validator(
            evidence,
            "--expected-runtime-binding-sha256", "e" * 64,
        )
        self.assertEqual(wrong_binding.returncode, 2)
        self.assertIn("observer's exact binding", wrong_binding.stderr)

    def test_schema_and_verified_status_fail_closed(self) -> None:
        evidence = self.evidence()
        evidence["unexpected"] = True
        self.assert_invalid(evidence, "incomplete or unexpected shape")

        evidence = self.evidence()
        evidence["status"] = "PENDING"
        self.assert_invalid(evidence, "not VERIFIED")

        evidence = self.evidence()
        evidence["releaseCandidate"]["unexpected"] = "x"
        self.assert_invalid(evidence, "release candidate")

    def test_runtime_network_and_public_boundary_fail_closed(self) -> None:
        cases = [
            ("orchestrationBinding", "executionStatus", "FAILED", "did not succeed"),
            ("orchestrationBinding", "brokerInjectedSecretCount", 1, "injected secret"),
            ("orchestrationBinding", "noDangerousIamActionsVerified", False,
             "noDangerousIamActionsVerified"),
            ("runtimeBinding", "cloneTaskArn", "arn:aws:ecs:eu-west-2:123456789012:task/other/" + "1" * 32,
             "exact cluster"),
            ("runtimeBinding", "semanticSecurityGroupId", "sg-0123456789abcdef0",
             "not distinct"),
            ("networkIsolation", "staticRulesTerraformOwned", False, "not Terraform-owned"),
            ("networkIsolation", "securityGroupRuleCount", 9, "exactly ten"),
            ("networkIsolation", "brokerSecurityGroupRuleCount", 4, "exactly three"),
            ("networkIsolation", "semanticEniCountBeforeStart", 1, "reviewed exact value"),
            ("networkIsolation", "semanticEniCountAfterContainment", 1, "reviewed exact value"),
            ("networkIsolation", "restoredDatabasePubliclyAccessible", True, "publicly accessible"),
            ("publicSafety", "publicEntrypointFixed503", False, "not fixed 503"),
            ("publicSafety", "applicationDesiredCount", 1, "desired count"),
            ("publicSafety", "runningApplicationTaskCount", 1, "fleet was running"),
            ("publicSafety", "pendingApplicationTaskCount", 1, "pending tasks"),
            ("restoreControlPlane", "restoredBucketExactControlsVerified", False,
             "restoredBucketExactControlsVerified"),
        ]
        for section, key, value, message in cases:
            with self.subTest(section=section, key=key):
                evidence = self.evidence()
                evidence[section][key] = value
                self.assert_invalid(evidence, message)

    def test_exact_seven_database_canaries_and_clone_binding_are_required(self) -> None:
        evidence = self.evidence()
        evidence["databaseVerification"]["exactCanaryRowCounts"]["payment"] = 0
        self.assert_invalid(evidence, "exactly one per logical database")

        evidence = self.evidence()
        evidence["databaseVerification"]["logicalDatabases"] = DATABASES[:-1]
        self.assert_invalid(evidence, "exact seven")

        evidence = self.evidence()
        evidence["orchestrationBinding"]["replayDatabase"] = "restore_replay_unbound"
        self.assert_invalid(evidence, "48 bits")

    def test_restored_s3_versions_hashes_metadata_and_scope_are_required(self) -> None:
        evidence = self.evidence()
        evidence["documentVerification"]["generations"][1]["versionId"] = "destination-version-one"
        self.assert_invalid(evidence, "VersionIds are not distinct")

        evidence = self.evidence()
        evidence["documentVerification"]["deleteMarkerCount"] = 1
        self.assert_invalid(evidence, "delete marker")

        evidence = self.evidence()
        evidence["documentVerification"]["generations"][0]["exactSourceMetadataVerified"] = False
        self.assert_invalid(evidence, "exactSourceMetadataVerified")

        evidence = self.evidence()
        evidence["documentVerification"]["generations"][1]["sourceSha256"] = "a" * 64
        self.assert_invalid(evidence, "payload generations are not distinct")

        evidence = self.evidence()
        evidence["documentVerification"]["customerGeneratedDocumentMappingClaimed"] = True
        self.assert_invalid(evidence, "overclaims customer document mapping")

    def test_journal_retry_retention_and_readiness_are_exact(self) -> None:
        evidence = self.evidence()
        evidence["erasureReplayVerification"]["operationId"] = REPLAY
        self.assert_invalid(evidence, "reserved UUIDv4 namespace")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["versionCount"] = 2
        self.assert_invalid(evidence, "exactly one immutable version")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["deleteMarkerCount"] = 1
        self.assert_invalid(evidence, "delete marker")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["journal"]["minimumRetentionDays"] = 35
        self.assert_invalid(evidence, "minimum retention")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["sourceCanonicalRetryVerified"] = False
        self.assert_invalid(evidence, "sourceCanonicalRetryVerified")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["sourceOperationPreexistingBeforeAttempt"] = True
        self.assert_invalid(evidence, "attempt one cannot contain")

        evidence = self.evidence()
        evidence["orchestrationBinding"]["markerAttempt"] = 2
        evidence["erasureReplayVerification"]["attempt"] = 2
        evidence["erasureReplayVerification"]["replayOperationPreexistingBeforeAttempt"] = True
        self.assert_invalid(evidence, "cannot preexist without")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["replayReadiness"]["backupRetentionPending"] = 0
        self.assert_invalid(evidence, "exactly one synthetic")

        evidence = self.evidence()
        evidence["erasureReplayVerification"]["sourceReadiness"]["backupRetentionOverdue"] = 1
        self.assert_invalid(evidence, "backupRetentionOverdue")

        evidence = self.evidence()
        evidence["scopeLimitations"].remove("CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED")
        self.assert_invalid(evidence, "limitations")

        evidence = self.evidence()
        evidence["scopeLimitations"].remove("AGGREGATE_DOCUMENT_STORAGE_HEALTH_NOT_CLAIMED")
        self.assert_invalid(evidence, "limitations")

    def test_duplicate_json_keys_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schemaVersion":"one","schemaVersion":"two"}', encoding="utf-8")
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(duplicate)],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate semantic evidence key", result.stderr)

            target = root / "target.json"
            target.write_text(json.dumps(self.evidence()), encoding="utf-8")
            symlink = root / "link.json"
            symlink.symlink_to(target)
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--evidence", str(symlink)],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsafe semantic evidence file", result.stderr)

    def test_observer_tracks_and_removes_every_sensitive_temporary_file(self) -> None:
        observer = (ROOT / "scripts" / "aws" / "run_restore_semantic_verification.sh").read_text(
            encoding="utf-8"
        )
        helper_block = observer[
            observer.index("temporary_files=()") : observer.index("require_safe_file()")
        ]
        self.assertNotIn("$(new_temporary_file)", observer)
        self.assertIn('printf -v "$target_variable"', helper_block)

        for expected_status in (0, 7):
            program = (
                "set -euo pipefail\n"
                + helper_block
                + "\nnew_temporary_file first\n"
                + "new_temporary_file second\n"
                + "printf '%s\\n%s\\n' \"$first\" \"$second\"\n"
                + ("exit 7\n" if expected_status else "exit 0\n")
            )
            result = subprocess.run(
                ["bash", "-c", program], check=False, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, expected_status, result.stderr)
            paths = [Path(value) for value in result.stdout.splitlines()]
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_start_reconstructs_deterministic_running_or_closed_execution_and_rejects_collision(self) -> None:
        restore = {
            "schemaVersion": "jsc-public-beta-restore-request.v1",
            "status": "RESTORES_STARTED", "environment": "public-beta", "drillId": DRILL,
            "isolatedDestinations": {
                "rds": f"jsc-public-beta-restore-{DRILL}",
                "s3": f"jsc-public-beta-restore-{ACCOUNT}-{DRILL}",
            },
            "restoreJobIds": {"rds": "rds-job-12345678", "s3": "s3-job-12345678"},
            "sourceRecoveryPoints": {
                "rds": f"arn:aws:rds:eu-west-2:{ACCOUNT}:snapshot:awsbackup:job-rds-fixture",
                "s3": f"arn:aws:backup:eu-west-2:{ACCOUNT}:recovery-point:s3-fixture",
            },
            "releaseCandidate": {
                "releaseId": RELEASE, "releaseAttestationId": "6" * 64,
                "documentStoreImageDigest": "sha256:" + "4" * 64,
                "releaseOperatorImageDigest": "sha256:" + "5" * 64,
            },
            "restoreSource": {
                "logicalDatabaseCount": 7, "documentObjectVersionCount": 2,
                "canaryId": DRILL, "markerSha256": "9" * 64, "evidenceSha256": "8" * 64,
            },
            "restoreSourceEvidenceSha256": "8" * 64,
            "restoreRoleArn": f"arn:aws:iam::{ACCOUNT}:role/jsc-public-beta-backup-restore",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            restore_path = root / "restore-start-evidence.json"
            restore_path.write_text(json.dumps(restore, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            restore_sha = hashlib.sha256(restore_path.read_bytes()).hexdigest()
            state_input = {
                "drillId": DRILL, "releaseId": RELEASE,
                "releaseAttestationId": "6" * 64, "sourceCanaryId": DRILL,
                "sourceEvidenceSha256": "8" * 64, "sourceMarkerSha256": "9" * 64,
                "restoreStartEvidenceSha256": restore_sha,
                "rdsRestoreJobId": "rds-job-12345678", "s3RestoreJobId": "s3-job-12345678",
                "rdsRecoveryPointArn": restore["sourceRecoveryPoints"]["rds"],
                "s3RecoveryPointArn": restore["sourceRecoveryPoints"]["s3"],
                "restoreRoleArn": restore["restoreRoleArn"],
            }
            state_input_json = json.dumps(state_input, sort_keys=True, separators=(",", ":"))
            execution_name = f"jsc-rs-{DRILL}-{restore_sha[:12]}"
            execution_arn = (
                f"arn:aws:states:eu-west-2:{ACCOUNT}:execution:"
                f"jsc-public-beta-restore-semantic:{execution_name}"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_aws = fake_bin / "aws"
            fake_aws.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                "if [[ \"$*\" == *\"stepfunctions describe-execution\"* ]]; then\n"
                "  if [[ \"${FAKE_MODE}\" == absent && ! -f \"${FAKE_STARTED}\" ]]; then echo 'ExecutionDoesNotExist' >&2; exit 254; fi\n"
                "  input=${FAKE_STATE_INPUT}; [[ \"${FAKE_MODE}\" == collision ]] && input='{}'\n"
                "  jq -cn --arg arn \"${FAKE_EXECUTION_ARN}\" --arg machine \"${FAKE_MACHINE_ARN}\" --arg name \"${FAKE_EXECUTION_NAME}\" --arg status \"${FAKE_STATUS}\" --arg input \"$input\" '{executionArn:$arn,stateMachineArn:$machine,name:$name,status:$status,input:$input,startDate:\"2026-08-23T01:00:00Z\"}'\n"
                "elif [[ \"$*\" == *\"stepfunctions start-execution\"* ]]; then\n"
                "  : >\"${FAKE_STARTED}\"\n"
                "  jq -cn --arg arn \"${FAKE_EXECUTION_ARN}\" '{executionArn:$arn,startDate:\"2026-08-23T01:00:00Z\"}'\n"
                "else echo \"unexpected fake AWS call: $*\" >&2; exit 90; fi\n",
                encoding="utf-8",
            )
            fake_aws.chmod(0o755)
            base_environment = {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "GITHUB_REF": "refs/heads/main", "AWS_ACCOUNT_ID": ACCOUNT,
                "AWS_REGION": "eu-west-2", "RESTORE_DRILL_ID": DRILL,
                "RESTORE_SEMANTIC_CONFIRMATION": f"START RESTORE SEMANTIC VERIFICATION {DRILL}",
                "RESTORE_START_EVIDENCE": str(restore_path),
                "FAKE_STATE_INPUT": state_input_json, "FAKE_EXECUTION_ARN": execution_arn,
                "FAKE_EXECUTION_NAME": execution_name,
                "FAKE_MACHINE_ARN": f"arn:aws:states:eu-west-2:{ACCOUNT}:stateMachine:jsc-public-beta-restore-semantic",
                "FAKE_STARTED": str(root / "started"),
            }
            for status in ("RUNNING", "SUCCEEDED", "FAILED"):
                output = root / f"output-{status.lower()}"
                output.mkdir()
                environment = base_environment | {
                    "FAKE_MODE": "existing", "FAKE_STATUS": status,
                    "RESTORE_SEMANTIC_OUTPUT_DIRECTORY": str(output),
                }
                result = subprocess.run(
                    [str(ROOT / "scripts/aws/run_restore_semantic_verification.sh"), "start"],
                    cwd=ROOT, env=environment, check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                artifact = json.loads((output / f"restore-semantic-start-{DRILL}.json").read_text())
                self.assertEqual(artifact["executionArn"], execution_arn)

            collision_output = root / "output-collision"
            collision_output.mkdir()
            result = subprocess.run(
                [str(ROOT / "scripts/aws/run_restore_semantic_verification.sh"), "start"], cwd=ROOT,
                env=base_environment | {
                    "FAKE_MODE": "collision", "FAKE_STATUS": "RUNNING",
                    "RESTORE_SEMANTIC_OUTPUT_DIRECTORY": str(collision_output),
                }, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("execution is not bound to the exact input", result.stderr)

    def test_cloudtrail_runtask_history_accepts_prior_partial_and_exact_failed_call(self) -> None:
        events, tasks, context = self.run_task_fixture()
        VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture(prior_verifier_placement_failure=True)
        VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_runtask_history_rejects_unknown_or_extra_request_controls(self) -> None:
        events, tasks, context = self.run_task_fixture()
        child_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["brokerRoleArn"]
        )
        child_event["requestParameters"]["clientToken"] = "f" * 64
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "unknown attempt/stage client token"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        child_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["brokerRoleArn"]
        )
        child_event["requestParameters"]["enableExecuteCommand"] = True
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "RunTask request.*unexpected shape"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_runtask_history_rejects_duplicate_environment_and_prior_live_task(self) -> None:
        events, tasks, context = self.run_task_fixture()
        events[-1]["requestParameters"]["overrides"]["containerOverrides"][0]["environment"].append(
            copy.deepcopy(
                events[-1]["requestParameters"]["overrides"]["containerOverrides"][0]["environment"][0]
            )
        )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "duplicate name"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        prior_clone = next(
            task for task in tasks["tasks"]
            if task["taskArn"] not in context["currentTasks"].values()
            and task["group"] == "family:jsc-public-beta-restore-semantic-clone"
        )
        prior_clone["lastStatus"] = "RUNNING"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "attempt 1 clone task is not exact and STOPPED"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_runtask_history_rejects_current_marker_mismatch(self) -> None:
        events, tasks, context = self.run_task_fixture()
        context["currentTasks"]["clone"] = (
            f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{99:032x}"
        )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError,
            "current attempt RunTask response ARNs do not match the durable marker",
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_state_broker_history_is_exact_and_stopped(self) -> None:
        events, tasks, context = self.run_task_fixture()
        state_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["stateMachineRoleArn"]
        )
        state_event["requestParameters"]["enableExecuteCommand"] = True
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "state RunTask request.*unexpected shape"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_state_broker_accepts_only_canonical_aws_owned_defaults(self) -> None:
        for omitted in (("count",), ("startedBy",), ("count", "startedBy")):
            with self.subTest(omitted=omitted):
                events, tasks, context = self.run_task_fixture()
                state_event = next(
                    event for event in events
                    if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
                    == context["stateMachineRoleArn"]
                )
                for field in omitted:
                    state_event["requestParameters"].pop(field)
                VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        mutations = (
            ("count", 2, "service-owned Count drifted"),
            ("startedBy", "jsc-restore-semantic-broker", "service-owned StartedBy drifted"),
            ("group", "family:jsc-public-beta-restore-semantic-broker", "Group drifted"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                events, tasks, context = self.run_task_fixture()
                state_event = next(
                    event for event in events
                    if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
                    == context["stateMachineRoleArn"]
                )
                state_event["requestParameters"][field] = value
                with self.assertRaisesRegex(VALIDATOR_MODULE.SemanticEvidenceError, message):
                    VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        state_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["stateMachineRoleArn"]
        )
        state_event["requestParameters"]["overrides"]["containerOverrides"][0]["command"][-1] = (
            "contain"
        )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "broker command/environment drifted"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_task_facts_bind_state_and_child_started_by_and_group(self) -> None:
        events, tasks, context = self.run_task_fixture()
        marker_task = next(
            task for task in tasks["tasks"] if task["taskArn"] == context["markerBrokerTaskArn"]
        )
        marker_task["startedBy"] = "jsc-restore-semantic-broker"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "broker task is not exact and STOPPED"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        marker_task = next(
            task for task in tasks["tasks"] if task["taskArn"] == context["markerBrokerTaskArn"]
        )
        marker_task["group"] = "family:jsc-public-beta-restore-semantic-broker"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "broker task is not exact and STOPPED"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        clone_task = next(
            task for task in tasks["tasks"]
            if task["taskArn"] == context["currentTasks"]["clone"]
        )
        clone_task["startedBy"] = "AWS Step Functions"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "attempt 2 clone task is not exact and STOPPED"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_state_broker_failed_requests_remain_attempt_bounded(self) -> None:
        events, tasks, context = self.run_task_fixture()
        state_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["stateMachineRoleArn"]
        )
        for number in range(2, 5):
            failed = copy.deepcopy(state_event)
            failed["eventTime"] = f"2026-08-23T00:5{number}:00Z"
            failed["requestParameters"]["clientToken"] = f"state-token-fixture-{number}"
            failed["responseElements"] = None
            failed["errorCode"] = "ClientException"
            failed["errorMessage"] = "bounded fixture failure"
            events.append(failed)
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "exceeded three bounded attempts"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        context["markerBrokerTaskArn"] = (
            f"arn:aws:ecs:eu-west-2:{ACCOUNT}:task/jsc-public-beta/{99:032x}"
        )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "durable marker broker task"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        marker_task = next(
            task for task in tasks["tasks"] if task["taskArn"] == context["markerBrokerTaskArn"]
        )
        marker_task["lastStatus"] = "RUNNING"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "broker task is not exact and STOPPED"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_task_facts_reject_duplicate_or_second_eni(self) -> None:
        events, tasks, context = self.run_task_fixture()
        tasks["tasks"][0]["attachments"][0]["details"].append(
            {"name": "subnetId", "value": context["privateSubnetIds"][0]}
        )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "ENI details are duplicate or unexpected"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        tasks["tasks"][0]["attachments"].append(copy.deepcopy(tasks["tasks"][0]["attachments"][0]))
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "exactly one ENI attachment"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_attempt_windows_cannot_overlap_or_swap(self) -> None:
        events, tasks, context = self.run_task_fixture()
        prior_child = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["brokerRoleArn"] and event["eventTime"].startswith("2026-08-23T01:")
        )
        prior_child["eventTime"] = "2026-08-23T03:30:00Z"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "outside its recorded attempt window|overlaps attempt"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_cloudtrail_runtask_history_rejects_missing_or_out_of_order_prerequisites(self) -> None:
        events, tasks, context = self.run_task_fixture()
        prior_event = next(
            event for event in events
            if event["userIdentity"]["sessionContext"]["sessionIssuer"]["arn"]
            == context["brokerRoleArn"]
            and event["requestParameters"]["clientToken"]
            == VALIDATOR_MODULE._run_task_token(
                context["inputBindingSha256"], 1, "clone", context["definitions"]["clone"]
            )
        )
        prior_clone = prior_event["responseElements"]["tasks"][0]["taskArn"]
        events.remove(prior_event)
        tasks["tasks"] = [task for task in tasks["tasks"] if task["taskArn"] != prior_clone]
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "source RunTask preceded successful clone"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

        events, tasks, context = self.run_task_fixture()
        current_verifier = next(
            event for event in events
            if event["requestParameters"]["clientToken"]
            == VALIDATOR_MODULE._run_task_token(
                context["inputBindingSha256"], 2, "verifier", context["definitions"]["verifier"]
            )
        )
        current_verifier["eventTime"] = "2026-08-23T03:00:00Z"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "verifier RunTask preceded exact application prerequisites"
        ):
            VALIDATOR_MODULE.validate_run_task_history(events, tasks, context)

    def test_task_contract_helpers_reject_duplicate_names_and_wrong_secret_arn(self) -> None:
        with self.assertRaisesRegex(VALIDATOR_MODULE.SemanticEvidenceError, "duplicate name"):
            VALIDATOR_MODULE._named_values(
                [{"name": "A", "value": "one"}, {"name": "A", "value": "one"}],
                "task environment",
            )
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "exact document_store password field"
        ):
            VALIDATOR_MODULE.validate_database_secret_field(
                f"arn:aws:secretsmanager:eu-west-2:{ACCOUNT}:secret:jsc-public-beta/runtime/core-AbCd12:password::",
                "document_store", ACCOUNT, "application task",
            )

        observer = (ROOT / "scripts" / "aws" / "run_restore_semantic_verification.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--task-definitions", observer)
        self.assertIn("--task-definition-context", observer)

    def test_exact_iam_contract_accepts_reviewed_documents(self) -> None:
        documents, context = self.iam_fixture()
        VALIDATOR_MODULE.validate_iam_contracts(documents, context)
        observer = (ROOT / "scripts" / "aws" / "run_restore_semantic_verification.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--iam-contracts", observer)
        self.assertIn("--iam-context", observer)
        self.assertNotIn("verify_role()", observer)

    def test_exact_iam_contract_rejects_same_action_on_wildcard_resource(self) -> None:
        documents, context = self.iam_fixture()
        policy = documents["roles"]["brokerTask"]["inlineDocuments"]["restore-semantic-broker"]
        next(
            statement for statement in policy["Statement"]
            if statement["Sid"] == "RunOnlyExactRestoreSemanticChildren"
        )["Resource"] = "*"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "full policy document drifted"
        ):
            VALIDATOR_MODULE.validate_iam_contracts(documents, context)

    def test_exact_iam_contract_rejects_extra_trust_principal(self) -> None:
        documents, context = self.iam_fixture()
        documents["roles"]["cloneExecution"]["getRole"]["Role"]["AssumeRolePolicyDocument"][
            "Statement"
        ][0]["Principal"]["AWS"] = f"arn:aws:iam::{ACCOUNT}:root"
        with self.assertRaisesRegex(VALIDATOR_MODULE.SemanticEvidenceError, "trust policy drifted"):
            VALIDATOR_MODULE.validate_iam_contracts(documents, context)

    def test_exact_iam_contract_rejects_condition_and_managed_policy_drift(self) -> None:
        documents, context = self.iam_fixture()
        policy = documents["roles"]["stateMachine"]["inlineDocuments"][
            "restore-semantic-state-machine"
        ]
        next(
            statement for statement in policy["Statement"]
            if statement["Sid"] == "PassOnlyExactRestoreSemanticBrokerRoles"
        )["Condition"]["StringEquals"]["iam:PassedToService"] = "lambda.amazonaws.com"
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "full policy document drifted"
        ):
            VALIDATOR_MODULE.validate_iam_contracts(documents, context)

        documents, context = self.iam_fixture()
        documents["managedExecutionPolicy"]["version"]["PolicyVersion"]["Document"][
            "Statement"
        ][0]["Action"].append("secretsmanager:GetSecretValue")
        with self.assertRaisesRegex(
            VALIDATOR_MODULE.SemanticEvidenceError, "managed ECS execution policy full document drifted"
        ):
            VALIDATOR_MODULE.validate_iam_contracts(documents, context)


if __name__ == "__main__":
    unittest.main()
