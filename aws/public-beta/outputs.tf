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
    backup_vault_arn    = aws_backup_vault.customer_data.arn
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
  value = aws_sns_topic.operations.arn
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
