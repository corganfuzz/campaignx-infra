import base64
import concurrent.futures
import io
import json
import os
import random
import re
import time

try:
    from PIL import Image, ImageDraw, ImageFont, features
    PIL_AVAILABLE = True
    FREETYPE_AVAILABLE = features.check('freetype')
except ImportError:
    PIL_AVAILABLE = False
    FREETYPE_AVAILABLE = False

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
    """Wraps text into lines based on pixel width."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
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
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def composite_text_overlay(image_bytes: bytes, message: str, ratio: str) -> bytes:
    """Renders a premium text overlay onto the generated image."""
    if not PIL_AVAILABLE:
        return image_bytes
        
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size
        short_side = min(w, h)
        msg_font_size = max(42, short_side // 10)
        
        # Load bundled Roboto Slab font
        font_path = os.path.join(os.path.dirname(__file__), "assets", "RobotoSlab-Bold.ttf")
        try:
            if FREETYPE_AVAILABLE and os.path.exists(font_path):
                msg_font = ImageFont.truetype(font_path, msg_font_size)
            else:
                msg_font = ImageFont.load_default()
        except:
            msg_font = ImageFont.load_default()

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        max_text_w = int(w * 0.90)
        msg_lines = _wrap_text(message or "", msg_font, max_text_w, draw)
        line_count = len(msg_lines)
        
        line_gap = int(msg_font_size * 0.15)
        text_h = line_count * msg_font_size + (line_count - 1) * line_gap if line_count > 0 else 0
        v_margin = int(msg_font_size * 0.4)
        strip_h = text_h + v_margin * 2
        strip_top = h - strip_h - int(h * 0.05)
        
        # Draw dark aesthetic backdrop
        draw.rectangle([(0, strip_top), (w, strip_top + strip_h)], fill=(0, 0, 0, 180))
        
        y = strip_top + v_margin
        for line in msg_lines:
            bbox = draw.textbbox((0, 0), line, font=msg_font)
            line_w = bbox[2] - bbox[0]
            x = (w - line_w) // 2
            
            # Subtle drop shadow and main text
            draw.text((x + 2, y + 2), line, font=msg_font, fill=(0, 0, 0, 160))
            draw.text((x, y), line, font=msg_font, fill=(255, 255, 255, 255))
            y += msg_font_size + line_gap
            
        composited = Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        composited.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
    except Exception as exc:
        print(f"Overlay failed: {exc}")
        return image_bytes

def generate_all_ratios(image_prompt: str, campaign_id: str, product_name: str, message: str = "") -> dict:
    images = {}
    
    def _generate_one(ratio: str, meta: dict) -> tuple[str, dict]:
        try:
            dims = IMAGE_RATIOS[ratio]
            body = json.dumps({
                "taskType": "TEXT_IMAGE",
                "textToImageParams": {"text": image_prompt, "negativeText": IMAGE_NEGATIVE_PROMPT},
                "imageGenerationConfig": {
                    "numberOfImages": 1,
                    "width": dims["width"],
                    "height": dims["height"],
                    "cfgScale": 8.0,
                    "quality": "standard",
                },
            })
            
            raw_image_bytes = None
            for attempt in range(4):
                try:
                    time.sleep((2 ** attempt) + random.random())
                    response = bedrock_runtime.invoke_model(
                        modelId=NOVA_CANVAS_MODEL_ID, body=body, contentType="application/json", accept="application/json"
                    )
                    result = json.loads(response["body"].read())
                    raw_image_bytes = base64.b64decode(result["images"][0])
                    break
                except Exception as e:
                    if attempt == 3: raise e
            
            composited_bytes = composite_text_overlay(raw_image_bytes, message, ratio)
            s3_key = upload_image(composited_bytes, campaign_id, product_name, ratio)
            url = presign(OUTPUTS_BUCKET, s3_key)
            
            return ratio, {
                "url": url, "key": s3_key, "format": meta["format"], "dimensions": meta["dimensions"],
                "ratio": ratio, "generated": True, "prompt": image_prompt[:200]
            }
        except Exception as exc:
            ref_key, ref_url = get_reference_image(product_name)
            if ref_key:
                try:
                    obj = s3_client.get_object(Bucket=ASSETS_BUCKET, Key=ref_key)
                    ref_bytes = obj["Body"].read()
                    comp_bytes = composite_text_overlay(ref_bytes, message, ratio)
                    s3_key = upload_image(comp_bytes, campaign_id, product_name, ratio)
                    ref_url, ref_key = presign(OUTPUTS_BUCKET, s3_key), s3_key
                except: pass
            return ratio, {
                "url": ref_url, "key": ref_key, "format": meta["format"], 
                "dimensions": meta["dimensions"], "ratio": ratio, "generated": False
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(IMAGE_RATIOS)) as pool:
        futures = {pool.submit(_generate_one, ratio, meta): ratio for ratio, meta in IMAGE_RATIOS.items()}
        for future in concurrent.futures.as_completed(futures):
            ratio, result = future.result()
            images[ratio] = result
    return images