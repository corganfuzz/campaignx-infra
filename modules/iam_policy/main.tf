data "aws_iam_policy_document" "broad_poc_policy" {
  statement {
    actions   = ["s3:*"]
    resources = flatten([for arn in var.storage_bucket_arns : ["${arn}", "${arn}/*"]])
  }
  statement {
    actions   = ["dynamodb:*"]
    resources = flatten([for arn in var.dynamodb_table_arns : ["${arn}", "${arn}/index/*"]])
  }
  statement {
    actions   = ["bedrock:*"]
    resources = ["*"]
  }
  statement {
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = ["*"]
  }
  statement {
    actions   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
    resources = ["*"]
  }
  statement {
    actions   = ["sns:Publish"]
    resources = ["*"]
  }
  statement {
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
    resources = ["*"]
  }
  statement {
    actions   = ["glue:GetTable", "glue:GetPartitions"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "poc_policy" {
  name   = "${var.project_name}-${var.environment}-poc-policy"
  policy = data.aws_iam_policy_document.broad_poc_policy.json
}
