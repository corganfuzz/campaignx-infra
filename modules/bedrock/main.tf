# ── Knowledge Base (OpenSearch Serverless) ─────────────────
resource "aws_opensearchserverless_collection" "kb_collection" {
  name = "${var.project_name}-${var.environment}-kb"
  type = "VECTORSEARCH"
}

# (In a real implementation you would also need data access policies, 
# network policies, and the actual index creation which often requires a Lambda custom resource.
# For this POC config, we just define the Bedrock KB resource pointing to the collection)

resource "time_sleep" "wait_for_iam" {
  create_duration = "60s"
}

resource "aws_bedrockagent_knowledge_base" "main" {
  depends_on = [time_sleep.wait_for_iam]
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

  prompt_override_configuration {
    prompt_configurations {
      prompt_type          = "ORCHESTRATION"
      base_prompt_template = file("${path.module}/src/agent.txt")
      prompt_state         = "ENABLED"
      prompt_creation_mode = "OVERRIDDEN"

      inference_configuration {
        temperature = 0.3
        top_p       = 0.9
        top_k       = 50
        max_length  = 2000
      }
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "creative" {
  agent_id          = aws_bedrockagent_agent.orchestrator.id
  agent_version     = "DRAFT"
  action_group_name = "CreativeStrategy"
  action_group_executor {
    lambda = var.lambda_creative_arn
  }
}

resource "aws_bedrockagent_agent_action_group" "compliance" {
  agent_id          = aws_bedrockagent_agent.orchestrator.id
  agent_version     = "DRAFT"
  action_group_name = "ComplianceCheck"
  action_group_executor {
    lambda = var.lambda_compliance_arn
  }
}

resource "aws_bedrockagent_agent_knowledge_base_association" "kb_association" {
  agent_id             = aws_bedrockagent_agent.orchestrator.id
  agent_version        = "DRAFT"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.main.id
  knowledge_base_state = "ENABLED"
  description          = "KB for brand guidelines and trends"
}
