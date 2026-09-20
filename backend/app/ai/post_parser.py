import json
import logging
from typing import Optional, Dict, Any
from google.genai import types
from backend.app.ai.gemini_client import gemini_service

logger = logging.getLogger(__name__)

PARSE_PROMPT = """
You are an expert product data extraction assistant for an E-Liquid / Vape shop.
Given a raw text/caption from a Telegram channel post, extract the product information and return ONLY a valid JSON object with the following fields:

- name: (string) Clean name of the e-liquid / vape liquid flavor
- description: (string) Taste description, flavor notes, cooling effect, etc.
- price: (float) Price in GEL. If not found or ambiguous, default to 0.0
- volume_ml: (integer) Bottle size in ml (e.g. 10, 30, 60, 100, 120). Default 30 if not mentioned
- color_type: (string) E.g. "Salt Nicotine", "Freebase", or flavor category
- vg_pg_ratio: (string) E.g. "50/50", "70/30". Default "50/50" for salt, "70/30" for standard
- nicotine_mg: (string) E.g. "20mg", "50mg", "3mg", "0mg"
- stock_quantity: (integer) Default 10 if not explicitly mentioned

Return ONLY valid JSON without markdown fences.
"""

async def parse_channel_post_content(post_text: str) -> Optional[Dict[str, Any]]:
    """
    Parses channel post text using Gemini into structured product attributes.
    """
    if not post_text or not post_text.strip():
        return None

    if not gemini_service.client:
        logger.warning("Gemini service client not configured, cannot auto-parse channel post.")
        return None

    try:
        config = types.GenerateContentConfig(
            system_instruction=PARSE_PROMPT,
            temperature=0.1,
            response_mime_type="application/json"
        )

        response = await gemini_service.client.aio.models.generate_content(
            model=gemini_service.model_name,
            contents=[types.Content(
                role="user",
                parts=[types.Part.from_text(text=f"Extract product data from this post:\n\n{post_text}")]
            )],
            config=config
        )

        if not response or not response.text:
            return None

        data = json.loads(response.text.strip())
        logger.info(f"Successfully parsed channel post: {data.get('name')}")
        return data

    except Exception as e:
        logger.error(f"Error parsing channel post with Gemini: {e}", exc_info=True)
        return None
