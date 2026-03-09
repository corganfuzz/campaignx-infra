variable "project_name" { type = string }
variable "environment" { type = string }
variable "bucket_key" { type = string }
variable "versioning" { type = bool }

variable "cors_rules" {
  description = "Optional CORS rules for the bucket"
  type = list(object({
    allowed_headers = list(string)
    allowed_methods = list(string)
    allowed_origins = list(string)
    expose_headers  = optional(list(string), [])
    max_age_seconds = optional(number, 3000)
  }))
  default = []
}
