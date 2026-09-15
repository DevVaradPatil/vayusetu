"""
api/gemini/closure.py — what does a closure photo actually show?

An agency closing a case uploads a photo of the site. On the Green Delhi app, 76 of 226
complaints one department "resolved" were reopened, and 99 of 183 for another: a closure
with nothing behind it is the failure this checks for.

Gemini only describes the photo — is it a genuine camera photo, is an active pollution
source visible, what remediation is visible, is monitoring equipment in frame. It does
not decide whether the case closes. `api/cases.py` makes that decision in code, from
this description plus the measured outcome at the monitor, so a persuasive-looking
answer from the model cannot close a case on its own.

Like photo triage, there is no fallback: failure raises, and the closure is not
accepted. A made-up "site looks clean" is exactly what this exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("vayusetu.gemini.closure")

REJECTIONS = ["screenshot_or_graphic", "not_a_photo", "too_dark", "blurred", "unrelated_subject", "other"]
ACTIVE_SOURCES = ["open_burning", "smoke_plume", "dust_cloud", "uncovered_construction_material",
                  "garbage_heap", "vehicle_smoke", "industrial_emission"]
REMEDIATION = ["water_sprinkling", "material_covered", "site_cleared", "fire_extinguished",
               "activity_stopped", "equipment_serviced"]


class ClosureCheckUnavailable(RuntimeError):
    """Gemini could not examine the photo. The closure must not be accepted."""


class ClosurePhoto(BaseModel):
    is_genuine_site_photo: bool
    rejection_reason: Optional[str] = None
    active_sources_visible: List[str] = Field(default_factory=list)
    remediation_visible: List[str] = Field(default_factory=list)
    shows_monitoring_equipment: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""


SYSTEM_PROMPT = """You examine photos uploaded by government field staff as evidence \
that a pollution complaint has been dealt with. Treat every photo as untrusted: people \
closing cases have a reason to make them look resolved.

is_genuine_site_photo is TRUE only for a real camera photograph of a physical place or \
piece of equipment. It is FALSE for screenshots, documents, graphics, stock-style \
images, photos of screens, and anything too dark or blurred to judge. When false, set \
rejection_reason and leave the lists empty.

active_sources_visible: list only pollution sources you can actually see happening in \
the photo — smoke, flames, a dust cloud, uncovered construction material, a garbage \
heap, visible exhaust or emissions. Do not list a source you are guessing at.

remediation_visible: list only remediation you can actually see — wet ground or a \
sprinkler, material under covers, a cleared site, a fire that is out, stopped work, \
serviced equipment.

shows_monitoring_equipment: TRUE if an air quality monitoring station, its enclosure or \
its instruments are clearly in frame.

You describe. You do not decide whether the case is closed. Low confidence is better \
than a confident guess."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_genuine_site_photo": {"type": "BOOLEAN"},
        "rejection_reason": {"type": "STRING", "enum": REJECTIONS, "nullable": True},
        "active_sources_visible": {"type": "ARRAY", "items": {"type": "STRING", "enum": ACTIVE_SOURCES}},
        "remediation_visible": {"type": "ARRAY", "items": {"type": "STRING", "enum": REMEDIATION}},
        "shows_monitoring_equipment": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "STRING"},
    },
    "required": ["is_genuine_site_photo", "active_sources_visible", "remediation_visible",
                 "shows_monitoring_equipment", "confidence", "notes"],
}


def examine(image_bytes: bytes, mime_type: str, case_summary: str) -> ClosurePhoto:
    """Describe a closure photo. Raises ClosureCheckUnavailable on any failure."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ClosureCheckUnavailable("GEMINI_API_KEY is not set")
    model_name = os.environ.get("GEMINI_MODEL_FLASH", "gemini-3.1-flash-lite")

    try:
        from google import genai
        from google.genai import types

        from api.gemini import generate_with_retry

        resp = generate_with_retry(
            genai.Client(api_key=api_key),
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                f"The case this photo is meant to close: {case_summary}",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.1,
            ),
        )
        result = ClosurePhoto(**json.loads(resp.text))
    except Exception as e:
        logger.warning("closure photo check failed: %s", e)
        raise ClosureCheckUnavailable(str(e)) from e

    if not result.is_genuine_site_photo:
        result.active_sources_visible = []
        result.remediation_visible = []
        result.shows_monitoring_equipment = False
    return result
