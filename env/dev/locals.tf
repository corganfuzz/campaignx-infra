locals {
  # ── Project ─────────────────────────────────────────
  project_name     = "campaignx"
  environment      = "dev"
  aws_region       = "us-east-1"
  enable_ai_engine = true

  # ── Storage ─────────────────────────────────────────
  s3_buckets = {
    "rag-docs"     = { versioning = true } # brand guidelines + regional trends
    "assets-input" = { versioning = true } # uploaded brand images
    "outputs"      = { versioning = true } # generated campaign images
    "analytics"    = { versioning = true } # kinesis firehose events
  }

  dynamodb_tables = {
    "campaigns" = {}
  }

  sqs_queues = {
    "campaign-gen" = {}
  }

  sns_topics = {
    "approvals" = { email_recipient = "creative-team@company.com" }
  }

  analytics_streams = {
    "events" = {}
  }

  # ── IAM Roles ───────────────────────────────────────
  iam_roles = {
    "bedrock-agent"     = { trust_service = "bedrock.amazonaws.com" }
    "bedrock-kb"        = { trust_service = "bedrock.amazonaws.com" }
    "submit-brief"      = { trust_service = "lambda.amazonaws.com" }
    "generate-campaign" = { trust_service = "lambda.amazonaws.com" }
    "check-compliance"  = { trust_service = "lambda.amazonaws.com" }
    "get-campaigns"     = { trust_service = "lambda.amazonaws.com" }
    "get-insights"      = { trust_service = "lambda.amazonaws.com" }
    "refresh-knowledge" = { trust_service = "lambda.amazonaws.com" }
    "update-approval"   = { trust_service = "lambda.amazonaws.com" }
    "firehose"          = { trust_service = "firehose.amazonaws.com" }
  }

  # ── Bedrock ─────────────────────────────────────────
  bedrock_config = {
    embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    foundation_model    = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    vector_index_name   = "bedrock-knowledge-base-default-index"
    agent_version       = "DRAFT"
  }

  # ── Guardrails ──────────────────────────────────────
  guardrails = {
    "default" = {
      blocked_words = [
        "guaranteed", "clinically proven", "miracle",
        "instant results", "100% effective", "best in world"
      ]
      denied_topics = [
        "competitor brand mentions",
        "medical claims",
        "financial guarantees"
      ]
    }
  }

  # ── Lambda Functions ─────────────────────────────────
  lambda_functions = {
    "submit-brief" = {
      role = "submit-brief"
      config = {
        runtime       = "python3.12"
        handler       = "submit_brief.handler"
        timeout       = 10
        memory_size   = 256
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
    "generate-campaign" = {
      role = "generate-campaign"
      config = {
        runtime       = "python3.12"
        handler       = "generate_campaign.handler"
        timeout       = 300  # 5min for image gen
        memory_size   = 1024 # Pillow needs memory
        architectures = ["arm64"]
        layers        = ["pillow"]
      }
      env_vars = {}
    }
    "check-compliance" = {
      role = "check-compliance"
      config = {
        runtime       = "python3.12"
        handler       = "check_compliance.handler"
        timeout       = 30
        memory_size   = 256
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
    "get-campaigns" = {
      role = "get-campaigns"
      config = {
        runtime       = "python3.12"
        handler       = "get_campaigns.handler"
        timeout       = 10
        memory_size   = 256
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
    "get-insights" = {
      role = "get-insights"
      config = {
        runtime       = "python3.12"
        handler       = "get_insights.handler"
        timeout       = 30
        memory_size   = 256
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
    "refresh-knowledge" = {
      role = "refresh-knowledge"
      config = {
        runtime       = "python3.12"
        handler       = "refresh_knowledge.handler"
        timeout       = 300
        memory_size   = 512
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
    "update-approval" = {
      role = "update-approval"
      config = {
        runtime       = "python3.12"
        handler       = "update_approval.handler"
        timeout       = 10
        memory_size   = 256
        architectures = ["x86_64"]
      }
      env_vars = {}
    }
  }

}
