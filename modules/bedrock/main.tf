# The Vector Store
data "aws_caller_identity" "current" {}

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.project_name}-${var.environment}-oss-net"
  type = "network"
  policy = jsonencode([
    {
      Description = "Public access for OSS"
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${var.project_name}-${var.environment}-collection"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${var.project_name}-${var.environment}-collection"]
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
        Resource     = ["collection/${var.project_name}-${var.environment}-collection"]
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
          Resource     = ["index/${var.project_name}-${var.environment}-collection/*"]
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
          Resource     = ["collection/${var.project_name}-${var.environment}-collection"]
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

resource "aws_iam_role_policy" "oss_access" {
  name = "${var.project_name}-${var.environment}-oss-access"
  role = var.bedrock_kb_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "aoss:APIAccessAll"
        Resource = aws_opensearchserverless_collection.this.arn
      }
    ]
  })
}

resource "aws_opensearchserverless_collection" "this" {
  name       = "${var.project_name}-${var.environment}-collection"
  type       = "VECTORSEARCH"
  depends_on = [aws_opensearchserverless_security_policy.encryption, aws_opensearchserverless_security_policy.network]
}

resource "time_sleep" "wait_for_oss_policy" {
  depends_on = [aws_opensearchserverless_access_policy.this, aws_iam_role_policy.oss_access]

  create_duration = "60s"
}

resource "opensearch_index" "this" {
  name               = var.bedrock_config.vector_index_name
  number_of_shards   = 2
  number_of_replicas = 0
  index_knn          = true

  mappings      = <<EOF
{
  "properties": {
    "bedrock-knowledge-base-default-vector": {
      "type": "knn_vector",
      "dimension": 1024,
      "method": {
        "name": "hnsw",
        "engine": "faiss",
        "space_type": "l2"
      }
    },
    "AMAZON_BEDROCK_METADATA": {
      "type": "text",
      "index": false
    },
    "AMAZON_BEDROCK_TEXT_CHUNK": {
      "type": "text",
      "index": true
    }
  }
}
EOF
  force_destroy = true
  depends_on    = [time_sleep.wait_for_oss_policy]
}

# Knowledge Base (KB)
resource "aws_bedrockagent_knowledge_base" "this_v2" {
  depends_on = [opensearch_index.this]
  name       = "${var.project_name}-${var.environment}-kb-v2"
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
      collection_arn    = aws_opensearchserverless_collection.this.arn
      vector_index_name = var.bedrock_config.vector_index_name
      field_mapping {
        vector_field   = "bedrock-knowledge-base-default-vector"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }
}

resource "aws_bedrockagent_data_source" "this_v2" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.this_v2.id
  name              = "${var.project_name}-${var.environment}-ds-v3"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = var.kb_s3_bucket_arn
      inclusion_prefixes = ["guidelines/"]
    }
  }
}

# Bedrock Agent
resource "aws_bedrockagent_agent" "this" {
  agent_name              = "${var.project_name}-${var.environment}-agent"
  agent_resource_role_arn = var.bedrock_agent_role_arn
  foundation_model        = var.bedrock_config.foundation_model
  instruction             = file("${path.module}/src/agent.txt")
}

resource "aws_bedrockagent_agent_action_group" "fred" {
  action_group_name          = "MortgageRateTools"
  agent_id                   = aws_bedrockagent_agent.this.id
  agent_version              = "DRAFT"
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = var.lambda_function_arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "fetch_mortgage_rates"
        description = "Synchronizes and ingests live mortgage indices (30yr, 15yr, 5yr ARM, 10yr Treasury) from the Federal Reserve (FRED) directly into our S3 Data Lake (Bronze layer)."
      }
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "databricks_expert" {
  action_group_name          = "DatabricksExpert"
  agent_id                   = aws_bedrockagent_agent.this.id
  agent_version              = "DRAFT"
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = var.databricks_bridge_lambda_arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "invoke_mortgage_expert"
        description = "Routes complex mortgage analysis queries to a specialized LLM on Databricks. Use for: detailed refinance scenarios, ARM vs fixed analysis, DTI edge cases, or any query requiring deep domain reasoning."
        parameters {
          map_block_key = "query"
          type          = "string"
          description   = "The mortgage-related question or analysis request"
          required      = true
        }
      }
    }
  }
}

resource "aws_bedrockagent_agent_knowledge_base_association" "this" {
  agent_id             = aws_bedrockagent_agent.this.id
  agent_version        = var.bedrock_config.agent_version
  knowledge_base_id    = aws_bedrockagent_knowledge_base.this_v2.id
  description          = "Access to ALL internal mortgage guidelines, DTI limits, and documentation standards. Use this first for all financing questions."
  knowledge_base_state = "ENABLED"
}
