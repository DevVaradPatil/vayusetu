"""
api/gemini/agent.py — "Ask Vayu" Conversational Function-Calling Agent.

W3.4: Implements the Vayu AI assistant using Gemini 2.5 Pro function calling.
      Six defined tools — citations required in every response.

Tools:
  1. get_current_aqi     — PM2.5 and AQI band for a location
  2. get_forecast        — 72h forecast for a city
  3. list_hotspots       — Top N ranked hotspot cells for a tenant
  4. get_fires_upwind    — Active fire pixels in upwind sector for a cell
  5. explain_cell        — Full grounded attribution brief for a cell
  6. compare_cities      — Side-by-side AQI comparison between two tenants

Rule R5: Agent must cite tool-returned data fields in every substantive claim.
         Agent never invents numbers or measurements.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vayusetu.gemini.agent")


# ---------------------------------------------------------------------------
# Tool implementations (backed by seed data; hook to BigQuery in production)
# ---------------------------------------------------------------------------

def _tool_get_current_aqi(tenant: str, location_name: Optional[str] = None) -> Dict[str, Any]:
    """Returns current PM2.5 prediction and AQI band for tenant."""
    from ingestion.stations import generate_seed_stations
    from ingestion.common import resolve_as_of
    from ml.common import compute_idw_baseline, get_cpcb_aqi_band

    stations = generate_seed_stations(tenant)
    if not stations:
        return {"error": f"No stations found for tenant '{tenant}'"}

    avg_pm25 = round(sum(s["value"] for s in stations) / len(stations), 1)
    band, color = get_cpcb_aqi_band(avg_pm25)

    return {
        "tenant": tenant,
        "location": location_name or tenant.upper(),
        "pm25_current": avg_pm25,
        "aqi_band": band,
        "color_hex": color,
        "station_count": len(stations),
        "as_of": resolve_as_of().isoformat(),
    }


def _tool_get_forecast(tenant: str, city: str = "Delhi") -> Dict[str, Any]:
    """Returns 72h multi-horizon PM2.5 forecast."""
    from datetime import timedelta
    from ml.common import get_cpcb_aqi_band

    now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    horizons = [6, 24, 48, 72]
    base = 210.0
    points = []
    for h in horizons:
        spike = 90.0 if h == 24 else (40.0 if h == 48 else 10.0)
        p50 = round(base + spike, 1)
        band, _ = get_cpcb_aqi_band(p50)
        points.append({
            "horizon_h": h,
            "target_ts": (now_utc + timedelta(hours=h)).isoformat(),
            "pm25_p50": p50,
            "pm25_p10": round(p50 - 25, 1),
            "pm25_p90": round(p50 + 35, 1),
            "aqi_band": band,
        })

    return {
        "tenant": tenant,
        "city": city,
        "issued_at": now_utc.isoformat(),
        "forecast_points": points,
        "peak_horizon_h": 24,
        "peak_pm25_p50": 300.0,
        "peak_aqi_band": "Severe",
    }


def _tool_list_hotspots(tenant: str, limit: int = 5) -> Dict[str, Any]:
    """Returns top N hotspot cells ranked by residual."""
    from ml.common import get_cpcb_aqi_band

    # Seed hotspot data representative of Sonipat corridor
    hotspots = [
        {"rank": 1, "cell_id": "ncr-2863-7731", "lat": 28.63, "lon": 77.31,
         "pm25_pred": 310.4, "idw_baseline": 181.2, "residual": 129.2,
         "confidence": 0.78, "population_exposed": 84000, "aqi_band": "Severe"},
        {"rank": 2, "cell_id": "ncr-2860-7729", "lat": 28.60, "lon": 77.29,
         "pm25_pred": 271.0, "idw_baseline": 185.0, "residual": 86.0,
         "confidence": 0.71, "population_exposed": 52000, "aqi_band": "Severe"},
        {"rank": 3, "cell_id": "ncr-2858-7725", "lat": 28.58, "lon": 77.25,
         "pm25_pred": 238.0, "idw_baseline": 184.0, "residual": 54.0,
         "confidence": 0.64, "population_exposed": 31000, "aqi_band": "Very Poor"},
    ]

    return {
        "tenant": tenant,
        "count": min(limit, len(hotspots)),
        "hotspots": hotspots[:limit],
    }


def _tool_get_fires_upwind(tenant: str, cell_id: str, wind_dir_deg: float = 310.0) -> Dict[str, Any]:
    """Returns fire pixels detected in the upwind sector of a given cell."""
    from ingestion.fires import generate_seed_fires
    from ingestion.common import get_cell_center
    from api.gemini.attribution import assemble_upwind_fires

    # Normalize cell_id separators (accept both 'ncr:2863:7731' and 'ncr-2863-7731')
    normalized_cell_id = cell_id.replace(":", "-")
    lat, lon = get_cell_center(normalized_cell_id)
    ncr_bbox = (28.20, 76.80, 28.95, 77.60)
    fires = generate_seed_fires(ncr_bbox)
    count, total_frp, upwind_fires = assemble_upwind_fires(lat, lon, fires, wind_dir_deg)

    return {
        "cell_id": cell_id,
        "wind_dir_deg": wind_dir_deg,
        "upwind_fires_count": count,
        "upwind_fires_total_frp_mw": total_frp,
        "fires": [f.model_dump() for f in upwind_fires[:10]],   # Max 10 for prompt length
    }


def _tool_explain_cell(tenant: str, cell_id: str) -> Dict[str, Any]:
    """Returns grounded attribution brief for a hotspot cell."""
    from ingestion.fires import generate_seed_fires
    from ingestion.common import get_cell_center
    from api.gemini.attribution import assemble_evidence, generate_attribution_brief

    # Normalize cell_id separators (accept both 'ncr:2863:7731' and 'ncr-2863-7731')
    normalized_cell_id = cell_id.replace(":", "-")
    lat, lon = get_cell_center(normalized_cell_id)
    cell_id = normalized_cell_id
    fires = generate_seed_fires((28.20, 76.80, 28.95, 77.60))

    evidence = assemble_evidence(
        cell_id=normalized_cell_id, cell_lat=lat, cell_lon=lon,
        pm25_pred=310.4, idw_baseline=181.2, confidence_score=0.78,
        wind_dir_deg=310.0, wind_speed_ms=3.0,
        fires=fires, no2_col_ratio=2.1,
        citizen_reports_count=3,
        citizen_source_votes={"crop_residue_burning": 3},
    )
    brief = generate_attribution_brief(evidence)

    return {
        "cell_id": cell_id,
        "tenant": tenant,
        "pm25_pred": evidence.pm25_pred,
        "residual": evidence.residual,
        "confidence": evidence.confidence_score,
        "cause_category": brief.cause_category,
        "cause": brief.cause,
        "narrative": brief.narrative,
        "evidence_cited": brief.evidence_cited,
        "recommended_actions": brief.recommended_actions,
    }


def _tool_compare_cities(tenant_a: str, tenant_b: str) -> Dict[str, Any]:
    """Compares AQI and hotspot count between two tenants."""
    result_a = _tool_get_current_aqi(tenant_a)
    result_b = _tool_get_current_aqi(tenant_b)
    hotspots_a = _tool_list_hotspots(tenant_a, limit=100)
    hotspots_b = _tool_list_hotspots(tenant_b, limit=100)

    return {
        "comparison": [
            {
                "tenant": tenant_a,
                "pm25_current": result_a.get("pm25_current"),
                "aqi_band": result_a.get("aqi_band"),
                "hotspot_count": hotspots_a.get("count", 0),
            },
            {
                "tenant": tenant_b,
                "pm25_current": result_b.get("pm25_current"),
                "aqi_band": result_b.get("aqi_band"),
                "hotspot_count": hotspots_b.get("count", 0),
            },
        ]
    }


# Tool dispatch table
TOOL_HANDLERS = {
    "get_current_aqi": _tool_get_current_aqi,
    "get_forecast": _tool_get_forecast,
    "list_hotspots": _tool_list_hotspots,
    "get_fires_upwind": _tool_get_fires_upwind,
    "explain_cell": _tool_explain_cell,
    "compare_cities": _tool_compare_cities,
}

# Gemini tool declarations
GEMINI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "get_current_aqi",
                "description": "Get current PM2.5 and AQI band for a tenant/city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant": {"type": "string", "description": "Tenant ID, e.g. 'ncr' or 'lko'"},
                        "location_name": {"type": "string", "description": "Optional human-readable city name"},
                    },
                    "required": ["tenant"],
                },
            },
            {
                "name": "get_forecast",
                "description": "Get 72h PM2.5 forecast at +6h, +24h, +48h, +72h horizons.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant": {"type": "string"},
                        "city": {"type": "string"},
                    },
                    "required": ["tenant"],
                },
            },
            {
                "name": "list_hotspots",
                "description": "List top N pollution hotspots ranked by residual PM2.5 for a tenant.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant": {"type": "string"},
                        "limit": {"type": "integer", "description": "Max hotspots to return (default 5)"},
                    },
                    "required": ["tenant"],
                },
            },
            {
                "name": "get_fires_upwind",
                "description": "Get active fire pixels in the 100 km upwind sector of a grid cell.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant": {"type": "string"},
                        "cell_id": {"type": "string"},
                        "wind_dir_deg": {"type": "number", "description": "Wind direction (degrees FROM which wind blows)"},
                    },
                    "required": ["tenant", "cell_id"],
                },
            },
            {
                "name": "explain_cell",
                "description": "Get grounded source attribution brief for a hotspot grid cell.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant": {"type": "string"},
                        "cell_id": {"type": "string"},
                    },
                    "required": ["tenant", "cell_id"],
                },
            },
            {
                "name": "compare_cities",
                "description": "Compare current AQI and hotspot count between two city tenants.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_a": {"type": "string"},
                        "tenant_b": {"type": "string"},
                    },
                    "required": ["tenant_a", "tenant_b"],
                },
            },
        ]
    }
]


# ---------------------------------------------------------------------------
# Agent: simple agentic loop (Gemini function calling)
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_PROMPT = """\
You are Vayu, the AI assistant for VayuSetu, India's air-quality intelligence platform.
You have access to live air quality data tools listed below.

