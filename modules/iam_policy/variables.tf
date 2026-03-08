variable "project_name" { type = string }
variable "environment" { type = string }

variable "storage_bucket_arns" { type = list(string) }
variable "dynamodb_table_arns" { type = list(string) }
