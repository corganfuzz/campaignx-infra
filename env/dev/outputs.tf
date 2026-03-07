output "knowledge_base_sync_command" {
  description = "Execution command to synchronize PDF data into the Knowledge Base"
  value       = "To sync your PDFs, run the following command from the root:\n./scripts/sync_kb.sh ${module.infrastructure.bedrock_kb_id} ${module.infrastructure.bedrock_data_source_id}"
}

output "api_url" {
  description = "The Invoke URL for the API Gateway"
  value       = module.infrastructure.api_url
}