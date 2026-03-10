resource "aws_sqs_queue" "dlq" {
  name = "${var.project_name}-${var.environment}-${var.queue_key}-dlq"
}

resource "aws_sqs_queue" "this" {
  name                       = "${var.project_name}-${var.environment}-${var.queue_key}"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

