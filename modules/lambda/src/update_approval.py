import json
import boto3
import os
import time

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['CAMPAIGN_TABLE'])

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    path_parameters = event.get('pathParameters') or {}
    campaign_id = path_parameters.get('id')
    
    try:
        body = json.loads(event.get('body', '{}'))
        product_name = body.get('product_name') # Frontend must provide this
        status = body.get('approval_status')
        notes = body.get('reviewer_notes', '')
        
        if not product_name:
             return {
                "statusCode": 400,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "Missing product_name in request body"})
            }

        table.update_item(
            Key={
                'campaign_id': campaign_id,
                'product_name': product_name
            },
            UpdateExpression="SET approval_status = :s, reviewer_notes = :n, reviewed_at = :t, reviewed_by = :r",
            ExpressionAttributeValues={
                ':s': status,
                ':n': notes,
                ':t': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                ':r': 'reviewer@company.com'
            }
        )
        
        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": "Approval status updated"})
        }
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }
