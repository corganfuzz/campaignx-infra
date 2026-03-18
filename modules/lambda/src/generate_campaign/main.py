import json

from .orchestrator import process_product


def handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    if "actionGroup" in event:
        return fetch_brand_guidelines(event)

    if "Records" in event:
        return handle_sqs(event)


def fetch_brand_guidelines(event: dict) -> dict:
    """Handles Bedrock Action Group requests to fetch brand guidelines.
    NOTE: Returns a hardcoded mock response."""
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
