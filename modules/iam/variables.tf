variable "project_name" { type = string }
variable "environment" { type = string }
variable "role_key" { type = string }
variable "trust_service" { type = string }
variable "policy_arns" {
  type    = list(string)
  default = []
}
