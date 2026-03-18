import concurrent.futures
import json
from .orchestrator import process_product

def handler(event, context):
    """Entry point for the Campaign Generation Lambda."""
    # SQS trigger (Async generation)
    if "Records" in event:
        return handle_sqs(event)
    
    # Bedrock Action Group trigger (Guidelines fetch)
    if "actionGroup" in event:
        return fetch_brand_guidelines(event)
    
    return {"statusCode": 400, "body": "Unknown event source"}

def fetch_brand_guidelines(event: dict) -> dict:
    """Handles requests to fetch localized brand guidelines."""
    action_group = event["actionGroup"]
    function = event["function"]
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    product_name = parameters.get("product_name", "the product")
    market = parameters.get("market_trends", "general market")

    response_text = (
        f"Brand Guidelines for {product_name} targeting {market}:\n\n"
        f"Voice: Premium, aspirational, and authentic.\n"
        f"Style: Cinematic lighting, clear product focus, urban or contextual settings.\n"
        f"Themes: Focus on real-world use cases. Use urban/audio settings for electronics, cold weather for outerwear."
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
    """Processes messages from SQS to generate full campaign blueprints."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        campaign_id = body.get("campaignId")
        products = body.get("products", [])
        region = body.get("region", "global")
        audience = body.get("audience", "General")
        message = body.get("message", "")
        language = body.get("language", "en")

        print(f"Processing {len(products)} products for campaign {campaign_id}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(
                    process_product,
                    campaign_id=campaign_id,
                    product_name=p,
                    region=region,
                    audience=audience,
                    message=message,
                    language=language
                ) for p in products
            ]
            concurrent.futures.wait(futures)

    return {"statusCode": 200}
