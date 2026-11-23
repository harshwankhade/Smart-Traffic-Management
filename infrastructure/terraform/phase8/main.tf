resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Phase 8 requires reviewed cost evidence and explicit deployment approval."
    }
  }
}

locals {
  tags     = { Project = "SmartTraffic", Phase = "8", ManagedBy = "Terraform" }
  services = toset(["sensor-registry", "traffic-ingestion", "event-publisher", "signal-recommendation", "incident-manager", "traffic-analytics"])
  workload_policy_arns = {
    "event-publisher"       = aws_iam_policy.publisher_archive.arn
    "signal-recommendation" = module.derived.signal_recommendation_policy_arn
    "traffic-analytics"     = module.derived.traffic_analytics_policy_arn
    "incident-manager"      = module.alerts.incident_manager_send_policy_arn
  }
  public  = { for i, az in var.availability_zones : az => cidrsubnet("10.80.0.0/16", 8, i) }
  private = { for i, az in var.availability_zones : az => cidrsubnet("10.80.0.0/16", 8, i + 10) }
}

resource "aws_vpc" "main" {
  cidr_block           = "10.80.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = local.tags
  depends_on           = [terraform_data.deployment_guard]
}
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = local.tags
}
resource "aws_subnet" "public" {
  for_each          = local.public
  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = merge(local.tags, { "kubernetes.io/role/elb" = "1" })
}
resource "aws_subnet" "private" {
  for_each          = local.private
  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = merge(local.tags, { "kubernetes.io/role/internal-elb" = "1", "for-use-with-amazon-emr-managed-policies" = "true" })
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = local.tags
}
resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}
resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = local.tags
}
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = values(aws_subnet.public)[0].id
  tags          = local.tags
  depends_on    = [aws_route.public_internet, aws_route_table_association.public]
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = local.tags
}
resource "aws_route" "private_nat" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}
resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# EMR runs in a private subnet.  Native EMR CloudWatch Logs publishing requires
# a Logs interface endpoint; one ENI in the single-worker EMR subnet keeps the
# Phase 9 demonstration within its cost cap.
resource "aws_vpc_endpoint" "cloudwatch_logs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [values(aws_subnet.private)[0].id]
  security_group_ids  = [module.processing.cloudwatch_logs_endpoint_security_group_id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:DescribeLogGroups", "logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"]
      Resource  = "*"
    }]
  })
  tags = merge(local.tags, { Purpose = "Phase9EmrCloudWatchLogs" })
}

resource "aws_iam_role" "eks_cluster" {
  name_prefix        = "${var.project_name}-eks-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = local.tags
  depends_on         = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}
resource "aws_iam_role" "eks_nodes" {
  name_prefix        = "${var.project_name}-nodes-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }] })
  tags               = local.tags
  depends_on         = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy_attachment" "eks_nodes" {
  for_each   = toset(["arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy", "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly", "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"])
  role       = aws_iam_role.eks_nodes.name
  policy_arn = each.value
}
resource "aws_eks_cluster" "main" {
  name     = var.project_name
  role_arn = aws_iam_role.eks_cluster.arn
  vpc_config {
    subnet_ids              = values(aws_subnet.private)[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.admin_cidrs
  }
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  tags                      = local.tags
  depends_on                = [aws_iam_role_policy_attachment.eks_cluster]
}
resource "aws_cloudwatch_log_group" "eks_application" {
  name              = "/smarttraffic/${var.project_name}/eks"
  retention_in_days = 7
  tags              = local.tags
  depends_on        = [terraform_data.deployment_guard]
}
resource "aws_iam_role" "fluent_bit" {
  name_prefix = "${var.project_name}-fluent-bit-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" }, Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy" "fluent_bit" {
  role = aws_iam_role.fluent_bit.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.eks_application.arn}:*"
  }] })
}
resource "aws_eks_pod_identity_association" "fluent_bit" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "smarttraffic-observability"
  service_account = "aws-for-fluent-bit"
  role_arn        = aws_iam_role.fluent_bit.arn
  depends_on      = [aws_eks_addon.pod_identity, aws_iam_role_policy.fluent_bit]
}
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "application"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = values(aws_subnet.private)[*].id
  instance_types  = ["t3.large"]
  scaling_config {
    desired_size = var.eks_worker_count
    min_size     = var.eks_worker_count
    max_size     = var.eks_worker_count
  }
  # Private nodes need working egress during bootstrap, including ECR and STS.
  depends_on = [aws_iam_role_policy_attachment.eks_nodes, aws_route.private_nat, aws_route_table_association.private]
}
data "aws_ecr_repository" "services" {
  for_each = local.services
  name     = "${var.project_name}/${each.key}"
}

