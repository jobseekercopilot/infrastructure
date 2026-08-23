resource "aws_iam_role" "operator_database_execution" {
  name                 = "${local.name_prefix}-release-operator-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "operator_database_execution" {
  role       = aws_iam_role.operator_database_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "operator_secrets" {
  statement {
    sid     = "ReadDatabaseBootstrapSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_db_instance.postgres.master_user_secret[0].secret_arn],
      [for secret in aws_secretsmanager_secret.database : secret.arn],
    )
  }

  statement {
    sid       = "DecryptDatabaseBootstrapSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "operator_database_secrets" {
  name   = "database-bootstrap-secrets"
  role   = aws_iam_role.operator_database_execution.id
  policy = data.aws_iam_policy_document.operator_secrets.json
}

resource "aws_iam_role" "operator_preflight_execution" {
  name                 = "${local.name_prefix}-release-preflight-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "operator_preflight_execution" {
  role       = aws_iam_role.operator_preflight_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "operator_preflight_secret" {
  statement {
    sid       = "ReadOnlyPreflightIdentity"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.core.arn]
  }

  statement {
    sid       = "DecryptOnlyPreflightIdentity"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "operator_preflight_secret" {
  name   = "release-preflight-identity"
  role   = aws_iam_role.operator_preflight_execution.id
  policy = data.aws_iam_policy_document.operator_preflight_secret.json
}

resource "aws_iam_role" "operator_task" {
  name                 = "${local.name_prefix}-release-operator-role"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role" "operator_restore_canary_task" {
  name                 = "${local.name_prefix}-restore-canary-task"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

data "aws_iam_policy_document" "operator_restore_canary" {
  statement {
    sid       = "ReadOnlyRestoreCanaryBucketVersioning"
    actions   = ["s3:GetBucketVersioning"]
    resources = [aws_s3_bucket.documents.arn]
  }

  statement {
    sid = "ListOnlyRestoreCanaryVersions"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [aws_s3_bucket.documents.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["restore-canary/v1/*"]
    }
  }

  statement {
    sid = "ReadWriteOnlyRestoreCanaryObjects"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.documents.arn}/restore-canary/v1/*"]
  }

  statement {
    sid = "UseOnlyFoundationDataKeyForRestoreCanary"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.foundation_data_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        aws_s3_bucket.documents.arn,
        "${aws_s3_bucket.documents.arn}/restore-canary/v1/*",
      ]
    }
  }

  statement {
    sid       = "ReadOnlyExactDatabaseBootstrapMarker"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/jsc/${var.environment}/release/database-bootstrap"]
  }

  statement {
    sid = "ManageOnlyExactRestoreSourceCanaryMarker"
    actions = [
      "ssm:AddTagsToResource",
      "ssm:GetParameter",
      "ssm:ListTagsForResource",
      "ssm:PutParameter",
    ]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/jsc/${var.environment}/release/restore-source-canary"]
  }
}

resource "aws_iam_role_policy" "operator_restore_canary" {
  name   = "restore-source-canary"
  role   = aws_iam_role.operator_restore_canary_task.id
  policy = data.aws_iam_policy_document.operator_restore_canary.json
}

resource "aws_iam_role" "restore_semantic_clone_execution" {
  name                 = "${local.name_prefix}-restore-semantic-clone-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "restore_semantic_clone_execution" {
  role       = aws_iam_role.restore_semantic_clone_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "restore_semantic_clone_secrets" {
  statement {
    sid     = "ReadOnlyRestoreCloneDatabaseSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_db_instance.postgres.master_user_secret[0].secret_arn,
      aws_secretsmanager_secret.database["document_store"].arn,
    ]
  }

  statement {
    sid       = "DecryptOnlyRestoreCloneDatabaseSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "restore_semantic_clone_secrets" {
  name   = "restore-semantic-clone-secrets"
  role   = aws_iam_role.restore_semantic_clone_execution.id
  policy = data.aws_iam_policy_document.restore_semantic_clone_secrets.json
}

resource "aws_iam_role" "restore_semantic_document_store_execution" {
  name                 = "${local.name_prefix}-restore-semantic-document-store-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "restore_semantic_document_store_execution" {
  role       = aws_iam_role.restore_semantic_document_store_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "restore_semantic_document_store_secrets" {
  statement {
    sid       = "ReadOnlyRestoreDocumentStoreSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database["document_store"].arn]
  }

  statement {
    sid       = "DecryptOnlyRestoreDocumentStoreSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "restore_semantic_document_store_secrets" {
  name   = "restore-semantic-document-store-secrets"
  role   = aws_iam_role.restore_semantic_document_store_execution.id
  policy = data.aws_iam_policy_document.restore_semantic_document_store_secrets.json
}

resource "aws_iam_role" "restore_semantic_document_store_task" {
  name                 = "${local.name_prefix}-restore-semantic-document-store-task"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

# This policy is action/condition-equivalent to the production journal
# fragment, while its object resource is narrowed to the permanently reserved
# non-customer verification UUID namespace. A protected drill therefore cannot
# read or overwrite a future customer journal record even if its inputs are
# malicious. Contract tests compare both fragments modulo this resource scope.
data "aws_iam_policy_document" "restore_semantic_document_store_journal" {
  statement {
    sid     = "WriteOnlyImmutableErasureJournalRecords"
    actions = ["s3:PutObject"]
    resources = [
      "arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}/permanent-erasures/v1/7e57c0de-*",
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [var.foundation_erasure_journal_kms_key_arn]
    }
  }

  statement {
    sid = "ReadOnlyBoundErasureJournalRecords"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = [
      "arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}/permanent-erasures/v1/7e57c0de-*",
    ]
  }

  statement {
    sid = "UseOnlyErasureJournalKeyThroughS3"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.foundation_erasure_journal_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}"]
    }
  }
}

resource "aws_iam_role_policy" "restore_semantic_document_store_journal" {
  name   = "restore-semantic-document-store-journal"
  role   = aws_iam_role.restore_semantic_document_store_task.id
  policy = data.aws_iam_policy_document.restore_semantic_document_store_journal.json
}

resource "aws_iam_role" "restore_semantic_verifier_execution" {
  name                 = "${local.name_prefix}-restore-semantic-verifier-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "restore_semantic_verifier_execution" {
  role       = aws_iam_role.restore_semantic_verifier_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "restore_semantic_verifier_secrets" {
  statement {
    sid       = "ReadOnlyRestoreVerifierSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for secret in aws_secretsmanager_secret.database : secret.arn]
  }

  statement {
    sid       = "DecryptOnlyRestoreVerifierSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "restore_semantic_verifier_secrets" {
  name   = "restore-semantic-verifier-secrets"
  role   = aws_iam_role.restore_semantic_verifier_execution.id
  policy = data.aws_iam_policy_document.restore_semantic_verifier_secrets.json
}

resource "aws_iam_role" "restore_semantic_verifier_task" {
  name                 = "${local.name_prefix}-restore-semantic-verifier-task"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

data "aws_iam_policy_document" "restore_semantic_verifier" {
  statement {
    sid       = "ListOnlyRestoreCanaryVersions"
    actions   = ["s3:ListBucketVersions"]
    resources = ["arn:aws:s3:::jsc-public-beta-restore-${var.aws_account_id}-*"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["restore-canary/v1/*"]
    }
  }

  statement {
    sid = "ReadOnlyRestoreCanaryObjects"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["arn:aws:s3:::jsc-public-beta-restore-${var.aws_account_id}-*/restore-canary/v1/*"]
  }

  statement {
    sid       = "DecryptOnlyRestoredCanaryThroughS3"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["arn:aws:s3:::jsc-public-beta-restore-${var.aws_account_id}-*"]
    }
  }

  statement {
    sid       = "ListOnlyExactErasureJournalRecord"
    actions   = ["s3:ListBucketVersions"]
    resources = ["arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["permanent-erasures/v1/7e57c0de-*"]
    }
  }

  statement {
    sid = "ReadOnlyExactErasureJournalRecord"
    actions = [
      "s3:GetObject",
      "s3:GetObjectRetention",
      "s3:GetObjectVersion",
    ]
    resources = ["arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}/permanent-erasures/v1/7e57c0de-*"]
  }

  statement {
    sid       = "DecryptOnlyErasureJournalThroughS3"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_erasure_journal_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}"]
    }
  }
}

resource "aws_iam_role_policy" "restore_semantic_verifier" {
  name   = "restore-semantic-verifier-read-only"
  role   = aws_iam_role.restore_semantic_verifier_task.id
  policy = data.aws_iam_policy_document.restore_semantic_verifier.json
}

resource "aws_iam_role" "restore_semantic_broker_execution" {
  name                 = "${local.name_prefix}-restore-semantic-broker-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "restore_semantic_broker_execution" {
  role       = aws_iam_role.restore_semantic_broker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "restore_semantic_broker_task" {
  name                 = "${local.name_prefix}-restore-semantic-broker-task"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-restore-semantic-broker-boundary"
}

data "aws_iam_policy_document" "restore_semantic_broker_task" {
  statement {
    sid = "ReadOnlyRestoreSemanticControlPlane"
    actions = [
      "backup:DescribeRestoreJob",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribePrefixLists",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSecurityGroups",
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListServices",
      "ecs:ListTagsForResource",
      "ecs:ListTasks",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeRules",
      "rds:DescribeDBInstances",
      "rds:ListTagsForResource",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ReadOnlyExactRestoreBucketControls"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPolicyStatus",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:GetPublicAccessBlock",
    ]
    resources = ["arn:aws:s3:::jsc-public-beta-restore-${var.aws_account_id}-*"]
  }

  statement {
    sid       = "ReadOnlyExactRestoreSourceMarker"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/jsc/${var.environment}/release/restore-source-canary"]
  }

  statement {
    sid = "ManageOnlyOwnedRestoreSemanticMarker"
    actions = [
      "ssm:AddTagsToResource",
      "ssm:GetParameter",
      "ssm:ListTagsForResource",
      "ssm:PutParameter",
    ]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/jsc/${var.environment}/restore-semantic/*/start"]
  }

  statement {
    sid     = "RunOnlyExactRestoreSemanticChildren"
    actions = ["ecs:RunTask"]
    resources = [
      aws_ecs_task_definition.restore_semantic_clone.arn,
      aws_ecs_task_definition.restore_semantic_document_store.arn,
      aws_ecs_task_definition.restore_semantic_verifier.arn,
    ]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["RestoreSemanticVerification"]
    }

    condition {
      test     = "Null"
      variable = "aws:RequestTag/RestoreDrillId"
      values   = ["false"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Application", "Environment", "ManagedBy", "RestoreDrillId"]
    }
  }

  statement {
    sid       = "TagOnlyNewRestoreSemanticChildren"
    actions   = ["ecs:TagResource"]
    resources = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task/${aws_ecs_cluster.main.name}/*"]

    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RunTask"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["RestoreSemanticVerification"]
    }

    condition {
      test     = "Null"
      variable = "aws:RequestTag/RestoreDrillId"
      values   = ["false"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Application", "Environment", "ManagedBy", "RestoreDrillId"]
    }
  }

  statement {
    sid     = "PassOnlyExactRestoreSemanticChildRoles"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.restore_semantic_clone_execution.arn,
      aws_iam_role.restore_semantic_document_store_execution.arn,
      aws_iam_role.restore_semantic_document_store_task.arn,
      aws_iam_role.restore_semantic_verifier_execution.arn,
      aws_iam_role.restore_semantic_verifier_task.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "ContainOnlyTaggedRestoreSemanticChildren"
    actions   = ["ecs:StopTask"]
    resources = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task/${aws_ecs_cluster.main.name}/*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["RestoreSemanticVerification"]
    }

    condition {
      test     = "Null"
      variable = "aws:ResourceTag/RestoreDrillId"
      values   = ["false"]
    }
  }
}

resource "aws_iam_role_policy" "restore_semantic_broker_task" {
  name   = "restore-semantic-broker"
  role   = aws_iam_role.restore_semantic_broker_task.id
  policy = data.aws_iam_policy_document.restore_semantic_broker_task.json
}

data "aws_iam_policy_document" "restore_semantic_state_machine_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:states:${var.aws_region}:${var.aws_account_id}:stateMachine:${local.name_prefix}-restore-semantic"]
    }
  }
}

resource "aws_iam_role" "restore_semantic_state_machine" {
  name                 = "${local.name_prefix}-restore-semantic-state-machine"
  assume_role_policy   = data.aws_iam_policy_document.restore_semantic_state_machine_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-restore-semantic-broker-boundary"
}

locals {
  database_operator_environment = flatten([
    for key, database in local.databases : [
      { name = "${upper(key)}_DATABASE", value = database.database },
      { name = "${upper(key)}_USERNAME", value = database.username },
    ]
  ])

  database_operator_secrets = concat(
    [
      { name = "MASTER_USERNAME", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:username::" },
      { name = "MASTER_PASSWORD", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:password::" },
    ],
    [for key, secret in aws_secretsmanager_secret.database : {
      name      = "${upper(key)}_PASSWORD"
      valueFrom = "${secret.arn}:password::"
    }],
  )

  preflight_endpoints = join(",", [
    for name, service in local.raw_services :
    "http://${name}.${local.namespace_name}:${service.port}${service.healthPath}"
  ])

  restore_semantic_document_store_environment = merge(
    local.service_environment["document-store-service"],
    {
      SERVER_PORT                                             = "8089"
      DOCUMENT_STORE_DATABASE_URL                             = "jdbc:postgresql://invalid.restore.local:5432/document_store?sslmode=verify-full&sslrootcert=/etc/jsc/rds/global-bundle.pem"
      DOCUMENT_STORE_OBJECT_BUCKET                            = "jsc-public-beta-invalid-restore"
      DOCUMENT_STORE_PURGE_ENABLED                            = "true"
      DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED                = "true"
      DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED    = "true"
      DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED         = "true"
      DOCUMENT_STORE_RETENTION_POLICY_VERSION                 = try(local.document_store_erasure_approval.retentionPolicyVersion, "NOT_CONFIGURED")
      DOCUMENT_STORE_BACKUP_RETENTION_POLICY_VERSION          = try(local.document_store_erasure_approval.backupRetentionPolicyVersion, "NOT_CONFIGURED")
      DOCUMENT_STORE_MAXIMUM_BACKUP_RETENTION_DAYS            = "35"
      DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION = try(local.document_store_erasure_approval.journalRetentionPolicyVersion, "NOT_CONFIGURED")
      DOCUMENT_STORE_RECONCILIATION_INITIAL_DELAY_MS          = "28800000"
      DOCUMENT_STORE_RECONCILIATION_FIXED_DELAY_MS            = "28800000"
      DOCUMENT_STORE_PERMANENT_ERASURE_FIXED_DELAY_MS         = "28800000"
      DOCUMENT_STORE_RETENTION_FIXED_DELAY_MS                 = "28800000"
      DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED            = "false"
      DOCUMENT_STORE_UPLOAD_CLEANUP_ENABLED                   = "false"
      # These deliberately invalid sentinels are replaced by the fixed broker
      # with distinct deterministic drill-only values. Production core
      # credentials are never injected into a semantic verification task.
      DOCUMENT_STORE_PRODUCER_TOKEN                    = "invalid-restore-semantic-producer"
      DOCUMENT_STORE_READER_TOKEN                      = "invalid-restore-semantic-reader"
      DOCUMENT_STORE_RETENTION_ADMIN_TOKEN             = "invalid-restore-semantic-admin-token-0000"
      DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY           = "invalid-restore-semantic-fingerprint"
      DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS = ""
      APPLICATION_TRACKER_PRODUCER_TOKEN               = "invalid-restore-semantic-tracker-producer"
      APPLICATION_TRACKER_READER_TOKEN                 = "invalid-restore-semantic-tracker-reader"
      ENVIRONMENT_DATA_TOKEN                           = "invalid-restore-semantic-environment"
      AUTH_JWKS_URI                                    = "http://127.0.0.1:1/unavailable"
      APPLICATION_TRACKER_SERVICE_URL                  = "http://127.0.0.1:1"
      DOCUMENT_STORE_CLAMAV_HOST                       = "127.0.0.1"
      DOCUMENT_STORE_CLAMAV_PORT                       = "1"
    },
  )
}

resource "aws_ecs_task_definition" "database_bootstrap" {
  family                   = "${local.name_prefix}-database-bootstrap"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.operator_database_execution.arn
  task_role_arn            = aws_iam_role.operator_task.arn

  container_definitions = jsonencode([{
    name      = "database-bootstrap"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/bootstrap-databases.sh"]
    environment = concat([
      { name = "PGHOST", value = aws_db_instance.postgres.address },
      { name = "PGPORT", value = tostring(aws_db_instance.postgres.port) },
      { name = "PGSSLMODE", value = "verify-full" },
      { name = "PGSSLROOTCERT", value = "/etc/jsc/rds/global-bundle.pem" },
    ], local.database_operator_environment)
    secrets                = local.database_operator_secrets
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 32
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "database-bootstrap"
      }
    }
  }])

  tags = {
    Purpose      = "database-bootstrap"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [aws_iam_role_policy.operator_database_secrets]
}

resource "aws_ecs_task_definition" "release_preflight" {
  family                   = "${local.name_prefix}-release-preflight"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.operator_preflight_execution.arn
  task_role_arn            = aws_iam_role.operator_task.arn

  container_definitions = jsonencode([{
    name      = "release-preflight"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/preflight.sh"]
    environment = [
      { name = "SERVICE_ENDPOINTS", value = local.preflight_endpoints },
      { name = "PAYMENT_READINESS_ENDPOINT", value = "http://payment-gateway.${local.namespace_name}:8098/api/v2/payments/checkout-readiness" },
      { name = "EXPECTED_CHECKOUT_AVAILABLE", value = tostring(var.enabled_integrations.stripe) },
      { name = "DOCUMENT_ERASURE_READINESS_ENDPOINT", value = "http://document-store-service.${local.namespace_name}:8089/internal/retention/v1/permanent-erasures/readiness" },
      { name = "DOCUMENT_ERASURE_RETENTION_POLICY_VERSION", value = try(local.document_store_erasure_approval.retentionPolicyVersion, "NOT_CONFIGURED") },
      { name = "DOCUMENT_ERASURE_BACKUP_POLICY_VERSION", value = try(local.document_store_erasure_approval.backupRetentionPolicyVersion, "NOT_CONFIGURED") },
      { name = "DOCUMENT_ERASURE_MAXIMUM_BACKUP_RETENTION_DAYS", value = tostring(try(local.document_store_erasure_approval.maximumBackupRetentionDays, 0)) },
    ]
    secrets = [
      { name = "BFF_TO_PAYMENT_GATEWAY_TOKEN", valueFrom = "${aws_secretsmanager_secret.core.arn}:BFF_TO_PAYMENT_GATEWAY_TOKEN::" },
      { name = "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN", valueFrom = "${aws_secretsmanager_secret.core.arn}:DOCUMENT_STORE_RETENTION_ADMIN_TOKEN::" },
    ]
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 32
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "release-preflight"
      }
    }
  }])

  tags = {
    Purpose      = "release-preflight"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [aws_iam_role_policy.operator_preflight_secret]
}

resource "aws_ecs_task_definition" "migration_verification" {
  family                   = "${local.name_prefix}-migration-verification"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.operator_database_execution.arn
  task_role_arn            = aws_iam_role.operator_task.arn

  container_definitions = jsonencode([{
    name      = "migration-verification"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/verify-migrations.sh"]
    environment = concat([
      { name = "PGHOST", value = aws_db_instance.postgres.address },
      { name = "PGPORT", value = tostring(aws_db_instance.postgres.port) },
      { name = "PGSSLMODE", value = "verify-full" },
      { name = "PGSSLROOTCERT", value = "/etc/jsc/rds/global-bundle.pem" },
    ], local.database_operator_environment)
    secrets                = local.database_operator_secrets
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 32
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migration-verification"
      }
    }
  }])

  tags = {
    Purpose      = "migration-verification"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [aws_iam_role_policy.operator_database_secrets]
}

resource "aws_ecs_task_definition" "restore_source_canary" {
  family                   = "${local.name_prefix}-restore-source-canary"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.operator_database_execution.arn
  task_role_arn            = aws_iam_role.operator_restore_canary_task.arn

  container_definitions = jsonencode([{
    name      = "restore-source-canary"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/prepare-restore-source-canary.sh"]
    environment = concat([
      { name = "AWS_REGION", value = var.aws_region },
      { name = "PGHOST", value = aws_db_instance.postgres.address },
      { name = "PGPORT", value = tostring(aws_db_instance.postgres.port) },
      { name = "PGSSLMODE", value = "verify-full" },
      { name = "PGSSLROOTCERT", value = "/etc/jsc/rds/global-bundle.pem" },
      { name = "DOCUMENT_BUCKET", value = aws_s3_bucket.documents.bucket },
      { name = "DOCUMENT_KMS_KEY_ARN", value = var.foundation_data_kms_key_arn },
      { name = "RELEASE_ID", value = local.image_manifest.releaseId },
      { name = "RELEASE_ATTESTATION_ID", value = local.release_attestation_id },
      { name = "RESTORE_SOURCE_CANARY_MARKER", value = "/jsc/${var.environment}/release/restore-source-canary" },
      { name = "DATABASE_BOOTSTRAP_MARKER", value = "/jsc/${var.environment}/release/database-bootstrap" },
    ], local.database_operator_environment)
    secrets                = local.database_operator_secrets
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 32
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "restore-source-canary"
      }
    }
  }])

  tags = {
    Purpose      = "restore-source-canary"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [
    aws_iam_role_policy.operator_database_secrets,
    aws_iam_role_policy.operator_restore_canary,
  ]
}

resource "aws_ecs_task_definition" "restore_semantic_broker" {
  family                   = "${local.name_prefix}-restore-semantic-broker"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.restore_semantic_broker_execution.arn
  task_role_arn            = aws_iam_role.restore_semantic_broker_task.arn

  container_definitions = jsonencode([{
    name      = "restore-semantic-broker"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/run-restore-semantic-broker.sh", "start"]
    environment = [
      { name = "AWS_ACCOUNT_ID", value = var.aws_account_id },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "RESTORE_CLUSTER_ARN", value = aws_ecs_cluster.main.arn },
      { name = "RESTORE_CLUSTER_NAME", value = aws_ecs_cluster.main.name },
      { name = "RESTORE_VPC_ID", value = aws_vpc.main.id },
      { name = "RESTORE_PRIVATE_SUBNET_IDS_JSON", value = jsonencode([for subnet in aws_subnet.private : subnet.id]) },
      { name = "RESTORE_DATA_SUBNET_IDS_JSON", value = jsonencode([for subnet in aws_subnet.data : subnet.id]) },
      { name = "RESTORE_DATA_KMS_KEY_ARN", value = var.foundation_data_kms_key_arn },
      { name = "RESTORE_DB_SUBNET_GROUP_NAME", value = aws_db_subnet_group.postgres.name },
      { name = "RESTORE_DB_PARAMETER_GROUP_NAME", value = aws_db_parameter_group.postgres.name },
      { name = "RESTORE_DATABASE_SECURITY_GROUP_ID", value = aws_security_group.restore_database.id },
      { name = "RESTORE_SEMANTIC_SECURITY_GROUP_ID", value = aws_security_group.restore_semantic_verifier.id },
      { name = "RESTORE_BROKER_SECURITY_GROUP_ID", value = aws_security_group.restore_semantic_broker.id },
      { name = "RESTORE_CLONE_TASK_DEFINITION_ARN", value = aws_ecs_task_definition.restore_semantic_clone.arn },
      { name = "RESTORE_APP_TASK_DEFINITION_ARN", value = aws_ecs_task_definition.restore_semantic_document_store.arn },
      { name = "RESTORE_VERIFIER_TASK_DEFINITION_ARN", value = aws_ecs_task_definition.restore_semantic_verifier.arn },
      { name = "RESTORE_CLONE_EXECUTION_ROLE_ARN", value = aws_iam_role.restore_semantic_clone_execution.arn },
      { name = "RESTORE_APP_EXECUTION_ROLE_ARN", value = aws_iam_role.restore_semantic_document_store_execution.arn },
      { name = "RESTORE_APP_TASK_ROLE_ARN", value = aws_iam_role.restore_semantic_document_store_task.arn },
      { name = "RESTORE_VERIFIER_EXECUTION_ROLE_ARN", value = aws_iam_role.restore_semantic_verifier_execution.arn },
      { name = "RESTORE_VERIFIER_TASK_ROLE_ARN", value = aws_iam_role.restore_semantic_verifier_task.arn },
      { name = "DOCUMENT_STORE_IMAGE_DIGEST", value = local.image_manifest.images["document-store-service"].digest },
      { name = "DOCUMENT_STORE_SOURCE_COMMIT", value = local.image_manifest.images["document-store-service"].revision },
      { name = "RELEASE_OPERATOR_IMAGE_DIGEST", value = local.image_manifest.images["release-operator"].digest },
      { name = "RELEASE_OPERATOR_SOURCE_COMMIT", value = local.image_manifest.images["release-operator"].revision },
    ]
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 64
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "restore-semantic-broker"
      }
    }
  }])

  tags = {
    Purpose      = "restore-semantic-broker"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [
    aws_iam_role_policy.restore_semantic_broker_task,
    aws_iam_role_policy_attachment.restore_semantic_broker_execution,
  ]
}

resource "aws_ecs_task_definition" "restore_semantic_clone" {
  family                   = "${local.name_prefix}-restore-semantic-clone"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.restore_semantic_clone_execution.arn
  # Deliberately no task role. The exact release-operator command can clone
  # only through injected restored-RDS credentials and has no AWS API identity.

  container_definitions = jsonencode([{
    name      = "restore-semantic-clone"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/clone-restored-document-store.sh"]
    environment = [
      { name = "PGHOST", value = "invalid.restore.local" },
      { name = "PGPORT", value = "5432" },
      { name = "PGSSLMODE", value = "verify-full" },
      { name = "PGSSLROOTCERT", value = "/etc/jsc/rds/global-bundle.pem" },
      { name = "DOCUMENT_STORE_DATABASE", value = "document_store" },
      { name = "DOCUMENT_STORE_USERNAME", value = "document_store" },
      { name = "RESTORE_REPLAY_DATABASE", value = "invalid_restore_replay" },
      { name = "RESTORE_DRILL_ID", value = "invalid-drill" },
      { name = "RESTORE_SOURCE_CANARY_ID", value = "invalid-canary" },
      { name = "RESTORE_SOURCE_MARKER_SHA256", value = "invalid" },
      { name = "RELEASE_ID", value = "invalid" },
    ]
    secrets = [
      { name = "MASTER_USERNAME", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:username::" },
      { name = "MASTER_PASSWORD", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:password::" },
      { name = "DOCUMENT_STORE_PASSWORD", valueFrom = "${aws_secretsmanager_secret.database["document_store"].arn}:password::" },
    ]
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 32
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "restore-semantic-clone"
      }
    }
  }])

  tags = {
    Purpose      = "restore-semantic-clone"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [aws_iam_role_policy.restore_semantic_clone_secrets]
}

resource "aws_ecs_task_definition" "restore_semantic_document_store" {
  family                   = "${local.name_prefix}-restore-semantic-document-store"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.restore_semantic_document_store_execution.arn
  task_role_arn            = aws_iam_role.restore_semantic_document_store_task.arn

  container_definitions = jsonencode([{
    name      = "restore-semantic-document-store"
    image     = "${aws_ecr_repository.image["document-store-service"].repository_url}@${local.image_manifest.images["document-store-service"].digest}"
    essential = true
    cpu       = 256
    memory    = 1024
    portMappings = [{
      name          = "http"
      containerPort = 8089
      hostPort      = 8089
      protocol      = "tcp"
      appProtocol   = "http"
    }]
    environment = [for key, value in local.restore_semantic_document_store_environment : {
      name  = key
      value = value
    }]
    # Only the restored database password is a live secret. The broker supplies
    # deterministic, drill-only authentication and fingerprint values as fixed
    # named overrides; none of the production core token secret is exposed.
    secrets = [{
      name      = "DOCUMENT_STORE_DATABASE_PASSWORD"
      valueFrom = "${aws_secretsmanager_secret.database["document_store"].arn}:password::"
    }]
    user                   = "10001:10001"
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 128
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    healthCheck = {
      command     = ["CMD-SHELL", "wget -q --spider http://127.0.0.1:8089/actuator/health/liveness || exit 1"]
      interval    = 15
      timeout     = 10
      retries     = 4
      startPeriod = 120
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "restore-semantic-document-store"
        mode                  = "non-blocking"
        max-buffer-size       = "25m"
      }
    }
    stopTimeout = 90
  }])

  tags = {
    Purpose      = "restore-semantic-document-store"
    ImageDigest  = local.image_manifest.images["document-store-service"].digest
    SourceCommit = local.image_manifest.images["document-store-service"].revision
  }

  depends_on = [
    aws_iam_role_policy.restore_semantic_document_store_journal,
    aws_iam_role_policy.restore_semantic_document_store_secrets,
  ]
}

resource "aws_ecs_task_definition" "restore_semantic_verifier" {
  family                   = "${local.name_prefix}-restore-semantic-verifier"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.restore_semantic_verifier_execution.arn
  task_role_arn            = aws_iam_role.restore_semantic_verifier_task.arn

  container_definitions = jsonencode([{
    name      = "restore-semantic-verifier"
    image     = "${aws_ecr_repository.image["release-operator"].repository_url}@${local.image_manifest.images["release-operator"].digest}"
    essential = true
    cpu       = 256
    memory    = 512
    command   = ["/opt/jsc/verify-restored-semantics.sh"]
    environment = concat([
      { name = "AWS_ACCOUNT_ID", value = var.aws_account_id },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "PGHOST", value = "invalid.restore.local" },
      { name = "PGPORT", value = "5432" },
      { name = "PGSSLMODE", value = "verify-full" },
      { name = "PGSSLROOTCERT", value = "/etc/jsc/rds/global-bundle.pem" },
      { name = "DOCUMENT_KMS_KEY_ARN", value = var.foundation_data_kms_key_arn },
      { name = "ERASURE_JOURNAL_BUCKET", value = var.foundation_erasure_journal_bucket_name },
      { name = "ERASURE_JOURNAL_KMS_KEY_ARN", value = var.foundation_erasure_journal_kms_key_arn },
      { name = "ERASURE_JOURNAL_RETENTION_DAYS", value = tostring(var.foundation_erasure_journal_retention_days) },
      { name = "RESTORE_SOURCE_CANARY_MARKER", value = "/jsc/${var.environment}/release/restore-source-canary" },
      { name = "RESTORE_DOCUMENT_BUCKET", value = "jsc-public-beta-invalid-restore" },
      { name = "RESTORE_DRILL_ID", value = "invalid-drill" },
      { name = "RESTORE_SOURCE_CANARY_ID", value = "invalid-canary" },
      { name = "RESTORE_SOURCE_EVIDENCE_SHA256", value = "invalid" },
      { name = "RESTORE_SOURCE_MARKER_SHA256", value = "invalid" },
      { name = "RELEASE_ID", value = "invalid" },
      { name = "RESTORE_REPLAY_DATABASE", value = "invalid_restore_replay" },
      { name = "RESTORE_ERASURE_OPERATION_ID", value = "invalid" },
      { name = "RESTORE_ERASURE_REPLAY_ID", value = "invalid" },
      { name = "SOURCE_DOCUMENT_STORE_URL", value = "http://127.0.0.1:1" },
      { name = "REPLAY_DOCUMENT_STORE_URL", value = "http://127.0.0.1:1" },
      { name = "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN", value = "invalid-restore-semantic-admin-token-0000" },
    ], local.database_operator_environment)
    secrets = [for key, secret in aws_secretsmanager_secret.database : {
      name      = "${upper(key)}_PASSWORD"
      valueFrom = "${secret.arn}:password::"
    }]
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [{
        containerPath = "/tmp"
        size          = 64
        mountOptions  = ["rw", "noexec", "nosuid", "nodev"]
      }]
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operator.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "restore-semantic-verifier"
      }
    }
  }])

  tags = {
    Purpose      = "restore-semantic-verifier"
    ImageDigest  = local.image_manifest.images["release-operator"].digest
    SourceCommit = local.image_manifest.images["release-operator"].revision
  }

  depends_on = [
    aws_iam_role_policy.restore_semantic_verifier,
    aws_iam_role_policy.restore_semantic_verifier_secrets,
  ]
}

data "aws_iam_policy_document" "restore_semantic_state_machine" {
  statement {
    sid       = "RunOnlyExactSecretFreeRestoreSemanticBroker"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.restore_semantic_broker.arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["RestoreSemanticBroker"]
    }

    condition {
      test     = "Null"
      variable = "aws:RequestTag/RestoreDrillId"
      values   = ["false"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Application", "Environment", "ManagedBy", "RestoreDrillId"]
    }
  }

  statement {
    sid       = "TagOnlyNewRestoreSemanticBroker"
    actions   = ["ecs:TagResource"]
    resources = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task/${aws_ecs_cluster.main.name}/*"]

    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RunTask"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/ManagedBy"
      values   = ["RestoreSemanticBroker"]
    }

    condition {
      test     = "Null"
      variable = "aws:RequestTag/RestoreDrillId"
      values   = ["false"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Application", "Environment", "ManagedBy", "RestoreDrillId"]
    }
  }

  statement {
    sid     = "PassOnlyExactRestoreSemanticBrokerRoles"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.restore_semantic_broker_execution.arn,
      aws_iam_role.restore_semantic_broker_task.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "ObserveOnlyBrokerTaskForSynchronousIntegration"
    actions   = ["ecs:DescribeTasks"]
    resources = ["*"]
  }

  statement {
    sid       = "StopOnlyTaggedBrokerTaskForSynchronousIntegration"
    actions   = ["ecs:StopTask"]
    resources = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task/${aws_ecs_cluster.main.name}/*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Application"
      values   = ["Job Seeker Copilot"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [var.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/ManagedBy"
      values   = ["RestoreSemanticBroker"]
    }

    condition {
      test     = "Null"
      variable = "aws:ResourceTag/RestoreDrillId"
      values   = ["false"]
    }
  }

  statement {
    sid = "UseOnlyStepFunctionsEcsTaskEventsRule"
    actions = [
      "events:DescribeRule",
      "events:PutRule",
      "events:PutTargets",
    ]
    resources = ["arn:aws:events:${var.aws_region}:${var.aws_account_id}:rule/StepFunctionsGetEventsForECSTaskRule"]
  }
}

resource "aws_iam_role_policy" "restore_semantic_state_machine" {
  name   = "restore-semantic-state-machine"
  role   = aws_iam_role.restore_semantic_state_machine.id
  policy = data.aws_iam_policy_document.restore_semantic_state_machine.json
}

locals {
  restore_semantic_broker_static_environment = [
    { Name = "RESTORE_BROKER_TASK_DEFINITION_ARN", Value = aws_ecs_task_definition.restore_semantic_broker.arn },
    { Name = "RESTORE_BROKER_EXECUTION_ROLE_ARN", Value = aws_iam_role.restore_semantic_broker_execution.arn },
    { Name = "RESTORE_BROKER_TASK_ROLE_ARN", Value = aws_iam_role.restore_semantic_broker_task.arn },
  ]
  restore_semantic_broker_dynamic_environment = [
    { Name = "RESTORE_DRILL_ID", "Value.$" = "$.drillId" },
    { Name = "RELEASE_ID", "Value.$" = "$.releaseId" },
    { Name = "RELEASE_ATTESTATION_ID", "Value.$" = "$.releaseAttestationId" },
    { Name = "RESTORE_SOURCE_CANARY_ID", "Value.$" = "$.sourceCanaryId" },
    { Name = "RESTORE_SOURCE_EVIDENCE_SHA256", "Value.$" = "$.sourceEvidenceSha256" },
    { Name = "RESTORE_SOURCE_MARKER_SHA256", "Value.$" = "$.sourceMarkerSha256" },
    { Name = "RESTORE_START_EVIDENCE_SHA256", "Value.$" = "$.restoreStartEvidenceSha256" },
    { Name = "RDS_RESTORE_JOB_ID", "Value.$" = "$.rdsRestoreJobId" },
    { Name = "S3_RESTORE_JOB_ID", "Value.$" = "$.s3RestoreJobId" },
    { Name = "RDS_RECOVERY_POINT_ARN", "Value.$" = "$.rdsRecoveryPointArn" },
    { Name = "S3_RECOVERY_POINT_ARN", "Value.$" = "$.s3RecoveryPointArn" },
    { Name = "RESTORE_ROLE_ARN", "Value.$" = "$.restoreRoleArn" },
    { Name = "STATE_MACHINE_EXECUTION_ARN", "Value.$" = "$$.Execution.Id" },
  ]
  restore_semantic_broker_network = {
    AwsvpcConfiguration = {
      Subnets        = [for subnet in aws_subnet.private : subnet.id]
      SecurityGroups = [aws_security_group.restore_semantic_broker.id]
      AssignPublicIp = "DISABLED"
    }
  }
  restore_semantic_broker_tags = [
    { Key = "Application", Value = "Job Seeker Copilot" },
    { Key = "Environment", Value = var.environment },
    { Key = "ManagedBy", Value = "RestoreSemanticBroker" },
    { Key = "RestoreDrillId", "Value.$" = "$.drillId" },
  ]
}

resource "aws_sfn_state_machine" "restore_semantic" {
  name     = "${local.name_prefix}-restore-semantic"
  role_arn = aws_iam_role.restore_semantic_state_machine.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "Fixed-network, secret-free broker for isolated restore semantic verification"
    StartAt = "RunVerifierBroker"
    States = {
      RunVerifierBroker = {
        Type           = "Task"
        Resource       = "arn:aws:states:::ecs:runTask.sync"
        TimeoutSeconds = 7200
        Parameters = {
          Cluster              = aws_ecs_cluster.main.arn
          TaskDefinition       = aws_ecs_task_definition.restore_semantic_broker.arn
          LaunchType           = "EC2"
          Group                = "jsc-restore-semantic-broker"
          NetworkConfiguration = local.restore_semantic_broker_network
          Overrides = {
            ExecutionRoleArn = aws_iam_role.restore_semantic_broker_execution.arn
            TaskRoleArn      = aws_iam_role.restore_semantic_broker_task.arn
            ContainerOverrides = [{
              Name        = "restore-semantic-broker"
              Command     = ["/opt/jsc/run-restore-semantic-broker.sh", "start"]
              Environment = concat(local.restore_semantic_broker_static_environment, local.restore_semantic_broker_dynamic_environment)
            }]
          }
          Tags                 = local.restore_semantic_broker_tags
          EnableECSManagedTags = false
        }
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.brokerFailure", Next = "ContainChildren" }]
        End   = true
      }
      ContainChildren = {
        Type           = "Task"
        Resource       = "arn:aws:states:::ecs:runTask.sync"
        TimeoutSeconds = 900
        Parameters = {
          Cluster              = aws_ecs_cluster.main.arn
          TaskDefinition       = aws_ecs_task_definition.restore_semantic_broker.arn
          LaunchType           = "EC2"
          Group                = "jsc-restore-semantic-contain"
          NetworkConfiguration = local.restore_semantic_broker_network
          Overrides = {
            ExecutionRoleArn = aws_iam_role.restore_semantic_broker_execution.arn
            TaskRoleArn      = aws_iam_role.restore_semantic_broker_task.arn
            ContainerOverrides = [{
              Name    = "restore-semantic-broker"
              Command = ["/opt/jsc/run-restore-semantic-broker.sh", "contain"]
              Environment = concat(local.restore_semantic_broker_static_environment, [
                { Name = "RESTORE_DRILL_ID", "Value.$" = "$.drillId" },
              ])
            }]
          }
          Tags                 = local.restore_semantic_broker_tags
          EnableECSManagedTags = false
        }
        Next = "VerificationFailed"
      }
      VerificationFailed = {
        Type  = "Fail"
        Error = "RestoreSemanticVerificationFailed"
        Cause = "The fixed broker failed; child containment was invoked."
      }
    }
  })

  tags = {
    Purpose = "restore-semantic-broker"
  }

  depends_on = [aws_iam_role_policy.restore_semantic_state_machine]
}

data "aws_ssm_parameter" "database_bootstrap" {
  count = var.application_desired_count > 0 && !var.offline_activation_validation ? 1 : 0
  name  = "/jsc/${var.environment}/release/database-bootstrap"
}

data "aws_ssm_parameter" "release_preflight" {
  count = var.public_entrypoint_enabled && !var.offline_activation_validation ? 1 : 0
  name  = "/jsc/${var.environment}/release/preflight"
}

resource "terraform_data" "runtime_attestations" {
  input = {
    database_bootstrap = var.offline_activation_validation ? "offline-validation-only" : (
      var.application_desired_count > 0 ? data.aws_ssm_parameter.database_bootstrap[0].value : "not-required"
    )
    release_preflight = var.offline_activation_validation ? "offline-validation-only" : (
      var.public_entrypoint_enabled ? data.aws_ssm_parameter.release_preflight[0].value : "not-required"
    )
    attestation_id = local.release_attestation_id
  }

  lifecycle {
    precondition {
      condition = (
        var.application_desired_count == 0 ||
        var.offline_activation_validation ||
        data.aws_ssm_parameter.database_bootstrap[0].value == local.release_attestation_id
      )
      error_message = "Database bootstrap must complete for this exact release and runtime configuration before application tasks can start."
    }

    precondition {
      condition = (
        !var.public_entrypoint_enabled ||
        var.offline_activation_validation ||
        data.aws_ssm_parameter.release_preflight[0].value == local.release_attestation_id
      )
      error_message = "Private fleet preflight must pass for this exact release and runtime configuration before the public listener can activate."
    }
  }
}
