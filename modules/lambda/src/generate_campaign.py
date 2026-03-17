import base64
import json
import os
import re
import time
import boto3

# ── AWS clients ───────────────────────────────────────────────────────────────

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
bedrock_agent = boto3.client("bedrock-agent")
bedrock_runtime = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

# ── Environment / constants ───────────────────────────────────────────────────

CAMPAIGN_TABLE = os.environ["CAMPAIGN_TABLE"]
ASSETS_BUCKET = os.environ["ASSETS_BUCKET"]
OUTPUTS_BUCKET = os.environ["OUTPUTS_BUCKET"]
PROJECT_NAME = os.environ.get("PROJECT_NAME", "campaignx")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
USE_DRAFT = os.environ.get("USE_DRAFT_AGENT", "false").lower() == "true"
AGENT_NAME = f"{PROJECT_NAME}-{ENVIRONMENT}-campaign-orchestrator"
AGENT_ALIAS_NAME = "dev-alias"
DRAFT_ALIAS_ID = "TSTALIASID"
NOVA_CANVAS_MODEL_ID = "amazon.nova-canvas-v1:0"
PRESIGNED_URL_TTL = 604800  # 7 days

IMAGE_RATIOS = {
    "1x1": {
        "width": 1024,
        "height": 1024,
        "format": "Instagram Feed",
        "dimensions": "1080 × 1080px",
    },
    "9x16": {
        "width": 768,
        "height": 1280,
        "format": "TikTok / Reels",
        "dimensions": "1080 × 1920px",
    },
    "16x9": {
        "width": 1280,
        "height": 768,
        "format": "YouTube / Facebook",
        "dimensions": "1920 × 1080px",
    },
}

IMAGE_NEGATIVE_PROMPT = (
    "blurry, low quality, text overlays, watermarks, distorted faces, signature"
)

table = dynamodb.Table(CAMPAIGN_TABLE)

# ── Agent discovery (cached across warm invocations) ─────────────────────────

agent_cache: dict = {}


# Returns (agent_id, alias_id), discovering and caching on first warm invocation
def get_agent_ids() -> tuple[str, str]:
    if agent_cache:
        return agent_cache["agent_id"], agent_cache["alias_id"]

    agents = bedrock_agent.list_agents().get("agentSummaries", [])
    agent_id = next(
        (a["agentId"] for a in agents if a["agentName"] == AGENT_NAME), None
    )

    if not agent_id:
        raise ValueError(f"Bedrock agent '{AGENT_NAME}' not found")

    alias_id = resolve_alias(agent_id)
    agent_cache["agent_id"] = agent_id
    agent_cache["alias_id"] = alias_id

    return agent_id, alias_id


# Uses the draft alias in dev/draft mode, otherwise looks up the named alias by name
def resolve_alias(agent_id: str) -> str:
    if ENVIRONMENT == "dev" or USE_DRAFT:
        return DRAFT_ALIAS_ID

    aliases = bedrock_agent.list_agent_aliases(agentId=agent_id).get(
        "agentAliasSummaries", []
    )
    return next(
        (a["agentAliasId"] for a in aliases if a["agentAliasName"] == AGENT_ALIAS_NAME),
        DRAFT_ALIAS_ID,
    )


# ── Agent invocation ──────────────────────────────────────────────────────────

# Sends a prompt to the Bedrock agent and streams back the full text completion
def invoke_agent(session_id: str, prompt: str) -> str:
    agent_id, alias_id = get_agent_ids()

    response = bedrock_agent_runtime.invoke_agent(
        agentId=agent_id,
        agentAliasId=alias_id,
        sessionId=session_id,
        inputText=prompt,
    )

    completion = ""
    for event in response.get("completion"):
        chunk = event.get("chunk")
        if chunk:
            completion += chunk["bytes"].decode()

    return completion


def build_campaign_prompt(
    product: str, region: str, audience: str, message: str, language: str
) -> str:
    return (
        f"Generate a complete localized advertising campaign for:\n"
        f"Product: {product}\n"
        f"Region: {region}\n"
        f"Audience: {audience}\n"
        f"Core message: {message}\n"
        f"Language: {language}\n\n"
        f"Please provide: 1) Creative strategy 2) Ad copy headline and body "
        f"3) An image generation prompt suitable for Amazon Nova Canvas that "
        f"captures the campaign's visual direction."
    )


# ── Image prompt extraction ───────────────────────────────────────────────────

IMAGE_PROMPT_PATTERNS = [
    r"(?:image prompt|visual prompt|image generation prompt)[:\s]+([^\n]{20,})",
    r"(?:DALL-E|Stable Diffusion|Nova Canvas)[:\s]+([^\n]{20,})",
]


# Pulls an explicit image prompt from the agent output; synthesizes a rich fallback if none found
def extract_image_prompt(
    agent_text: str, product: str, region: str, audience: str, message: str
) -> str:
    for pattern in IMAGE_PROMPT_PATTERNS:
        match = re.search(pattern, agent_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:500]

    return (
        f"Professional advertising photograph for {product}. "
        f"Target audience: {audience}. Region: {region}. "
        f"Campaign message: '{message}'. "
        f"High-production-quality commercial photography, studio lighting, "
        f"vivid brand colors, clean composition, 4K, editorial style."
    )


# ── Image generation ──────────────────────────────────────────────────────────

