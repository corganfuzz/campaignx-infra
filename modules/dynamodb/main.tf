resource "aws_dynamodb_table" "this" {
  name         = "${var.project_name}-${var.environment}-${var.table_key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "campaign_id"
  range_key    = "product_name"

  attribute {
    name = "campaign_id"
    type = "S"
  }

  attribute {
    name = "product_name"
    type = "S"
  }

  attribute {
    name = "approval_status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "approval_status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
