import json
import boto3
import os
import time

bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')
bedrock_agent = boto3.client('bedrock-agent')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['CAMPAIGN_TABLE'])

# Global cache for discovery to save API calls
_DISCOVERY_CACHE = {}

def discover_agent_details():
    if 'agent_id' in _DISCOVERY_CACHE:
        return _DISCOVERY_CACHE['agent_id'], _DISCOVERY_CACHE['alias_id']
    
    project = os.environ.get('PROJECT_NAME', 'campaignx')
    env = os.environ.get('ENVIRONMENT', 'dev')
    target_agent_name = f"{project}-{env}-campaign-orchestrator"
    target_alias_name = "dev-alias"
    
    agents = bedrock_agent.list_agents().get('agentSummaries', [])
    agent_id = next((a['agentId'] for a in agents if a['agentName'] == target_agent_name), None)
    
    if not agent_id:
        raise Exception(f"Agent '{target_agent_name}' not found")
        
    # If in dev or explicitly requested, use the working DRAFT (TSTALIASID)
    # This ensures we pick up changes to the foundation model without needing 
    # to create a new version/update the alias every time.
    if env == 'dev' or os.environ.get('USE_DRAFT_AGENT') == 'true':
        alias_id = "TSTALIASID"
    else:
        aliases = bedrock_agent.list_agent_aliases(agentId=agent_id).get('agentAliasSummaries', [])
        alias_id = next((a['agentAliasId'] for a in aliases if a['agentAliasName'] == target_alias_name), "TSTALIASID")
        
    _DISCOVERY_CACHE['agent_id'] = agent_id
    _DISCOVERY_CACHE['alias_id'] = alias_id
    return agent_id, alias_id

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    if 'actionGroup' in event:
        action_group = event['actionGroup']
        function = event['function']
        parameters = {p['name']: p['value'] for p in event.get('parameters', [])}
        
        response_text = f"Localized strategy for {parameters.get('product_name')}. Recommended focus: {parameters.get('market_trends', 'Generic trends')[:100]}..."
        
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": function,
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": response_text
                        }
                    }
                }
            }
        }

    if 'Records' in event:
        for record in event['Records']:
            body = json.loads(record['body'])
            campaign_id = body.get('campaignId')
            products = body.get('products', ["Generic"])
            
            for product_name in products:
                prompt = f"""
                Generate a localized campaign for:
                Product: {product_name}
                Region: {body.get('region')}
                Audience: {body.get('audience')}
                Message: {body.get('message')}
                Language: {body.get('language')}
                """
                
                try:
                    agent_id, alias_id = discover_agent_details()
                    response = bedrock_agent_runtime.invoke_agent(
                        agentId=agent_id,
                        agentAliasId=alias_id,
                        sessionId=campaign_id,
                        inputText=prompt
                    )
                    
                    completion = ""
                    for event in response.get('completion'):
                        chunk = event.get('chunk')
                        if chunk:
                            completion += chunk.get('bytes').decode()
                    
                    # Image Lookup
                    image_url = ""
                    try:
                        product_search = product_name.replace(" ", "-")
                        s3_client = boto3.client('s3')
                        assets_bucket = os.environ['ASSETS_BUCKET']
                        objs = s3_client.list_objects_v2(Bucket=assets_bucket, Prefix=f"products/{product_search}")
                        if 'Contents' in objs:
                            image_key = objs['Contents'][0]['Key']
                            image_url = f"https://{assets_bucket}.s3.amazonaws.com/{image_key}"
                    except: pass

                    blueprint = {
                        "campaign_id": campaign_id,
                        "product_name": product_name,
                        "region": body.get('region'),
                        "audience": body.get('audience'),
                        "message": body.get('message'),
                        "strategy": completion,
                        "images": {
                            "1x1":  {"url": image_url, "format": "Instagram Feed",     "dimensions": "1080 × 1080px", "ratio": "1x1"},
                            "9x16": {"url": image_url, "format": "TikTok / Reels",     "dimensions": "1080 × 1920px", "ratio": "9x16"},
                            "16x9": {"url": image_url, "format": "YouTube / Facebook", "dimensions": "1920 × 1080px", "ratio": "16x9"},
                        },
                        "adCopy": [{"lang": body.get('language'), "text": completion}],
                        "approval_status": "pending_review",
                        "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    }
                    
                    table.put_item(Item=blueprint)
                    
                except Exception as e:
                    print(f"Error for {product_name}: {str(e)}")
        
        return {"statusCode": 200}
