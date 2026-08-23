resource "aws_ecr_repository" "image" {
  for_each = local.required_image_names

  name                 = "${local.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.foundation_data_kms_key_arn
  }

  image_scanning_configuration { scan_on_push = true }

  tags = {
    Name         = each.key
    ReleaseImage = "true"
  }
}

resource "aws_ecr_lifecycle_policy" "image" {
  for_each = aws_ecr_repository.image

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain the twenty most recent immutable release images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "service" {
  for_each = local.raw_services

  name              = "/jsc/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.foundation_data_kms_key_arn

  tags = {
    Service   = each.key
    DataClass = "operational-redacted"
  }
}

resource "aws_cloudwatch_log_group" "clamav" {
  name              = "/jsc/${var.environment}/clamav"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.foundation_data_kms_key_arn

  tags = {
    Service   = "clamav"
    DataClass = "operational-redacted"
  }
}

resource "aws_cloudwatch_log_group" "operator" {
  name              = "/jsc/${var.environment}/release-operator"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.foundation_data_kms_key_arn
  tags              = { DataClass = "operational-redacted" }
}

resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/jsc/${var.environment}/ecs-exec"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.foundation_data_kms_key_arn
  tags              = { DataClass = "break-glass-session" }
}

resource "aws_ecs_account_setting_default" "awsvpc_trunking" {
  name  = "awsvpcTrunking"
  value = "enabled"
}

resource "aws_ecs_cluster" "main" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      kms_key_id = var.foundation_data_kms_key_arn
      logging    = "OVERRIDE"

      log_configuration {
        cloud_watch_encryption_enabled = false
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.ecs_exec.name
      }
    }
  }

  tags = { Name = local.name_prefix }
}

resource "aws_iam_role" "ecs_instance" {
  name                 = "${local.name_prefix}-ecs-instance"
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_instance" {
  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "ecs_ssm" {
  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ecs" {
  name = "${local.name_prefix}-ecs"
  role = aws_iam_role.ecs_instance.name
}

resource "aws_launch_template" "ecs" {
  name_prefix   = "${local.name_prefix}-ecs-"
  image_id      = var.ecs_ami_id
  instance_type = var.instance_type

  iam_instance_profile { name = aws_iam_instance_profile.ecs.name }

  vpc_security_group_ids = [aws_security_group.ecs_hosts.id]

  user_data = base64encode(<<-USERDATA
    #!/bin/bash
    set -euo pipefail
    cat >> /etc/ecs/ecs.config <<'ECSCONFIG'
    ECS_CLUSTER=${aws_ecs_cluster.main.name}
    ECS_AWSVPC_BLOCK_IMDS=true
    ECS_ENABLE_TASK_IAM_ROLE=true
    ECS_ENABLE_TASK_IAM_ROLE_NETWORK_HOST=true
    ECS_RESERVED_MEMORY=4096
    ECS_CONTAINER_STOP_TIMEOUT=90s
    ECS_IMAGE_PULL_BEHAVIOR=always
    ECS_ENABLE_CONTAINER_METADATA=true
    ECSCONFIG
  USERDATA
  )

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  monitoring { enabled = true }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      delete_on_termination = true
      encrypted             = true
      kms_key_id            = var.foundation_data_kms_key_arn
      volume_size           = 100
      volume_type           = "gp3"
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${local.name_prefix}-ecs"
      PatchGroup  = "jsc-public-beta"
      Application = "Job Seeker Copilot"
      Environment = "public-beta"
      ManagedBy   = "Terraform"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name        = "${local.name_prefix}-ecs"
      Application = "Job Seeker Copilot"
      Environment = "public-beta"
      ManagedBy   = "Terraform"
    }
  }

  tag_specifications {
    resource_type = "network-interface"
    tags = {
      Name        = "${local.name_prefix}-ecs"
      Application = "Job Seeker Copilot"
      Environment = "public-beta"
      ManagedBy   = "Terraform"
    }
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_autoscaling_group" "ecs" {
  name_prefix = "${local.name_prefix}-ecs-"

  min_size         = local.node_count
  desired_capacity = local.node_count
  # The approved $750 alert budget cannot absorb an unreviewed second lean
  # node. HA is the explicit, cost-reviewed scale-out switch.
  max_size = local.node_count

  vpc_zone_identifier       = [for subnet in aws_subnet.private : subnet.id]
  health_check_type         = "EC2"
  health_check_grace_period = 300
  protect_from_scale_in     = true

  launch_template {
    id = aws_launch_template.ecs.id
    # Bind the ASG to an immutable numeric version. A literal "$Latest" does
    # not change when a new launch-template version is published, so Terraform
    # would have no version delta on which to start or roll back a refresh.
    version = aws_launch_template.ecs.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      # Keep the hard ASG node bound during host replacement. Lean refreshes
      # have a documented maintenance outage; HA refreshes drain and replace
      # one of two nodes at a time without a temporary third cost node.
      min_healthy_percentage       = var.high_availability ? 50 : 0
      max_healthy_percentage       = 100
      instance_warmup              = 300
      scale_in_protected_instances = "Refresh"
      standby_instances            = "Terminate"
      skip_matching                = true
      auto_rollback                = true
    }
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-ecs"
    propagate_at_launch = true
  }

  # The AWS provider intentionally does not apply `default_tags` to Auto
  # Scaling groups. These three explicit tags are therefore both a runtime
  # ownership boundary and a prerequisite of the bootstrap Apply policy.
  tag {
    key                 = "Application"
    value               = "Job Seeker Copilot"
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = "public-beta"
    propagate_at_launch = true
  }

  tag {
    key                 = "ManagedBy"
    value               = "Terraform"
    propagate_at_launch = true
  }

  lifecycle { create_before_destroy = true }

  depends_on = [
    aws_ecs_account_setting_default.awsvpc_trunking,
    aws_iam_role_policy_attachment.ecs_instance,
    aws_iam_role_policy_attachment.ecs_ssm,
  ]
}

