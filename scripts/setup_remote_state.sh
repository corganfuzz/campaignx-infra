#!/bin/bash

BUCKET_NAME="concrete-fc-tfstate-$(aws sts get-caller-identity --query Account --output text)"
REGION="us-east-1"

if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
    echo "State bucket exists: $BUCKET_NAME"
else
    echo "Creating S3 bucket: $BUCKET_NAME"
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION"
fi
