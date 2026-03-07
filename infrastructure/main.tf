terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    databricks = {
      source = "databricks/databricks"
    }
    time = {
      source = "hashicorp/time"
    }
  }
}

module "vpc" {
  for_each = var.vpcs
  source   = "../modules/networking/vpc"

  project_name = var.project_name
  environment  = var.environment
  vpc_cidr     = each.value.cidr_block
}

module "subnets" {
  for_each = var.vpcs
  source   = "../modules/networking/subnets"

  project_name  = var.project_name
  environment   = var.environment
  vpc_id        = module.vpc[each.key].vpc_id
  subnet_config = each.value.subnets
}

module "gateways" {
  for_each = var.vpcs
  source   = "../modules/networking/gateways"

  project_name = var.project_name
  environment  = var.environment

  nat_gateway_config = {
    for k, v in each.value.subnets : k => module.subnets[each.key].subnet_ids[k] if v.public
  }
}

module "routing" {
  for_each = var.vpcs
  source   = "../modules/networking/routing"

  project_name      = var.project_name
  environment       = var.environment
  vpc_id            = module.vpc[each.key].vpc_id
  igw_id            = module.vpc[each.key].igw_id
  public_subnet_ids = module.subnets[each.key].public_subnet_ids

  private_routing_config = {
    for k, v in each.value.subnets : k => {
      subnet_id      = module.subnets[each.key].subnet_ids[k]
      nat_gateway_id = module.gateways[each.key].nat_gateway_ids[[for pk, pv in each.value.subnets : pk if pv.public && pv.availability_zone == v.availability_zone][0]]
    } if !v.public
  }
}

module "storage" {
  source = "../modules/storage"

  project_name = var.project_name
  environment  = var.environment
  s3_buckets   = var.s3_buckets
}

module "iam" {
  source = "../modules/iam"

  project_name        = var.project_name
  environment         = var.environment
  storage_bucket_arns = module.storage.bucket_arns
  iam_roles           = var.iam_roles
}

resource "time_sleep" "wait_60_seconds" {
  depends_on = [module.iam]

  create_duration = "60s"
}

module "databricks" {
  depends_on = [time_sleep.wait_60_seconds]
  source     = "../modules/databricks"

  project_name        = var.project_name
  environment         = var.environment
  databricks_role_arn = module.iam.databricks_role_arn
  s3_buckets          = module.storage.bucket_names
  databricks_config   = var.databricks_config

  providers = {
    databricks = databricks
  }
}

module "lambda" {
  for_each = var.enable_ai_engine ? var.lambdas : {}
  source   = "../modules/lambda"

  project_name    = var.project_name
  environment     = var.environment
  aws_region      = var.aws_region
  lambda_role_arn = module.iam.role_arns[each.value.role_key]
  function_name   = each.key
  source_dir      = "${path.module}/../modules/lambda/${each.value.source_dir}"

  lambda_config = {
    runtime       = each.value.runtime
    handler       = each.value.handler
    timeout       = each.value.timeout
    memory_size   = each.value.memory_size
    allow_bedrock = each.value.allow_bedrock
  }

  environment_variables = merge(
    {
      for k, v in each.value.env_vars : k => (
        v == "raw" ? module.storage.bucket_names["raw"] :
        v == "BEDROCK_AGENT_ID" ? module.bedrock["enabled"].agent_id :
        v == "DATABRICKS_MODEL_SERVING_URL" ? module.databricks.model_serving_url :
        v
      )
    }
  )
}

module "bedrock" {
  for_each = var.enable_ai_engine ? { "enabled" = true } : {}
  source   = "../modules/bedrock"

  project_name                 = var.project_name
  environment                  = var.environment
  aws_region                   = var.aws_region
  kb_s3_bucket_arn             = module.storage.bucket_arns["kb-source"]
  kb_s3_bucket_name            = module.storage.bucket_names["kb-source"]
  lambda_function_arn          = try(module.lambda["fred-fetcher"].function_arn, null)
  databricks_bridge_lambda_arn = try(module.lambda["databricks-bridge"].function_arn, null)
  bedrock_kb_role_arn          = module.iam.role_arns["bedrock-kb"]
  bedrock_kb_role_name         = module.iam.role_names["bedrock-kb"]
  bedrock_agent_role_arn       = module.iam.role_arns["bedrock-agent"]
  bedrock_config               = var.bedrock_config
}

module "api_gateway" {
  for_each = var.enable_ai_engine ? { "enabled" = true } : {}
  source   = "../modules/api_gateway"

  project_name         = var.project_name
  environment          = var.environment
  lambda_invoke_arn    = module.lambda["api-proxy"].invoke_arn
  lambda_function_name = module.lambda["api-proxy"].function_name
}

