output "bucket_name" {
  value = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.this.arn
}

output "initial_content_ids" {
  value = [for obj in aws_s3_object.content : obj.id]
}