# Invokes Nova Canvas for the given aspect ratio; returns (s3_key, presigned_url)
def generate_image(
    image_prompt: str, campaign_id: str, product_name: str, ratio: str
) -> tuple[str, str]:
    dims = IMAGE_RATIOS[ratio]

    body = json.dumps(
        {
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {
                "text": image_prompt,
                "negativeText": IMAGE_NEGATIVE_PROMPT,
            },
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "width": dims["width"],
                "height": dims["height"],
                "cfgScale": 8.0,
                "quality": "standard",
            },
        }
    )

    response = bedrock_runtime.invoke_model(
        modelId=NOVA_CANVAS_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    image_data = base64.b64decode(result["images"][0])

    s3_key = upload_image(image_data, campaign_id, product_name, ratio)
    url = presign(OUTPUTS_BUCKET, s3_key)
    return s3_key, url


def upload_image(
    image_data: bytes, campaign_id: str, product_name: str, ratio: str
) -> str:
    safe_product = re.sub(r"[^a-zA-Z0-9\-_]", "-", product_name)
    s3_key = f"generated/{campaign_id}/{safe_product}/{ratio}.png"
    s3_client.put_object(
        Bucket=OUTPUTS_BUCKET, Key=s3_key, Body=image_data, ContentType="image/png"
    )
    return s3_key


# Fallback: returns the uploaded reference image for this product from the assets bucket
def get_reference_image(product_name: str) -> tuple[str, str]:
    prefix = f"products/{product_name.replace(' ', '-')}"
    objs = s3_client.list_objects_v2(Bucket=ASSETS_BUCKET, Prefix=prefix)

    if "Contents" not in objs:
        return "", ""

    key = objs["Contents"][0]["Key"]
    return key, presign(ASSETS_BUCKET, key)


def presign(bucket: str, key: str) -> str:
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL,
    )


# ── Campaign orchestration ────────────────────────────────────────────────────

# Runs the full 4-step generation pipeline for a single product
def process_product(
    campaign_id: str,
    product_name: str,
    region: str,
    audience: str,
    message: str,
    language: str,
) -> None:
    # Pre-flight: flip status to 'generating' so the frontend transitions out of 'pending'
    table.update_item(
        Key={"campaign_id": campaign_id, "product_name": product_name},
        UpdateExpression="SET approval_status = :s",
        ExpressionAttributeValues={":s": "generating"},
    )

    prompt = build_campaign_prompt(product_name, region, audience, message, language)
    completion = invoke_agent(session_id=campaign_id, prompt=prompt)
    print(f"Agent completion for {product_name}:\n{completion}")

    image_prompt = extract_image_prompt(
        completion, product_name, region, audience, message
    )
    print(f"Image prompt: {image_prompt}")

    images = generate_all_ratios(image_prompt, campaign_id, product_name)

    blueprint = {
        "campaign_id": campaign_id,
        "product_name": product_name,
        "region": region,
        "audience": audience,
        "message": message,
        "strategy": completion,
        "images": images,
        "adCopy": [{"lang": language, "text": completion}],
        "image_prompt": image_prompt,
        "approval_status": "pending_review",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    table.put_item(Item=blueprint)
    print(f"Blueprint saved for {product_name} (campaign {campaign_id})")


def generate_all_ratios(image_prompt: str, campaign_id: str, product_name: str) -> dict:
    images = {}

    for ratio, meta in IMAGE_RATIOS.items():
        try:
            s3_key, url = generate_image(image_prompt, campaign_id, product_name, ratio)
            images[ratio] = {
                "url": url,
                "key": s3_key,
                "format": meta["format"],
                "dimensions": meta["dimensions"],
                "ratio": ratio,
                "generated": True,
                "prompt": image_prompt[:200],
            }
            print(f"Nova Canvas generated {ratio}: {s3_key}")
        except Exception as exc:
            print(
                f"Nova Canvas failed for {ratio}: {exc}. Falling back to reference image."
            )
            ref_key, ref_url = get_reference_image(product_name)
            images[ratio] = {
                "url": ref_url,
                "key": ref_key,
                "format": meta["format"],
                "dimensions": meta["dimensions"],
                "ratio": ratio,
                "generated": False,
            }

    return images


# ── Lambda entry point ────────────────────────────────────────────────────────


def handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    if "actionGroup" in event:
        return fetch_brand_guidelines(event)

    if "Records" in event:
        return handle_sqs(event)


# Handles Bedrock Action Group requests to fetch established business rules.
# NOTE: This returns a hardcoded mock response
# In production, it would query a real marketing database or headless CMS.
def fetch_brand_guidelines(event: dict) -> dict:
    action_group = event["actionGroup"]
    function = event["function"]
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    product_name = parameters.get("product_name", "the product")
    market = parameters.get("market_trends", "general market")

    response_text = (
        f"Creative strategy for {product_name} targeting {market}:\n\n"
        f"Strategy: Focus on aspirational lifestyle imagery and authentic storytelling. "
        f"Headline: 'Built for every adventure.' "
        f"Body copy: Engineered for performance, designed for the journey ahead. "
        f"Image prompt: A professional outdoor adventure photograph showing {product_name} "
        f"in a dramatic mountain landscape at golden hour, high-production commercial photography, vivid colors."
    )

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {"responseBody": {"TEXT": {"body": response_text}}},
        },
    }


def handle_sqs(event: dict) -> dict:
    for record in event["Records"]:
        body = json.loads(record["body"])
        campaign_id = body.get("campaignId")
        products = body.get("products", ["Generic Product"])

        for product_name in products:
            try:
                process_product(
                    campaign_id=campaign_id,
                    product_name=product_name,
                    region=body.get("region", "us"),
                    audience=body.get("audience", "General"),
                    message=body.get("message", ""),
                    language=body.get("language", "en"),
                )
            except Exception as exc:
                print(
                    f"Error processing {product_name} in campaign {campaign_id}: {exc}"
                )

    return {"statusCode": 200}