# Preserve the old provider address until existing state has been reconciled.
# This compatibility module declares no MSK, archive or other resources.
module "streaming" {
  source = "../phase3-provider-compat"
}

module "processing" {
  source                  = "../phase4"
  deployment_approved     = var.deployment_approved
  project_name            = "${var.project_name}-emr"
  emr_instance_type       = "m5.xlarge"
  emr_single_node         = true
  vpc_id                  = aws_vpc.main.id
  private_subnet_ids      = values(aws_subnet.private)[*].id
  kafka_auth_mode         = "tls"
  kafka_cluster_arn       = ""
  kafka_port              = 9093
  kafka_security_group_id = ""
  kafka_cidr              = aws_vpc.main.cidr_block
  kafka_bootstrap_servers = "kafka.smarttraffic.internal:9093"
  archive_bucket          = aws_s3_bucket.archive.id
  s3_prefix_list_id       = aws_vpc_endpoint.s3.prefix_list_id
  jar_path                = var.emr_jar_path
  # Gate only EMR creation on private-network readiness; legacy child providers
  # prevent module-level depends_on, and EKS itself is not a prerequisite.
  bootstrap_dependency_ids = concat([aws_route.private_nat.id, aws_vpc_endpoint.cloudwatch_logs.id], [for association in aws_route_table_association.private : association.id])
}
module "derived" {
  source              = "../phase5"
  deployment_approved = var.deployment_approved
  project_name        = var.project_name
}
module "alerts" {
  source              = "../phase6"
  deployment_approved = var.deployment_approved
  project_name        = var.project_name
  lambda_zip_path     = var.lambda_zip_path
}

resource "aws_db_subnet_group" "main" {
  name_prefix = "${var.project_name}-"
  subnet_ids  = values(aws_subnet.private)[*].id
  tags        = local.tags
  depends_on  = [terraform_data.deployment_guard]
}
resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-rds-"
  description = "PostgreSQL ingress only from the EKS cluster security group"
  vpc_id      = aws_vpc.main.id
  tags        = local.tags
  depends_on  = [terraform_data.deployment_guard]
}
resource "aws_vpc_security_group_ingress_rule" "rds_from_eks" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_db_instance" "main" {
  identifier                  = "${var.project_name}-postgres"
  engine                      = "postgres"
  engine_version              = "17"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  db_name                     = "smarttraffic"
  username                    = "traffic_admin"
  manage_master_user_password = true
  storage_encrypted           = true
  publicly_accessible         = false
  vpc_security_group_ids      = [aws_security_group.rds.id]
  skip_final_snapshot         = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  tags                        = local.tags
  depends_on                  = [terraform_data.deployment_guard]
}

# This value contains resource identifiers and the generated RDS-secret ARN,
# never the RDS password. External Secrets exposes it only inside the cluster.
resource "aws_secretsmanager_secret" "runtime_config" {
  name                    = "${var.project_name}-runtime-config"
  recovery_window_in_days = 0
  tags                    = local.tags
  depends_on              = [terraform_data.deployment_guard]
}
resource "aws_secretsmanager_secret_version" "runtime_config" {
  secret_id = aws_secretsmanager_secret.runtime_config.id
  secret_string = jsonencode({
    SENSOR_REGISTRY_DATABASE_SECRET_ARN  = aws_db_instance.main.master_user_secret[0].secret_arn
    INCIDENT_MANAGER_DATABASE_SECRET_ARN = aws_db_instance.main.master_user_secret[0].secret_arn
    SMARTTRAFFIC_RDS_HOST                = aws_db_instance.main.address
    KAFKA_BOOTSTRAP_SERVERS              = "kafka.smarttraffic.internal:9093"
    KAFKA_SSL_CA_PEM                     = tls_self_signed_cert.kafka.cert_pem
    ARCHIVE_BUCKET                       = aws_s3_bucket.archive.id
    RECOMMENDATIONS_TABLE                = module.derived.recommendations_table
    SUMMARIES_TABLE                      = module.derived.summaries_table
    ALERT_QUEUE_URL                      = module.alerts.alert_queue_url
  })
}

