import base64
import concurrent.futures
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
COMPLIANCE_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
PRESIGNED_URL_TTL = 604800  # 7 days

IMAGE_RATIOS = {
    "1x1": {
        "width": 1024,
        "height": 1024,
        "format": "Instagram Feed",
        "dimensions": "1080 x 1080px",
    },
    "9x16": {
        "width": 720,
        "height": 1280,
        "format": "TikTok / Reels",
        "dimensions": "1080 x 1920px",
    },
    "16x9": {
        "width": 1280,
        "height": 720,
        "format": "YouTube / Facebook",
        "dimensions": "1920 x 1080px",
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
        f"Language Code: {language}\n\n"
        f"CRITICAL REQUIREMENT: You MUST output the final Ad Copy (both headline and body) strictly in the target language associated with the language code '{language}'.\n"
        f"The creative strategy and image generation prompt must remain in English.\n\n"
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


# Isolates the actual ad copy (headline/body) from the agent's full narrative response
def extract_ad_copy(agent_text: str) -> str:
    # Pattern looks for text between the 'Ad Copy' header and the 'Image Gen' header
    # Correctly handles various LLM numbering/formatting styles
    pattern = r"(?:2\)?\s*Ad copy|Ad Copy)[:\s]+(.*?)(?=3\)?\s*An image|Image generation|Image Prompt|$)"
    match = re.search(pattern, agent_text, re.IGNORECASE | re.DOTALL)

    if match:
        cleaned = match.group(1).strip()
        # Remove any lingering markdown-style bolding from headers if they exist
        return re.sub(r"^\**Headline:?\**\s*", "", cleaned, flags=re.IGNORECASE).strip()

    return agent_text.strip()


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

    # Retry logic (3 attempts) specifically for Throttling or model availability issues
    # common when launching multiple Nova requests in parallel.
    last_exc = None
    for attempt in range(3):
        try:
            # Introduce a tiny staggered jitter for the parallel workers
            time.sleep(attempt * 0.5)
            
            response = bedrock_runtime.invoke_model(
                modelId=NOVA_CANVAS_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            
            if "images" not in result or not result["images"]:
                # Check for safety filter or context-specific rejection
                error_msg = result.get("error", "No images returned (likely safety filter)")
                raise Exception(error_msg)
                
            image_data = base64.b64decode(result["images"][0])
            s3_key = upload_image(image_data, campaign_id, product_name, ratio)
            url = presign(OUTPUTS_BUCKET, s3_key)
            return s3_key, url
            
        except Exception as e:
            last_exc = e
            print(f"Attempt {attempt+1} failed for {ratio}: {e}")
            if "Throttling" not in str(e) and "limit" not in str(e).lower():
                # If it's not a throttling issue, immediate retry is less likely to help, 
                # but we'll try again anyway unless it's a fatal validation error.
                pass
    if last_exc:
        raise last_exc
    raise Exception(f"Failed to generate image for {ratio} after multiple attempts")


def upload_image(
    image_data: bytes, campaign_id: str, product_name: str, ratio: str
) -> str:
    safe_product = re.sub(r"[^a-zA-Z0-9\-_]", "-", product_name)
    safe_ratio = ratio.replace("x", "-")
    s3_key = f"generated/{campaign_id}/{safe_product}/{safe_ratio}.png"
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


# ── Compliance check ─────────────────────────────────────────────────────────


# Sends the generated ad copy to Claude for structured compliance evaluation.
# Returns a list of {label, status} dicts matching the frontend ComplianceItem type.
def run_compliance_check(ad_copy: str, product: str, region: str, language: str) -> list:
    prompt = (
        f"You are a legal and brand compliance auditor for global advertising campaigns.\n"
        f"Evaluate the following ad copy for a product called '{product}' "
        f"targeting the '{region}' market in language code '{language}'.\n\n"
        f"Ad copy:\n<copy>\n{ad_copy}\n</copy>\n\n"
        f"Run exactly these 5 checks and return ONLY a JSON array with no extra text, markdown, or explanation:\n"
        f"1. Prohibited Claims - Does the copy make unsubstantiated superlative claims "
        f"(e.g. '#1', 'best ever', 'guaranteed', 'cure', 'promise results', 'risk-free')?\n"
        f"2. Legal Disclaimer - Does the copy include an appropriate legal disclaimer or "
        f"is the product claim modest enough not to require one?\n"
        f"3. Brand Voice - Is the tone premium, aspirational, and consistent with a "
        f"high-end consumer goods brand?\n"
        f"4. Cultural Sensitivity - Is the content appropriate and respectful for the '{region}' market?\n"
        f"5. PII / Data Risk - Does the copy contain any personal information, phone numbers, "
        f"email addresses, or URLs?\n\n"
        f'Return this exact JSON structure with a short one-sentence "reason" for each result: '
        f'[{{"label": "Prohibited Claims", "status": "pass", "reason": "No unsubstantiated claims found."}}, ...]\n'
        f"Use 'pass' if fully met, 'warn' if borderline, 'fail' if violated. Keep each reason under 15 words."
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })

    try:
        response = bedrock_runtime.invoke_model(
            modelId=COMPLIANCE_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        raw_text = result["content"][0]["text"].strip()

        # Strip markdown fences if Claude wraps output in ```json
        raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()
        checks = json.loads(raw_text)

        valid_statuses = {"pass", "warn", "fail"}
        return [
            {
                "label": c["label"],
                "status": c["status"] if c["status"] in valid_statuses else "warn",
                "reason": c.get("reason", ""),
            }
            for c in checks
            if "label" in c and "status" in c
        ]
    except Exception as exc:
        print(f"Compliance check failed: {exc}")
        return [{"label": "Compliance Check", "status": "warn"}]


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

    ad_copy_text = extract_ad_copy(completion)

    # Run image generation (3 ratios) and compliance check concurrently —
    # they share no state so there is no risk of a race condition.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        images_future = pool.submit(generate_all_ratios, image_prompt, campaign_id, product_name)
        compliance_future = pool.submit(run_compliance_check, ad_copy_text, product_name, region, language)
        images = images_future.result()
        compliance = compliance_future.result()

    print(f"Compliance results: {json.dumps(compliance)}")

    blueprint = {
        "campaign_id": campaign_id,
        "product_name": product_name,
        "region": region,
        "audience": audience,
        "message": message,
        "strategy": completion,
        "images": images,
        "adCopy": [{"lang": language, "text": ad_copy_text}],
        "image_prompt": image_prompt,
        "compliance": compliance,
        "approval_status": "pending_review",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    table.put_item(Item=blueprint)
    print(f"Blueprint saved for {product_name} (campaign {campaign_id})")


def generate_all_ratios(image_prompt: str, campaign_id: str, product_name: str) -> dict:
    """Generates all image formats concurrently using a thread pool."""
    images = {}

    def _generate_one(ratio: str, meta: dict) -> tuple[str, dict]:
        try:
            s3_key, url = generate_image(image_prompt, campaign_id, product_name, ratio)
            print(f"Nova Canvas generated {ratio}: {s3_key}")
            return ratio, {
                "url": url,
                "key": s3_key,
                "format": meta["format"],
                "dimensions": meta["dimensions"],
                "ratio": ratio,
                "generated": True,
                "prompt": image_prompt[:200],
            }
        except Exception as exc:
            print(f"Nova Canvas failed for {ratio}: {exc}. Falling back to reference image.")
            ref_key, ref_url = get_reference_image(product_name)
            return ratio, {
                "url": ref_url,
                "key": ref_key,
                "format": meta["format"],
                "dimensions": meta["dimensions"],
                "ratio": ratio,
                "generated": False,
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(IMAGE_RATIOS)) as pool:
        futures = {pool.submit(_generate_one, ratio, meta): ratio for ratio, meta in IMAGE_RATIOS.items()}
        for future in concurrent.futures.as_completed(futures):
            ratio, result = future.result()
            images[ratio] = result

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
        f"Brand Guidelines for {product_name} targeting {market}:\n\n"
        f"Brand Voice: Premium, aspirational, authentic, and lifestyle-oriented.\n"
        f"Visual Style: High-production commercial photography, vivid lighting, clear product focus.\n"
        f"Themes: Contextualize the product in its ideal real-world use case. DO NOT use generic outdoor settings unless relevant to the product. Headphones should be shown in commuter/urban/audio settings. Parkas in cold weather."
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
