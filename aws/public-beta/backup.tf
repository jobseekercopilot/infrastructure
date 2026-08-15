resource "aws_backup_vault" "customer_data" {
  name        = "${local.name_prefix}-customer-data"
  kms_key_arn = aws_kms_key.data.arn

  tags = {
    DataClass   = "customer-confidential"
    RestoreTest = "required-before-launch"
  }
}

resource "aws_backup_vault_lock_configuration" "customer_data" {
  backup_vault_name  = aws_backup_vault.customer_data.name
  min_retention_days = 7
  max_retention_days = 35
}

resource "aws_iam_role" "backup" {
  name = "${local.name_prefix}-backup"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.aws_account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "backup_s3" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Backup"
}

resource "aws_iam_role" "backup_restore" {
  name = "${local.name_prefix}-backup-restore"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.aws_account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup_restore" {
  role       = aws_iam_role.backup_restore.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

resource "aws_iam_role_policy_attachment" "backup_restore_s3" {
  role       = aws_iam_role.backup_restore.name
  policy_arn = "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Restore"
}

resource "aws_backup_plan" "customer_data" {
  name = "${local.name_prefix}-customer-data"

  rule {
    rule_name         = "daily-35-day-retention"
    target_vault_name = aws_backup_vault.customer_data.name
    schedule          = "cron(0 5 * * ? *)"
    start_window      = 60
    completion_window = 360

    lifecycle { delete_after = 35 }

    recovery_point_tags = {
      Environment = var.environment
      RestoreTest = "quarterly"
    }
  }

  tags = { Purpose = "customer-data-disaster-recovery" }
}

resource "aws_backup_selection" "customer_data" {
  name         = "${local.name_prefix}-customer-data"
  iam_role_arn = aws_iam_role.backup.arn
  plan_id      = aws_backup_plan.customer_data.id
  resources = [
    aws_db_instance.postgres.arn,
    aws_s3_bucket.documents.arn,
  ]

  depends_on = [
    aws_iam_role_policy_attachment.backup,
    aws_iam_role_policy_attachment.backup_s3,
  ]
}

resource "aws_backup_vault_notifications" "customer_data" {
  backup_vault_name = aws_backup_vault.customer_data.name
  sns_topic_arn     = aws_sns_topic.operations.arn
  backup_vault_events = [
    "BACKUP_JOB_FAILED",
    "COPY_JOB_FAILED",
    "RESTORE_JOB_FAILED",
  ]

  depends_on = [aws_sns_topic_policy.operations]
}
