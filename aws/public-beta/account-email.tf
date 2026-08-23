locals {
  account_email_event_types = toset([
    "BOUNCE",
    "COMPLAINT",
    "DELIVERY",
    "DELIVERY_DELAY",
    "REJECT",
    "SEND",
  ])
}

# The landing stack owns the shared domain identity and DKIM records. This
# application release unit owns only its purpose-specific configuration set and
# event destination. Keeping the resource independent of the runtime switch
# prevents disabling account email from destroying its monitoring history.
resource "aws_sesv2_configuration_set" "account_email" {
  configuration_set_name = var.ses_configuration_set

  reputation_options {
    reputation_metrics_enabled = true
  }

  sending_options {
    sending_enabled = true
  }

  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }

  tags = {
    Purpose   = "account-email-delivery"
    DataClass = "operational"
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [terraform_data.release_contract]
}

# The retained bootstrap operations topic is the single operator-owned alert
# destination. Its topic and KMS key policies grant only this exact
# configuration set permission to publish; no recipient is configured here.
resource "aws_sesv2_configuration_set_event_destination" "account_email" {
  configuration_set_name = aws_sesv2_configuration_set.account_email.configuration_set_name
  event_destination_name = "account-email-events"

  event_destination {
    enabled              = true
    matching_event_types = local.account_email_event_types

    sns_destination {
      topic_arn = var.foundation_operations_topic_arn
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
