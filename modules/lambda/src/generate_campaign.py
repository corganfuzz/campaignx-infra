import json
import boto3
import os
import time
import base64
import re

bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')
bedrock_agent         = boto3.client('bedrock-agent')
bedrock_runtime       = boto3.client('bedrock-runtime')
dynamodb              = boto3.resource('dynamodb')
s3_client             = boto3.client('s3')

table          = dynamodb.Table(os.environ['CAMPAIGN_TABLE'])
ASSETS_BUCKET  = os.environ['ASSETS_BUCKET']
OUTPUTS_BUCKET = os.environ['OUTPUTS_BUCKET']

# Global cache for discovery to save API calls
_DISCOVERY_CACHE = {}


def discover_agent_details():
    if 'agent_id' in _DISCOVERY_CACHE:
        return _DISCOVERY_CACHE['agent_id'], _DISCOVERY_CACHE['alias_id']

    project = os.environ.get('PROJECT_NAME', 'campaignx')
    env     = os.environ.get('ENVIRONMENT', 'dev')
    target_agent_name = f"{project}-{env}-campaign-orchestrator"

    agents   = bedrock_agent.list_agents().get('agentSummaries', [])
    agent_id = next((a['agentId'] for a in agents if a['agentName'] == target_agent_name), None)

    if not agent_id:
        raise Exception(f"Agent '{target_agent_name}' not found")

    # In dev use the DRAFT alias so changes are instantly reflected
    alias_id = "TSTALIASID" if (env == 'dev' or os.environ.get('USE_DRAFT_AGENT') == 'true') else (
        next(
            (a['agentAliasId'] for a in bedrock_agent.list_agent_aliases(agentId=agent_id).get('agentAliasSummaries', [])
             if a['agentAliasName'] == 'dev-alias'),
            "TSTALIASID"
        )
    )

    _DISCOVERY_CACHE['agent_id'] = agent_id
    _DISCOVERY_CACHE['alias_id'] = alias_id
    return agent_id, alias_id


def extract_image_prompt(agent_text: str, product: str, region: str, audience: str, message: str) -> str:
    """
    Try to pull a dedicated image prompt from the agent response.
    Falls back to a rich marketing prompt if none is found.
    """
    # Look for explicit image prompt section from agent
    patterns = [
        r'(?:image prompt|visual prompt|image generation prompt)[:\s]+([^\n]{20,})',
        r'(?:DALL-E|Stable Diffusion|Nova Canvas)[:\s]+([^\n]{20,})',
    ]
    for pat in patterns:
        m = re.search(pat, agent_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:500]

    # Synthesize a strong marketing prompt from context
    return (
        f"Professional advertising photograph for {product}. "
        f"Target audience: {audience}. Region: {region}. "
        f"Campaign message: '{message}'. "
        f"High-production-quality commercial photography, studio lighting, "
        f"vivid brand colors, clean composition, 4K, editorial style."
    )


def generate_image_with_nova_canvas(image_prompt: str, campaign_id: str, product_name: str, ratio: str) -> tuple[str, str]:
    """
    Call Amazon Nova Canvas to generate a campaign image.
    Returns (s3_key, presigned_url).
    Ratio sizes: 1x1 → 1024×1024, 9x16 → 768×1280, 16x9 → 1280×768
    """
    size_map = {
        '1x1':  (1024, 1024),
        '9x16': (768,  1280),
        '16x9': (1280, 768),
    }
    width, height = size_map.get(ratio, (1024, 1024))

    body = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": image_prompt,
            "negativeText": "blurry, low quality, text overlays, watermarks, distorted faces, signature"
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width":  width,
            "height": height,
            "cfgScale": 8.0,
            "quality": "standard"
        }
    })

    response = bedrock_runtime.invoke_model(
        modelId='amazon.nova-canvas-v1:0',
        body=body,
        contentType='application/json',
        accept='application/json'
    )

    result     = json.loads(response['body'].read())
    image_b64  = result['images'][0]
    image_data = base64.b64decode(image_b64)

    # Save to S3 outputs bucket
    safe_product = re.sub(r'[^a-zA-Z0-9\-_]', '-', product_name)
    s3_key = f"generated/{campaign_id}/{safe_product}/{ratio}.png"

    s3_client.put_object(
        Bucket=OUTPUTS_BUCKET,
        Key=s3_key,
        Body=image_data,
        ContentType='image/png'
    )

    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': OUTPUTS_BUCKET, 'Key': s3_key},
        ExpiresIn=604800  # 7 days
    )

    return s3_key, presigned_url


def get_reference_image_url(product_name: str) -> tuple[str, str]:
    """Fallback: find the uploaded product reference image in the assets bucket."""
    product_search = product_name.replace(' ', '-')
    objs = s3_client.list_objects_v2(Bucket=ASSETS_BUCKET, Prefix=f'products/{product_search}')
    if 'Contents' in objs:
        key = objs['Contents'][0]['Key']
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': ASSETS_BUCKET, 'Key': key},
            ExpiresIn=604800
        )
        return key, url
    return '', ''


