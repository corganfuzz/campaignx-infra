locals {
  project_name     = "concrete-fc"
  environment      = "prod"
  aws_region       = "us-east-1"
  enable_ai_engine = true

  s3_buckets = {
    "raw"       = { versioning = true }
    "bronze"    = { versioning = true }
    "silver"    = { versioning = true }
    "gold"      = { versioning = true }
    "kb-source" = { versioning = true }
  }

  iam_roles = {
    "bedrock-agent" = { trust_service = "bedrock.amazonaws.com" }
    "bedrock-kb"    = { trust_service = "bedrock.amazonaws.com" }
    "databricks"    = { trust_service = "ec2.amazonaws.com" }
    "fred-fetcher"  = { trust_service = "lambda.amazonaws.com" }
    "api-proxy"     = { trust_service = "lambda.amazonaws.com" }
  }

  bedrock_config = {
    embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    foundation_model    = "anthropic.claude-3-haiku-20240307-v1:0"
    vector_index_name   = "bedrock-knowledge-base-default-index"
    agent_version       = "DRAFT"
  }

  lambda_config = {
    runtime       = "python3.11"
    handler       = "fred_fetcher.handler"
    timeout       = 60
    memory_size   = 512
    allow_bedrock = true
  }

  api_proxy_config = {
    runtime       = "python3.11"
    handler       = "index.lambda_handler"
    timeout       = 30
    memory_size   = 256
    allow_bedrock = false
  }
}
