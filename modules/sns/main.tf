resource "aws_sns_topic" "this" {
  name = "${var.project_name}-${var.environment}-${var.topic_key}"
}

resource "aws_sns_topic_subscription" "email_sub" {
  topic_arn = aws_sns_topic.this.arn
  protocol  = "email"
  endpoint  = var.email_recipient
}
