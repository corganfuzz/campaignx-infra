resource "aws_bedrock_guardrail" "this" {
  name                      = "${var.project_name}-${var.environment}-${var.guardrail_key}"
  description               = "CampaignX Guardrails for Brand and Legal Compliance"
  blocked_input_messaging   = "This prompt contains blocked language."
  blocked_outputs_messaging = "The generated response contains blocked language."

  content_policy_config {
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "HATE"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "VIOLENCE"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "SEXUAL"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "INSULTS"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "MISCONDUCT"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "PROMPT_ATTACK"
    }
  }

  topic_policy_config {
    dynamic "topics_config" {
      for_each = var.guardrail_config.denied_topics
      content {
        name       = replace(topics_config.value, " ", "_")
        definition = topics_config.value
        examples   = []
        type       = "DENY"
      }
    }
  }

  word_policy_config {
    dynamic "words_config" {
      for_each = var.guardrail_config.blocked_words
      content {
        text = words_config.value
      }
    }
  }
}

resource "aws_bedrock_guardrail_version" "this" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "Initial version"
}
