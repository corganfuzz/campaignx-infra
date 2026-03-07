# output "vpcs" {
#   description = "Map of created VPCs and their properties"
#   value = {
#     for k, v in module.vpc : k => {
#       vpc_id             = v.vpc_id
#       public_subnet_ids  = module.subnets[k].public_subnet_ids
#       private_subnet_ids = module.subnets[k].private_subnet_ids
#     }
#   }
# }

output "s3_buckets" {
  value = module.storage.bucket_names
}

output "iam_roles" {
  value = module.iam.role_arns
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
  value = try(module.api_gateway["enabled"].api_url, "N/A - Module Disabled")
}

output "api_key" {
  value     = try(module.api_gateway["enabled"].api_key, "N/A - Module Disabled")
  sensitive = true
}
