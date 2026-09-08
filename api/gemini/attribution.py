"""
api/gemini/attribution.py — Gemini 2.5 Pro Source Attribution Module.

W3.1 + W3.2: Assembles structured evidence payload from upwind wind-sector analysis
and invokes Gemini 2.5 Pro to produce grounded source attribution briefs.

Rule R5: Gemini gets structured evidence, not raw speculation.
         Every claim in the brief must cite a field in the evidence payload.
         Gemini never invents a measurement; missing fields are declared as such.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ml.common import (
    haversine_distance_km,
    is_point_in_upwind_sector,
    get_cpcb_aqi_band,
)

logger = logging.getLogger("vayusetu.gemini.attribution")


# ---------------------------------------------------------------------------
# Evidence payload schema (R5 compliance)
# ---------------------------------------------------------------------------

class UpwindFire(BaseModel):
    fire_id: str
    lat: float
    lon: float
    distance_km: float
    bearing_deg: float
    frp: float
    confidence: str


class AttributionEvidence(BaseModel):
    """Structured evidence payload assembled before calling Gemini 2.5 Pro."""
    cell_id: str
    cell_lat: float
    cell_lon: float
    as_of: str

    # Predicted air quality
    pm25_pred: float
    pm25_p10: Optional[float] = None
    pm25_p90: Optional[float] = None
    idw_baseline: float
    residual: float
    confidence_score: float
    aqi_band: str

    # Wind at time of analysis
    wind_dir_deg: float          # direction wind comes FROM
    wind_speed_kmh: float
    wind_u: Optional[float] = None   # m/s eastward component
    wind_v: Optional[float] = None   # m/s northward component

    # Upwind fire sector (100 km cone)
    upwind_fires_count: int
    upwind_fires_total_frp: float
    upwind_fires: List[UpwindFire] = Field(default_factory=list)

    # Satellite-derived indicators
    aod_550nm: Optional[float] = None          # MAIAC AOD
    no2_col_ratio: Optional[float] = None      # NO2 column / 30-day mean
    satellite_age_h: Optional[float] = None    # Hours since last MAIAC pass

    # Land use of hotspot cell
    land_use_dominant: Optional[str] = None    # crop, urban, industrial, bare
    population_density: Optional[float] = None

    # Citizen reports
    citizen_reports_count: int = 0
    citizen_source_votes: Dict[str, int] = Field(default_factory=dict)


class AttributionBrief(BaseModel):
    """Grounded attribution output from Gemini 2.5 Pro."""
    cause: str
    cause_category: str    # crop_residue_burning | industrial | vehicular | dust | fog | unknown
    confidence: float      # 0.0 – 1.0
    evidence_cited: List[str]    # Must reference fields from AttributionEvidence
    narrative: str               # ≤ 400 chars
    recommended_actions: List[Dict[str, str]]
    generated_at: str
    model_used: str


# ---------------------------------------------------------------------------
# Step 1: Upwind sector fire aggregation (W3.1)
# ---------------------------------------------------------------------------

def assemble_upwind_fires(
    cell_lat: float,
    cell_lon: float,
    fires: List[Dict[str, Any]],
    wind_dir_deg: float,
    cone_angle_deg: float = 30.0,
    max_radius_km: float = 100.0,
) -> Tuple[int, float, List[UpwindFire]]:
    """
    Filters fires list to those lying inside the upwind sector cone.
    Returns (count, total_frp, list[UpwindFire]).

    wind_dir_deg is direction wind comes FROM per ml/common.py convention.
    """
    upwind: List[UpwindFire] = []

    for f in fires:
        fire_lat = f.get("lat")
        fire_lon = f.get("lon")
        frp = f.get("frp", 0.0)
        if fire_lat is None or fire_lon is None:
            continue

        in_sector, dist_km, bearing_deg = is_point_in_upwind_sector(
            cell_lat, cell_lon, fire_lat, fire_lon,
            wind_dir_deg=wind_dir_deg,
            cone_angle_deg=cone_angle_deg,
            max_radius_km=max_radius_km,
        )

        if in_sector:
            upwind.append(UpwindFire(
                fire_id=f.get("fire_id", "unknown"),
                lat=fire_lat,
                lon=fire_lon,
                distance_km=dist_km,
                bearing_deg=bearing_deg,
                frp=frp,
                confidence=f.get("confidence", "nominal"),
            ))

    total_frp = round(sum(u.frp for u in upwind), 1)
    return len(upwind), total_frp, upwind


def assemble_evidence(
    cell_id: str,
    cell_lat: float,
    cell_lon: float,
    pm25_pred: float,
    idw_baseline: float,
    confidence_score: float,
    wind_dir_deg: float,
    wind_speed_ms: float,
    fires: List[Dict[str, Any]],
    pm25_p10: Optional[float] = None,
    pm25_p90: Optional[float] = None,
    aod_550nm: Optional[float] = None,
    no2_col_ratio: Optional[float] = None,
    satellite_age_h: Optional[float] = None,
    land_use_dominant: Optional[str] = None,
    population_density: Optional[float] = None,
    citizen_reports_count: int = 0,
    citizen_source_votes: Optional[Dict[str, int]] = None,
    as_of: Optional[datetime] = None,
) -> AttributionEvidence:
    """
    Assembles the full structured evidence payload for a hotspot cell (W3.1).
    This is the only object that Gemini receives — no raw data, no speculation.
    """
    as_of_dt = as_of or datetime.now(timezone.utc)
    wind_speed_kmh = round(wind_speed_ms * 3.6, 1)

    # Wind vector components (wind_dir convention: direction wind comes FROM)
    import math
    wind_u = round(-wind_speed_ms * math.sin(math.radians(wind_dir_deg)), 2)
    wind_v = round(-wind_speed_ms * math.cos(math.radians(wind_dir_deg)), 2)

    count, total_frp, upwind_fires = assemble_upwind_fires(
        cell_lat, cell_lon, fires, wind_dir_deg
    )

    aqi_band, _ = get_cpcb_aqi_band(pm25_pred)
    residual = round(pm25_pred - idw_baseline, 1)

    return AttributionEvidence(
        cell_id=cell_id,
        cell_lat=cell_lat,
        cell_lon=cell_lon,
        as_of=as_of_dt.isoformat(),
        pm25_pred=pm25_pred,
        pm25_p10=pm25_p10,
        pm25_p90=pm25_p90,
        idw_baseline=idw_baseline,
        residual=residual,
        confidence_score=confidence_score,
        aqi_band=aqi_band,
        wind_dir_deg=wind_dir_deg,
        wind_speed_kmh=wind_speed_kmh,
        wind_u=wind_u,
        wind_v=wind_v,
        upwind_fires_count=count,
        upwind_fires_total_frp=total_frp,
        upwind_fires=upwind_fires,
        aod_550nm=aod_550nm,
        no2_col_ratio=no2_col_ratio,
        satellite_age_h=satellite_age_h,
        land_use_dominant=land_use_dominant,
        population_density=population_density,
        citizen_reports_count=citizen_reports_count,
        citizen_source_votes=citizen_source_votes or {},
    )


# ---------------------------------------------------------------------------
# Step 2: Gemini 2.5 Pro source attribution brief (W3.2)
# ---------------------------------------------------------------------------

_ATTRIBUTION_SYSTEM_PROMPT = """\
You are the attribution engine for VayuSetu, India's air-quality hotspot platform.
Your ONLY source of facts is the JSON evidence payload provided by the user.
Do NOT invent measurements, distances, or fire counts.
If a field is null or absent, say so explicitly.

