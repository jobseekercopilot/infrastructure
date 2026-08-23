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
    sid     = "ReadOnlyRestoreDocumentStoreSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.database["document_store"].arn,
      aws_secretsmanager_secret.core.arn,
    ]
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

# The isolated canary and production Document Store consume the same rendered
# journal policy document. The canary role deliberately receives no production
# document-bucket permission; its empty synthetic scope needs only the real
# immutable journal path.
resource "aws_iam_role_policy" "restore_semantic_document_store_journal" {
  name   = "restore-semantic-document-store-journal"
  role   = aws_iam_role.restore_semantic_document_store_task.id
  policy = data.aws_iam_policy_document.document_store_journal.json
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
    sid     = "ReadOnlyRestoreVerifierSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [for secret in aws_secretsmanager_secret.database : secret.arn],
      [aws_secretsmanager_secret.core.arn],
    )
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
    sid       = "ReadOnlyExactRestoreSourceMarker"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/jsc/${var.environment}/release/restore-source-canary"]
  }

  statement {
    sid = "ListOnlyRestoreCanaryVersions"
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
    sid = "ListOnlyExactErasureJournalRecord"
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
      SERVER_PORT                                         = "8089"
      DOCUMENT_STORE_DATABASE_URL                         = "jdbc:postgresql://invalid.restore.local:5432/document_store?sslmode=verify-full&sslrootcert=/etc/jsc/rds/global-bundle.pem"
      DOCUMENT_STORE_OBJECT_BUCKET                        = "jsc-public-beta-invalid-restore"
      DOCUMENT_STORE_PURGE_ENABLED                        = "true"
      DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED            = "true"
      DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED = "true"
      DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED     = "true"
      DOCUMENT_STORE_RETENTION_POLICY_VERSION             = try(local.document_store_erasure_approval.retentionPolicyVersion, "NOT_CONFIGURED")
      DOCUMENT_STORE_BACKUP_RETENTION_POLICY_VERSION      = try(local.document_store_erasure_approval.backupRetentionPolicyVersion, "NOT_CONFIGURED")
      DOCUMENT_STORE_MAXIMUM_BACKUP_RETENTION_DAYS        = "35"
      DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION = try(local.document_store_erasure_approval.journalRetentionPolicyVersion, "NOT_CONFIGURED")
      AUTH_JWKS_URI                                       = "http://127.0.0.1:1/unavailable"
      APPLICATION_TRACKER_SERVICE_URL                     = "http://127.0.0.1:1"
      DOCUMENT_STORE_CLAMAV_HOST                          = "127.0.0.1"
      DOCUMENT_STORE_CLAMAV_PORT                          = "1"
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
    secrets = [
      { name = "DOCUMENT_STORE_DATABASE_PASSWORD", valueFrom = "${aws_secretsmanager_secret.database["document_store"].arn}:password::" },
      { name = "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN", valueFrom = "${aws_secretsmanager_secret.core.arn}:DOCUMENT_STORE_RETENTION_ADMIN_TOKEN::" },
      { name = "DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY", valueFrom = "${aws_secretsmanager_secret.core.arn}:DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY::" },
      { name = "DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS", valueFrom = "${aws_secretsmanager_secret.core.arn}:DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS::" },
    ]
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
      command     = ["CMD-SHELL", "wget -q --spider http://127.0.0.1:8089/actuator/health || exit 1"]
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
    ], local.database_operator_environment)
    secrets = concat(
      [for key, secret in aws_secretsmanager_secret.database : {
        name      = "${upper(key)}_PASSWORD"
        valueFrom = "${secret.arn}:password::"
      }],
      [{ name = "DOCUMENT_STORE_RETENTION_ADMIN_TOKEN", valueFrom = "${aws_secretsmanager_secret.core.arn}:DOCUMENT_STORE_RETENTION_ADMIN_TOKEN::" }],
    )
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
