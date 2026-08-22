resource "aws_secretsmanager_secret" "core" {
  name                    = "${local.name_prefix}/runtime/core"
  description             = "Generated JWT material and service-to-service tokens; initially has no value"
  kms_key_id              = var.foundation_data_kms_key_arn
  recovery_window_in_days = 30

  tags = {
    SecretClass = "core-runtime"
    SeedBefore  = "application-start"
  }
}

resource "aws_secretsmanager_secret" "database" {
  for_each = local.databases

  name                    = "${local.name_prefix}/database/${each.key}"
  description             = "Logical PostgreSQL database credentials for ${each.key}; initially has no value"
  kms_key_id              = var.foundation_data_kms_key_arn
  recovery_window_in_days = 30

  tags = {
    SecretClass = "database-user"
    Database    = each.value.database
    SeedBefore  = "database-bootstrap"
  }
}

resource "aws_secretsmanager_secret" "integration" {
  for_each = local.integration_secret_names

  name                    = "${local.name_prefix}/integration/${each.key}"
  description             = "External ${each.key} credentials; approval and a secret version are separate prerequisites"
  kms_key_id              = var.foundation_data_kms_key_arn
  recovery_window_in_days = 30

  tags = {
    SecretClass = "external-provider"
    Integration = each.key
    SeedBefore  = "integration-enable"
  }
}

resource "aws_s3_bucket" "access_logs" {
  # Keep the physical name deterministic so the bootstrap Apply role and
  # workload boundary can name this one bucket exactly. A random
  # `bucket_prefix` suffix would not match those least-privilege ARNs.
  bucket        = "${local.name_prefix}-access-logs-${var.aws_account_id}"
  force_destroy = false

  tags = {
    Name      = "${local.name_prefix}-access-logs"
    DataClass = "operational"
    Retention = "${var.log_retention_days}-days"
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "expire-operational-access-logs"
    status = "Enabled"

    filter {}

    expiration { days = var.log_retention_days }

    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket" "documents" {
  # This exact account-qualified name is part of the task-IAM, backup and
  # permanent-erasure contracts; do not replace it with a random prefix.
  bucket        = "${local.name_prefix}-documents-${var.aws_account_id}"
  force_destroy = false

  tags = {
    Name        = "${local.name_prefix}-documents"
    DataClass   = "customer-confidential"
    Backup      = "jsc-public-beta"
    BetaBlocker = "true"
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.foundation_data_kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "documents" {
  bucket        = aws_s3_bucket.documents.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "s3/documents/"

  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "temporary-object-cleanup"
    status = "Enabled"

    filter { prefix = "tmp/" }
    expiration { days = 1 }
  }

  rule {
    id     = "stale-application-upload-quarantine"
    status = "Enabled"

    filter { prefix = "quarantine/application-uploads/" }
    expiration { days = 7 }
  }

  rule {
    id     = "noncurrent-recovery-window"
    status = "Enabled"

    filter {}
    noncurrent_version_expiration { noncurrent_days = 35 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

data "aws_iam_policy_document" "access_logs" {
  statement {
    sid       = "AllowS3ServerAccessLogs"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/s3/documents/*"]

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.documents.arn]
    }
  }

  statement {
    sid       = "AllowAlbAccessLogs"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/alb/AWSLogs/${var.aws_account_id}/*"]

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:loadbalancer/*"]
    }
  }

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.access_logs.arn,
      "${aws_s3_bucket.access_logs.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs.json
}

data "aws_iam_policy_document" "documents" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.documents.arn,
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "DenyMissingObjectEncryption"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["true"]
    }
  }

  statement {
    sid     = "DenyWrongObjectEncryptionAlgorithm"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid     = "DenyMissingObjectKmsKey"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = ["true"]
    }
  }

  statement {
    sid     = "DenyWrongObjectKmsKey"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.documents.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [var.foundation_data_kms_key_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = data.aws_iam_policy_document.documents.json
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${local.name_prefix}-postgres"
  subnet_ids = [for subnet in aws_subnet.data : subnet.id]
  tags       = { Name = "${local.name_prefix}-postgres" }
}

resource "aws_db_parameter_group" "postgres" {
  name_prefix = "${local.name_prefix}-postgres15-"
  family      = "postgres15"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "log_min_duration_statement"
    value        = "-1"
    apply_method = "immediate"
  }

  # Public-beta CloudWatch database logs deliberately retain connection,
  # disconnection and terse server error signals, but never statement text or
  # bind parameters.  A tag such as "operational-redacted" is not a redaction
  # control; PostgreSQL must suppress payload-bearing fields before export.
  parameter {
    name         = "log_statement"
    value        = "none"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_duration"
    value        = "0"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_min_error_statement"
    value        = "panic"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_parameter_max_length"
    value        = "0"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_parameter_max_length_on_error"
    value        = "0"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_error_verbosity"
    value        = "terse"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_connections"
    value        = "1"
    apply_method = "immediate"
  }

  parameter {
    name         = "log_disconnections"
    value        = "1"
    apply_method = "immediate"
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_iam_role" "rds_monitoring" {
  name                 = "${local.name_prefix}-rds-monitoring"
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.aws_account_id }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:db:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage_gib
  max_allocated_storage = 200
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.foundation_data_kms_key_arn

  username                      = "jscadmin"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.foundation_data_kms_key_arn
  port                          = 5432

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = var.high_availability

  parameter_group_name = aws_db_parameter_group.postgres.name
  ca_cert_identifier   = "rds-ca-rsa2048-g1"

  backup_retention_period  = var.db_backup_retention_days
  backup_window            = "01:00-02:00"
  maintenance_window       = "sun:03:00-sun:04:00"
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-postgres-final"

  auto_minor_version_upgrade      = true
  apply_immediately               = false
  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.foundation_data_kms_key_arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Name        = "${local.name_prefix}-postgres"
    DataClass   = "customer-confidential"
    Backup      = "jsc-public-beta"
    BetaBlocker = "true"
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [aws_iam_role_policy_attachment.rds_monitoring]
}
