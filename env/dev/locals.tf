locals {
  # ==============================================
  # Project Settings
  # ==============================================
  project_name     = "mortgage-xpert"
  environment      = "dev"
  aws_region       = "us-east-1"
  enable_ai_engine = true

  # ==============================================
  # Networking Configuration
  # ==============================================
  vpcs = {
    "main" = {
      cidr_block = "10.0.0.0/16"
      subnets = {
        "public-1a"  = { cidr_block = "10.0.1.0/24", availability_zone = "us-east-1a", public = true }
        "private-1a" = { cidr_block = "10.0.11.0/24", availability_zone = "us-east-1a", public = false }
      }
    }
  }

  # ==============================================
  # Storage Configuration
  # ==============================================
  s3_buckets = {
    "raw"       = { versioning = true }
    "bronze"    = { versioning = true }
    "silver"    = { versioning = true }
    "gold"      = { versioning = true }
    "kb-source" = { versioning = true }
  }

  # ==============================================
  # IAM Roles and Permissions
  # ==============================================
  iam_roles = {
    "bedrock-agent" = { trust_service = "bedrock.amazonaws.com" }
    "bedrock-kb"    = { trust_service = "bedrock.amazonaws.com" }
    "databricks"    = { trust_service = "ec2.amazonaws.com" }
    "fred-fetcher"  = { trust_service = "lambda.amazonaws.com" }
    "api-proxy"     = { trust_service = "lambda.amazonaws.com" }
  }

  # ==============================================
  # Amazon Bedrock Configuration
  # ==============================================
  bedrock_config = {
    embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    foundation_model    = "anthropic.claude-3-haiku-20240307-v1:0"
    vector_index_name   = "bedrock-knowledge-base-default-index"
    agent_version       = "DRAFT"
  }

  # ==============================================
  # AWS Lambda Configuration
  # ==============================================
  lambdas = {
    "fred-fetcher" = {
      runtime       = "python3.11"
      handler       = "fred_fetcher.handler"
      timeout       = 60
      memory_size   = 512
      allow_bedrock = true
      source_dir    = "src"
      role_key      = "fred-fetcher"
      env_vars = {
        FRED_API_KEY    = var.fred_api_key
        RAW_BUCKET_NAME = "raw" # Will be resolved to actual bucket name
      }
    }
    "databricks-bridge" = {
      runtime       = "python3.11"
      handler       = "databricks_bridge.handler"
      timeout       = 120
      memory_size   = 256
      allow_bedrock = true
      source_dir    = "src_databricks"
      role_key      = "api-proxy" # Reusing existing role
      env_vars = {
        DATABRICKS_TOKEN        = var.databricks_token
        DATABRICKS_ENDPOINT_URL = "DATABRICKS_MODEL_SERVING_URL" # Will be set dynamically
      }
    }
    "api-proxy" = {
      runtime       = "python3.11"
      handler       = "index.lambda_handler"
      timeout       = 30
      memory_size   = 256
      allow_bedrock = false
      source_dir    = "src_proxy"
      role_key      = "api-proxy"
      env_vars = {
        AGENT_ID        = "BEDROCK_AGENT_ID" # Will be set dynamically
        AGENT_ALIAS_ID  = "TSTALIASID"
        RAW_BUCKET_NAME = "raw"
      }
    }
  }

  # ==============================================
  # Databricks Modern Stack Configuration
  # ==============================================
  databricks_config = {
    catalog_name             = "mortgage_xpert"
    schemas                  = ["bronze", "silver", "gold"]
    warehouse_cluster_size   = "2X-Small"
    warehouse_auto_stop_mins = 10
  }
}