Output ONLY a valid JSON object matching this exact schema:
{
  "cause": "<concise phrase, ≤ 10 words>",
  "cause_category": "<one of: crop_residue_burning | industrial | vehicular | dust | fog | unknown>",
  "confidence": <float 0.0–1.0>,
  "evidence_cited": ["<field_name>=<value>", ...],
  "narrative": "<factual paragraph ≤ 400 chars citing evidence fields>",
  "recommended_actions": [
    {"actor": "<role>", "action": "<specific action>", "urgency": "<high|medium|low>"}
  ]
}

Citation rules:
- evidence_cited must list the evidence payload fields that support your conclusion.
- narrative must not assert any number that is not in the evidence payload.
- If upwind_fires_count is 0, do not assert fires as the cause.
- If no2_col_ratio is null, do not reference NO₂ as evidence.
"""


def _make_attribution_mock(evidence: AttributionEvidence) -> AttributionBrief:
    """Fallback attribution without Gemini API key — constructs a grounded brief from evidence."""
    fires_count = evidence.upwind_fires_count
    frp = evidence.upwind_fires_total_frp
    wind_dir = evidence.wind_dir_deg
    wind_speed = evidence.wind_speed_kmh
    residual = evidence.residual
    no2 = evidence.no2_col_ratio
    citizen_votes = evidence.citizen_source_votes

    # Determine cause category from evidence
    if fires_count >= 5:
        cause_cat = "crop_residue_burning"
        cause = f"Long-range stubble smoke transport from {fires_count} upwind fires"
    elif citizen_votes.get("industrial_plume", 0) >= 2:
        cause_cat = "industrial"
        cause = "Local industrial plume (citizen observation)"
    elif evidence.land_use_dominant == "urban":
        cause_cat = "vehicular"
        cause = "Dense vehicular and local combustion emissions"
    else:
        cause_cat = "unknown"
        cause = "Mixed sources — insufficient evidence to isolate cause"

    cited = [
        f"upwind_fires_count={fires_count}",
        f"upwind_fires_total_frp={frp}",
        f"wind_dir_deg={wind_dir}",
        f"wind_speed_kmh={wind_speed}",
        f"residual={residual}",
        f"citizen_reports_count={evidence.citizen_reports_count}",
    ]
    if no2 is not None:
        cited.append(f"no2_col_ratio={no2}")

    narrative = (
        f"{fires_count} fire pixels ({frp} MW total FRP) detected "
        f"{evidence.upwind_fires[0].distance_km if evidence.upwind_fires else '?'} km upwind "
        f"on a {wind_dir}° wind at {wind_speed} km/h. "
        f"Residual PM2.5 above IDW baseline: {residual} µg/m³. "
        f"AQI band: {evidence.aqi_band}."
    )[:400]

    actions = [
        {
            "actor": "District agriculture officer",
            "action": f"Field inspection of {fires_count} detected stubble fire locations",
            "urgency": "high" if fires_count >= 10 else "medium",
        }
    ]

    return AttributionBrief(
        cause=cause,
        cause_category=cause_cat,
        confidence=min(0.9, round(0.5 + fires_count * 0.02 + 0.1 * (1 if no2 else 0), 2)),
        evidence_cited=cited,
        narrative=narrative,
        recommended_actions=actions,
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_used="mock_grounded",
    )


def generate_attribution_brief(evidence: AttributionEvidence) -> AttributionBrief:
    """
    Calls Gemini 2.5 Pro with structured evidence payload.
    Falls back to grounded mock if API key missing.
    Enforces citation checking per Rule R5.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        logger.info("Gemini API key not configured. Using grounded mock attribution.")
        return _make_attribution_mock(evidence)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-2.5-pro",
            system_instruction=_ATTRIBUTION_SYSTEM_PROMPT,
        )

        user_payload = json.dumps(evidence.model_dump(), indent=2)
        response = model.generate_content(
            user_payload,
            generation_config={"response_mime_type": "application/json"},
        )

        data = json.loads(response.text)

        # R5 enforcement: verify that evidence_cited fields exist in evidence payload
        evidence_dict = evidence.model_dump()
        flat_evidence_keys = set(evidence_dict.keys())
        for citation in data.get("evidence_cited", []):
            field_name = citation.split("=")[0].strip()
            if field_name not in flat_evidence_keys:
                logger.warning(
                    f"R5 violation: Gemini cited non-existent field '{field_name}'. "
                    f"Falling back to grounded mock."
                )
                return _make_attribution_mock(evidence)

        return AttributionBrief(
            **data,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used="gemini-2.5-pro",
        )

    except Exception as e:
        logger.warning(f"Gemini attribution failed ({e}). Falling back to grounded mock.")
        return _make_attribution_mock(evidence)