Rules:
- ALWAYS call tools to get real data before making claims.
- NEVER invent PM2.5 numbers, fire counts, or AQI bands.
- Cite the specific field names and values from tool results in your response.
- Respond clearly and concisely. Lead with the most important fact.
- Keep responses under 300 words unless the user asks for detail.
- For actionable hotspots, always mention population exposure if available.
"""


class VayuAgentResponse:
    def __init__(self, answer: str, tool_calls_made: List[str], model_used: str):
        self.answer = answer
        self.tool_calls_made = tool_calls_made
        self.model_used = model_used


def ask_vayu(question: str, max_tool_rounds: int = 5) -> VayuAgentResponse:
    """
    Processes a user question through the Vayu conversational agent.
    Uses Gemini 2.5 Pro function calling with automatic tool dispatch.
    Falls back to a grounded mock answer if API key is missing.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        logger.info("Gemini API key not configured. Using mock agent response.")
        return _mock_agent_response(question)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-2.5-pro",
            system_instruction=_AGENT_SYSTEM_PROMPT,
            tools=GEMINI_TOOLS,
        )

        chat = model.start_chat()
        tool_calls_made = []

        # Agentic loop with max_tool_rounds guard
        response = chat.send_message(question)

        for _ in range(max_tool_rounds):
            if not response.candidates:
                break

            candidate = response.candidates[0]
            # Check for function calls
            has_function_call = any(
                part.function_call.name
                for part in candidate.content.parts
                if hasattr(part, "function_call") and part.function_call.name
            )

            if not has_function_call:
                break

            # Execute all function calls in parallel
            tool_responses = []
            for part in candidate.content.parts:
                if not hasattr(part, "function_call") or not part.function_call.name:
                    continue
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args)
                tool_calls_made.append(fn_name)

                if fn_name in TOOL_HANDLERS:
                    result = TOOL_HANDLERS[fn_name](**fn_args)
                else:
                    result = {"error": f"Unknown tool: {fn_name}"}

                tool_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": result},
                        )
                    )
                )

            if tool_responses:
                response = chat.send_message(tool_responses)
            else:
                break

        # Extract final text response
        final_text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text"):
                final_text += part.text

        return VayuAgentResponse(
            answer=final_text.strip(),
            tool_calls_made=tool_calls_made,
            model_used="gemini-2.5-pro",
        )

    except Exception as e:
        logger.warning(f"Ask Vayu agent failed ({e}). Using mock response.")
        return _mock_agent_response(question)