resource "aws_iam_role" "workloads" {
  for_each = local.services
  # IAM role name_prefix is limited to 38 characters; service names are enough
  # to distinguish these run-scoped workload identities.
  name_prefix = "p8-${each.key}-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" },
    Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy_attachment" "workload_service" {
  for_each   = local.workload_policy_arns
  role       = aws_iam_role.workloads[each.key].name
  policy_arn = each.value
}

# High-congestion recommendations enqueue the same durable alert request as
# Incident Manager.  Keep this permission separate and scoped to only the
# Signal Recommendation workload and the Terraform-owned alerts queue.
resource "aws_iam_role_policy_attachment" "signal_recommendation_alerts" {
  role       = aws_iam_role.workloads["signal-recommendation"].name
  policy_arn = module.alerts.signal_recommendation_send_policy_arn
}
resource "aws_iam_role_policy" "workload_database_secret" {
  for_each = toset(["sensor-registry", "incident-manager"])
  role     = aws_iam_role.workloads[each.key].name
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"],
    Resource = aws_db_instance.main.master_user_secret[0].secret_arn
  }] })
}
resource "aws_eks_pod_identity_association" "workloads" {
  for_each        = local.services
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "smarttraffic"
  service_account = each.key
  role_arn        = aws_iam_role.workloads[each.key].arn
  depends_on      = [aws_eks_addon.pod_identity]
}

resource "aws_iam_policy" "aws_load_balancer_controller" {
  name_prefix = "${var.project_name}-aws-lbc-"
  # Vendored verbatim from controller v2.14.1; SHA-256 16f232c9d9f79366fe949c4550ad517a202380058a9e48d45a4e215044a20a6a.
  policy     = file("${path.module}/aws-load-balancer-controller-v2.14.1-iam-policy.json")
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_role" "aws_load_balancer_controller" {
  name_prefix = "${var.project_name}-aws-lbc-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_role_policy_attachment" "aws_load_balancer_controller" {
  role       = aws_iam_role.aws_load_balancer_controller.name
  policy_arn = aws_iam_policy.aws_load_balancer_controller.arn
}

resource "aws_eks_addon" "pod_identity" {
  cluster_name                = aws_eks_cluster.main.name
  addon_name                  = "eks-pod-identity-agent"
  resolve_conflicts_on_create = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.main]
}

resource "aws_iam_role" "ebs_csi" {
  name_prefix = "${var.project_name}-ebs-csi-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" },
    Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  tags = local.tags
}
resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
resource "aws_eks_pod_identity_association" "ebs_csi" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "kube-system"
  service_account = "ebs-csi-controller-sa"
  role_arn        = aws_iam_role.ebs_csi.arn
  depends_on      = [aws_eks_addon.pod_identity, aws_iam_role_policy_attachment.ebs_csi]
}
resource "aws_eks_addon" "ebs_csi" {
  cluster_name                = aws_eks_cluster.main.name
  addon_name                  = "aws-ebs-csi-driver"
  resolve_conflicts_on_create = "OVERWRITE"
  depends_on                  = [aws_eks_pod_identity_association.ebs_csi]
}

resource "aws_eks_pod_identity_association" "aws_load_balancer_controller" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.aws_load_balancer_controller.arn
  depends_on      = [aws_eks_addon.pod_identity, aws_iam_role_policy_attachment.aws_load_balancer_controller]
}

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "1.14.1"
  atomic     = true
  wait       = true
  values = [yamlencode({
    clusterName  = aws_eks_cluster.main.name
    region       = var.aws_region
    vpcId        = aws_vpc.main.id
    replicaCount = 1
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller"
    }
  })]
  depends_on = [aws_eks_pod_identity_association.aws_load_balancer_controller]
}