# ---------------------------------------------------------------------------
# Demo / Self-Test
# ---------------------------------------------------------------------------

def demo():
    print("=== Gemini 2.5 Pro Source Attribution Demo (W3.1 + W3.2) ===")

    from ingestion.fires import generate_seed_fires

    # Seed fire data for Sonipat-Panipat belt
    ncr_bbox = (28.20, 76.80, 28.95, 77.60)
    fires = generate_seed_fires(ncr_bbox)
    print(f"  [OK] Loaded {len(fires)} seed fire records from Sonipat/Panipat belt")

    # Assemble upwind fire sector for hotspot cell at 28.63°N, 77.31°E
    # Wind FROM 310° (NW) at 3 m/s — typical Delhi winter anticyclone
    count, frp, upwind = assemble_upwind_fires(
        cell_lat=28.63, cell_lon=77.31,
        fires=fires,
        wind_dir_deg=310.0,
    )
    print(f"  [OK] Upwind fires in 310° sector (100km, ±30°): {count} fires, total FRP {frp} MW")
    assert count >= 1, "Expected at least 1 upwind fire in the 310° sector"

    # Assemble full evidence payload
    evidence = assemble_evidence(
        cell_id="ncr:2863:7731",
        cell_lat=28.63,
        cell_lon=77.31,
        pm25_pred=310.4,
        idw_baseline=181.2,
        confidence_score=0.78,
        wind_dir_deg=310.0,
        wind_speed_ms=3.0,
        fires=fires,
        pm25_p10=285.0,
        pm25_p90=338.0,
        aod_550nm=1.42,
        no2_col_ratio=2.1,
        satellite_age_h=6.0,
        land_use_dominant="crop",
        population_density=4200.0,
        citizen_reports_count=3,
        citizen_source_votes={"crop_residue_burning": 3},
    )

    # Validate evidence payload schema
    assert evidence.residual == 129.2, f"Residual mismatch: {evidence.residual}"
    assert evidence.upwind_fires_count == count
    assert evidence.wind_u is not None and evidence.wind_v is not None
    print(f"  [OK] Evidence payload assembled: residual={evidence.residual} µg/m³, "
          f"upwind_fires={evidence.upwind_fires_count}, NO2 ratio={evidence.no2_col_ratio}")
    print(f"  [OK] Wind vector: U={evidence.wind_u} m/s, V={evidence.wind_v} m/s "
          f"(FROM {evidence.wind_dir_deg}°, {evidence.wind_speed_kmh} km/h)")

    # Generate attribution brief
    brief = generate_attribution_brief(evidence)
    print(f"\n  Attribution Brief:")
    print(f"    Cause Category : {brief.cause_category}")
    print(f"    Cause          : {brief.cause}")
    print(f"    Confidence     : {brief.confidence}")
    print(f"    Evidence Cited : {brief.evidence_cited}")
    print(f"    Narrative      : {brief.narrative}")
    print(f"    Actions        : {brief.recommended_actions}")
    print(f"    Model          : {brief.model_used}")

    # Validate brief schema
    assert brief.cause_category in {
        "crop_residue_burning", "industrial", "vehicular", "dust", "fog", "unknown"
    }, f"Invalid cause_category: {brief.cause_category}"
    assert 0.0 <= brief.confidence <= 1.0, f"Confidence out of bounds: {brief.confidence}"
    assert len(brief.narrative) <= 400, f"Narrative too long: {len(brief.narrative)} chars"
    assert len(brief.evidence_cited) >= 1, "Must cite at least one evidence field"

    print("\nAll attribution module checks passed successfully!")


if __name__ == "__main__":
    demo()
