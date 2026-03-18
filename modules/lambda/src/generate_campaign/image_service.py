import base64
import concurrent.futures
import io
import json
import re
import textwrap
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not available — text overlay will be skipped.")

from .config import (
    s3_client,
    bedrock_runtime,
    ASSETS_BUCKET,
    OUTPUTS_BUCKET,
    NOVA_CANVAS_MODEL_ID,
    IMAGE_RATIOS,
    IMAGE_NEGATIVE_PROMPT,
    PRESIGNED_URL_TTL,
)


def upload_image(image_data: bytes, campaign_id: str, product_name: str, ratio: str) -> str:
    safe_product = re.sub(r"[^a-zA-Z0-9\-_]", "-", product_name)
    safe_ratio = ratio.replace("x", "-")
    s3_key = f"generated/{campaign_id}/{safe_product}/{safe_ratio}.png"
    s3_client.put_object(
        Bucket=OUTPUTS_BUCKET, Key=s3_key, Body=image_data, ContentType="image/png"
    )
    return s3_key


def presign(bucket: str, key: str) -> str:
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL,
    )


def get_reference_image(product_name: str) -> tuple[str, str]:
    prefix = f"products/{product_name.replace(' ', '-')}"
    objs = s3_client.list_objects_v2(Bucket=ASSETS_BUCKET, Prefix=prefix)

    if "Contents" not in objs:
        return "", ""

    key = objs["Contents"][0]["Key"]
    return key, presign(ASSETS_BUCKET, key)


def composite_text_overlay(
    image_bytes: bytes,
    message: str,
    ad_copy_headline: str,
    ratio: str,
) -> bytes:
    """Composites the campaign message and ad-copy headline onto the image.

    Renders a semi-transparent dark strip at the bottom of the image with:
      - Campaign message  (large, white, bold-style)
      - Ad-copy headline  (smaller, light-grey, below the message)

    Returns the modified image as PNG bytes. If Pillow is unavailable the
    original bytes are returned unchanged so the pipeline never hard-fails.
    """
    if not PIL_AVAILABLE:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size

        # Font sizing
        short_side = min(w, h)
        msg_font_size = max(24, short_side // 22)
        copy_font_size = max(16, short_side // 34)

        try:
            msg_font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", msg_font_size)
            copy_font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", copy_font_size)
        except (IOError, OSError):
            msg_font = ImageFont.load_default()
            copy_font = ImageFont.load_default()

        # Wrap text to fit image width with comfortable padding
        padding = int(w * 0.05)
        approx_char_w = msg_font_size * 0.55
        chars_per_line = max(20, int((w - 2 * padding) / approx_char_w))

        msg_lines = textwrap.wrap(message or "", width=chars_per_line)
        copy_lines = textwrap.wrap(ad_copy_headline or "", width=chars_per_line + 10)

        # Measure total text block height
        line_gap = int(msg_font_size * 0.35)
        msg_block_h = len(msg_lines) * (msg_font_size + line_gap)
        copy_block_h = len(copy_lines) * (copy_font_size + line_gap) if copy_lines else 0
        v_pad = int(short_side * 0.04)
        strip_h = msg_block_h + copy_block_h + v_pad * 3

        # Draw semi-transparent backdrop strip
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        strip_top = h - strip_h
        draw.rectangle(
            [(0, strip_top), (w, h)],
            fill=(0, 0, 0, 175),
        )

        # Write campaign message lines
        y = strip_top + v_pad
        for line in msg_lines:
            draw.text((padding, y), line, font=msg_font, fill=(255, 255, 255, 255))
            y += msg_font_size + line_gap

        # Write ad-copy headline lines
        if copy_lines:
            y += line_gap
            for line in copy_lines:
                draw.text((padding, y), line, font=copy_font, fill=(210, 210, 210, 220))
                y += copy_font_size + line_gap

        composited = Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        composited.save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    except Exception as exc:
        print(f"Text overlay failed ({ratio}): {exc} — uploading raw image.")
        return image_bytes


def generate_all_ratios(
    image_prompt: str,
    campaign_id: str,
    product_name: str,
    message: str = "",
    ad_copy_headline: str = "",
) -> dict:
    """Generates all image formats concurrently and composites the campaign
    message text overlay onto each image before uploading to S3."""
    images = {}

    def _generate_one(ratio: str, meta: dict) -> tuple[str, dict]:
        try:
            dims = IMAGE_RATIOS[ratio]
            body = json.dumps({
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
            })

            last_exc = None
            raw_image_bytes = None
            for attempt in range(3):
                try:
                    time.sleep(attempt * 0.5)
                    response = bedrock_runtime.invoke_model(
                        modelId=NOVA_CANVAS_MODEL_ID,
                        body=body,
                        contentType="application/json",
                        accept="application/json",
                    )
                    result = json.loads(response["body"].read())
                    if "images" not in result or not result["images"]:
                        raise Exception(result.get("error", "No images returned"))
                    raw_image_bytes = base64.b64decode(result["images"][0])
                    break
                except Exception as e:
                    last_exc = e
                    print(f"Attempt {attempt+1} failed for {ratio}: {e}")

            if raw_image_bytes is None:
                raise last_exc or Exception(f"All retries failed for {ratio}")

            composited_bytes = composite_text_overlay(
                raw_image_bytes, message, ad_copy_headline, ratio
            )

            s3_key = upload_image(composited_bytes, campaign_id, product_name, ratio)
            url = presign(OUTPUTS_BUCKET, s3_key)
            print(f"Nova Canvas generated {ratio} (overlay applied): {s3_key}")
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
            if ref_key:
                try:
                    obj = s3_client.get_object(Bucket=ASSETS_BUCKET, Key=ref_key)
                    ref_bytes = obj["Body"].read()
                    composited_bytes = composite_text_overlay(
                        ref_bytes, message, ad_copy_headline, ratio
                    )
                    s3_key = upload_image(composited_bytes, campaign_id, product_name, ratio)
                    ref_url = presign(OUTPUTS_BUCKET, s3_key)
                    ref_key = s3_key
                except Exception as overlay_exc:
                    print(f"Overlay on fallback failed for {ratio}: {overlay_exc}")
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
