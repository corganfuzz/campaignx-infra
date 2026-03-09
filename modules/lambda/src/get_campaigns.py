import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['CAMPAIGN_TABLE']
table = dynamodb.Table(table_name)

ASSETS_BUCKET  = os.environ.get('ASSETS_BUCKET', '')
OUTPUTS_BUCKET = os.environ.get('OUTPUTS_BUCKET', '')

def _bucket_for_key(key: str) -> str:
    """Route the key to the correct S3 bucket based on prefix."""
    if key.startswith('generated/'):
        return OUTPUTS_BUCKET
    return ASSETS_BUCKET  # 'products/' reference photos

def _refresh_presigned_urls(item: dict) -> dict:
    """Re-generate pre-signed URLs for all image ratios so they never expire."""
    images = item.get('images', {})
    if not images:
        return item

    s3 = boto3.client('s3')
    refreshed = {}
    for ratio, img in images.items():
        key = img.get('key') or ''
        url = img.get('url') or ''

        if key:
            bucket = _bucket_for_key(key)
            try:
                url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket, 'Key': key},
                    ExpiresIn=604800  # 7 days
                )
            except Exception as e:
                print(f"Could not re-sign {key} from {bucket}: {e}")

        refreshed[ratio] = {**img, 'url': url}

    return {**item, 'images': refreshed}


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
            
            # Re-sign image URLs for each blueprint
            refreshed_items = [_refresh_presigned_urls(item) for item in items]

            return {
                "statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
                "body": json.dumps({
                    "id": campaign_id,
                    "blueprints": refreshed_items
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