# ─── Action Group Handler (called by Bedrock Agent) ──────────────────────────
def handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    if 'actionGroup' in event:
        action_group = event['actionGroup']
        function     = event['function']
        parameters   = {p['name']: p['value'] for p in event.get('parameters', [])}

        response_text = (
            f"Creative strategy for {parameters.get('product_name', 'the product')} "
            f"targeting {parameters.get('market_trends', 'general market')}:\n\n"
            f"Strategy: Focus on aspirational lifestyle imagery and authentic storytelling. "
            f"Headline: 'Built for every adventure.' "
            f"Body copy: Engineered for performance, designed for the journey ahead. "
            f"Image prompt: A professional outdoor adventure photograph showing {parameters.get('product_name', 'a premium product')} "
            f"in a dramatic mountain landscape at golden hour, high-production commercial photography, vivid colors."
        )

        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": function,
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {"body": response_text}
                    }
                }
            }
        }

    # ─── SQS Trigger (main campaign generation flow) ─────────────────────────
    if 'Records' in event:
        for record in event['Records']:
            body        = json.loads(record['body'])
            campaign_id = body.get('campaignId')
            products    = body.get('products', ['Generic Product'])

            for product_name in products:
                region   = body.get('region', 'us')
                audience = body.get('audience', 'General')
                message  = body.get('message', '')
                language = body.get('language', 'en')

                prompt = (
                    f"Generate a complete localized advertising campaign for:\n"
                    f"Product: {product_name}\n"
                    f"Region: {region}\n"
                    f"Audience: {audience}\n"
                    f"Core message: {message}\n"
                    f"Language: {language}\n\n"
                    f"Please provide: 1) Creative strategy 2) Ad copy headline and body 3) An image generation prompt "
                    f"suitable for Amazon Nova Canvas that captures the campaign's visual direction."
                )

                try:
                    # ── Step 1: Invoke Bedrock Agent for creative strategy ──
                    agent_id, alias_id = discover_agent_details()
                    response = bedrock_agent_runtime.invoke_agent(
                        agentId=agent_id,
                        agentAliasId=alias_id,
                        sessionId=campaign_id,
                        inputText=prompt
                    )

                    completion = ''
                    for evt in response.get('completion'):
                        chunk = evt.get('chunk')
                        if chunk:
                            completion += chunk.get('bytes').decode()

                    print(f"Agent completion for {product_name}:\n{completion}")

                    # ── Step 2: Extract the image prompt from agent response ──
                    image_prompt = extract_image_prompt(completion, product_name, region, audience, message)
                    print(f"Image prompt for Nova Canvas: {image_prompt}")

                    # ── Step 3: Generate all 3 ratios with Nova Canvas ────────
                    images = {}
                    ratio_meta = {
                        '1x1':  ('Instagram Feed',     '1080 × 1080px'),
                        '9x16': ('TikTok / Reels',     '1080 × 1920px'),
                        '16x9': ('YouTube / Facebook', '1920 × 1080px'),
                    }

                    for ratio, (fmt, dims) in ratio_meta.items():
                        try:
                            s3_key, presigned_url = generate_image_with_nova_canvas(
                                image_prompt, campaign_id, product_name, ratio
                            )
                            images[ratio] = {
                                'url':        presigned_url,
                                'key':        s3_key,
                                'format':     fmt,
                                'dimensions': dims,
                                'ratio':      ratio,
                                'generated':  True,    # flag: AI-generated
                                'prompt':     image_prompt[:200],
                            }
                            print(f"Nova Canvas generated {ratio}: {s3_key}")
                        except Exception as img_err:
                            print(f"Nova Canvas failed for {ratio}: {img_err}. Using reference image.")
                            # Graceful fallback to the uploaded reference photo
                            ref_key, ref_url = get_reference_image_url(product_name)
                            images[ratio] = {
                                'url':        ref_url,
                                'key':        ref_key,
                                'format':     fmt,
                                'dimensions': dims,
                                'ratio':      ratio,
                                'generated':  False,   # flag: fallback photo
                            }

                    # ── Step 4: Save blueprint to DynamoDB ────────────────────
                    blueprint = {
                        'campaign_id':     campaign_id,
                        'product_name':    product_name,
                        'region':          region,
                        'audience':        audience,
                        'message':         message,
                        'strategy':        completion,
                        'images':          images,
                        'adCopy':          [{'lang': language, 'text': completion}],
                        'image_prompt':    image_prompt,
                        'approval_status': 'pending_review',
                        'created_at':      time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    }

                    table.put_item(Item=blueprint)
                    print(f"Blueprint saved for {product_name} (campaign {campaign_id})")

                except Exception as e:
                    print(f"Error generating campaign for {product_name}: {str(e)}")

        return {'statusCode': 200}
