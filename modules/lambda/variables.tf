variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }

variable "function_name" { type = string }
variable "lambda_role_arn" { type = string }

variable "lambda_config" {
  type = object({
    runtime       = string
    handler       = string
    timeout       = number
    memory_size   = number
    architectures = list(string)
    layers        = optional(list(string), [])
  })
}

variable "source_dir" { type = string }
variable "environment_variables" { type = map(string) }

variable "sqs_trigger_arn" {
  type    = string
  default = null
}

variable "create_sqs_trigger" {
  type    = bool
  default = false
}

variable "api_gateway_execution_arn" {
  type    = string
  default = null
}

variable "create_apigw_permission" {
  type    = bool
  default = false
}

variable "create_bedrock_permission" {
  type    = bool
  default = false
}
