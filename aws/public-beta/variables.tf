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

variable "offline_validation" {
  description = "CI-only switch. Release plans must set this to false."
  type        = bool
  default     = false
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
  description = "Create and DNS-validate an ACM certificate for app_domain_name."
  type        = bool
  default     = true
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
    condition     = var.expanded_capacity_approval_reference == "" || length(trimspace(var.expanded_capacity_approval_reference)) >= 3
    error_message = "expanded_capacity_approval_reference must be empty or a meaningful reviewed evidence reference."
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
  type    = string
  default = "accounts@jobseekercopilot.com"
}

variable "ses_identity_domain" {
  description = "Existing verified SES identity owned by the landing/email stacks."
  type        = string
  default     = "jobseekercopilot.com"
}

variable "ses_configuration_set" {
  type    = string
  default = "JobSeekerCopilotAccountEmails"
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
