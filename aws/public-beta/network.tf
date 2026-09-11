locals {
  zones = {
    a = {
      name         = var.availability_zones[0]
      public_cidr  = "10.42.0.0/24"
      private_cidr = "10.42.16.0/20"
      data_cidr    = "10.42.240.0/24"
    }
    b = {
      name         = var.availability_zones[1]
      public_cidr  = "10.42.1.0/24"
      private_cidr = "10.42.32.0/20"
      data_cidr    = "10.42.241.0/24"
    }
  }

  service_public_https_egress = toset(compact([
    var.enabled_integrations.postcodes_gb ? "postcode-io-gateway" : "",
    var.enabled_integrations.google_maps ? "google-maps-gateway" : "",
    var.enabled_integrations.reed ? "reed-gateway" : "",
    var.enabled_integrations.adzuna ? "adzuna-gateway" : "",
    var.enabled_integrations.jsearch ? "jsearch-gateway" : "",
    var.enabled_integrations.nhs_jobs ? "nhs-jobs-gateway" : "",
    var.enabled_integrations.apprenticeships ? "apprenticeships-gateway" : "",
    var.enabled_integrations.bedrock ? "llm-gateway" : "",
    var.enabled_integrations.stripe ? "stripe-gateway" : "",
    var.enabled_integrations.account_email ? "authentication-service" : "",
  ]))
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name    = "${local.name_prefix}-vpc"
    Network = "public-beta"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.name
  cidr_block              = each.value.public_cidr
  map_public_ip_on_launch = false

  tags = {
    Name    = "${local.name_prefix}-public-${each.key}"
    Tier    = "public"
    Network = "load-balancer-and-nat"
  }
}

resource "aws_subnet" "private" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.name
  cidr_block              = each.value.private_cidr
  map_public_ip_on_launch = false

  tags = {
    Name    = "${local.name_prefix}-private-${each.key}"
    Tier    = "private"
    Network = "ecs"
  }
}

resource "aws_subnet" "data" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.name
  cidr_block              = each.value.data_cidr
  map_public_ip_on_launch = false

  tags = {
    Name    = "${local.name_prefix}-data-${each.key}"
    Tier    = "isolated"
    Network = "rds"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name_prefix}-public" }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  for_each = var.high_availability ? local.zones : { a = local.zones.a }

  domain = "vpc"
  tags   = { Name = "${local.name_prefix}-nat-${each.key}" }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  for_each = aws_eip.nat

  allocation_id = each.value.id
  subnet_id     = aws_subnet.public[each.key].id

  tags = { Name = "${local.name_prefix}-nat-${each.key}" }

  depends_on = [aws_route_table_association.public]
}

resource "aws_route_table" "private" {
  for_each = local.zones

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[var.high_availability ? each.key : "a"].id
  }

  tags = { Name = "${local.name_prefix}-private-${each.key}" }
}

resource "aws_route_table_association" "private" {
  for_each = local.zones

  subnet_id      = aws_subnet.private[each.key].id
  route_table_id = aws_route_table.private[each.key].id
}

resource "aws_route_table" "data" {
  for_each = local.zones

  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-isolated-${each.key}" }
}

