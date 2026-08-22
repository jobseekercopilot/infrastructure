resource "aws_iam_role" "backup" {
  name                 = "${local.name_prefix}-backup"
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-backup-boundary"

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
  name                 = "${local.name_prefix}-backup-restore"
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-backup-restore-boundary"

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

resource "aws_backup_selection" "customer_data" {
  name         = "${local.name_prefix}-customer-data"
  iam_role_arn = aws_iam_role.backup.arn
  plan_id      = var.foundation_backup_plan_id
  resources = [
    aws_db_instance.postgres.arn,
    aws_s3_bucket.documents.arn,
  ]

  depends_on = [
    aws_iam_role_policy_attachment.backup,
    aws_iam_role_policy_attachment.backup_s3,
  ]
}
