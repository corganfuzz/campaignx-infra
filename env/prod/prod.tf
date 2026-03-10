module "infrastructure" {
  source = "../../infrastructure"

  project_name     = local.project_name
  environment      = local.environment
  aws_region       = local.aws_region
  enable_ai_engine = local.enable_ai_engine
  s3_buckets       = local.s3_buckets
  iam_roles        = local.iam_roles
  bedrock_config   = local.bedrock_config
  lambda_config    = local.lambda_config
  api_proxy_config = local.api_proxy_config
}
