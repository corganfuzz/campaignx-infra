variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "enable_ai_engine" {
  type = bool
}

variable "s3_buckets" {
  type = map(object({
    versioning = bool
  }))
}

variable "iam_roles" {
  type = map(object({
    trust_service = string
  }))
}

variable "bedrock_config" {
  type = object({
    embedding_model_arn = string
    foundation_model    = string
    vector_index_name   = string
    agent_version       = string
  })
}

variable "dynamodb_tables" {
  type = map(any)
}

variable "sqs_queues" {
  type = map(any)
}


variable "guardrails" {
  type = map(object({
    blocked_words = list(string)
    denied_topics = list(string)
  }))
}


variable "lambda_functions" {
  type = map(object({
    role = string
    config = object({
      runtime       = string
      handler       = string
      timeout       = number
      memory_size   = number
      architectures = list(string)
      layers        = optional(list(string), [])
    })
    env_vars = map(string)
  }))
}

