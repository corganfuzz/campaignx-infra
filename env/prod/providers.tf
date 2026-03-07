provider "aws" {
  region = local.aws_region
}

terraform {
  required_version = ">= 1.0.0"
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
    opensearch = {
      source  = "opensearch-project/opensearch"
      version = "~> 2.0"
    }
  }
  backend "s3" {
    bucket = "concrete-fc-tfstate-446311000231"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "databricks" {
  host  = var.databricks_host
  token = var.databricks_token
}

provider "opensearch" {
  url         = module.infrastructure.bedrock_collection_endpoint
  healthcheck = false
}
