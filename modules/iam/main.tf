data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = [var.trust_service]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.project_name}-${var.environment}-${var.role_key}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

# Attach Lambda basic execution role if this is a Lambda role
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  count      = var.trust_service == "lambda.amazonaws.com" ? 1 : 0
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Attach any additional policy ARNs passed in
resource "aws_iam_role_policy_attachment" "additional" {
  count      = length(var.policy_arns)
  role       = aws_iam_role.this.name
  policy_arn = var.policy_arns[count.index]
}
