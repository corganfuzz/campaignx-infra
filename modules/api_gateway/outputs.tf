output "api_endpoint" {
  value = aws_api_gateway_stage.api_stage.invoke_url
}

output "api_key" {
  value     = aws_api_gateway_api_key.key.value
  sensitive = true
}

output "api_execution_arn" {
  value = aws_api_gateway_rest_api.api.execution_arn
}
