module "infrastructure" {
  source = "../../infrastructure"

  project_name      = local.project_name
  environment       = local.environment
  aws_region        = local.aws_region
  vpcs              = local.vpcs
  enable_ai_engine  = local.enable_ai_engine
  s3_buckets        = local.s3_buckets
  iam_roles         = local.iam_roles
  databricks_host   = var.databricks_host
  databricks_token  = var.databricks_token
  fred_api_key      = var.fred_api_key
  bedrock_config    = local.bedrock_config
  lambdas           = local.lambdas
  databricks_config = local.databricks_config

  providers = {
    aws        = aws
    databricks = databricks
  }
}
