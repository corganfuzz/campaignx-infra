import re

from .config import (
    bedrock_agent,
    bedrock_agent_runtime,
    AGENT_NAME,
    AGENT_ALIAS_NAME,
    DRAFT_ALIAS_ID,
    ENVIRONMENT,
    USE_DRAFT,
)

agent_cache: dict = {}


def get_agent_ids() -> tuple[str, str]:
    if agent_cache:
        return agent_cache["agent_id"], agent_cache["alias_id"]

    agents = bedrock_agent.list_agents().get("agentSummaries", [])
    agent_id = next(
        (a["agentId"] for a in agents if a["agentName"] == AGENT_NAME), None
    )

    if not agent_id:
        raise ValueError(f"Bedrock agent '{AGENT_NAME}' not found")

    alias_id = _resolve_alias(agent_id)
    agent_cache["agent_id"] = agent_id
    agent_cache["alias_id"] = alias_id

    return agent_id, alias_id


def _resolve_alias(agent_id: str) -> str:
    if ENVIRONMENT == "dev" or USE_DRAFT:
        return DRAFT_ALIAS_ID

    aliases = bedrock_agent.list_agent_aliases(agentId=agent_id).get(
        "agentAliasSummaries", []
    )
    return next(
        (a["agentAliasId"] for a in aliases if a["agentAliasName"] == AGENT_ALIAS_NAME),
        DRAFT_ALIAS_ID,
    )


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
        f"Please provide:\n"
        f"1) Creative strategy\n"
        f"2) Ad copy headline and body\n"
        f"3) An image generation prompt suitable for Amazon Nova Canvas\n"
        f"4) A direct translation of the core message '{message}' into language '{language}' specifically for use as a high-impact image overlay."
    )


IMAGE_PROMPT_PATTERNS = [
    r"(?:image prompt|visual prompt|image generation prompt)[:\s]+([^\n]{20,})",
    r"(?:DALL-E|Stable Diffusion|Nova Canvas)[:\s]+([^\n]{20,})",
]


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


def extract_ad_copy(agent_text: str) -> str:
    pattern = r"(?:2\)?\s*Ad copy|Ad Copy)[:\s]+(.*?)(?=3\)?\s*An image|Image generation|Image Prompt|4\)?|$)"
    match = re.search(pattern, agent_text, re.IGNORECASE | re.DOTALL)

    if match:
        cleaned = match.group(1).strip()
        return re.sub(r"^\**Headline:?\**\s*", "", cleaned, flags=re.IGNORECASE).strip()

    return agent_text.strip()


def extract_overlay_text(agent_text: str, original_message: str, region: str) -> str:
    """Extracts the translated overlay text from field #4 or falls back to the original."""
    if region.lower() in ["united states", "usa", "us"]:
        return original_message

    pattern = r"(?:4\)?\s*Direct translation|4\)?\s*Translation|4\)?\s*Image overlay)[:\s]+(.*?)(?=$)"
    match = re.search(pattern, agent_text, re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(1).strip().replace('"', "").replace("*", "")

    return original_message
