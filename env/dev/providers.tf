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
    klayers = {
      version = "~> 1.0.0"
      source  = "ldcorentin/klayer"
    }
    archive = {
      source = "hashicorp/archive"
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
    key    = "dev/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "opensearch" {
  url         = module.infrastructure.bedrock_collection_endpoint
  healthcheck = false
}
