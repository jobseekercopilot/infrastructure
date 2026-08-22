locals {
  alarm_actions = [var.foundation_operations_topic_arn]
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
  kms_key_id        = var.foundation_data_kms_key_arn
  tags              = { DataClass = "network-metadata" }
}

resource "aws_iam_role" "vpc_flow" {
  name                 = "${local.name_prefix}-vpc-flow"
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/jsc-public-beta-workload-boundary"

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