# ExternalDNS creates only the approved public hostname alias after the
# controller has published the GitOps Ingress ALB address.
resource "aws_iam_role" "external_dns" {
  name_prefix = "${var.project_name}-external-dns-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" },
    Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy" "external_dns" {
  role = aws_iam_role.external_dns.name
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["route53:ChangeResourceRecordSets"], Resource = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}", aws_route53_zone.kafka.arn] },
    { Effect = "Allow", Action = ["route53:ListHostedZones", "route53:ListResourceRecordSets"], Resource = "*" },
    { Effect = "Allow", Action = ["route53:GetChange"], Resource = "arn:aws:route53:::change/*" }
  ] })
}
resource "aws_eks_pod_identity_association" "external_dns" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "kube-system"
  service_account = "external-dns"
  role_arn        = aws_iam_role.external_dns.arn
  depends_on      = [aws_eks_addon.pod_identity, aws_iam_role_policy.external_dns]
}
resource "helm_release" "external_dns" {
  name       = "external-dns"
  repository = "https://kubernetes-sigs.github.io/external-dns/"
  chart      = "external-dns"
  version    = "1.24.0"
  namespace  = "kube-system"
  atomic     = true
  wait       = true
  values = [yamlencode({
    provider   = { name = "aws" }
    policy     = "sync"
    registry   = "txt"
    txtOwnerId = var.project_name
    # The AWS provider matches a hosted-zone name, not an individual record.
    # `public_dns_name` is the approved one-label API host (api.<zone>), so
    # remove that label while retaining a narrowly scoped zone filter.
    domainFilters  = [join(".", slice(split(".", var.public_dns_name), 1, length(split(".", var.public_dns_name)))), "smarttraffic.internal"]
    extraArgs      = { "zone-id-filter" = [var.route53_zone_id, aws_route53_zone.kafka.zone_id], "listen-endpoint-events" = true }
    interval       = "30s"
    serviceAccount = { create = true, name = "external-dns" }
  })]
  depends_on = [aws_eks_pod_identity_association.external_dns]
}

# External Secrets is the only workload that may read the runtime-reference
# secret. Database passwords stay in the RDS-managed secret and are read only
# by the two database-owning service identities.
resource "aws_iam_role" "external_secrets" {
  name_prefix = "${var.project_name}-external-secrets-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" },
    Action = ["sts:AssumeRole", "sts:TagSession"]
  }] })
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy" "external_secrets" {
  role = aws_iam_role.external_secrets.name
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Action = ["secretsmanager:GetSecretValue"],
    Resource = [aws_secretsmanager_secret.runtime_config.arn, aws_secretsmanager_secret.kafka_tls.arn]
  }] })
}
resource "aws_eks_pod_identity_association" "external_secrets" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.external_secrets.arn
  depends_on      = [aws_eks_addon.pod_identity, aws_iam_role_policy.external_secrets]
}
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  version          = "0.20.4"
  atomic           = true
  wait             = true
  values = [yamlencode({
    installCRDs    = true
    serviceAccount = { create = true, name = "external-secrets" }
  })]
  # The load-balancer admission webhook must have endpoints before another
  # chart creates Services, or parallel installs can fail admission.
  depends_on = [aws_eks_pod_identity_association.external_secrets, helm_release.aws_load_balancer_controller]
}
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  version          = "10.17.0"
  atomic           = true
  wait             = true
  depends_on       = [helm_release.aws_load_balancer_controller, helm_release.external_dns, helm_release.external_secrets]
}

# Terraform seeds only Argo CD's root Application. Argo then reconciles every
# namespace, workload, Service, ConfigMap, Ingress and ZooKeeper resource from Git.
resource "helm_release" "argocd_root_application" {
  count     = var.gitops_bootstrap_enabled ? 1 : 0
  name      = "smarttraffic-root"
  chart     = "${path.module}/charts/argocd-root-application"
  namespace = "argocd"
  atomic    = true
  wait      = true
  values = [yamlencode({
    application = {
      name      = "smarttraffic-root"
      namespace = "argocd"
      project   = "default"
      source = {
        repoURL        = var.git_repository_url
        targetRevision = "main"
        path           = "deploy/gitops/apps"
      }
      destination = {
        server    = "https://kubernetes.default.svc"
        namespace = "smarttraffic"
      }
      syncPolicy = {
        automated   = { prune = true, selfHeal = true }
        syncOptions = ["CreateNamespace=true", "PruneLast=true"]
      }
    }
  })]
  depends_on = [helm_release.argocd]
}

# Private DNS points directly to the Kafka pod's VPC address. Permit only
# EMR's primary node to reach its TLS listener through the pod/node SG.
resource "aws_vpc_security_group_ingress_rule" "kafka_from_emr" {
  security_group_id            = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = module.processing.emr_primary_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 9093
  to_port                      = 9093
  description                  = "EMR to private Kafka TLS pod endpoint"
}
