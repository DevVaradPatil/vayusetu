"""
api/main.py — the FastAPI service.

Most of the product lives in `api/routes_episode.py`, which serves everything the
website reads: the episode, the open interchange event, the timeline, the map, the
hotspots, and the resident page in ten languages. What remains here is the service
shell plus the two things that are not about one hour of air: the citizen photo
upload, and the federated model registry.

Ten endpoints that used to sit in this file were deleted rather than kept, because
they returned invented numbers. `/grid` and `/hotspots` ranked cells by a Gaussian
plume added in Python around a hardcoded coordinate, with `population_exposed`
literally written as `84000 if rank == 1 else 32000`. `/forecast` returned a
"spike at +24h" that was the constant 90. `/cells/{id}` returned 310.4 for any cell
id containing "2863". A demo that fabricates the thing the project claims to detect
is worse than no demo: it cannot be distinguished from a working one. The real
detector is `api/hotspots.py`, which is measurement only and reports zero when
there is nothing to report.
"""

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

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware

from ingestion.common import get_cell_id
from api.gemini.vision import analyze_citizen_photo, VisionUnavailable
from api.validation import validate_citizen_upload
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

    # No fabricated triage on failure. This used to fall back to a fixed "heavy
    # haze" grade for every photo; a resident is better told "try again later"
    # than told their clear sky is smoke.
    try:
        analysis = analyze_citizen_photo(content, file.content_type or "image/jpeg")
    except VisionUnavailable as e:
        raise HTTPException(status_code=503, detail=f"Photo check is unavailable right now: {e}")

    return {
        "report_id": f"rep_{int(now_utc.timestamp())}",
        "tenant": tenant,
        "cell_id": get_cell_id(tenant, lat, lon),
        "is_valid": True,
        "gemini_analysis": analysis.model_dump()
    }


@app.get("/api/v1/registry", summary="List federated model registry")
def get_registry(tenant: Optional[str] = None):
    """Lists all published model cards, optionally filtered by tenant."""
    cards = list_registry(tenant)
    return {"count": len(cards), "cards": cards}


@app.post("/api/v1/registry/import", summary="Import model from registry to target city")
def registry_import(
    model_id: str = Query(...),
    source_tenant: str = Query(...),
    task: str = Query("gridded_pm25_estimation"),
    target_tenant: str = Query(...),
):
    """Imports a model card from source city to target city with honest transfer metrics."""
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
