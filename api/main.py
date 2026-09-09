"""
api/main.py — FastAPI Application for VayuSetu.

Implements REST API endpoints per docs/DATA_CONTRACTS.md §5:
- GET /healthz
- GET /api/v1/tenants
- GET /api/v1/{tenant}/stations/current
- GET /api/v1/{tenant}/grid
- GET /api/v1/{tenant}/hotspots
- GET /api/v1/{tenant}/cells/{cell_id}
- GET /api/v1/{tenant}/forecast
- POST /api/v1/{tenant}/reports

W3 additions:
- POST /api/v1/{tenant}/cells/{cell_id}/attribution   (W3.1+W3.2)
- POST /api/v1/{tenant}/alerts                        (W3.3)
- GET  /api/v1/advisory                               (W3.5)
- POST /api/v1/ask                                    (W3.4)
- GET  /api/v1/registry                               (W3.10)
- POST /api/v1/registry/import                        (W3.11)
"""

import math
import os
import yaml
from pathlib import Path

# Load .env before anything imports os.environ at module scope. Without this the
# service starts fine and then 500s on the first BigQuery call, which is a
# confusing way to discover a missing variable. setdefault, so a real environment
# (Cloud Run) always wins over the local file.
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Form, Body
from fastapi.middleware.cors import CORSMiddleware

from ingestion.common import resolve_as_of, get_cell_id, get_cell_center
from ingestion.stations import generate_seed_stations
from ingestion.fires import generate_seed_fires
from ingestion.static_layers import generate_grid_cells_for_tenant
from ml.common import compute_idw_baseline, compute_confidence, is_hotspot, get_cpcb_aqi_band
from api.gemini.vision import analyze_citizen_photo
from api.validation import validate_citizen_upload, apply_fusion_rule
from api.gemini.attribution import assemble_evidence, generate_attribution_brief
from api.gemini.advisory import generate_advisory, SUPPORTED_LANGUAGES
from api.gemini.agent import ask_vayu
from api.alerts import generate_alert
from ml.registry import list_registry, import_model_card

app = FastAPI(
    title="VayuSetu Intelligence API",
    description="Federated air-quality intelligence platform API for India",
    version="1.0.0"
)

from api.routes_episode import router as episode_router

