import base64
import concurrent.futures
import io
import json
import os
import re
import time
try:
    from PIL import Image, ImageDraw, ImageFont, features
    PIL_AVAILABLE = True
    FREETYPE_AVAILABLE = features.check('freetype')
    print(f"INFO: Pillow loaded. Freetype support: {FREETYPE_AVAILABLE}")
except ImportError:
    PIL_AVAILABLE = False
    FREETYPE_AVAILABLE = False
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
def _slugify(text: str) -> str:
    """Standardizes product names for S3 keys and local folders."""
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", text.strip()).replace("--", "-").strip("-")
def upload_image(image_data: bytes, campaign_id: str, product_name: str, ratio: str) -> str:
    safe_product = _slugify(product_name)
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
    safe_product = _slugify(product_name)
    prefix = f"products/{safe_product}/"
    objs = s3_client.list_objects_v2(Bucket=ASSETS_BUCKET, Prefix=prefix)
    if "Contents" not in objs:
        return "", ""
    key = objs["Contents"][0]["Key"]
    return key, presign(ASSETS_BUCKET, key)
def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wraps text into lines that fit within max_width based on pixel width."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        # Check if adding this word exceeding max_width
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                # Word itself is too wide, force it anyway
                lines.append(word)
                current_line = []
                
    if current_line:
        lines.append(" ".join(current_line))
    return lines
def composite_text_overlay(
    image_bytes: bytes,
    message: str,
    ad_copy_headline: str, # Kept for backward compatibility, but not rendered
    ratio: str,
) -> bytes:
    """Composites the campaign message onto the image.
    Renders a semi-transparent dark strip at the bottom of the image with the
    localized campaign message (large, white, high-legibility).
    Returns the modified image as PNG bytes. If Pillow is unavailable the
    original bytes are returned unchanged so the pipeline never hard-fails.
    """
    if not PIL_AVAILABLE:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size
        # Use bundled font for consistency in Lambda environment
        # Font sizing (Short side basis)
        short_side = min(w, h)
        msg_font_size = max(42, short_side // 10)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "RobotoSlab-Bold.ttf")

        try:
            abs_dir = os.path.dirname(os.path.abspath(__file__))
            font_path = os.path.join(abs_dir, "assets", "RobotoSlab-Bold.ttf")
            print(f"DEBUG: __file__ is {__file__}")
            print(f"DEBUG: Searching for font at {font_path}")
            
            if not FREETYPE_AVAILABLE:
                print("ERROR: Pillow missing freetype support.")
                msg_font = ImageFont.load_default()
            elif os.path.exists(font_path):
                print(f"DEBUG: Loading font from {font_path}")
                msg_font = ImageFont.truetype(font_path, msg_font_size)
            else:
                print("DEBUG: Local assets/ font not found, searching...")
                msg_font = ImageFont.load_default()
                for root, dirs, files in os.walk(abs_dir):
                    if "RobotoSlab-Bold.ttf" in files:
                        found_path = os.path.join(root, "RobotoSlab-Bold.ttf")
                        print(f"DEBUG: Found font at: {found_path}")
                        msg_font = ImageFont.truetype(found_path, msg_font_size)
                        break
        except Exception as e:
            print(f"DEBUG: Font load exception: {e}")
            msg_font = ImageFont.load_default()
        # Create a temporary draw object for measurement
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        # Wrap text into lines using pixel-width metrics (90% of image width)
        max_text_w = int(w * 0.90)
        msg_lines = _wrap_text(message or "", msg_font, max_text_w, draw)
        line_count = len(msg_lines)
        # Measure dimensions for precise fit
        line_gap = int(msg_font_size * 0.15)
        text_h = line_count * msg_font_size + (line_count - 1) * line_gap if line_count > 0 else 0
        
        # Tight padding to "fit perfectly"
        v_margin = int(msg_font_size * 0.4)
        strip_h = text_h + v_margin * 2
        # Draw refined backdrop (gradient bar)
        strip_top = h - strip_h - int(h * 0.05) # Lift slightly off the bottom edge
        
        # Draw a slightly rounded or softened bar that fits the text
        draw.rectangle(
            [(0, strip_top), (w, strip_top + strip_h)], 
            fill=(0, 0, 0, 180)
        )
        # Write localized campaign message (Centered)
        y = strip_top + v_margin
        for line in msg_lines:
            # Calculate centering for this specific line
            bbox = draw.textbbox((0, 0), line, font=msg_font)
            line_w = bbox[2] - bbox[0]
            x = (w - line_w) // 2
            # Subtle drop shadow for depth
            draw.text((x + 2, y + 2), line, font=msg_font, fill=(0, 0, 0, 160))
            draw.text((x, y), line, font=msg_font, fill=(255, 255, 255, 255))
            y += msg_font_size + line_gap
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
            import random
            last_exc: Exception = Exception(f"All retries failed for {ratio}")
            raw_image_bytes = None
            for attempt in range(4):
                try:
                    # Exponential backoff with jitter to prevent RPS race conditions
                    sleep_time = (2 ** attempt) + (random.random() * 0.5)
                    time.sleep(sleep_time)
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
                raise last_exc
            assert raw_image_bytes is not None
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