def _mock_agent_response(question: str) -> VayuAgentResponse:
    """Grounded mock response exercising all 6 tool handlers."""
    q_lower = question.lower()

    if "hotspot" in q_lower or "worst" in q_lower:
        data = _tool_list_hotspots("ncr", limit=3)
        top = data["hotspots"][0]
        answer = (
            f"The current worst hotspot in Delhi-NCR is cell {top['cell_id']} "
            f"(lat={top['lat']}, lon={top['lon']}) with a predicted PM2.5 of "
            f"{top['pm25_pred']} µg/m³ — {top['residual']} µg/m³ above the station "
            f"interpolation baseline. AQI: {top['aqi_band']}. "
            f"~{top['population_exposed']:,} people exposed."
        )
        tools = ["list_hotspots"]
    elif "forecast" in q_lower or "tomorrow" in q_lower:
        data = _tool_get_forecast("ncr", "Delhi")
        peak = data["forecast_points"][1]  # +24h
        answer = (
            f"Delhi PM2.5 forecast: peak at +{peak['horizon_h']}h with "
            f"P50={peak['pm25_p50']} µg/m³ [P10={peak['pm25_p10']}, P90={peak['pm25_p90']}]. "
            f"AQI band: {peak['aqi_band']}. Exercise and outdoor events should be avoided."
        )
        tools = ["get_forecast"]
    elif "fire" in q_lower or "upwind" in q_lower:
        data = _tool_get_fires_upwind("ncr", "ncr-2863-7731", wind_dir_deg=310.0)
        answer = (
            f"Upwind sector analysis for cell ncr:2863:7731 (wind FROM 310°): "
            f"{data['upwind_fires_count']} active fire pixels, total FRP "
            f"{data['upwind_fires_total_frp_mw']} MW — consistent with post-harvest "
            f"stubble burning in Sonipat-Panipat belt."
        )
        tools = ["get_fires_upwind"]
    elif "explain" in q_lower or "attribut" in q_lower or "source" in q_lower:
        data = _tool_explain_cell("ncr", "ncr-2863-7731")
        answer = (
            f"Attribution for {data['cell_id']}: {data['narrative']} "
            f"Evidence cited: {', '.join(data['evidence_cited'][:3])}."
        )
        tools = ["explain_cell"]
    elif "compar" in q_lower or "lucknow" in q_lower or "vs" in q_lower:
        data = _tool_compare_cities("ncr", "lko")
        cities = data["comparison"]
        answer = (
            f"Comparison — {cities[0]['tenant'].upper()}: PM2.5={cities[0]['pm25_current']} µg/m³ "
            f"({cities[0]['aqi_band']}), {cities[0]['hotspot_count']} hotspots | "
            f"{cities[1]['tenant'].upper()}: PM2.5={cities[1]['pm25_current']} µg/m³ "
            f"({cities[1]['aqi_band']}), {cities[1]['hotspot_count']} hotspots."
        )
        tools = ["compare_cities"]
    else:
        data = _tool_get_current_aqi("ncr", "Delhi-NCR")
        answer = (
            f"Current Delhi-NCR air quality: PM2.5 = {data['pm25_current']} µg/m³ "
            f"(AQI band: {data['aqi_band']}). Based on {data['station_count']} reporting stations."
        )
        tools = ["get_current_aqi"]

    return VayuAgentResponse(answer=answer, tool_calls_made=tools, model_used="mock_grounded")


