data "aws_caller_identity" "current" {}

# ── OpenSearch Serverless (OSS) Policies ───────────────
resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.project_name}-${var.environment}-oss-net"
  type = "network"
  policy = jsonencode([
    {
      Description = "Public access for OSS"
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${var.project_name}-${var.environment}-kb"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${var.project_name}-${var.environment}-kb"]
        }
      ]
      AllowFromPublic = true
    }
  ])
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.project_name}-${var.environment}-oss-enc"
  type = "encryption"
  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${var.project_name}-${var.environment}-kb"]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_access_policy" "this" {
  name = "${var.project_name}-${var.environment}-access"
  type = "data"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "index"
          Resource     = ["index/${var.project_name}-${var.environment}-kb/*"]
          Permission = [
            "aoss:ReadDocument",
            "aoss:WriteDocument",
            "aoss:CreateIndex",
            "aoss:DeleteIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex"
          ]
        },
        {
          ResourceType = "collection"
          Resource     = ["collection/${var.project_name}-${var.environment}-kb"]
          Permission = [
            "aoss:CreateCollectionItems",
            "aoss:DeleteCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems"
          ]
        }
      ]
      Principal = [var.bedrock_kb_role_arn, data.aws_caller_identity.current.arn]
    }
  ])
}

# Attach OSS API access directly to the KB role
resource "aws_iam_role_policy" "oss_access" {
  name = "${var.project_name}-${var.environment}-oss-access"
  role = var.bedrock_kb_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "aoss:APIAccessAll"
        Resource = aws_opensearchserverless_collection.kb_collection.arn
      }
    ]
  })
}

# ── OSS Collection ─────────────────────────────────────
resource "aws_opensearchserverless_collection" "kb_collection" {
  name       = "${var.project_name}-${var.environment}-kb"
  type       = "VECTORSEARCH"
  depends_on = [aws_opensearchserverless_security_policy.encryption, aws_opensearchserverless_security_policy.network]
}

resource "time_sleep" "wait_for_oss_policy" {
  depends_on      = [aws_opensearchserverless_access_policy.this, aws_iam_role_policy.oss_access]
  create_duration = "60s"
}

# ── OSS Index Creation ─────────────────────────────────
resource "opensearch_index" "kb_index" {
  name               = var.bedrock_config.vector_index_name
  number_of_shards   = 2
  number_of_replicas = 0
  index_knn          = true

  mappings = jsonencode({
    properties = {
      "bedrock-embedding" = {
        type      = "knn_vector"
        dimension = 1024 # Titan Embed v2 (standard)
        method = {
          name       = "hnsw"
          engine     = "faiss"
          space_type = "l2"
        }
      }
      "AMAZON_BEDROCK_METADATA" = {
        type  = "text"
        index = false
      }
      "AMAZON_BEDROCK_TEXT_CHUNK" = {
        type  = "text"
        index = true
      }
    }
  })

  force_destroy = true
  depends_on    = [time_sleep.wait_for_oss_policy]
}

# ── Bedrock Knowledge Base (KB) ──────────────────────
resource "time_sleep" "wait_for_iam" {
  create_duration = "60s"
}

resource "aws_bedrockagent_knowledge_base" "main" {
  depends_on = [opensearch_index.kb_index, time_sleep.wait_for_iam]
  name       = "${var.project_name}-${var.environment}-kb"
  role_arn   = var.bedrock_kb_role_arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = var.bedrock_config.embedding_model_arn
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb_collection.arn
      vector_index_name = var.bedrock_config.vector_index_name
      field_mapping {
        vector_field   = "bedrock-embedding"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }
}

resource "aws_bedrockagent_data_source" "main" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.main.id
  name              = "${var.project_name}-${var.environment}-ds"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = var.kb_s3_bucket_arn
    }
  }
}

# ── Agent ───────────────────────────────────────────────────────
resource "aws_bedrockagent_agent" "orchestrator" {
  depends_on              = [time_sleep.wait_for_iam]
  agent_name              = "${var.project_name}-${var.environment}-campaign-orchestrator"
  agent_resource_role_arn = var.bedrock_agent_role_arn
  foundation_model        = var.bedrock_config.foundation_model
  instruction             = file("${path.module}/src/agent.txt")

}

resource "aws_bedrockagent_agent_action_group" "creative" {
  agent_id          = aws_bedrockagent_agent.orchestrator.id
  agent_version     = "DRAFT"
  action_group_name = "CreativeStrategy"
  prepare_agent     = false
  action_group_executor {
    lambda = var.lambda_creative_arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "generate_creative_concepts"
        description = "Generates localized ad copy and visual concepts for a product."
        parameters {
          map_block_key = "product_name"
          description   = "The name of the product"
          type          = "string"
          required      = true
        }
        parameters {
          map_block_key = "market_trends"
          description   = "Cultural and marketing trends retrieved from the Knowledge Base"
          type          = "string"
          required      = true
        }
      }
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "compliance" {
  agent_id          = aws_bedrockagent_agent.orchestrator.id
  agent_version     = "DRAFT"
  action_group_name = "ComplianceCheck"
  prepare_agent     = false
  action_group_executor {
    lambda = var.lambda_compliance_arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "validate_brand_compliance"
        description = "Passes generated copy and concepts through brand and legal guardrails."
        parameters {
          map_block_key = "creative_copy"
          description   = "The localization ad copy to validate"
          type          = "string"
          required      = true
        }
      }
    }
  }
}

resource "aws_bedrockagent_agent_knowledge_base_association" "kb_association" {
  agent_id             = aws_bedrockagent_agent.orchestrator.id
  agent_version        = "DRAFT"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.main.id
  knowledge_base_state = "ENABLED"
  description          = "KB for brand guidelines and trends"
}

# ── Agent Alias ──────────────────────────────────────────────────
# Stable endpoint for Lambda to call
resource "aws_bedrockagent_agent_alias" "dev" {
  agent_id         = aws_bedrockagent_agent.orchestrator.id
  agent_alias_name = "dev-alias"
  description      = "Development alias"

  # Ensure we only create alias after everything is wired
  depends_on = [
    aws_bedrockagent_agent_action_group.creative,
    aws_bedrockagent_agent_action_group.compliance,
    aws_bedrockagent_agent_knowledge_base_association.kb_association
  ]
}

# Wait for agent preparation to settle
resource "time_sleep" "wait_for_agent" {
  depends_on      = [aws_bedrockagent_agent_alias.dev]
  create_duration = "30s"
}
