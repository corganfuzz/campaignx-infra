#!/bin/bash

BUCKET_NAME="concrete-fc-tfstate-$(aws sts get-caller-identity --query Account --output text)"
REGION="us-east-1"

read -p "Confirm deletion of s3://$BUCKET_NAME [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    aws s3 rm "s3://$BUCKET_NAME" --recursive
    aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$REGION"
fi