# ---------------------------------------------------------------------------
# Demo / Self-Test
# ---------------------------------------------------------------------------

def demo():
    print("=== Ask Vayu Function-Calling Agent Demo (W3.4) ===")

    # Test all 6 tool handlers directly
    print("\n--- Tool 1: get_current_aqi ---")
    r1 = _tool_get_current_aqi("ncr", "Delhi")
    assert "pm25_current" in r1 and "aqi_band" in r1
    print(f"  [OK] PM2.5={r1['pm25_current']}, Band={r1['aqi_band']}, Stations={r1['station_count']}")

    print("\n--- Tool 2: get_forecast ---")
    r2 = _tool_get_forecast("ncr", "Delhi")
    assert len(r2["forecast_points"]) == 4
    assert all(p["horizon_h"] in [6, 24, 48, 72] for p in r2["forecast_points"])
    print(f"  [OK] 4 forecast horizons, peak at +{r2['peak_horizon_h']}h: {r2['peak_pm25_p50']} µg/m³")

    print("\n--- Tool 3: list_hotspots ---")
    r3 = _tool_list_hotspots("ncr", limit=3)
    assert r3["count"] >= 1
    top = r3["hotspots"][0]
    assert top["residual"] > 60, "Top hotspot should have residual > 60"
    print(f"  [OK] Top hotspot: {top['cell_id']}, residual={top['residual']} µg/m³, "
          f"pop_exposed={top['population_exposed']:,}")

    print("\n--- Tool 4: get_fires_upwind ---")
    r4 = _tool_get_fires_upwind("ncr", "ncr-2863-7731", wind_dir_deg=310.0)
    assert r4["upwind_fires_count"] >= 1
    print(f"  [OK] {r4['upwind_fires_count']} upwind fires, total FRP={r4['upwind_fires_total_frp_mw']} MW")

    print("\n--- Tool 5: explain_cell ---")
    r5 = _tool_explain_cell("ncr", "ncr-2863-7731")
    assert "narrative" in r5 and len(r5["evidence_cited"]) >= 1
    print(f"  [OK] Cause: {r5['cause_category']}, Evidence citations: {len(r5['evidence_cited'])}")

    print("\n--- Tool 6: compare_cities ---")
    r6 = _tool_compare_cities("ncr", "lko")
    assert len(r6["comparison"]) == 2
    print(f"  [OK] NCR vs LKO: "
          f"{r6['comparison'][0]['pm25_current']} vs {r6['comparison'][1]['pm25_current']} µg/m³")

    # End-to-end question routing
    print("\n--- End-to-End Question Routing ---")
    test_questions = [
        ("What are the worst hotspots right now?", "list_hotspots"),
        ("What will air quality be tomorrow?", "get_forecast"),
        ("Are there fires upwind of Delhi?", "get_fires_upwind"),
        ("Explain the pollution source at cell ncr-2863-7731", "explain_cell"),
        ("Compare Delhi and Lucknow air quality", "compare_cities"),
        ("What is the current AQI in Delhi?", "get_current_aqi"),
    ]

    for question, expected_tool in test_questions:
        response = ask_vayu(question)
        assert expected_tool in response.tool_calls_made, (
            f"Expected tool '{expected_tool}' for question: '{question}', "
            f"got {response.tool_calls_made}"
        )
        assert len(response.answer) > 20, f"Answer too short for: '{question}'"
        print(f"  [OK] Q: '{question[:50]}...' -> Tool: {response.tool_calls_made}")

    print("\nAll Ask Vayu agent checks passed successfully!")


if __name__ == "__main__":
    demo()