resource "aws_ecs_capacity_provider" "ec2" {
  name = "${local.name_prefix}-ec2"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs.arn
    managed_termination_protection = "ENABLED"
    managed_draining               = "ENABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 1
      instance_warmup_period    = 300
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = [aws_ecs_capacity_provider.ec2.name]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ec2.name
    base              = 1
    weight            = 100
  }
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = local.namespace_name
  description = "Private service discovery for Job Seeker Copilot public beta"
  vpc         = aws_vpc.main.id

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_service_discovery_service" "service" {
  for_each = local.raw_services

  name = each.key

  # Do not add an empty health_check_custom_config block. AWS provider 6.55
  # does not materialise it, then proposes a ForceNew replacement forever.

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }

  tags = { Service = each.key }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_service_discovery_service" "clamav" {
  name = "clamav"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }

  tags = { Service = "clamav" }

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "task_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:*"]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each = local.raw_services

  name                 = "${local.name_prefix}-${each.key}-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "execution" {
  for_each = local.raw_services

  role       = aws_iam_role.execution[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ClamAV deliberately has an execution role only. With no task role and
# ECS_AWSVPC_BLOCK_IMDS enabled on every host, the upstream scanner cannot use
# Document Store's S3/KMS permissions or any EC2 instance credentials.
resource "aws_iam_role" "clamav_execution" {
  name                 = "${local.name_prefix}-clamav-execution"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

resource "aws_iam_role_policy_attachment" "clamav_execution" {
  role       = aws_iam_role.clamav_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

locals {
  service_secret_values = {
    for service_name, specifications in local.service_secret_specs : service_name => [
      for environment_name, specification in specifications : {
        name = environment_name
        valueFrom = "${(
          split(":", specification)[0] == "core" ? aws_secretsmanager_secret.core.arn :
          startswith(split(":", specification)[0], "database/") ? aws_secretsmanager_secret.database[trimprefix(split(":", specification)[0], "database/")].arn :
          aws_secretsmanager_secret.integration[trimprefix(split(":", specification)[0], "integration/")].arn
        )}:${split(":", specification)[1]}::"
      }
    ]
  }

  service_secret_arns = {
    for service_name, specifications in local.service_secret_specs : service_name => distinct([
      for _, specification in specifications : (
        split(":", specification)[0] == "core" ? aws_secretsmanager_secret.core.arn :
        startswith(split(":", specification)[0], "database/") ? aws_secretsmanager_secret.database[trimprefix(split(":", specification)[0], "database/")].arn :
        aws_secretsmanager_secret.integration[trimprefix(split(":", specification)[0], "integration/")].arn
      )
    ])
  }

  services_with_secrets = {
    for service_name, specifications in local.service_secret_specs :
    service_name => local.service_secret_arns[service_name]
    if length(specifications) > 0
  }
}

data "aws_iam_policy_document" "execution_secrets" {
  for_each = local.services_with_secrets

  statement {
    sid       = "ReadOnlyDeclaredRuntimeSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = each.value
  }

  statement {
    sid       = "DecryptRuntimeSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  for_each = local.services_with_secrets

  name   = "declared-runtime-secrets"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution_secrets[each.key].json
}

resource "aws_iam_role" "task" {
  for_each = local.raw_services

  name                 = "${local.name_prefix}-${each.key}-task"
  assume_role_policy   = data.aws_iam_policy_document.task_trust.json
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"
}

data "aws_iam_policy_document" "document_store" {
  statement {
    sid = "DocumentBucketMetadata"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.documents.arn]
  }

  statement {
    sid       = "ListExactPermanentErasureVersions"
    actions   = ["s3:ListBucketVersions"]
    resources = [aws_s3_bucket.documents.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "documents/*",
        "quarantine/application-uploads/*",
      ]
    }
  }

  statement {
    sid = "DocumentObjects"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.documents.arn}/documents/*",
      "${aws_s3_bucket.documents.arn}/quarantine/application-uploads/*",
    ]
  }

  statement {
    sid     = "DeleteExactPermanentErasureVersions"
    actions = ["s3:DeleteObjectVersion"]
    resources = [
      "${aws_s3_bucket.documents.arn}/documents/*",
      "${aws_s3_bucket.documents.arn}/quarantine/application-uploads/*",
    ]
  }

  statement {
    sid = "DocumentEncryption"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:ReEncryptFrom",
      "kms:ReEncryptTo",
    ]
    resources = [var.foundation_data_kms_key_arn]
  }

  statement {
    sid     = "WriteOnlyImmutableErasureJournalRecords"
    actions = ["s3:PutObject"]
    resources = [
      "arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}/permanent-erasures/v1/*",
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

    condition {
      test     = "Bool"
      variable = "s3:x-amz-server-side-encryption-bucket-key-enabled"
      values   = ["true"]
    }
  }

  statement {
    sid = "ReadOnlyBoundErasureJournalRecords"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = [
      "arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}/permanent-erasures/v1/*",
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

    # S3 Bucket Keys use the bucket ARN, rather than each object ARN, as the
    # KMS encryption context. The object permission above remains prefix-exact.
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["arn:aws:s3:::${var.foundation_erasure_journal_bucket_name}"]
    }
  }

}

resource "aws_iam_role_policy" "document_store" {
  name   = "document-object-storage"
  role   = aws_iam_role.task["document-store-service"].id
  policy = data.aws_iam_policy_document.document_store.json
}

data "aws_iam_policy_document" "account_email" {
  statement {
    sid     = "SendAccountEmail"
    effect  = "Allow"
    actions = ["ses:SendEmail"]
    resources = [
      "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:identity/${var.ses_identity_domain}",
      "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:configuration-set/${var.ses_configuration_set}",
    ]

    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.account_email_sender]
    }

    condition {
      test     = "StringEquals"
      variable = "ses:ApiVersion"
      values   = ["2010-12-01"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role_policy" "account_email" {
  count = var.enabled_integrations.account_email ? 1 : 0

  name   = "account-email"
  role   = aws_iam_role.task["authentication-service"].id
  policy = data.aws_iam_policy_document.account_email.json
}

data "aws_iam_policy_document" "ecs_exec" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }

  statement {
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.foundation_data_kms_key_arn]
  }

  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ecs_exec.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ecs_exec" {
  for_each = var.enable_ecs_exec ? local.raw_services : {}

  name   = "break-glass-ecs-exec"
  role   = aws_iam_role.task[each.key].id
  policy = data.aws_iam_policy_document.ecs_exec.json
}

resource "aws_ecs_task_definition" "service" {
  for_each = local.raw_services

  family                   = "${local.name_prefix}-${each.key}"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${aws_ecr_repository.image[each.key].repository_url}@${local.image_manifest.images[each.key].digest}"
      essential = true
      cpu       = each.value.cpu
      memory    = each.value.memory
      portMappings = [{
        name          = "http"
        containerPort = each.value.port
        hostPort      = each.value.port
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      environment            = [for key, value in local.service_environment[each.key] : { name = key, value = value }]
      secrets                = local.service_secret_values[each.key]
      user                   = each.key == "job-seeker-copilot-client" ? "1000:1000" : "10001:10001"
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
        command = each.key == "job-seeker-copilot-client" ? [
          "CMD-SHELL",
          "node -e \"require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))\"",
        ] : ["CMD-SHELL", "wget -q --spider http://127.0.0.1:${each.value.port}${each.value.healthPath} || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 90
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "service"
          mode                  = "non-blocking"
          max-buffer-size       = "25m"
        }
      }
      stopTimeout = 90
      ulimits = [{
        name      = "nofile"
        softLimit = 65536
        hardLimit = 65536
      }]
    }
  ])

  tags = {
    Service      = each.key
    ImageDigest  = local.image_manifest.images[each.key].digest
    SourceCommit = local.image_manifest.images[each.key].revision
  }

  depends_on = [
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy.document_store,
    aws_iam_role_policy.account_email,
  ]
}

resource "aws_ecs_task_definition" "clamav" {
  family                   = "${local.name_prefix}-clamav"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.clamav_execution.arn
  # Deliberately no application task role: the upstream scanner receives no
  # AWS API identity and cannot inherit the Document Store S3/KMS role.

  container_definitions = jsonencode([{
    name      = "clamav"
    image     = "${aws_ecr_repository.image["clamav"].repository_url}@${local.image_manifest.images.clamav.digest}"
    essential = true
    cpu       = 512
    # The official signatures require substantial native memory. This matches
    # the governed local ceiling and is included in the Terraform capacity
    # assertions for both lean and HA shapes.
    memory = 4096
    portMappings = [{
      name          = "clamd"
      containerPort = 3310
      hostPort      = 3310
      protocol      = "tcp"
    }]
    environment = [
      { name = "FRESHCLAM_CHECKS", value = "12" },
      { name = "FRESHCLAM_CONF_ConnectTimeout", value = "10" },
      { name = "FRESHCLAM_CONF_ReceiveTimeout", value = "30" },
      { name = "CLAMD_CONF_StreamMaxLength", value = "11M" },
      { name = "CLAMD_CONF_MaxFileSize", value = "11M" },
      { name = "CLAMD_CONF_MaxScanSize", value = "32M" },
      { name = "CLAMD_CONF_MaxScanTime", value = "30000" },
      { name = "CLAMD_CONF_MaxFiles", value = "512" },
      { name = "CLAMD_CONF_MaxRecursion", value = "16" },
      { name = "CLAMD_CONF_SelfCheck", value = "60" },
    ]
    # The upstream entrypoint needs a writable root layer. The preloaded
    # signature database remains on that disposable task layer so an empty
    # mount cannot hide it and force a full CDN download on every restart.
    # Socket/log/scratch paths are bounded task tmpfs owned by the image's
    # clamav user (uid 100/gid 101); no scanner filesystem is durable/restored.
    readonlyRootFilesystem = false
    linuxParameters = {
      initProcessEnabled = true
      tmpfs = [
        { containerPath = "/tmp", size = 64, mountOptions = ["rw", "noexec", "nosuid", "nodev", "uid=100", "gid=101", "mode=1770"] },
        { containerPath = "/var/log/clamav", size = 64, mountOptions = ["rw", "noexec", "nosuid", "nodev", "uid=100", "gid=101", "mode=0750"] },
        { containerPath = "/run/clamav", size = 16, mountOptions = ["rw", "noexec", "nosuid", "nodev", "uid=100", "gid=101", "mode=0750"] },
      ]
    }
    healthCheck = {
      command = [
        "CMD-SHELL",
        "set -eu; clamdcheck.sh; daemon=\"$(clamdscan --version)\"; disk=\"$(freshclam --version)\"; daemon_version=\"$(echo \"$daemon\" | cut -d/ -f2)\"; disk_version=\"$(echo \"$disk\" | cut -d/ -f2)\"; if [ \"$daemon_version\" != \"$disk_version\" ]; then clamdscan --reload >/dev/null 2>&1; exit 42; fi; signature=\"$${daemon#*/*/}\"; signature_epoch=\"$(date -u -D '%a %b %e %H:%M:%S %Y' -d \"$signature\" +%s)\"; now=\"$(date -u +%s)\"; test \"$((now - signature_epoch))\" -le 172800",
      ]
      interval = 30
      timeout  = 10
      retries  = 3
      # ECS rejects values above its API maximum of 300 seconds.
      startPeriod = 300
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.clamav.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "scanner"
        mode                  = "non-blocking"
        max-buffer-size       = "25m"
      }
    }
    stopTimeout = 90
  }])

  tags = {
    Service      = "clamav"
    ImageDigest  = local.image_manifest.images.clamav.digest
    SourceCommit = local.image_manifest.images.clamav.revision
    AwsApiAccess = "none"
  }

  depends_on = [aws_iam_role_policy_attachment.clamav_execution]
}

