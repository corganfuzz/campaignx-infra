variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }

variable "kb_s3_bucket_arn" { type = string }
variable "kb_s3_bucket_name" { type = string }
variable "bedrock_kb_role_arn" { type = string }
variable "bedrock_kb_role_name" { type = string }
variable "bedrock_agent_role_arn" { type = string }

variable "bedrock_config" {
  type = object({
    embedding_model_arn = string
    foundation_model    = string
    vector_index_name   = string
    agent_version       = string
  })
}

variable "guardrail_id" { type = string }

variable "lambda_creative_arn" { type = string }

variable "enable_kb_sync" {
  description = "Whether to trigger an initial sync of the Knowledge Base"
  type        = bool
  default     = false
}

variable "sync_dependency" {
  description = "A list of resources to wait for before performing the sync"
  type        = any
  default     = []
}
