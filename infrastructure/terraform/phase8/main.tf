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
    "event-publisher"       = module.streaming.publisher_policy_arn
    "signal-recommendation" = module.derived.signal_recommendation_policy_arn
    "traffic-analytics"     = module.derived.traffic_analytics_policy_arn
    "incident-manager"      = module.alerts.incident_manager_send_policy_arn
  }
  public   = { for i, az in var.availability_zones : az => cidrsubnet("10.80.0.0/16", 8, i) }
  private  = { for i, az in var.availability_zones : az => cidrsubnet("10.80.0.0/16", 8, i + 10) }
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
  tags              = merge(local.tags, { "kubernetes.io/role/internal-elb" = "1" })
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
  depends_on    = [aws_internet_gateway.main]
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
  tags       = local.tags
  depends_on = [aws_iam_role_policy_attachment.eks_cluster]
}
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "application"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = values(aws_subnet.private)[*].id
  instance_types  = ["t3.medium"]
  scaling_config {
    desired_size = 2
    min_size     = 2
    max_size     = 3
  }
  depends_on = [aws_iam_role_policy_attachment.eks_nodes]
}
resource "aws_ecr_repository" "services" {
  for_each             = local.services
  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
}

module "streaming" {
  source                        = "../phase3"
  deployment_approved           = var.deployment_approved
  project_name                  = "${var.project_name}-kafka"
  vpc_id                        = aws_vpc.main.id
  private_subnet_ids            = values(aws_subnet.private)[*].id
  private_route_table_ids       = [aws_route_table.private.id]
  application_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}
module "processing" {
  source                  = "../phase4"
  deployment_approved     = var.deployment_approved
  project_name            = "${var.project_name}-emr"
  vpc_id                  = aws_vpc.main.id
  private_subnet_ids      = values(aws_subnet.private)[*].id
  kafka_cluster_arn       = module.streaming.kafka_cluster_arn
  kafka_security_group_id = module.streaming.kafka_security_group_id
  kafka_bootstrap_servers = module.streaming.kafka_bootstrap_servers
  archive_bucket          = module.streaming.archive_bucket
  s3_prefix_list_id       = module.streaming.s3_prefix_list_id
  jar_path                = var.emr_jar_path
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
    SENSOR_REGISTRY_DATABASE_SECRET_ARN = aws_db_instance.main.master_user_secret[0].secret_arn
    INCIDENT_MANAGER_DATABASE_SECRET_ARN = aws_db_instance.main.master_user_secret[0].secret_arn
    KAFKA_BOOTSTRAP_SERVERS              = module.streaming.kafka_bootstrap_servers
    ARCHIVE_BUCKET                       = module.streaming.archive_bucket
    RECOMMENDATIONS_TABLE                = module.derived.recommendations_table
    SUMMARIES_TABLE                      = module.derived.summaries_table
    ALERT_QUEUE_URL                      = module.alerts.alert_queue_url
  })
}

resource "aws_iam_role" "workloads" {
  for_each    = local.services
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
resource "aws_iam_role_policy" "workload_database_secret" {
  for_each = toset(["sensor-registry", "incident-manager"])
  role     = aws_iam_role.workloads[each.key].name
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
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
data "http" "aws_load_balancer_controller_policy" {
  # Pinned upstream policy recommended by the EKS controller installation guide.
  url                = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.14.1/docs/install/iam_policy.json"
  request_timeout_ms = 30000
}

resource "aws_iam_policy" "aws_load_balancer_controller" {
  name_prefix = "${var.project_name}-aws-lbc-"
  policy      = data.http.aws_load_balancer_controller_policy.response_body
  tags        = local.tags
  depends_on  = [terraform_data.deployment_guard]
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
    clusterName = aws_eks_cluster.main.name
    region      = var.aws_region
    vpcId       = aws_vpc.main.id
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
    { Effect = "Allow", Action = ["route53:ChangeResourceRecordSets"], Resource = "arn:aws:route53:::hostedzone/${var.route53_zone_id}" },
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
  namespace  = "kube-system"
  atomic     = true
  wait       = true
  values = [yamlencode({
    provider       = { name = "aws" }
    policy         = "sync"
    registry       = "txt"
    txtOwnerId     = var.project_name
    domainFilters  = [var.public_dns_name]
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
    Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
    Resource = aws_secretsmanager_secret.runtime_config.arn
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
    installCRDs = true
    serviceAccount = { create = true, name = "external-secrets" }
  })]
  depends_on = [aws_eks_pod_identity_association.external_secrets]
}
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  version          = "7.8.26"
  atomic           = true
  wait             = true
  depends_on       = [helm_release.aws_load_balancer_controller, helm_release.external_dns, helm_release.external_secrets]
}

# Terraform seeds only Argo CD's root Application. Argo then reconciles every
# namespace, workload, Service, ConfigMap, Ingress and ZooKeeper resource from Git.
resource "helm_release" "argocd_root_application" {
  name       = "smarttraffic-root"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-applications"
  namespace  = "argocd"
  version    = "1.4.1"
  atomic     = true
  wait       = true
  values = [yamlencode({
    applications = [{
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
    }]
  })]
  depends_on = [helm_release.argocd]
}
