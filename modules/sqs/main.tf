resource "aws_sqs_queue" "dlq" {
  name = "${var.project_name}-${var.environment}-${var.queue_key}-dlq"
}

resource "aws_sqs_queue" "this" {
  name                       = "${var.project_name}-${var.environment}-${var.queue_key}"
  visibility_timeout_seconds = 360   # 60s buffer above Lambda timeout of 300s
  message_retention_seconds  = 86400 # 1 day

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_cloudwatch_metric_alarm" "dlq_alarm" {
  alarm_name          = "${var.project_name}-${var.environment}-${var.queue_key}-dlq-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 0
  alarm_description   = "Alarm when messages are in DLQ"

  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }

  alarm_actions = [var.sns_topic_arn]
}
