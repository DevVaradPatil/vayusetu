"""
api/gemini/brief.py — Turn measured evidence into an actionable brief with Gemini.

This is where Google AI does the work that nothing else in the stack can. The
numbers come from `api/evidence.py`, all measured from real observations. Gemini's
job is reasoning over them: deciding which driver dominates, how confident that
conclusion is, and which office should act — then saying it in language a district
officer or a resident can use.

Rule R5 (AGENTS.md) is enforced in code, not just requested in the prompt:
  - every field named in `evidence_cited` must exist in the payload
  - anything in `missing_fields` must appear in `caveats`
  - a brief that cites nothing is rejected

That check is what keeps this an explanation of the data rather than plausible
prose that happens to sit next to it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vayusetu.api.gemini.brief")

CAUSE_CATEGORIES = [
    "crop_residue_burning", "waste_burning", "construction_dust",
    "industrial_plume", "vehicular_smoke", "dust_storm",
    "secondary_formation", "meteorological_trapping", "unknown",
]

SYSTEM_PROMPT = """You are an air quality analyst writing an operational brief for \
Indian pollution control officials.

You will receive a JSON payload of MEASURED observations for one hour in one city.

Absolute rules:
1. Use ONLY numbers present in the payload. Never invent, estimate or round a \
measurement that is not there.
2. Every claim in your narrative must correspond to a field you list in \
evidence_cited. Use dotted paths, e.g. "upwind_fires.count".
3. Every entry in the payload's missing_fields MUST appear in your caveats.
4. If the evidence does not support a confident cause, return cause_category \
"unknown" with low confidence. A confident wrong attribution sends officials to the \
wrong district — that is worse than saying you do not know.
5. recommended_actions name a ROLE or OFFICE, never a person, never a contact detail.
6. Do not describe the method as back-trajectory modelling. It is a wind-sector cone.

Interpreting the drivers:
- boundary_layer_m below ~200 m means a collapsed inversion trapping emissions near \
the surface. This multiplies concentrations without any change in emissions.
- upwind_fires.count is fires inside a +/-30 degree cone up to 100 km upwind, over \
the last 48 hours. wind.from_bearing_deg is the direction wind comes FROM.
- ratio_to_baseline compares this hour to the trailing 14-day mean.

Return ONLY JSON with these keys:
  cause: one sentence naming the dominant driver
  cause_category: one of CAUSE_CATEGORIES
  confidence: 0.0-1.0
  evidence_cited: array of dotted field paths from the payload
  narrative: 2-4 sentences an official can read aloud, citing the actual numbers
  recommended_actions: array of {actor, action, urgency} where urgency is \
low|medium|high|immediate
  caveats: array of strings
  public_advisory: ONE plain sentence for residents, no jargon, no numbers beyond \
the AQI band
"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "cause": {"type": "STRING"},
        "cause_category": {"type": "STRING", "enum": CAUSE_CATEGORIES},
        "confidence": {"type": "NUMBER"},
        "evidence_cited": {"type": "ARRAY", "items": {"type": "STRING"}},
        "narrative": {"type": "STRING"},
        "recommended_actions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "actor": {"type": "STRING"},
                    "action": {"type": "STRING"},
                    "urgency": {"type": "STRING", "enum": ["low", "medium", "high", "immediate"]},
                },
                "required": ["actor", "action", "urgency"],
            },
        },
        "caveats": {"type": "ARRAY", "items": {"type": "STRING"}},
        "public_advisory": {"type": "STRING"},
    },
    "required": ["cause", "cause_category", "confidence", "evidence_cited",
                 "narrative", "recommended_actions", "caveats", "public_advisory"],
}


def _flatten(payload: Dict[str, Any], prefix: str = "") -> set:
    """All dotted paths in the payload, for citation checking."""
    out = set()
    for k, v in payload.items():
        path = f"{prefix}{k}"
        out.add(path)
        if isinstance(v, dict):
            out |= _flatten(v, f"{path}.")
    return out


def verify(brief: Dict[str, Any], evidence: Dict[str, Any]) -> List[str]:
    """
    Check the brief against R5. Returns a list of violations; empty means clean.

    Kept separate from generation so it can be run over any brief, including ones
    read back from storage.
    """
    problems: List[str] = []
    valid_paths = _flatten(evidence)

    cited = brief.get("evidence_cited") or []
    if not cited:
        problems.append("cites no evidence at all")
    for path in cited:
        root = path.split("=")[0].strip()
        if root not in valid_paths:
            problems.append(f"cites non-existent field '{root}'")

    missing = evidence.get("missing_fields") or []
    caveat_text = " ".join(brief.get("caveats") or []).lower()
    for m in missing:
        token = m.split()[0].lower().strip("(),")
        if token and token not in caveat_text:
            problems.append(f"missing field '{m}' not disclosed in caveats")

    for action in brief.get("recommended_actions") or []:
        actor = (action.get("actor") or "").lower()
        if "@" in actor or any(ch.isdigit() for ch in actor):
            problems.append(f"action actor looks like a contact detail: {actor!r}")

    conf = brief.get("confidence")
    if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
        problems.append(f"confidence out of range: {conf!r}")

    return problems


def generate(evidence: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a verified brief. Raises if Gemini is unavailable or output fails R5
    after one retry — a silently-degraded brief is worse than none, because it looks
    identical to a real one.
    """
    # google-genai, not google-generativeai: the latter is end-of-life and no longer
    # receives fixes, so shipping it in requirements.txt would be a liability.
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    model_name = model or os.environ.get("GEMINI_MODEL_PRO", "gemini-3.5-flash-lite")
    client = genai.Client(api_key=api_key)

    payload = json.dumps(evidence, indent=2, default=str)
    last_problems: List[str] = []

    from api.gemini import generate_with_retry

    for attempt in (1, 2):
        # Transient 503s are retried inside the helper; this loop is only for
        # briefs that come back but fail R5 verification.
        resp = generate_with_retry(
            client,
            model=model_name,
            contents=payload,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.2,
            ),
        )
        brief = json.loads(resp.text)
        problems = verify(brief, evidence)
        if not problems:
            brief["generated_at"] = datetime.now(timezone.utc).isoformat()
            brief["model"] = model_name
            brief["verified"] = True
            return brief

        last_problems = problems
        logger.warning("brief attempt %d failed R5: %s", attempt, problems)

    raise ValueError(f"Gemini brief failed R5 verification twice: {last_problems}")


def demo() -> None:
    from api import evidence as ev_mod

    ev = ev_mod.assemble(datetime(2025, 11, 11, 20, 0, tzinfo=timezone.utc))
    payload = ev.to_dict()
    brief = generate(payload)

    assert not verify(brief, payload), "generated brief must pass its own verifier"
    assert brief["cause_category"] in CAUSE_CATEGORIES

    print(f"CAUSE      : {brief['cause']}")
    print(f"CATEGORY   : {brief['cause_category']}  (confidence {brief['confidence']})")
    print(f"\nNARRATIVE  : {brief['narrative']}")
    print(f"\nCITED      : {', '.join(brief['evidence_cited'])}")
    print("\nACTIONS:")
    for a in brief["recommended_actions"]:
        print(f"  [{a['urgency'].upper():9s}] {a['actor']}: {a['action']}")
    print(f"\nCAVEATS    : {brief['caveats']}")
    print(f"\nPUBLIC     : {brief['public_advisory']}")
    print(f"\n[OK] verified against R5, model={brief['model']}")


if __name__ == "__main__":
    import pathlib
    logging.basicConfig(level=logging.WARNING)
    for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    demo()
