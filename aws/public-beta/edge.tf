resource "aws_acm_certificate" "app" {
  count = local.create_certificate ? 1 : 0

  domain_name       = var.app_domain_name
  validation_method = "DNS"

  options { certificate_transparency_logging_preference = "ENABLED" }

  tags = { Name = var.app_domain_name }

  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = local.create_certificate ? {
    for option in aws_acm_certificate.app[0].domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  } : {}

  zone_id = var.route53_hosted_zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "app" {
  count = local.create_certificate ? 1 : 0

  certificate_arn         = aws_acm_certificate.app[0].arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

resource "aws_lb" "app" {
  name = "${local.name_prefix}-app"

  internal                         = false
  load_balancer_type               = "application"
  security_groups                  = [aws_security_group.alb.id]
  subnets                          = [for subnet in aws_subnet.public : subnet.id]
  enable_deletion_protection       = true
  enable_http2                     = true
  drop_invalid_header_fields       = true
  preserve_host_header             = false
  desync_mitigation_mode           = "strictest"
  idle_timeout                     = 60
  enable_cross_zone_load_balancing = true

  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "alb"
    enabled = true
  }

  tags = {
    Name        = "${local.name_prefix}-app"
    DataClass   = "public-request-metadata"
    BetaBlocker = "true"
  }

  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_lb_target_group" "frontend" {
  name_prefix = "jscweb"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 60
  slow_start           = 30

  health_check {
    enabled             = true
    path                = "/api/runtime/legal-configuration"
    protocol            = "HTTP"
    port                = "traffic-port"
    matcher             = "200-399"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Service = "job-seeker-copilot-client" }

  lifecycle { create_before_destroy = true }
}

resource "aws_lb_target_group" "stripe" {
  name_prefix = "jscpay"
  port        = 8100
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/actuator/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    matcher             = "200-399"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Service = "stripe-gateway" }

  lifecycle { create_before_destroy = true }
}

# ECS requires every target group named on CreateService to already be
# associated with a load balancer, including when desired_count is zero. Keep
# that control-plane association separate from the public listeners so the
# dark foundation can create both services without making either route public.
#
# The ALB security group intentionally has no ingress for this listener port.
# The TEST-NET-1 source conditions provide a second fail-closed boundary if a
# later security-group edit is proposed accidentally. Listener/rule resources
# do not add an hourly charge to the already-reviewed ALB shape, and retaining
# them across activation/darkening prevents an association ordering race.
resource "aws_lb_listener" "dark_target_group_association" {
  load_balancer_arn = aws_lb.app.arn
  port              = 65535
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Not a public listener."
      status_code  = "503"
    }
  }
}

resource "aws_lb_listener_rule" "dark_frontend_association" {
  listener_arn = aws_lb_listener.dark_target_group_association.arn
  priority     = 49998

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    source_ip { values = ["192.0.2.0/24"] }
  }

  condition {
    host_header { values = ["frontend.dark-association.invalid"] }
  }
}

resource "aws_lb_listener_rule" "dark_stripe_association" {
  listener_arn = aws_lb_listener.dark_target_group_association.arn
  priority     = 49999

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.stripe.arn
  }

  condition {
    source_ip { values = ["192.0.2.0/24"] }
  }

  condition {
    host_header { values = ["stripe.dark-association.invalid"] }
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.has_tls_configuration ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = local.has_tls_configuration ? [] : [1]
    content {
      type = "fixed-response"
      fixed_response {
        content_type = "text/plain"
        message_body = "Job Seeker Copilot is not active."
        status_code  = "503"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.has_tls_configuration ? 1 : 0

  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = local.effective_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  dynamic "default_action" {
    for_each = var.public_entrypoint_enabled ? [1] : []
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.frontend.arn
    }
  }

  dynamic "default_action" {
    for_each = var.public_entrypoint_enabled ? [] : [1]
    content {
      type = "fixed-response"
      fixed_response {
        content_type = "text/plain"
        message_body = "Job Seeker Copilot is preparing for public beta."
        status_code  = "503"
      }
    }
  }

  depends_on = [aws_acm_certificate_validation.app]
}

resource "aws_lb_listener_rule" "stripe_webhook" {
  count = local.has_tls_configuration && var.public_entrypoint_enabled && var.enabled_integrations.stripe ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.stripe.arn
  }

  condition {
    path_pattern { values = ["/api/v1/stripe/webhook"] }
  }

  condition {
    http_request_method { values = ["POST"] }
  }
}

resource "aws_route53_record" "app" {
  count = local.has_domain ? 1 : 0

  zone_id = var.route53_hosted_zone_id
  name    = var.app_domain_name
  type    = "A"

  alias {
    name                   = aws_lb.app.dns_name
    zone_id                = aws_lb.app.zone_id
    evaluate_target_health = true
  }
}

resource "aws_wafv2_regex_pattern_set" "authenticated_document_uploads" {
  # Keep the existing Terraform address and AWS name stable. In addition to the
  # two document uploads, this set carries the exact authenticated saved-job
  # POST whose reviewed 64 KiB BFF limit exceeds WAF's inspected-body limit.
  name  = "${local.name_prefix}-authenticated-document-uploads"
  scope = "REGIONAL"

  regular_expression {
    regex_string = "^/api/v1/document-generation/applications/[0-9a-fA-F-]{36}/document-uploads$"
  }

  regular_expression {
    regex_string = "^/api/v1/document-generation/applications/[0-9a-fA-F-]{36}/replace$"
  }

  regular_expression {
    regex_string = "^/api/jobs/saved$"
  }

  tags = { Purpose = "narrow-waf-body-size-exception" }
}

resource "aws_wafv2_web_acl" "app" {
  name  = "${local.name_prefix}-app"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common-rule-set"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        scope_down_statement {
          not_statement {
            statement {
              and_statement {
                statement {
                  regex_pattern_set_reference_statement {
                    arn = aws_wafv2_regex_pattern_set.authenticated_document_uploads.arn

                    field_to_match {
                      uri_path {}
                    }

                    text_transformation {
                      priority = 0
                      type     = "NONE"
                    }
                  }
                }

                statement {
                  byte_match_statement {
                    positional_constraint = "EXACTLY"
                    search_string         = "POST"

                    field_to_match {
                      method {}
                    }

                    text_transformation {
                      priority = 0
                      type     = "NONE"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-common-rules"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "aws-common-rule-set-document-uploads"
    priority = 15

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }

        scope_down_statement {
          and_statement {
            statement {
              regex_pattern_set_reference_statement {
                arn = aws_wafv2_regex_pattern_set.authenticated_document_uploads.arn

                field_to_match {
                  uri_path {}
                }

                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }

            statement {
              byte_match_statement {
                positional_constraint = "EXACTLY"
                search_string         = "POST"

                field_to_match {
                  method {}
                }

                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-common-rules-document-uploads"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-bad-inputs"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "per-ip-rate-limit"
    priority = 30

    action {
      block {}
    }

    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.waf_rate_limit_per_five_minutes
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-rate-limit"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-web-acl"
    sampled_requests_enabled   = false
  }

  tags = { Name = "${local.name_prefix}-app" }
}

resource "aws_wafv2_web_acl_association" "app" {
  resource_arn = aws_lb.app.arn
  web_acl_arn  = aws_wafv2_web_acl.app.arn
}