app.include_router(episode_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_tenant_config() -> dict:
    config_path = Path(__file__).parent.parent / "infra" / "tenants.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.get("/healthz", summary="Liveness check")
def healthz():
    return {"status": "ok", "service": "vayusetu-api", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/tenants", summary="List active tenants and bounding boxes")
def list_tenants():
    config = load_tenant_config()
    tenants = config.get("tenants", {})
    output = []
    for key, data in tenants.items():
        output.append({
            "tenant": key,
            "name": data.get("name"),
            "state": data.get("state"),
            "bounds": data.get("bounds"),
            "description": data.get("description")
        })
    return {"tenants": output}


@app.get("/api/v1/{tenant}/stations/current", summary="Get current station readings")
def get_current_stations(tenant: str, as_of: Optional[str] = None):
    config = load_tenant_config()
    if tenant not in config.get("tenants", {}):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")

    as_of_dt = resolve_as_of(datetime.fromisoformat(as_of) if as_of else None)
    stations = generate_seed_stations(tenant, as_of_dt)

    now_utc = datetime.now(timezone.utc)
    for s in stations:
        ts_dt = datetime.fromisoformat(s["ts"])
        hours_old = (now_utc - ts_dt).total_seconds() / 3600.0
        s["is_stale"] = hours_old > 3.0

    return {
        "tenant": tenant,
        "as_of": as_of_dt.isoformat(),
        "count": len(stations),
        "stations": stations
    }


@app.get("/api/v1/{tenant}/grid", summary="Get cell grid predictions and residuals")
def get_grid(
    tenant: str,
    as_of: Optional[str] = None,
    layer: str = Query("pm25", regex="^(pm25|residual)$")
):
    config = load_tenant_config()
    if tenant not in config.get("tenants", {}):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")

    cells = generate_grid_cells_for_tenant(tenant)
    as_of_dt = resolve_as_of(datetime.fromisoformat(as_of) if as_of else None)
    stations = generate_seed_stations(tenant, as_of_dt)

    grid_output = []
    for c in cells[:600]:
        cell_id = c["cell_id"]
        idw = compute_idw_baseline(c["lat"], c["lon"], stations) or 180.0
        
        # Simulate hotspot plume around Sonipat corridor (28.63°N, 77.31°E)
        dist_plume = math.sqrt((c["lat"] - 28.63)**2 + (c["lon"] - 77.31)**2)
        plume_spike = 130.0 * math.exp(-dist_plume / 0.08)
        pred = round(idw + plume_spike, 1)
        res = round(pred - idw, 1)
        conf = compute_confidence(pred, pred - 15, pred + 25)
        hotspot = is_hotspot(pred, idw, conf)

        grid_output.append({
            "cell_id": cell_id,
            "lat": c["lat"],
            "lon": c["lon"],
            "pm25_pred": pred,
            "idw_baseline": idw,
            "residual": res,
            "confidence": conf,
            "is_hotspot": hotspot
        })

    return {
        "tenant": tenant,
        "as_of": as_of_dt.isoformat(),
        "layer": layer,
        "count": len(grid_output),
        "grid": grid_output
    }


@app.get("/api/v1/{tenant}/hotspots", summary="List ranked pollution hotspots")
def list_hotspots(tenant: str, limit: int = 10, district: Optional[str] = None):
    grid_res = get_grid(tenant)
    grid_cells = grid_res["grid"]

    hotspots = [c for c in grid_cells if c["is_hotspot"]]
    # Rank by severity x residual
    hotspots.sort(key=lambda x: x["residual"], reverse=True)

    ranked_output = []
    for rank, h in enumerate(hotspots[:limit], start=1):
        band, color = get_cpcb_aqi_band(h["pm25_pred"])
        ranked_output.append({
            "rank": rank,
            "cell_id": h["cell_id"],
            "lat": h["lat"],
            "lon": h["lon"],
            "predicted_pm25": h["pm25_pred"],
            "idw_baseline": h["idw_baseline"],
            "residual": h["residual"],
            "confidence": h["confidence"],
            "population_exposed": 84000 if rank == 1 else 32000,
            "aqi_band": band,
            "color_hex": color,
            "likely_source": "Long-range transport of crop residue smoke from Sonipat-Panipat belt"
        })

    return {
        "tenant": tenant,
        "count": len(ranked_output),
        "hotspots": ranked_output
    }


@app.get("/api/v1/{tenant}/cells/{cell_id}", summary="Get cell inspector payload")
def get_cell_inspector(tenant: str, cell_id: str):
    lat, lon = get_cell_center(cell_id)
    stations = generate_seed_stations(tenant)
    idw = compute_idw_baseline(lat, lon, stations) or 180.0
    pred = 310.4 if "2863" in cell_id else 195.0
    res = round(pred - idw, 1)
    conf = 0.78
    band, color = get_cpcb_aqi_band(pred)

    attribution = {
        "cause": "Long-range transport of crop residue smoke from Sonipat-Panipat belt",
        "cause_category": "crop_residue_burning",
        "confidence": conf,
        "evidence_cited": ["upwind_fires.count=47", "wind.bearing=310°", "no2_anomaly_ratio=2.1", "citizen_reports.source_votes=4"],
        "narrative": "47 active fire pixels detected 18–34 km upwind in Sonipat with a 310° wind at 11 km/h. NO₂ column 2.1× 30-day mean.",
        "recommended_actions": [
            {"actor": "Sonipat district agriculture officer", "action": "Field verification of 47 detected fire locations", "urgency": "high"}
        ]
    }

    return {
        "cell_id": cell_id,
        "tenant": tenant,
        "lat": lat,
        "lon": lon,
        "predicted_pm25": pred,
        "idw_baseline": idw,
        "residual": res,
        "confidence": conf,
        "is_hotspot": is_hotspot(pred, idw, conf),
        "population_exposed": 84000,
        "aqi_band": band,
        "color_hex": color,
        "attribution": attribution
    }


@app.get("/api/v1/{tenant}/forecast", summary="Get 72h AQI forecast")
def get_forecast(tenant: str, city: str = "Delhi"):
    now_utc = datetime.now(timezone.utc)
    base_ts = now_utc.replace(minute=0, second=0, microsecond=0)

    horizons = [6, 24, 48, 72]
    forecast_points = []
    base_pm25 = 210.0

    for h in horizons:
        target_ts = (base_ts + timedelta(hours=h)).isoformat()
        # Simulated spike at +24h
        spike = 90.0 if h == 24 else (40.0 if h == 48 else 10.0)
        p50 = round(base_pm25 + spike, 1)
        p10 = round(p50 - 25.0, 1)
        p90 = round(p50 + 35.0, 1)

        forecast_points.append({
            "horizon_h": h,
            "target_ts": target_ts,
            "pm25_p10": p10,
            "pm25_p50": p50,
            "pm25_p90": p90,
            "aqi_band": get_cpcb_aqi_band(p50)[0]
        })

    return {
        "tenant": tenant,
        "city": city,
        "issued_at": base_ts.isoformat(),
        "forecast": forecast_points
    }


@app.post("/api/v1/{tenant}/reports", summary="Upload citizen haze photo report")
async def upload_citizen_report(
    tenant: str,
    lat: float = Form(...),
    lon: float = Form(...),
    session_id: str = Form(...),
    file: UploadFile = File(...)
):
    config = load_tenant_config()
    tenants = config.get("tenants", {})
    if tenant not in tenants:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")

    bounds_dict = tenants[tenant]["bounds"]
    bbox = (bounds_dict["lat_min"], bounds_dict["lon_min"], bounds_dict["lat_max"], bounds_dict["lon_max"])

    content = await file.read()
    now_utc = datetime.now(timezone.utc)

    # Server-Side Trust Boundary Validation
    is_valid, err_reason = validate_citizen_upload(
        tenant=tenant, bbox=bbox, lat=lat, lon=lon,
        photo_ts=now_utc, file_size_bytes=len(content),
        content_type=file.content_type or "image/jpeg", session_id=session_id
    )

    if not is_valid:
        return {
            "report_id": f"rep_rejected_{now_utc.timestamp()}",
            "is_valid": False,
            "rejection_reason": err_reason,
            "gemini_analysis": None
        }

    # Gemini 2.5 Flash Vision Analysis
    analysis = analyze_citizen_photo(content, file.content_type or "image/jpeg")

    return {
        "report_id": f"rep_{int(now_utc.timestamp())}",
        "tenant": tenant,
        "cell_id": get_cell_id(tenant, lat, lon),
        "is_valid": True,
        "gemini_analysis": analysis.model_dump()
    }


# ---------------------------------------------------------------------------
# W3 Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/{tenant}/cells/{cell_id}/attribution", summary="Gemini 2.5 Pro source attribution brief")
def get_attribution(
    tenant: str,
    cell_id: str,
    wind_dir_deg: float = Query(310.0, description="Wind direction (degrees FROM which wind blows)"),
    wind_speed_ms: float = Query(3.0, description="Wind speed in m/s"),
):
    """W3.1 + W3.2: Returns grounded Gemini attribution brief for a hotspot cell."""
    config = load_tenant_config()
    if tenant not in config.get("tenants", {}):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")

    lat, lon = get_cell_center(cell_id)
    stations = generate_seed_stations(tenant)
    fires = generate_seed_fires((
        config["tenants"][tenant]["bounds"]["lat_min"],
        config["tenants"][tenant]["bounds"]["lon_min"],
        config["tenants"][tenant]["bounds"]["lat_max"],
        config["tenants"][tenant]["bounds"]["lon_max"],
    ))

    idw = compute_idw_baseline(lat, lon, stations) or 180.0
    pred = 310.4 if "2863" in cell_id else 195.0
    conf = compute_confidence(pred, pred - 25, pred + 35)

    evidence = assemble_evidence(
        cell_id=cell_id, cell_lat=lat, cell_lon=lon,
        pm25_pred=pred, idw_baseline=idw, confidence_score=conf,
        wind_dir_deg=wind_dir_deg, wind_speed_ms=wind_speed_ms,
        fires=fires,
        no2_col_ratio=2.1,
        citizen_reports_count=3,
        citizen_source_votes={"crop_residue_burning": 3},
    )
    brief = generate_attribution_brief(evidence)

    return {
        "cell_id": cell_id,
        "tenant": tenant,
        "evidence": evidence.model_dump(),
        "attribution": brief.model_dump(),
    }


@app.post("/api/v1/{tenant}/alerts", summary="Generate alert for a hotspot cell")
def trigger_alert(
    tenant: str,
    cell_id: str = Query(...),
    population_exposed: int = Query(0),
):
    """W3.3: Evaluates alert thresholds and dispatches to mock official accounts."""
    config = load_tenant_config()
    if tenant not in config.get("tenants", {}):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")

    lat, lon = get_cell_center(cell_id)
    stations = generate_seed_stations(tenant)
    fires = generate_seed_fires((
        config["tenants"][tenant]["bounds"]["lat_min"],
        config["tenants"][tenant]["bounds"]["lon_min"],
        config["tenants"][tenant]["bounds"]["lat_max"],
        config["tenants"][tenant]["bounds"]["lon_max"],
    ))

    idw = compute_idw_baseline(lat, lon, stations) or 180.0
    pred = 310.4 if "2863" in cell_id else 195.0
    conf = compute_confidence(pred, pred - 25, pred + 35)

    evidence = assemble_evidence(
        cell_id=cell_id, cell_lat=lat, cell_lon=lon,
        pm25_pred=pred, idw_baseline=idw, confidence_score=conf,
        wind_dir_deg=310.0, wind_speed_ms=3.0, fires=fires,
    )
    brief = generate_attribution_brief(evidence)
    alert = generate_alert(tenant, evidence, brief, population_exposed)

    if alert is None:
        return {"alert": None, "message": "Below alert threshold — no alert generated."}

    return {"alert": alert.model_dump()}


@app.get("/api/v1/advisory", summary="Get multilingual air quality advisory")
def get_advisory(
    aqi_band: str = Query("Severe", description="CPCB AQI band name"),
    lang: str = Query("en", description="ISO 639-1 language code (en, hi, ta, ...)"),
):
    """W3.5: Returns translated advisory text in the requested language."""
    result = generate_advisory(aqi_band, lang)
    return result.model_dump()


@app.get("/api/v1/advisory/languages", summary="List supported advisory languages")
def get_advisory_languages():
    """Returns the list of supported advisory languages."""
    return {"languages": SUPPORTED_LANGUAGES}


@app.post("/api/v1/ask", summary="Ask Vayu — conversational AI assistant")
def ask_vayu_endpoint(body: dict = Body(...)):
    """W3.4: Processes a natural language question through the Ask Vayu function-calling agent."""
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="'question' field is required")

    response = ask_vayu(question)
    return {
        "question": question,
        "answer": response.answer,
        "tool_calls_made": response.tool_calls_made,
        "model_used": response.model_used,
    }


@app.get("/api/v1/registry", summary="List federated model registry")
def get_registry(tenant: Optional[str] = None):
    """W3.10: Lists all published model cards, optionally filtered by tenant."""
    cards = list_registry(tenant)
    return {"count": len(cards), "cards": cards}


@app.post("/api/v1/registry/import", summary="Import model from registry to target city")
def registry_import(
    model_id: str = Query(...),
    source_tenant: str = Query(...),
    task: str = Query("gridded_pm25_estimation"),
    target_tenant: str = Query(...),
):
    """W3.11: Imports a model card from source city to target city with honest transfer metrics."""
    try:
        result = import_model_card(model_id, source_tenant, task, target_tenant)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
