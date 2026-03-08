#!/bin/bash

# ==============================================================================
# CampaignX Knowledge Base Sync Tool
# 
# This script triggers the ingestion job for the Bedrock Knowledge Base.
# Run this after updating files in the 'rag-docs' S3 bucket.
# ==============================================================================

set -e

# Support for passing IDs directly or via environment
KB_ID=${1:-$BEDROCK_KB_ID}
DS_ID=${2:-$BEDROCK_DATA_SOURCE_ID}
REGION=${AWS_REGION:-"us-east-1"}

if [ -z "$KB_ID" ] || [ -z "$DS_ID" ]; then
    echo "❌ Error: Missing Knowledge Base ID or Data Source ID."
    echo "Usage: ./sync_kb.sh <KB_ID> <DS_ID>"
    echo "Or set BEDROCK_KB_ID and BEDROCK_DATA_SOURCE_ID environment variables."
    exit 1
fi

echo "----------------------------------------------------------------"
echo "🚀 Starting CampaignX Knowledge Base Ingestion..."
echo "📍 Region:          $REGION"
echo "🆔 Knowledge Base:  $KB_ID"
echo "📂 Data Source:     $DS_ID"
echo "----------------------------------------------------------------"

# Start the ingestion job
JOB_INFO=$(aws bedrock-agent start-ingestion-job \
    --knowledge-base-id "$KB_ID" \
    --data-source-id "$DS_ID" \
    --region "$REGION")

JOB_ID=$(echo "$JOB_INFO" | grep -o '"ingestionJobId": "[^"]*' | cut -d'"' -f4)

if [ -n "$JOB_ID" ]; then
    echo "✅ Success! Ingestion Job started."
    echo "🆔 Job ID: $JOB_ID"
    echo "----------------------------------------------------------------"
    echo "Status: IN_PROGRESS"
    
    # Optional: Wait for completion (simple poll)
    echo "Waiting for completion..."
    while true; do
        STATUS_INFO=$(aws bedrock-agent get-ingestion-job \
            --knowledge-base-id "$KB_ID" \
            --data-source-id "$DS_ID" \
            --ingestion-job-id "$JOB_ID" \
            --region "$REGION")
        
        CURRENT_STATUS=$(echo "$STATUS_INFO" | grep -o '"status": "[^"]*' | cut -d'"' -f4)
        
        if [ "$CURRENT_STATUS" == "COMPLETE" ]; then
            echo "🏁 Sync COMPLETE!"
            break
        elif [ "$CURRENT_STATUS" == "FAILED" ]; then
            echo "❌ Sync FAILED!"
            echo "$STATUS_INFO"
            exit 1
        else
            echo "⏳ Status: $CURRENT_STATUS..."
            sleep 10
        fi
    done
else
    echo "❌ Error: Failed to start ingestion job."
    echo "$JOB_INFO"
    exit 1
fi
