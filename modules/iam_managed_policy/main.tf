resource "aws_iam_policy" "this" {
  name        = "${var.project_name}-${var.environment}-${var.policy_key}-policy"
  description = var.description
  policy      = var.policy_document
}
