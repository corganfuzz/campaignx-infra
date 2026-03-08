output "agent_id" {
  value = aws_bedrockagent_agent.orchestrator.id
}

output "agent_alias_id" {
  value = aws_bedrockagent_agent_alias.dev.agent_alias_id
}

output "kb_id" {
  value = aws_bedrockagent_knowledge_base.main.id
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.main.data_source_id
}

output "collection_endpoint" {
  value = aws_opensearchserverless_collection.kb_collection.collection_endpoint
}
