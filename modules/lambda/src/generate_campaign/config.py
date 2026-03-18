import os
import boto3

# AWS clients
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
bedrock_agent = boto3.client("bedrock-agent")
bedrock_runtime = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

# Environment
CAMPAIGN_TABLE = os.environ["CAMPAIGN_TABLE"]
ASSETS_BUCKET = os.environ["ASSETS_BUCKET"]
OUTPUTS_BUCKET = os.environ["OUTPUTS_BUCKET"]
PROJECT_NAME = os.environ.get("PROJECT_NAME", "campaignx")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
USE_DRAFT = os.environ.get("USE_DRAFT_AGENT", "false").lower() == "true"

# Model IDs
NOVA_CANVAS_MODEL_ID = "amazon.nova-canvas-v1:0"
COMPLIANCE_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"

# Agent
AGENT_NAME = f"{PROJECT_NAME}-{ENVIRONMENT}-campaign-orchestrator"
AGENT_ALIAS_NAME = "dev-alias"
DRAFT_ALIAS_ID = "TSTALIASID"

# S3
PRESIGNED_URL_TTL = 604800  # 7 days

# Image generation
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
