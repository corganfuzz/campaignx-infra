output "s3_buckets" {
  value = { for k, v in module.storage : k => v.bucket_name }
}

output "iam_roles" {
  value = { for k, v in module.iam : k => v.role_arn }
}

output "bedrock_kb_id" {
  value = try(module.bedrock["enabled"].kb_id, "N/A - Module Disabled")
}

output "bedrock_data_source_id" {
  value = try(module.bedrock["enabled"].data_source_id, "N/A - Module Disabled")
}

output "bedrock_collection_endpoint" {
  value = try(module.bedrock["enabled"].collection_endpoint, "")
}

output "api_url" {
  value = try(module.api_gateway["enabled"].api_endpoint, "N/A - Module Disabled")
}

output "api_key" {
  value     = try(module.api_gateway["enabled"].api_key, "N/A - Module Disabled")
  sensitive = true
}
