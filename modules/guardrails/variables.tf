variable "project_name" { type = string }
variable "environment" { type = string }
variable "guardrail_key" { type = string }
variable "guardrail_config" {
  type = object({
    blocked_words = list(string)
    denied_topics = list(string)
  })
}
