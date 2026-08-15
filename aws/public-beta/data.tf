resource "aws_kms_key" "data" {
  description             = "Job Seeker Copilot public-beta RDS, S3, Secrets Manager and backup encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name        = "${local.name_prefix}-data"
    DataClass   = "customer-confidential"
    BetaBlocker = "true"
  }
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name_prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_secretsmanager_secret" "core" {
  name                    = "${local.name_prefix}/runtime/core"
  description             = "Generated JWT material and service-to-service tokens; initially has no value"
  kms_key_id              = aws_kms_key.data.arn
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
  kms_key_id              = aws_kms_key.data.arn
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
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30

  tags = {
    SecretClass = "external-provider"
    Integration = each.key
    SeedBefore  = "integration-enable"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket_prefix = "${local.name_prefix}-access-logs-"
  force_destroy = false

  tags = {
    Name      = "${local.name_prefix}-access-logs"
    DataClass = "operational"
    Retention = "90-days"
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

    expiration { days = 90 }

    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket" "documents" {
  bucket_prefix = "${local.name_prefix}-documents-"
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
      kms_master_key_id = aws_kms_key.data.arn
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
    value        = "1000"
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
  name = "${local.name_prefix}-rds-monitoring"

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
  kms_key_id            = aws_kms_key.data.arn

  username                      = "jscadmin"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.arn
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
  performance_insights_kms_key_id = aws_kms_key.data.arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Name        = "${local.name_prefix}-postgres"
    DataClass   = "customer-confidential"
    Backup      = "jsc-public-beta"
    BetaBlocker = "true"
  }

  depends_on = [aws_iam_role_policy_attachment.rds_monitoring]
}
