import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['CAMPAIGN_TABLE']
table = dynamodb.Table(table_name)

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    path_parameters = event.get('pathParameters') or {}
    campaign_id = path_parameters.get('id')
    
    try:
        if campaign_id:
            # Query by campaign_id (the hash key)
            from boto3.dynamodb.conditions import Key
            response = table.query(
                KeyConditionExpression=Key('campaign_id').eq(campaign_id)
            )
            items = response.get('Items', [])
            
            if not items:
                return {
                    "statusCode": 404,
                    "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
                    "body": json.dumps({"error": f"Campaign {campaign_id} not found"})
                }
            
            # Since one campaign might have multiple product blueprints in this schema, 
            # we return the list or the first one aggregated.
            return {
                "statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
                "body": json.dumps({
                    "id": campaign_id,
                    "blueprints": items
                })
            }
        else:
            # List all (Scan)
            response = table.scan()
            return {
                "statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
                "body": json.dumps(response.get('Items', []))
            }
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }
