resource "aws_api_gateway_rest_api" "api" {
  name = "${var.project_name}-${var.environment}-api"
}

resource "aws_api_gateway_resource" "brief" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "brief"
}

resource "aws_api_gateway_method" "brief_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.brief.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "brief_post" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.brief.id
  http_method             = aws_api_gateway_method.brief_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["submit-brief"]
}

resource "aws_api_gateway_resource" "briefs" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "briefs"
}

resource "aws_api_gateway_resource" "briefs_batch" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.briefs.id
  path_part   = "batch"
}

resource "aws_api_gateway_method" "briefs_batch_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.briefs_batch.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "briefs_batch_post" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.briefs_batch.id
  http_method             = aws_api_gateway_method.briefs_batch_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["submit-brief"]
}

resource "aws_api_gateway_resource" "campaigns" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "campaigns"
}

resource "aws_api_gateway_method" "campaigns_get" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.campaigns.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "campaigns_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.campaigns.id
  http_method             = aws_api_gateway_method.campaigns_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["get-campaigns"]
}

resource "aws_api_gateway_resource" "campaigns_id" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.campaigns.id
  path_part   = "{id}"
}

resource "aws_api_gateway_method" "campaigns_id_get" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.campaigns_id.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "campaigns_id_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.campaigns_id.id
  http_method             = aws_api_gateway_method.campaigns_id_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["get-campaigns"]
}

resource "aws_api_gateway_resource" "campaigns_id_approval" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.campaigns_id.id
  path_part   = "approval"
}

resource "aws_api_gateway_method" "campaigns_id_approval_patch" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.campaigns_id_approval.id
  http_method      = "PATCH"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "campaigns_id_approval_patch" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.campaigns_id_approval.id
  http_method             = aws_api_gateway_method.campaigns_id_approval_patch.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["update-approval"]
}

resource "aws_api_gateway_resource" "insights" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "insights"
}

resource "aws_api_gateway_method" "insights_get" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.insights.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "insights_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.insights.id
  http_method             = aws_api_gateway_method.insights_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.lambda_integrations["get-insights"]
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  depends_on = [
    aws_api_gateway_integration.brief_post,
    aws_api_gateway_integration.briefs_batch_post,
    aws_api_gateway_integration.campaigns_get,
    aws_api_gateway_integration.campaigns_id_get,
    aws_api_gateway_integration.campaigns_id_approval_patch,
    aws_api_gateway_integration.insights_get,
  ]
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = var.environment
}

resource "aws_api_gateway_api_key" "key" {
  name = "${var.project_name}-${var.environment}-key"
}

resource "aws_api_gateway_usage_plan" "usage_plan" {
  name = "${var.project_name}-${var.environment}-usage-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.api_stage.stage_name
  }
}

resource "aws_api_gateway_usage_plan_key" "main" {
  key_id        = aws_api_gateway_api_key.key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.usage_plan.id
}


