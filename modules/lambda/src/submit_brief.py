import json
import boto3
import uuid
import os

sqs = boto3.client('sqs')
queue_url = os.environ['SQS_QUEUE_URL']

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    try:
        body = json.loads(event.get('body', '{}'))
        campaign_id = str(uuid.uuid4())
        
        # Add metadata
        body['campaignId'] = campaign_id
        
        # Send to SQS
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(body)
        )
        
        return {
            "statusCode": 202,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"campaignId": campaign_id})
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"error": str(e)})
        }
