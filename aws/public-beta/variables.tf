variable "aws_region" {
  description = "The only approved public-beta region."
  type        = string
  default     = "eu-west-2"

  validation {
    condition     = var.aws_region == "eu-west-2"
    error_message = "The public beta is approved only for eu-west-2 (London)."
  }
}

variable "environment" {
  type    = string
  default = "public-beta"

  validation {
    condition     = var.environment == "public-beta"
    error_message = "This root module is deliberately limited to public-beta."
  }
}

variable "aws_account_id" {
  description = "Target AWS account ID. The zero value permits account-free validation only."
  type        = string
  default     = "000000000000"

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "foundation_data_kms_key_arn" {
  description = "ApplicationDataKeyArn from the reviewed manual bootstrap stack; routine Terraform cannot create, retag or delete this key."
  type        = string
  default     = "arn:aws:kms:eu-west-2:000000000000:key/00000000-0000-0000-0000-000000000000"

  validation {
    condition     = can(regex("^arn:aws:kms:eu-west-2:[0-9]{12}:key/[0-9a-f-]{36}$", var.foundation_data_kms_key_arn))
    error_message = "foundation_data_kms_key_arn must be the exact eu-west-2 bootstrap KMS key ARN."
  }
}

variable "foundation_operations_topic_arn" {
  description = "OperationsTopicArn from the reviewed manual bootstrap stack; alarms publish to this exact retained topic."
  type        = string
  default     = "arn:aws:sns:eu-west-2:000000000000:jsc-public-beta-operations"

  validation {
    condition     = can(regex("^arn:aws:sns:eu-west-2:[0-9]{12}:jsc-public-beta-operations$", var.foundation_operations_topic_arn))
    error_message = "foundation_operations_topic_arn must be the exact eu-west-2 public-beta bootstrap topic ARN."
  }
}

variable "foundation_backup_plan_id" {
  description = "CustomerDataBackupPlanId from the reviewed manual bootstrap stack. Terraform may create only a selection on this exact plan."
  type        = string
  default     = "00000000-0000-0000-0000-000000000000"

  validation {
    condition     = can(regex("^[0-9a-f-]{36}$", var.foundation_backup_plan_id))
    error_message = "foundation_backup_plan_id must be the exact bootstrap AWS Backup plan ID."
  }
}

variable "foundation_erasure_journal_kms_key_arn" {
  description = "ErasureJournalKeyArn from the manual bootstrap; isolated from the customer-data key and inaccessible to routine Terraform control-plane mutation."
  type        = string
  default     = "arn:aws:kms:eu-west-2:000000000000:key/11111111-1111-1111-1111-111111111111"

  validation {
    condition     = can(regex("^arn:aws:kms:eu-west-2:[0-9]{12}:key/[0-9a-f-]{36}$", var.foundation_erasure_journal_kms_key_arn))
    error_message = "foundation_erasure_journal_kms_key_arn must be the exact eu-west-2 bootstrap journal KMS key ARN."
  }
}

variable "foundation_erasure_journal_bucket_name" {
  description = "ErasureJournalBucketName from the manual bootstrap; this retained/versioned bucket is outside the customer-data AWS Backup selection."
  type        = string
  default     = "jsc-public-beta-erasure-journal-000000000000"

  validation {
    condition     = can(regex("^jsc-public-beta-erasure-journal-[0-9]{12}$", var.foundation_erasure_journal_bucket_name))
    error_message = "foundation_erasure_journal_bucket_name must be the exact account-scoped bootstrap bucket name."
  }
}

variable "foundation_erasure_journal_retention_days" {
  description = "ErasureJournalRetentionDays from the manual bootstrap; must match reviewed privacy/recovery evidence and exceed the 35-day backup maximum."
  type        = number
  default     = 90

  validation {
    condition     = floor(var.foundation_erasure_journal_retention_days) == var.foundation_erasure_journal_retention_days && var.foundation_erasure_journal_retention_days >= 36 && var.foundation_erasure_journal_retention_days <= 400
    error_message = "foundation_erasure_journal_retention_days must be a whole number from 36 through 400."
  }
}

variable "foundation_approved_ecs_ami_id" {
  description = "ApprovedEcsAmiId from the manual bootstrap. Apply can launch only resources sourced from this reviewed AMI through the tagged ECS launch template."
  type        = string
  default     = "ami-00000000000000000"

  validation {
    condition     = can(regex("^ami-[0-9a-f]{17}$", var.foundation_approved_ecs_ami_id))
    error_message = "foundation_approved_ecs_ami_id must be an exact AMI ID."
  }
}

variable "foundation_monthly_alert_budget_usd" {
  description = "MonthlyAlertBudgetUsd from the manual bootstrap. The routine Terraform stack cannot create, update or delete this account-billing control."
  type        = number
  default     = 750

  validation {
    condition     = floor(var.foundation_monthly_alert_budget_usd) == var.foundation_monthly_alert_budget_usd && var.foundation_monthly_alert_budget_usd >= 100 && var.foundation_monthly_alert_budget_usd <= 750
    error_message = "foundation_monthly_alert_budget_usd must be the reviewed whole-dollar bootstrap alert ceiling from 100 through 750."
  }
}

variable "offline_validation" {
  description = "Account-free test-harness switch. It is accepted only from a disposable backend-free module copy under /tmp; protected release plans force false."
  type        = bool
  default     = false
}

variable "offline_activation_validation" {
  description = "Account-free test harness only: allow one desired task per service and the synthetic public-listener topology without provider refresh."
  type        = bool
  default     = false

  validation {
    condition     = !var.offline_activation_validation || var.offline_validation
    error_message = "offline_activation_validation is valid only with offline_validation=true."
  }
}

variable "image_manifest_path" {
  description = "Path relative to this module, or an absolute path, to the immutable release image manifest."
  type        = string
  default     = "config/image-manifest.json"
}

variable "approval_manifest_path" {
  description = "Path relative to this module, or an absolute path, to reviewed integration approvals."
  type        = string
  default     = "config/launch-approvals.json"
}

variable "application_desired_count" {
  description = "Zero creates dark infrastructure; one starts the private application fleet."
  type        = number
  default     = 0

  validation {
    condition     = contains([0, 1], var.application_desired_count)
    error_message = "The beta baseline permits an application desired count of only zero or one."
  }
}

variable "public_entrypoint_enabled" {
  description = "False makes HTTPS return a fixed maintenance response instead of forwarding to the app."
  type        = bool
  default     = false
}

variable "enabled_integrations" {
  description = "External calls are independently fail-closed. Approval metadata is additionally required."
  type = object({
    postcodes_gb    = bool
    postcodes_ni    = bool
    reed            = bool
    adzuna          = bool
    jsearch         = bool
    nhs_jobs        = bool
    apprenticeships = bool
    google_maps     = bool
    openai          = bool
    stripe          = bool
    account_email   = bool
  })
  default = {
    postcodes_gb    = false
    postcodes_ni    = false
    reed            = false
    adzuna          = false
    jsearch         = false
    nhs_jobs        = false
    apprenticeships = false
    google_maps     = false
    openai          = false
    stripe          = false
    account_email   = false
  }
}

variable "app_domain_name" {
  description = "For example app.jobseekercopilot.com. Empty keeps DNS and TLS unconfigured."
  type        = string
  default     = ""

  validation {
    condition     = var.app_domain_name == "" || can(regex("^[a-z0-9.-]+[.][a-z]{2,}$", var.app_domain_name))
    error_message = "app_domain_name must be empty or a lower-case DNS name."
  }
}

variable "route53_hosted_zone_id" {
  description = "Existing public hosted zone shared with the separately managed landing stack."
  type        = string
  default     = ""
}

variable "manage_certificate" {
  description = "Reserved compatibility switch. Public beta requires a separately reviewed existing ACM certificate because safe certificate deletion cannot be tag-scoped in IAM."
  type        = bool
  default     = false

  validation {
    condition     = !var.manage_certificate
    error_message = "Terraform-managed ACM is disabled: supply existing_certificate_arn from the reviewed certificate process."
  }
}

variable "existing_certificate_arn" {
  description = "Optional externally managed eu-west-2 ACM certificate ARN."
  type        = string
  default     = ""
}

variable "instance_type" {
  description = "Measured public-beta baseline from the capacity decision."
  type        = string
  default     = "m7i.2xlarge"

  validation {
    condition     = contains(["m7i.2xlarge", "m7i.4xlarge"], var.instance_type)
    error_message = "Use the measured m7i.2xlarge baseline or an explicitly larger approved shape."
  }
}

variable "ecs_ami_id" {
  description = "Pinned eu-west-2 Amazon Linux 2023 ECS-optimised AMI ID. Resolve and review immediately before a release plan."
  type        = string
  default     = "ami-00000000000000000"

  validation {
    condition     = can(regex("^ami-[0-9a-f]{17}$", var.ecs_ami_id))
    error_message = "ecs_ami_id must be a full 17-character EC2 AMI ID."
  }
}

variable "high_availability" {
  description = "Two ECS nodes, one NAT per AZ and Multi-AZ RDS. False is the approved lean beta topology."
  type        = bool
  default     = false
}

variable "availability_zones" {
  description = "Pinned London AZ names; do not discover account state during an offline plan."
  type        = list(string)
  default     = ["eu-west-2a", "eu-west-2b"]

  validation {
    condition = (
      length(var.availability_zones) == 2 &&
      length(distinct(var.availability_zones)) == 2 &&
      alltrue([for zone in var.availability_zones : startswith(zone, "eu-west-2")])
    )
    error_message = "Exactly two distinct eu-west-2 availability zones are required."
  }
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"

  validation {
    condition     = var.db_instance_class == "db.t4g.medium"
    error_message = "The reviewed public-beta database class is db.t4g.medium; a larger class requires a reviewed code change and cost model."
  }
}

variable "db_allocated_storage_gib" {
  type    = number
  default = 50

  validation {
    condition     = var.db_allocated_storage_gib >= 20 && var.db_allocated_storage_gib <= 200
    error_message = "Initial PostgreSQL storage must be between 20 and 200 GiB."
  }
}

variable "db_backup_retention_days" {
  type    = number
  default = 14

  validation {
    condition     = var.db_backup_retention_days >= 7 && var.db_backup_retention_days <= 35
    error_message = "Public-beta RDS backup retention must be 7-35 days."
  }
}

variable "monthly_budget_usd" {
  description = "Alerting threshold for this beta stack, not an AWS hard spending cap."
  type        = number
  default     = 750

  validation {
    condition     = var.monthly_budget_usd >= 100 && var.monthly_budget_usd <= 5000
    error_message = "The monthly AWS alert budget must remain between USD 100 and 5,000; expanded shapes are separately gated."
  }
}

variable "expanded_capacity_approval_reference" {
  description = "Dated calculator/cost approval required for HA, a larger EC2 shape, storage above 50 GiB or an alert ceiling above USD 750."
  type        = string
  default     = ""

  validation {
    condition     = var.expanded_capacity_approval_reference == "" || length(trimspace(var.expanded_capacity_approval_reference)) >= 8
    error_message = "expanded_capacity_approval_reference must be empty or a substantive reviewed evidence reference of at least eight characters."
  }
}

variable "alarm_email" {
  description = "Operator mailbox for alarms and cost notices. Subscription requires email confirmation."
  type        = string
  default     = ""

  validation {
    condition     = var.alarm_email == "" || can(regex("^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$", var.alarm_email))
    error_message = "alarm_email must be empty or a valid email address."
  }
}

variable "application_base_url" {
  description = "Public application origin used in email and payment redirects."
  type        = string
  default     = "https://app.jobseekercopilot.com"

  validation {
    condition     = can(regex("^https://[a-z0-9.-]+$", var.application_base_url))
    error_message = "application_base_url must be a lower-case HTTPS origin without credentials, port, path, query or fragment."
  }
}

variable "account_email_sender" {
  description = "Exact verified From address for Authentication Service account-security email."
  type        = string
  default     = "accounts@jobseekercopilot.com"

  validation {
    condition     = var.account_email_sender == "accounts@jobseekercopilot.com"
    error_message = "The public-beta account-email sender must remain accounts@jobseekercopilot.com."
  }
}

variable "ses_identity_domain" {
  description = "Existing verified SES domain identity and DKIM contract owned by the landing email stack."
  type        = string
  default     = "jobseekercopilot.com"

  validation {
    condition     = var.ses_identity_domain == "jobseekercopilot.com"
    error_message = "The public-beta account-email identity must remain jobseekercopilot.com."
  }
}

variable "ses_configuration_set" {
  description = "Terraform-owned, purpose-specific Authentication Service SES configuration set."
  type        = string
  default     = "JobSeekerCopilotAccountEmails"

  validation {
    condition     = var.ses_configuration_set == "JobSeekerCopilotAccountEmails"
    error_message = "The public-beta account-email configuration set must remain JobSeekerCopilotAccountEmails."
  }
}

variable "google_maximum_sessions" {
  description = "In-process session-store bound. GCP API quotas remain a separate launch prerequisite."
  type        = number
  default     = 1000

  validation {
    condition     = var.google_maximum_sessions >= 100 && var.google_maximum_sessions <= 10000
    error_message = "Google session storage must remain between 100 and 10,000 entries."
  }
}

variable "google_maximum_destinations" {
  type    = number
  default = 5

  validation {
    condition     = var.google_maximum_destinations >= 1 && var.google_maximum_destinations <= 5
    error_message = "Google route matrices are capped at five destinations per request."
  }
}

variable "waf_rate_limit_per_five_minutes" {
  type    = number
  default = 1000

  validation {
    condition     = var.waf_rate_limit_per_five_minutes >= 100 && var.waf_rate_limit_per_five_minutes <= 10000
    error_message = "WAF rate limit must remain between 100 and 10,000 requests per five minutes per IP."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = contains([30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch-supported value of at least 30 days."
  }
}

variable "enable_ecs_exec" {
  description = "Break-glass only. Leave false until an approved, audited operator session is required."
  type        = bool
  default     = false
}

variable "additional_tags" {
  type    = map(string)
  default = {}
}
