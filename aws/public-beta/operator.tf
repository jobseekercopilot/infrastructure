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
