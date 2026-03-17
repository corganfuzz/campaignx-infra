module "storage" {
  for_each = var.s3_buckets
  source   = "../modules/storage"

  project_name = var.project_name
  environment  = var.environment
  bucket_key   = each.key
  versioning   = each.value.versioning

  cors_rules = each.key == "outputs" ? [
    {
      allowed_headers = ["*"]
      allowed_methods = ["GET", "HEAD", "PUT", "POST"]
      allowed_origins = ["*"]
      expose_headers  = ["ETag", "Content-Disposition"]
      max_age_seconds = 3600
    }
  ] : []
}

module "dynamodb" {
  for_each = var.dynamodb_tables
  source   = "../modules/dynamodb"

  project_name = var.project_name
  environment  = var.environment
  table_key    = each.key
}

module "sqs" {
  for_each = var.sqs_queues
  source   = "../modules/sqs"

  project_name = var.project_name
  environment  = var.environment
  queue_key    = each.key
}

module "guardrails" {
  for_each = var.guardrails
  source   = "../modules/guardrails"

  project_name     = var.project_name
  environment      = var.environment
  guardrail_key    = each.key
  guardrail_config = each.value
}

module "iam" {
  for_each = var.iam_roles
  source   = "../modules/iam"

  project_name  = var.project_name
  environment   = var.environment
  role_key      = each.key
  trust_service = each.value.trust_service
  policy_arns   = each.value.policy_arns
}

module "iam_managed_policy" {
  for_each = var.iam_policies
  source   = "../modules/iam_managed_policy"

  project_name    = var.project_name
  environment     = var.environment
  policy_key      = each.key
  description     = each.value.description
  policy_document = each.value.policy_document
}

module "role_policy_attachment" {
  for_each = var.role_policy_attachments
  source   = "../modules/iam_role_policy_attachment"

  role_name  = module.iam[each.value.role].role_name
  policy_arn = module.iam_managed_policy[each.value.policy].policy_arn
}

module "bedrock" {
  for_each = var.enable_ai_engine ? { "enabled" = true } : {}
  source   = "../modules/bedrock"

  project_name           = var.project_name
  environment            = var.environment
  aws_region             = var.aws_region
  kb_s3_bucket_arn       = module.storage["rag-docs"].bucket_arn
  kb_s3_bucket_name      = module.storage["rag-docs"].bucket_name
  bedrock_kb_role_arn    = module.iam["bedrock-kb"].role_arn
  bedrock_kb_role_name   = module.iam["bedrock-kb"].role_name
  bedrock_agent_role_arn = module.iam["bedrock-agent"].role_arn
  bedrock_config         = var.bedrock_config
  guardrail_id           = module.guardrails["default"].guardrail_id

  lambda_creative_arn   = module.lambda["generate-campaign"].function_arn
  lambda_compliance_arn = module.lambda["check-compliance"].function_arn
}

module "lambda" {
  for_each = var.lambda_functions
  source   = "../modules/lambda"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  function_name   = each.key
  lambda_role_arn = module.iam[each.value.role].role_arn
  lambda_config   = each.value.config
  source_dir      = "${path.module}/../modules/lambda/src"

  environment_variables = merge(each.value.env_vars, {
    CAMPAIGN_TABLE = module.dynamodb["campaigns"].table_name
    OUTPUTS_BUCKET = module.storage["outputs"].bucket_name
    ASSETS_BUCKET  = module.storage["assets-input"].bucket_name
    RAG_BUCKET     = module.storage["rag-docs"].bucket_name
    SQS_QUEUE_URL  = module.sqs["campaign-gen"].queue_url
    SQS_QUEUE_ARN  = module.sqs["campaign-gen"].queue_arn
    PROJECT_NAME   = var.project_name
    ENVIRONMENT    = var.environment
    GUARDRAIL_ID   = module.guardrails["default"].guardrail_id
  })

  sqs_trigger_arn    = each.key == "generate-campaign" ? module.sqs["campaign-gen"].queue_arn : null
  create_sqs_trigger = each.key == "generate-campaign"

  api_gateway_execution_arn = try(module.api_gateway["enabled"].api_execution_arn, null)
  create_apigw_permission   = contains(["submit-brief", "get-campaigns", "get-insights", "update-approval"], each.key)
  create_bedrock_permission = contains(["generate-campaign", "check-compliance"], each.key)
}

module "api_gateway" {
  for_each = var.enable_ai_engine ? { "enabled" = true } : {}
  source   = "../modules/api_gateway"

  project_name = var.project_name
  environment  = var.environment

  lambda_integrations = {
    "submit-brief"    = module.lambda["submit-brief"].invoke_arn
    "get-campaigns"   = module.lambda["get-campaigns"].invoke_arn
    "get-insights"    = module.lambda["get-insights"].invoke_arn
    "update-approval" = module.lambda["update-approval"].invoke_arn
  }
}

resource "aws_s3_object" "rag_docs" {
  for_each = fileset("${path.module}/../rag-resource", "**/*.txt")

  bucket = module.storage["rag-docs"].bucket_name
  key    = "guidelines/${each.value}"
  source = "${path.module}/../rag-resource/${each.value}"
  etag   = filemd5("${path.module}/../rag-resource/${each.value}")
}

resource "aws_s3_object" "product_assets" {
  for_each = fileset("${path.module}/../scripts/images", "**/*.{png,jpg,jpeg}")

  bucket = module.storage["assets-input"].bucket_name
  key    = "products/${each.value}"
  source = "${path.module}/../scripts/images/${each.value}"
  etag   = filemd5("${path.module}/../scripts/images/${each.value}")
}

resource "terraform_data" "kb_sync" {
  depends_on = [aws_s3_object.rag_docs, aws_s3_object.product_assets, module.bedrock]

  triggers_replace = [
    timestamp()
  ]

  provisioner "local-exec" {
    command = "${path.module}/../scripts/sync_kb.sh ${module.bedrock["enabled"].kb_id} ${module.bedrock["enabled"].data_source_id}"
  }
}
