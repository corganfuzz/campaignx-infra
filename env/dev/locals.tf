data "aws_caller_identity" "current" {}

locals {
  # ── Project ─────────────────────────────────────────
  project_name     = "campaignx"
  environment      = "dev"
  aws_region       = "us-east-1"
  enable_ai_engine = true
  account_id       = data.aws_caller_identity.current.account_id

  # ── Storage ─────────────────────────────────────────
  s3_buckets = {
    "rag-docs"     = { versioning = true } # brand guidelines + regional trends
    "assets-input" = { versioning = true } # uploaded brand images
    "outputs"      = { versioning = true } # generated campaign images
  }

  dynamodb_tables = {
    "campaigns" = {}
  }

  sqs_queues = {
    "campaign-gen" = {}
  }

  # ── Predicted ARNs (to avoid circular dependency) ────
  s3_arns  = { for k, v in local.s3_buckets : k => "arn:aws:s3:::${local.project_name}-${local.environment}-${k}" }
  ddb_arns = { for k, v in local.dynamodb_tables : k => "arn:aws:dynamodb:${local.aws_region}:${local.account_id}:table/${local.project_name}-${local.environment}-${k}" }
  sqs_arns = { for k, v in local.sqs_queues : k => "arn:aws:sqs:${local.aws_region}:${local.account_id}:${local.project_name}-${local.environment}-${k}" }

  # ── IAM Roles ───────────────────────────────────────
  iam_roles = {
    "bedrock-agent"     = { trust_service = "bedrock.amazonaws.com", policy_arns = [] }
    "bedrock-kb"        = { trust_service = "bedrock.amazonaws.com", policy_arns = [] }
    "submit-brief"      = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
    "generate-campaign" = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
    "check-compliance"  = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
    "get-campaigns"     = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
    "get-insights"      = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
    "update-approval"   = { trust_service = "lambda.amazonaws.com", policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"] }
  }

  # ── IAM Policies ────────────────────────────────────
  iam_policies = {
    "lambda-data-access" = {
      description = "Grants access to project-specific S3 buckets, DynamoDB tables, and SQS queues."
      policy_document = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "S3Access"
            Effect   = "Allow"
            Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
            Resource = flatten([for arn in values(local.s3_arns) : [arn, "${arn}/*"]])
          },
          {
            Sid      = "DynamoAccess"
            Effect   = "Allow"
            Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"]
            Resource = flatten([for arn in values(local.ddb_arns) : [arn, "${arn}/index/*"]])
          },
          {
            Sid      = "SQSAccess"
            Effect   = "Allow"
            Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
            Resource = values(local.sqs_arns)
          }
        ]
      })
    }
    "bedrock-agent-invoke" = {
      description = "Allows invocation of Bedrock models and agents."
      policy_document = jsonencode({
        Version = "2012-10-17"
        Statement = [{
          Sid      = "BedrockInvoke"
          Effect   = "Allow"
          Action   = ["bedrock:InvokeAgent", "bedrock:InvokeModel"]
          Resource = ["*"]
        }]
      })
    }
    "bedrock-kb-access" = {
      description = "Grants Bedrock Knowledge Base access to S3 rag-docs and retrieval actions."
      policy_document = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "BedrockKB"
            Effect   = "Allow"
            Action   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate", "bedrock:IngestKnowledgeBaseDocuments"]
            Resource = ["*"]
          },
          {
            Sid      = "S3KBDocs"
            Effect   = "Allow"
            Action   = ["s3:GetObject", "s3:ListBucket"]
            Resource = [local.s3_arns["rag-docs"], "${local.s3_arns["rag-docs"]}/*"]
          }
        ]
      })
    }
  }

  role_policy_attachments = {
    "submit-brief-data"      = { role = "submit-brief", policy = "lambda-data-access" }
    "generate-campaign-data" = { role = "generate-campaign", policy = "lambda-data-access" }
    "get-campaigns-data"     = { role = "get-campaigns", policy = "lambda-data-access" }
    "get-insights-data"      = { role = "get-insights", policy = "lambda-data-access" }
    "update-approval-data"   = { role = "update-approval", policy = "lambda-data-access" }
    "check-compliance-data"  = { role = "check-compliance", policy = "lambda-data-access" }

    "generate-campaign-bedrock" = { role = "generate-campaign", policy = "bedrock-agent-invoke" }
    "check-compliance-bedrock"  = { role = "check-compliance", policy = "bedrock-agent-invoke" }

    "bedrock-kb-data"      = { role = "bedrock-kb", policy = "bedrock-kb-access" }
    "bedrock-agent-invoke" = { role = "bedrock-agent", policy = "bedrock-agent-invoke" }
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
        timeout       = 300
        memory_size   = 1024
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
