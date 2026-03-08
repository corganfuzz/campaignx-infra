data "archive_file" "this" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.root}/.terraform/lambda_builds/${var.function_name}.zip"
}

resource "aws_lambda_function" "this" {
  filename         = data.archive_file.this.output_path
  function_name    = "${var.project_name}-${var.environment}-${var.function_name}"
  role             = var.lambda_role_arn
  handler          = var.lambda_config.handler
  runtime          = var.lambda_config.runtime
  timeout          = var.lambda_config.timeout
  memory_size      = var.lambda_config.memory_size
  architectures    = var.lambda_config.architectures
  source_code_hash = data.archive_file.this.output_base64sha256

  layers = var.lambda_config.layers

  environment {
    variables = var.environment_variables
  }
}

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  for_each         = var.create_sqs_trigger ? { "enabled" = true } : {}
  event_source_arn = var.sqs_trigger_arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = 1
  scaling_config {
    maximum_concurrency = 10
  }
}

resource "aws_lambda_permission" "apigw" {
  for_each      = var.create_apigw_permission ? { "enabled" = true } : {}
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_gateway_execution_arn}/*/*"
}

resource "aws_lambda_permission" "bedrock" {
  for_each      = var.create_bedrock_permission ? { "enabled" = true } : {}
  statement_id  = "AllowExecutionFromBedrock"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "bedrock.amazonaws.com"
}
