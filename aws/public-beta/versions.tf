terraform {
  required_version = "= 1.15.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.55.0"
    }
  }

}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.offline_validation ? null : [var.aws_account_id]

  # The account-free CI plan uses explicit dummy credentials and these flags.
  # Release workflows must leave offline_validation=false.
  skip_credentials_validation = var.offline_validation
  skip_metadata_api_check     = var.offline_validation
  skip_requesting_account_id  = var.offline_validation

  default_tags {
    tags = merge(var.additional_tags, {
      Application = "Job Seeker Copilot"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Repository  = "jobseekercopilot/infrastructure"
      CostCentre  = "public-beta"
    })
  }
}
