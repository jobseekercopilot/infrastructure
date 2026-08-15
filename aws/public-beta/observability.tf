data "aws_iam_policy_document" "notifications_key" {
  statement {
    sid       = "AccountKeyAdministration"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }
  }

  statement {
    sid = "EncryptOperationalNotifications"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    principals {
      type = "Service"
      identifiers = [
        "backup.amazonaws.com",
        "budgets.amazonaws.com",
        "cloudwatch.amazonaws.com",
        "costalerts.amazonaws.com",
        "sns.amazonaws.com",
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_kms_key" "notifications" {
  description             = "Job Seeker Copilot public-beta operational and cost notifications"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.notifications_key.json

  tags = {
    Name      = "${local.name_prefix}-notifications"
    DataClass = "operational"
  }
}

resource "aws_kms_alias" "notifications" {
  name          = "alias/${local.name_prefix}-notifications"
  target_key_id = aws_kms_key.notifications.key_id
}

resource "aws_sns_topic" "operations" {
  name              = "${local.name_prefix}-operations"
  kms_master_key_id = aws_kms_key.notifications.arn

  tags = { Purpose = "operational-and-cost-alerts" }
}

data "aws_iam_policy_document" "operations_topic" {
  statement {
    sid       = "OwnerAdministration"
    effect    = "Allow"
    actions   = ["sns:*"]
    resources = [aws_sns_topic.operations.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceOwner"
      values   = [var.aws_account_id]
    }
  }

  statement {
    sid       = "AwsAlertPublishers"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.operations.arn]

    principals {
      type = "Service"
      identifiers = [
        "backup.amazonaws.com",
        "budgets.amazonaws.com",
        "cloudwatch.amazonaws.com",
        "costalerts.amazonaws.com",
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sns_topic_policy" "operations" {
  arn    = aws_sns_topic.operations.arn
  policy = data.aws_iam_policy_document.operations_topic.json
}

resource "aws_sns_topic_subscription" "operations_email" {
  count = var.alarm_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-monthly-alert-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:CostCentre$public-beta"]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 50
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  depends_on = [aws_sns_topic_policy.operations]
}

resource "aws_ce_anomaly_monitor" "services" {
  name              = "${local.name_prefix}-aws-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "daily" {
  name             = "${local.name_prefix}-daily-cost-anomalies"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "SNS"
    address = aws_sns_topic.operations.arn
  }

  threshold_expression {
    and {
      dimension {
        key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
        match_options = ["GREATER_THAN_OR_EQUAL"]
        values        = ["20"]
      }
    }
  }

  depends_on = [aws_sns_topic_policy.operations]
}

locals {
  alarm_actions = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${local.name_prefix}-rds-connections-reserve"
  alarm_description   = "Normal and one-at-a-time replacement pools are approaching the 120-connection beta budget."
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 60
  statistic           = "Maximum"
  threshold           = 100
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${local.name_prefix}-rds-free-storage"
  alarm_description   = "RDS has less than 10 GiB free; investigate growth before autoscaling reaches its reviewed ceiling."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 300
  statistic           = "Minimum"
  threshold           = 10737418240
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_free_memory" {
  alarm_name          = "${local.name_prefix}-rds-free-memory"
  namespace           = "AWS/RDS"
  metric_name         = "FreeableMemory"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 536870912
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name_prefix}-rds-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.app.arn_suffix }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "frontend_unhealthy" {
  count = var.application_desired_count > 0 ? 1 : 0

  alarm_name  = "${local.name_prefix}-frontend-unhealthy"
  namespace   = "AWS/ApplicationELB"
  metric_name = "UnHealthyHostCount"
  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.frontend.arn_suffix
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "service_cpu" {
  for_each = local.raw_services

  alarm_name  = "${local.name_prefix}-${each.key}-cpu"
  namespace   = "AWS/ECS"
  metric_name = "CPUUtilization"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.service[each.key].name
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "service_memory" {
  for_each = local.raw_services

  alarm_name  = "${local.name_prefix}-${each.key}-memory"
  namespace   = "AWS/ECS"
  metric_name = "MemoryUtilization"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.service[each.key].name
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "clamav_cpu" {
  alarm_name  = "${local.name_prefix}-clamav-cpu"
  namespace   = "AWS/ECS"
  metric_name = "CPUUtilization"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.clamav.name
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "clamav_memory" {
  alarm_name  = "${local.name_prefix}-clamav-memory"
  namespace   = "AWS/ECS"
  metric_name = "MemoryUtilization"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.clamav.name
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "clamav_running" {
  count = var.application_desired_count > 0 ? 1 : 0

  alarm_name        = "${local.name_prefix}-clamav-running"
  alarm_description = "The isolated malware-scanner fleet is below its reviewed one-per-node count."
  namespace         = "ECS/ContainerInsights"
  metric_name       = "RunningTaskCount"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.clamav.name
  }
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 60
  statistic           = "Minimum"
  threshold           = local.clamav_desired_count
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "cluster_cpu_reservation" {
  alarm_name          = "${local.name_prefix}-cluster-cpu-reservation"
  namespace           = "AWS/ECS"
  metric_name         = "CPUReservation"
  dimensions          = { ClusterName = aws_ecs_cluster.main.name }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 300
  statistic           = "Maximum"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "cluster_memory_reservation" {
  alarm_name          = "${local.name_prefix}-cluster-memory-reservation"
  namespace           = "AWS/ECS"
  metric_name         = "MemoryReservation"
  dimensions          = { ClusterName = aws_ecs_cluster.main.name }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  period              = 300
  statistic           = "Maximum"
  threshold           = 85
  treat_missing_data  = var.application_desired_count == 0 ? "notBreaching" : "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_log_group" "vpc_flow" {
  name              = "/jsc/${var.environment}/vpc-flow-rejects"
  retention_in_days = var.log_retention_days
  tags              = { DataClass = "network-metadata" }
}

resource "aws_iam_role" "vpc_flow" {
  name = "${local.name_prefix}-vpc-flow"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.aws_account_id }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:ec2:${var.aws_region}:${var.aws_account_id}:vpc-flow-log/*"
        }
      }
    }]
  })
}

data "aws_iam_policy_document" "vpc_flow" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.vpc_flow.arn}:*"]
  }

  statement {
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "vpc_flow" {
  name   = "write-vpc-flow-rejects"
  role   = aws_iam_role.vpc_flow.id
  policy = data.aws_iam_policy_document.vpc_flow.json
}

resource "aws_flow_log" "rejected" {
  iam_role_arn             = aws_iam_role.vpc_flow.arn
  log_destination          = aws_cloudwatch_log_group.vpc_flow.arn
  log_destination_type     = "cloud-watch-logs"
  traffic_type             = "REJECT"
  vpc_id                   = aws_vpc.main.id
  max_aggregation_interval = 60

  depends_on = [aws_iam_role_policy.vpc_flow]
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name_prefix}-operations"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "RDS connection and capacity budget"
          region = var.aws_region
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.postgres.identifier],
            [".", "CPUUtilization", ".", "."],
            [".", "FreeStorageSpace", ".", ".", { yAxis = "right" }],
            [".", "FreeableMemory", ".", ".", { yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS reservations"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "CPUReservation", "ClusterName", aws_ecs_cluster.main.name],
            [".", "MemoryReservation", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          title  = "Public edge health"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", aws_lb.app.arn_suffix, { stat = "Sum" }],
            ["AWS/WAFV2", "BlockedRequests", "WebACL", aws_wafv2_web_acl.app.name, "Region", var.aws_region, "Rule", "ALL", { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}
