variable "project_name" { type = string }
variable "environment" { type = string }
variable "enable_ai_engine" {
  type    = bool
  default = false
}
variable "aws_region" { type = string }

variable "s3_buckets" {
  description = "Map of S3 bucket configurations"
  type = map(object({
    versioning = bool
  }))
}

variable "iam_roles" {
  description = "Map of IAM role configurations"
  type = map(object({
    trust_service = string
  }))
}

variable "bedrock_config" {
  description = "Configuration for Bedrock Knowledge Base and Agent"
  type        = any
}

variable "lambdas" {
  description = "Map of Lambda function configurations"
  type        = any
}

