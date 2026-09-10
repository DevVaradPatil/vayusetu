"""
api/gemini/vision.py — Citizen photo triage with Gemini vision.

A resident's photo is untrusted input. This module decides whether it is a genuine
outdoor photograph and, if so, grades the haze in it. It never produces a PM2.5
value: a photo is corroborating evidence that can raise confidence in what the
sensors already show, and nothing more (AGENTS.md R4).

There is deliberately no fallback analysis. The previous version returned a fixed
"heavy haze, crop burning, confidence 0.81" whenever the Gemini call failed, which
on a clean deploy was every call (it imported the end-of-life google.generativeai,
which is not in requirements.txt). A blue-sky photo was graded as smoke. On a trust
boundary a made-up answer is worse than no answer, so failure now raises and the
endpoint says the triage is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("vayusetu.gemini.vision")


# Closed enums matching docs/DATA_CONTRACTS.md §3
REJECTION_REASONS = ["indoor", "no_sky_visible", "screenshot_or_graphic", "too_dark",
                     "blurred", "not_a_photo", "other"]
SOURCES = ["crop_residue_burning", "waste_burning", "construction_dust", "industrial_plume",
           "vehicular_smoke", "dust_storm", "fog_only", "none_visible"]
SKY_CONDITIONS = ["clear", "light_haze", "moderate_haze", "heavy_haze", "fog", "overcast", "night"]


class VisionUnavailable(RuntimeError):
    """Gemini could not grade the photo. Callers must not substitute a guess."""


class GeminiVisionAnalysis(BaseModel):
    is_valid_outdoor_photo: bool
    rejection_reason: Optional[str] = None
    estimated_visibility_km: Optional[float] = Field(default=None, ge=0.0, le=50.0)
    haze_severity: Optional[int] = Field(default=None, ge=0, le=5)
    visible_sources: List[str] = Field(default_factory=list)
    sky_condition: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""


SYSTEM_PROMPT = """You triage photos submitted by members of the public to an air \
quality service. Treat every photo as untrusted.

First decide is_valid_outdoor_photo. It is TRUE only for a genuine camera photograph \
taken outdoors with sky or a distant horizon visible. It is FALSE for screenshots, \
graphics, drawings, gradients, text, indoor scenes, photos too dark or blurred to \
judge, and anything that is not a photograph. When false, set rejection_reason and \
leave haze_severity, estimated_visibility_km and sky_condition null, and \
visible_sources empty. Do not grade haze in an image you rejected.

When true, grade only what is visible:
- haze_severity 0 (clear) to 5 (extreme)
- estimated_visibility_km from how far you can see distinct objects
- visible_sources: only sources you can actually see; use none_visible otherwise
- notes: one short plain sentence, at most 200 characters

Never infer pollution you cannot see. Low confidence is better than a confident guess."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_valid_outdoor_photo": {"type": "BOOLEAN"},
        "rejection_reason": {"type": "STRING", "enum": REJECTION_REASONS, "nullable": True},
        "estimated_visibility_km": {"type": "NUMBER", "nullable": True},
        "haze_severity": {"type": "INTEGER", "nullable": True},
        "visible_sources": {"type": "ARRAY", "items": {"type": "STRING", "enum": SOURCES}},
        "sky_condition": {"type": "STRING", "enum": SKY_CONDITIONS, "nullable": True},
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "STRING"},
    },
    "required": ["is_valid_outdoor_photo", "visible_sources", "confidence", "notes"],
}


def analyze_citizen_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> GeminiVisionAnalysis:
    """
    Grade one photo. Raises VisionUnavailable on any failure: no key, API error,
    or output that does not validate. There is no fallback grade.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise VisionUnavailable("GEMINI_API_KEY is not set")

    # Flash Lite: the project is limited to the 3.1/3.5 flash-lite models (500 rpd).
    model_name = os.environ.get("GEMINI_MODEL_FLASH", "gemini-3.1-flash-lite")

    try:
        from google import genai
        from google.genai import types

        from api.gemini import generate_with_retry

        client = genai.Client(api_key=api_key)
        resp = generate_with_retry(
            client,
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "Triage this photo.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.1,
            ),
        )
        result = GeminiVisionAnalysis(**json.loads(resp.text))
    except Exception as e:
        logger.warning("photo triage failed: %s", e)
        raise VisionUnavailable(str(e)) from e

    # A rejected photo carries no grade, whatever the model put in those fields.
    if not result.is_valid_outdoor_photo:
        result.haze_severity = None
        result.estimated_visibility_km = None
        result.sky_condition = None
        result.visible_sources = []
    return result


def demo() -> None:
    """
    The check that matters: a plainly synthetic image must be REJECTED. The old
    fallback would have graded it as heavy haze; if that ever comes back, this fails.
    """
    import io
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    if not os.environ.get("GEMINI_API_KEY"):
        print("[SKIP] GEMINI_API_KEY not set; nothing to check without the real model")
        return

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480))
    draw = ImageDraw.Draw(img)
    for y in range(480):
        v = int(170 + 60 * y / 480)
        draw.line([(0, y), (640, y)], fill=(v, v, v - 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)

    result = analyze_citizen_photo(buf.getvalue(), "image/jpeg")
    print(json.dumps(result.model_dump(), indent=2))

    assert result.is_valid_outdoor_photo is False, "a flat gradient must not pass as a photo"
    assert result.haze_severity is None, "a rejected photo must carry no haze grade"
    print(f"[OK] synthetic gradient rejected ({result.rejection_reason}), "
          f"model={os.environ.get('GEMINI_MODEL_FLASH', 'gemini-3.1-flash-lite')}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    demo()