resource "aws_ecs_service" "clamav" {
  name            = "clamav"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.clamav.arn
  desired_count   = local.clamav_desired_count

  enable_ecs_managed_tags = true
  enable_execute_command  = false
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = true

  deployment_maximum_percent         = 100
  deployment_minimum_healthy_percent = 0
  # ECS requires deployment_maximum_percent > 100 when AZ rebalancing is
  # enabled. The reviewed cost envelope deliberately uses stop-first 100%, so
  # rebalancing must remain disabled rather than requesting extra task copies.
  availability_zone_rebalancing = "DISABLED"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ec2.name
    base              = 1
    weight            = 100
  }

  network_configuration {
    subnets          = [for subnet in aws_subnet.private : subnet.id]
    security_groups  = [aws_security_group.clamav.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.clamav.arn
  }

  tags = {
    Service      = "clamav"
    AwsApiAccess = "none"
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    terraform_data.release_contract,
    terraform_data.runtime_attestations,
  ]
}

resource "aws_ecs_service" "service" {
  for_each = local.raw_services

  name            = each.key
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.service[each.key].arn
  desired_count   = var.application_desired_count

  enable_ecs_managed_tags = true
  enable_execute_command  = var.enable_ecs_exec
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = true

  # Keep the deployment envelope schedulable even if HA autoscaling has
  # already raised a service to two tasks. A 200% rolling update would demand
  # four copies of each service and overrun the reviewed two-node shape.
  # Releases are deliberately stop-first/ordered in both shapes.
  deployment_maximum_percent         = 100
  deployment_minimum_healthy_percent = 0
  health_check_grace_period_seconds  = contains(["job-seeker-copilot-client", "stripe-gateway"], each.key) ? 120 : null
  availability_zone_rebalancing      = "DISABLED"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ec2.name
    base              = 1
    weight            = 100
  }

  network_configuration {
    subnets          = [for subnet in aws_subnet.private : subnet.id]
    security_groups  = [aws_security_group.service[each.key].id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.service[each.key].arn
  }

  dynamic "load_balancer" {
    for_each = each.key == "job-seeker-copilot-client" ? [aws_lb_target_group.frontend.arn] : []
    content {
      target_group_arn = load_balancer.value
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  dynamic "load_balancer" {
    for_each = each.key == "stripe-gateway" ? [aws_lb_target_group.stripe.arn] : []
    content {
      target_group_arn = load_balancer.value
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  tags = { Service = each.key }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_lb_listener_rule.dark_frontend_association,
    aws_lb_listener_rule.dark_stripe_association,
    aws_lb_listener.http,
    aws_lb_listener.https,
    terraform_data.release_contract,
    terraform_data.runtime_attestations,
  ]
}
