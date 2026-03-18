import json
import re

from .config import bedrock_runtime, COMPLIANCE_MODEL_ID


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