resource "aws_route_table_association" "data" {
  for_each = local.zones

  subnet_id      = aws_subnet.data[each.key].id
  route_table_id = aws_route_table.data[each.key].id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for route_table in aws_route_table.private : route_table.id]

  tags = { Name = "${local.name_prefix}-s3" }
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.name_prefix}-alb-"
  description = "Public TLS and redirect ingress to the application load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP redirect or dark maintenance response"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Public HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-alb" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "ecs_hosts" {
  name_prefix = "${local.name_prefix}-ecs-hosts-"
  description = "ECS container instances; outbound control-plane access only"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "ECS, ECR, SSM and CloudWatch HTTPS control-plane access"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "VPC DNS over UDP"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["${cidrhost(aws_vpc.main.cidr_block, 2)}/32"]
  }

  egress {
    description = "VPC DNS over TCP"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["${cidrhost(aws_vpc.main.cidr_block, 2)}/32"]
  }

  tags = { Name = "${local.name_prefix}-ecs-hosts" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "service" {
  for_each = local.raw_services

  name_prefix = "${local.name_prefix}-${each.key}-"
  description = "Least-privilege awsvpc task boundary for ${each.key}"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-${each.key}"
    Service = each.key
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "operator" {
  name_prefix = "${local.name_prefix}-release-operator-"
  description = "One-shot database bootstrap and private health preflight"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-release-operator" }

  lifecycle { create_before_destroy = true }
}

# The protected restore-source task is the only release one-shot that must
# reach both S3 and SSM. Keep that HTTPS path off the shared operator SG; the
# task still reaches only the production DB SG on PostgreSQL and has no ingress.
resource "aws_security_group" "restore_source_canary" {
  name_prefix = "${local.name_prefix}-restore-source-"
  description = "No-ingress network boundary for protected restore-source canary preparation"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-restore-source-canary"
    Purpose = "RestoreSourceCanary"
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "restore_source_canary_https" {
  security_group_id = aws_security_group.restore_source_canary.id
  description       = "S3 gateway and regional SSM API HTTPS"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "restore_source_canary_dns_udp" {
  security_group_id = aws_security_group.restore_source_canary.id
  description       = "VPC DNS over UDP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "restore_source_canary_dns_tcp" {
  security_group_id = aws_security_group.restore_source_canary.id
  description       = "VPC DNS over TCP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "restore_source_canary_database" {
  security_group_id            = aws_security_group.restore_source_canary.id
  description                  = "TLS PostgreSQL source-canary preparation"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.database.id
}

resource "aws_vpc_security_group_ingress_rule" "database_restore_source_canary" {
  security_group_id            = aws_security_group.database.id
  description                  = "TLS PostgreSQL from protected restore-source canary"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.restore_source_canary.id
}

# These child groups contain a fixed, Terraform-owned allowlist. No task ENI uses
# the verifier group during normal operation, while the restored database group
# permits PostgreSQL only from that otherwise-unattached group. GitHub OIDC has
# no child RunTask/PassRole authority; the fixed Step Functions broker selects
# this exact group, and no drill role can mutate either group. That makes the
# restored-only database path an AWS-enforced boundary rather than a script
# convention.
resource "aws_security_group" "restore_database" {
  name_prefix = "${local.name_prefix}-restore-db-"
  description = "Dedicated RDS destination boundary for isolated restore drills"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-restore-database"
    Purpose = "RestoreDatabase"
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "restore_semantic_verifier" {
  name_prefix = "${local.name_prefix}-restore-verifier-"
  description = "Inert ENI boundary for the separately approved restore semantic verifier"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-restore-semantic-verifier"
    Purpose = "RestoreSemanticVerifier"
  }

  lifecycle { create_before_destroy = true }
}

# The Step Functions broker has no database or secret authority. Its fixed
# task definition needs only regional AWS control-plane HTTPS and VPC DNS so it
# can launch, observe and contain the separately isolated child tasks.
resource "aws_security_group" "restore_semantic_broker" {
  name_prefix = "${local.name_prefix}-restore-broker-"
  description = "No-ingress control-plane boundary for the fixed restore semantic broker"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-restore-semantic-broker"
    Purpose = "RestoreSemanticBroker"
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_broker_https" {
  security_group_id = aws_security_group.restore_semantic_broker.id
  description       = "Regional AWS control-plane APIs through the existing bounded NAT path"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_broker_dns_udp" {
  security_group_id = aws_security_group.restore_semantic_broker.id
  description       = "VPC DNS over UDP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_broker_dns_tcp" {
  security_group_id = aws_security_group.restore_semantic_broker.id
  description       = "VPC DNS over TCP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_security_group" "clamav" {
  name_prefix = "${local.name_prefix}-clamav-"
  description = "Isolated malware scanner with no application task role"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${local.name_prefix}-clamav"
    Service = "clamav"
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_ingress_rule" "restore_database_from_semantic_verifier" {
  security_group_id            = aws_security_group.restore_database.id
  description                  = "TLS PostgreSQL only from isolated restore semantic tasks"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.restore_semantic_verifier.id
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_verifier_database" {
  security_group_id            = aws_security_group.restore_semantic_verifier.id
  description                  = "TLS PostgreSQL only to the isolated restore database"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.restore_database.id
}

resource "aws_vpc_security_group_ingress_rule" "restore_semantic_verifier_self" {
  security_group_id            = aws_security_group.restore_semantic_verifier.id
  description                  = "Verifier caller to candidate Document Store only"
  from_port                    = 8089
  to_port                      = 8089
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.restore_semantic_verifier.id
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_verifier_self" {
  security_group_id            = aws_security_group.restore_semantic_verifier.id
  description                  = "Verifier caller to candidate Document Store only"
  from_port                    = 8089
  to_port                      = 8089
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.restore_semantic_verifier.id
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_verifier_s3" {
  security_group_id = aws_security_group.restore_semantic_verifier.id
  description       = "Restored canary and immutable journal through the S3 gateway endpoint"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_verifier_dns_udp" {
  security_group_id = aws_security_group.restore_semantic_verifier.id
  description       = "VPC DNS over UDP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "restore_semantic_verifier_dns_tcp" {
  security_group_id = aws_security_group.restore_semantic_verifier.id
  description       = "VPC DNS over TCP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name_prefix}-db-"
  description = "PostgreSQL ingress only from declared DB-owning services and release operator"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-database" }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "alb_frontend" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Only the application frontend target"
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service["job-seeker-copilot-client"].id
}

resource "aws_vpc_security_group_egress_rule" "alb_stripe" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Signed Stripe webhook target when separately enabled"
  from_port                    = 8100
  to_port                      = 8100
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service["stripe-gateway"].id
}

resource "aws_vpc_security_group_egress_rule" "service_dns_udp" {
  for_each = local.raw_services

  security_group_id = aws_security_group.service[each.key].id
  description       = "VPC DNS over UDP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "service_dns_tcp" {
  for_each = local.raw_services

  security_group_id = aws_security_group.service[each.key].id
  description       = "VPC DNS over TCP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "approved_public_https" {
  for_each = local.service_public_https_egress

  security_group_id = aws_security_group.service[each.key].id
  description       = "Approved external provider or AWS API HTTPS"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "document_store_s3" {
  security_group_id = aws_security_group.service["document-store-service"].id
  description       = "Document object storage through the S3 gateway endpoint"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

resource "aws_vpc_security_group_egress_rule" "clamav_dns_udp" {
  security_group_id = aws_security_group.clamav.id
  description       = "VPC DNS over UDP for signature mirrors"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "clamav_dns_tcp" {
  security_group_id = aws_security_group.clamav.id
  description       = "VPC DNS over TCP for signature mirrors"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "clamav_signature_refresh" {
  security_group_id = aws_security_group.clamav.id
  description       = "Upstream malware-signature refresh over HTTPS"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "clamav_from_document_store" {
  security_group_id            = aws_security_group.clamav.id
  description                  = "Document Store malware scan stream"
  from_port                    = 3310
  to_port                      = 3310
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service["document-store-service"].id
}

resource "aws_vpc_security_group_egress_rule" "document_store_clamav" {
  security_group_id            = aws_security_group.service["document-store-service"].id
  description                  = "Isolated malware scanner"
  from_port                    = 3310
  to_port                      = 3310
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.clamav.id
}

resource "aws_vpc_security_group_egress_rule" "operator_dns_udp" {
  security_group_id = aws_security_group.operator.id
  description       = "VPC DNS over UDP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_egress_rule" "operator_dns_tcp" {
  security_group_id = aws_security_group.operator.id
  description       = "VPC DNS over TCP"
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  cidr_ipv4         = "${cidrhost(aws_vpc.main.cidr_block, 2)}/32"
}

resource "aws_vpc_security_group_ingress_rule" "frontend_from_alb" {
  security_group_id            = aws_security_group.service["job-seeker-copilot-client"].id
  description                  = "Application load balancer to frontend"
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_ingress_rule" "stripe_from_alb" {
  security_group_id            = aws_security_group.service["stripe-gateway"].id
  description                  = "Application load balancer to signed Stripe webhook"
  from_port                    = 8100
  to_port                      = 8100
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_ingress_rule" "service_dependency" {
  for_each = local.service_dependencies

  security_group_id            = aws_security_group.service[each.value.target].id
  description                  = "${each.value.source} to declared dependency"
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service[each.value.source].id
}

resource "aws_vpc_security_group_egress_rule" "service_dependency" {
  for_each = local.service_dependencies

  security_group_id            = aws_security_group.service[each.value.source].id
  description                  = "Declared dependency ${each.value.target}"
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service[each.value.target].id
}

resource "aws_vpc_security_group_ingress_rule" "operator_preflight" {
  for_each = local.raw_services

  security_group_id            = aws_security_group.service[each.key].id
  description                  = "Release preflight health probe"
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.operator.id
}

resource "aws_vpc_security_group_egress_rule" "operator_preflight" {
  for_each = local.raw_services

  security_group_id            = aws_security_group.operator.id
  description                  = "Health probe for ${each.key}"
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service[each.key].id
}

resource "aws_vpc_security_group_ingress_rule" "database_service" {
  for_each = local.database_owners

  security_group_id            = aws_security_group.database.id
  description                  = "TLS PostgreSQL from ${each.key}"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.service[each.key].id
}

resource "aws_vpc_security_group_egress_rule" "database_service" {
  for_each = local.database_owners

  security_group_id            = aws_security_group.service[each.key].id
  description                  = "TLS PostgreSQL logical database ${each.value}"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.database.id
}

resource "aws_vpc_security_group_ingress_rule" "database_operator" {
  security_group_id            = aws_security_group.database.id
  description                  = "TLS PostgreSQL bootstrap and migration verification"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.operator.id
}

resource "aws_vpc_security_group_egress_rule" "operator_database" {
  security_group_id            = aws_security_group.operator.id
  description                  = "TLS PostgreSQL bootstrap and migration verification"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.database.id
}
