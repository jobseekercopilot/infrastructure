output "release_contract" {
  description = "Non-secret identifiers consumed by the protected release workflow."
  value = {
    region                                 = var.aws_region
    environment                            = var.environment
    release_id                             = local.image_manifest.releaseId
    release_attestation_id                 = local.release_attestation_id
    cluster_arn                            = aws_ecs_cluster.main.arn
    cluster_name                           = aws_ecs_cluster.main.name
    private_subnet_ids                     = [for subnet in aws_subnet.private : subnet.id]
    release_operator_security_group        = aws_security_group.operator.id
    database_bootstrap_task_definition     = aws_ecs_task_definition.database_bootstrap.arn
    migration_verification_task_definition = aws_ecs_task_definition.migration_verification.arn
    release_preflight_task_definition      = aws_ecs_task_definition.release_preflight.arn
    database_identifier                    = aws_db_instance.postgres.identifier
    rds_monitoring_role_arn                = aws_iam_role.rds_monitoring.arn
    database_bootstrap_marker              = "/jsc/${var.environment}/release/database-bootstrap"
    release_preflight_marker               = "/jsc/${var.environment}/release/preflight"
  }
}

output "public_endpoint" {
  value = {
    alb_dns_name = aws_lb.app.dns_name
    domain_name  = var.app_domain_name
    activated    = var.public_entrypoint_enabled
  }
}

output "emergency_darken_contract" {
  description = "Non-secret applied resource identifiers for approval-independent public containment."
  value = {
    aws_account_id = var.aws_account_id
    cluster_name   = aws_ecs_cluster.main.name
    service_names = sort(concat(
      [for service in values(aws_ecs_service.service) : service.name],
      [aws_ecs_service.clamav.name],
    ))
    https_listener_arn      = try(aws_lb_listener.https[0].arn, "")
    stripe_webhook_rule_arn = try(aws_lb_listener_rule.stripe_webhook[0].arn, "")
  }
}

output "data_recovery" {
  value = {
    document_bucket_arn = aws_s3_bucket.documents.arn
    postgres_arn        = aws_db_instance.postgres.arn
    backup_vault_arn    = "arn:aws:backup:${var.aws_region}:${var.aws_account_id}:backup-vault:jsc-public-beta-customer-data"
    restore_role_arn    = aws_iam_role.backup_restore.arn
  }
}

output "release_image_repositories" {
  value = {
    for name, repository in aws_ecr_repository.image : name => repository.repository_url
  }
}

output "runtime_secret_arns" {
  description = "Secret containers only; Terraform never stores their secret versions."
  value = {
    core         = aws_secretsmanager_secret.core.arn
    databases    = { for name, secret in aws_secretsmanager_secret.database : name => secret.arn }
    integrations = { for name, secret in aws_secretsmanager_secret.integration : name => secret.arn }
  }
}

output "operations_topic_arn" {
  value = var.foundation_operations_topic_arn
}

output "account_email_delivery" {
  description = "Non-secret, applied SES contract checked after foundation and before private/public service starts."
  value = {
    aws_account_id       = var.aws_account_id
    identity_domain      = var.ses_identity_domain
    sender               = var.account_email_sender
    configuration_set    = aws_sesv2_configuration_set.account_email.configuration_set_name
    event_destination    = aws_sesv2_configuration_set_event_destination.account_email.event_destination_name
    event_types          = sort(tolist(local.account_email_event_types))
    operations_topic_arn = var.foundation_operations_topic_arn
  }
}

output "monthly_alert_budget_usd" {
  description = "Retained foundation alert threshold; AWS Budgets does not enforce a hard spending cap."
  value       = var.foundation_monthly_alert_budget_usd
}

output "permanent_erasure_journal_contract" {
  description = "Non-secret retained erasure-journal foundation contract used by Document Store and isolated restore replay."
  value = {
    bucket_name     = var.foundation_erasure_journal_bucket_name
    kms_key_arn     = var.foundation_erasure_journal_kms_key_arn
    object_prefix   = "permanent-erasures/v1/"
    retention_days  = var.foundation_erasure_journal_retention_days
    backup_selected = false
  }
}

output "capacity_contract" {
  value = {
    node_count                       = local.node_count
    instance_type                    = var.instance_type
    application_service_count        = length(local.raw_services)
    clamav_desired_count             = local.clamav_desired_count
    deployment_copy_multiplier       = local.deployment_copy_multiplier
    reserved_cpu_units               = local.release_reserved_cpu
    reserved_memory_mib              = local.release_reserved_memory
    task_slots                       = local.release_task_slots
    steady_state_reserved_cpu_units  = local.steady_state_reserved_cpu
    steady_state_reserved_memory_mib = local.steady_state_reserved_memory
    steady_state_task_slots          = local.steady_state_task_slots
    db_connections_budget            = local.db_connection_budget
    monthly_alert_budget_usd         = var.monthly_budget_usd
  }
}
