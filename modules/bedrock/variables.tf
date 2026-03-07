variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment (dev/staging/prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "kb_s3_bucket_arn" {
  description = "ARN of the S3 bucket for Knowledge Base data source"
  type        = string
}

variable "kb_s3_bucket_name" {
  description = "Name of the S3 bucket for Knowledge Base data source"
  type        = string
}

variable "lambda_function_arn" {
  description = "ARN of the Agent's Action Group Lambda"
  type        = string
  default     = null
}

variable "databricks_bridge_lambda_arn" {
  description = "ARN of the Databricks Bridge Lambda"
  type        = string
  default     = null
}

variable "bedrock_kb_role_arn" {
  description = "IAM Role ARN for the Knowledge Base"
  type        = string
}

variable "bedrock_kb_role_name" {
  description = "IAM Role Name for the Knowledge Base (for attaching inline policies)"
  type        = string
}

variable "bedrock_agent_role_arn" {
  description = "IAM Role ARN for the Bedrock Agent"
  type        = string
}

variable "bedrock_config" {
  description = "Configuration for Bedrock Agent and KB"
  type = object({
    embedding_model_arn = string
    foundation_model    = string
    vector_index_name   = string
    agent_version       = string
  })
}
