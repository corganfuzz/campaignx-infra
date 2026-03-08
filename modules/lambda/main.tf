data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${var.source_dir}/${replace(var.function_name, "-", "_")}.py"
  output_path = "${path.module}/build/${var.function_name}.zip"
}

resource "aws_lambda_function" "function" {
  function_name    = "${var.project_name}-${var.environment}-${var.function_name}"
  role             = var.lambda_role_arn
  handler          = var.lambda_config.handler
  runtime          = var.lambda_config.runtime
  timeout          = var.lambda_config.timeout
  memory_size      = var.lambda_config.memory_size
  architectures    = var.lambda_config.architectures
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = var.environment_variables
  }
}

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  count            = var.create_sqs_trigger ? 1 : 0
  event_source_arn = var.sqs_trigger_arn
  function_name    = aws_lambda_function.function.arn
  batch_size       = 1
  scaling_config {
    maximum_concurrency = 10
  }
}

resource "aws_lambda_permission" "apigw" {
  count         = var.create_apigw_permission ? 1 : 0
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.function.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_gateway_execution_arn}/*/*"
}

resource "aws_lambda_permission" "bedrock" {
  count         = var.create_bedrock_permission ? 1 : 0
  statement_id  = "AllowExecutionFromBedrock"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.function.function_name
  principal     = "bedrock.amazonaws.com"
}
