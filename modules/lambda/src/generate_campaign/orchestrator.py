import concurrent.futures
import json
import time

from .config import table
from .agent_service import (
    invoke_agent,
    build_campaign_prompt,
    extract_image_prompt,
    extract_ad_copy,
    extract_overlay_text,
)
from .image_service import generate_all_ratios
from .compliance import run_compliance_check


def process_product(
    campaign_id: str,
    product_name: str,
    region: str,
    audience: str,
    message: str,
    language: str,
) -> None:
    table.update_item(
        Key={"campaign_id": campaign_id, "product_name": product_name},
        UpdateExpression="SET approval_status = :s",
        ExpressionAttributeValues={":s": "generating"},
    )

    prompt = build_campaign_prompt(product_name, region, audience, message, language)
    completion = invoke_agent(session_id=campaign_id, prompt=prompt)
    print(f"Agent completion for {product_name}:\n{completion}")

    image_prompt = extract_image_prompt(completion, product_name, region, audience, message)
    print(f"Image prompt: {image_prompt}")

    ad_copy_text = extract_ad_copy(completion)
    
    # Extract the localized message for overlay (requested via field #4 in prompt)
    overlay_headline = extract_overlay_text(completion, message, region)
    print(f"Overlay headline (localized): {overlay_headline}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        images_future = pool.submit(
            generate_all_ratios,
            image_prompt,
            campaign_id,
            product_name,
            message,
            overlay_headline,
        )
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
