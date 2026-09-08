"""
ingestion/fires.py — NASA FIRMS Active Fire Ingestion Module.

Fetches VIIRS/MODIS active fire detections within a 200 km buffer around tenant areas
(capturing stubble burning in Punjab and Haryana for NCR).
Formats records into `vayusetu_shared.raw_fires` strictly matching docs/DATA_CONTRACTS.md §2.
"""

import csv
import hashlib
import io
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ingestion.common import resolve_as_of, retry_with_backoff

logger = logging.getLogger("vayusetu.ingestion.fires")

# docs/DATA_CONTRACTS.md §2: raw_fires is not tenant-scoped precisely because the
# relevant fires are outside the tenant bbox. 200 km covers the Punjab-Haryana belt.
FIRE_BUFFER_KM = 200.0

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Boundary between the NRT and SP products. Query /api/data_availability/csv/{key}/all
# to re-check; it moves forward as NASA promotes NRT granules to science processing.
NRT_AVAILABLE_FROM = datetime(2026, 4, 28, tzinfo=timezone.utc)


def calculate_expanded_bbox(
    bbox: Tuple[float, float, float, float],
    buffer_km: float = 200.0
) -> Tuple[float, float, float, float]:
    """
    Expands bounding box (lat_min, lon_min, lat_max, lon_max) by buffer_km.
    At 28°N, 1 degree lat ~ 111 km, 1 degree lon ~ 98 km.
    """
    lat_buf = buffer_km / 111.0
    lon_buf = buffer_km / 98.0
    
    lat_min, lon_min, lat_max, lon_max = bbox
    return (
        round(lat_min - lat_buf, 4),
        round(lon_min - lon_buf, 4),
        round(lat_max + lat_buf, 4),
        round(lon_max + lon_buf, 4)
    )


def generate_fire_id(satellite: str, lat: float, lon: float, acq_ts: str) -> str:
    """
    Generates deterministic fire_id: hash("{satellite}:{lat}:{lon}:{acq_ts}")
    """
    raw_str = f"{satellite}:{lat:.4f}:{lon:.4f}:{acq_ts}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


@retry_with_backoff(max_retries=3, initial_delay=1.0)
def fetch_firms_fires(
    bbox: Tuple[float, float, float, float],
    as_of: Optional[datetime] = None,
    day_range: int = 2,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetches FIRMS active fire pixels for expanded bbox for date of `as_of`.
    """
    as_of_dt = resolve_as_of(as_of)
    map_key = os.getenv("FIRMS_MAP_KEY")

    if not map_key:
        logger.warning("FIRMS_MAP_KEY not set. Returning empty list for fallback handling.")
        return []

    # Expand before querying. The fires that drive Delhi's winter PM2.5 burn in
    # Punjab and Haryana, 100-200 km upwind and well outside the NCR bbox — so
    # querying the raw bbox returns almost nothing and leaves source attribution
    # with nothing to attribute to. calculate_expanded_bbox() existed for this and
    # was simply never called.
    expanded = calculate_expanded_bbox(bbox, buffer_km=FIRE_BUFFER_KM)
    lat_min, lon_min, lat_max, lon_max = expanded
    # FIRMS CSV bbox: min_lon,min_lat,max_lon,max_lat
    bbox_str = f"{lon_min},{lat_min},{lon_max},{lat_max}"

    # FIRMS treats the date as the START of a `day_range` window running FORWARD.
    # Passing as_of directly asks for a window that is mostly in the future and
    # returns zero rows — verified 2026-09-07: `/2/<today>` gave 0 while the same
    # query without a date gave 4. Back-date the start so the window ENDS at as_of.
    start_dt = as_of_dt - timedelta(days=max(0, day_range - 1))
    date_str = start_dt.strftime("%Y-%m-%d")

    # FIRMS splits the same instrument across two products by age, and querying the
    # wrong one returns an empty CSV rather than an error — which reads exactly like
    # "no fires burned". Verified against /api/data_availability on 2026-09-07:
    #
    #   VIIRS_SNPP_NRT : 2026-04-28 -> today      (near-real-time)
    #   VIIRS_SNPP_SP  : 2012-01-20 -> 2026-04-27 (science processing, historical)
    #
    # The Nov 2025 stubble-season backfill therefore needs SP. Auto-select on the
    # window's start date unless the caller pins a source.
    src = source or ("VIIRS_SNPP_NRT" if start_dt >= NRT_AVAILABLE_FROM else "VIIRS_SNPP_SP")
    url = f"{FIRMS_BASE_URL}/{map_key}/{src}/{bbox_str}/{day_range}/{date_str}"
    logger.info(f"Fetching FIRMS fire data from URL: {url.replace(map_key, 'REDACTED')}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "VayuSetu/1.0 (CleanAirCommunity)")

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            content = response.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            logger.info("Retrieved %d FIRMS pixels from %s starting %s", len(rows), src, date_str)
            return rows
    except Exception as e:
        logger.warning(f"Failed to fetch FIRMS fire data: {e}")
        return []


def parse_and_clean_fires(
    raw_fires: List[Dict[str, Any]],
    as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Parses FIRMS raw CSV dicts into `raw_fires` schema.
    """
    as_of_dt = resolve_as_of(as_of)
    ingested_at = datetime.now(timezone.utc)
    clean_records = []

    for row in raw_fires:
        try:
            lat = float(row.get("latitude", 0))
            lon = float(row.get("longitude", 0))
            frp = float(row.get("frp", 0.0))
            confidence_raw = str(row.get("confidence", "nominal")).lower()

            # Confidence normalization (h=high, n=nominal, l=low)
            if confidence_raw in ["h", "high"]:
                confidence = "high"
            elif confidence_raw in ["l", "low"]:
                confidence = "low"
            else:
                confidence = "nominal"

            acq_date = row.get("acq_date", as_of_dt.strftime("%Y-%m-%d"))
            acq_time = row.get("acq_time", "0000").zfill(4)
            hour = int(acq_time[:2])
            minute = int(acq_time[2:])

            dt_obj = datetime.strptime(acq_date, "%Y-%m-%d").replace(
                hour=hour, minute=minute, tzinfo=timezone.utc
            )
            acq_ts_str = dt_obj.isoformat()

            satellite = row.get("satellite", "VIIRS_SNPP")
            if "N" in satellite or "NOAA" in satellite:
                sat_enum = "VIIRS_NOAA20"
            elif "M" in satellite or "MODIS" in satellite:
                sat_enum = "MODIS"
            else:
                sat_enum = "VIIRS_SNPP"

            fire_id = generate_fire_id(sat_enum, lat, lon, acq_ts_str)

            clean_records.append({
                "fire_id": fire_id,
                "lat": lat,
                "lon": lon,
                "acq_ts": acq_ts_str,
                "confidence": confidence,
                "frp": frp,
                "satellite": sat_enum,
                "ingested_at": ingested_at.isoformat()
            })
        except Exception as e:
            logger.warning(f"Error parsing FIRMS row {row}: {e}")
            continue

    return clean_records


def generate_seed_fires(
    bbox: Tuple[float, float, float, float],
    as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Generates realistic active stubble burning seed fires upwind in Punjab/Haryana (Sonipat, Panipat, Karnal).
    """
    as_of_dt = resolve_as_of(as_of)
    ingested_at = datetime.now(timezone.utc)
    acq_ts = as_of_dt.replace(minute=30, second=0, microsecond=0).isoformat()

    # Clusters upwind of Delhi in Sonipat & Panipat
    seed_clusters = [
        {"lat": 28.99, "lon": 77.01, "frp": 18.5, "conf": "high"},  # Sonipat
        {"lat": 29.05, "lon": 76.95, "frp": 24.2, "conf": "high"},
        {"lat": 29.12, "lon": 76.88, "frp": 31.0, "conf": "high"},
        {"lat": 29.39, "lon": 76.97, "frp": 42.1, "conf": "high"},  # Panipat
        {"lat": 29.45, "lon": 76.85, "frp": 15.8, "conf": "nominal"},
        {"lat": 29.68, "lon": 76.98, "frp": 55.4, "conf": "high"},  # Karnal
    ]

    records = []
    for idx, f in enumerate(seed_clusters):
        sat = "VIIRS_SNPP"
        fid = generate_fire_id(sat, f["lat"], f["lon"], acq_ts)
        records.append({
            "fire_id": fid,
            "lat": f["lat"],
            "lon": f["lon"],
            "acq_ts": acq_ts,
            "confidence": f["conf"],
            "frp": f["frp"],
            "satellite": sat,
            "ingested_at": ingested_at.isoformat()
        })
    return records


def demo():
    print("=== Ingestion Demo: NASA FIRMS Active Fires ===")
    as_of = resolve_as_of()
    ncr_bbox = (28.20, 76.80, 28.95, 77.60)
    expanded_bbox = calculate_expanded_bbox(ncr_bbox, buffer_km=200.0)

    print(f"  [OK] Bounding box expansion (200km buffer): {ncr_bbox} -> {expanded_bbox}")

    raw_data = fetch_firms_fires(expanded_bbox, as_of)

    if not raw_data:
        print("  [INFO] FIRMS API key missing or endpoint offline. Using seed stubble-burning fire dataset.")
        records = generate_seed_fires(expanded_bbox, as_of)
    else:
        records = parse_and_clean_fires(raw_data, as_of)

    print(f"  [OK] Processed {len(records)} active fire records.")

    # Validate schema strictly against docs/DATA_CONTRACTS.md §2 raw_fires
    required_keys = {"fire_id", "lat", "lon", "acq_ts", "confidence", "frp", "satellite", "ingested_at"}
    for rec in records:
        missing = required_keys - rec.keys()
        assert not missing, f"Missing required keys in raw_fires: {missing}"
        assert rec["confidence"] in ["low", "nominal", "high"], f"Invalid confidence: {rec['confidence']}"
        assert rec["satellite"] in ["VIIRS_SNPP", "VIIRS_NOAA20", "MODIS"], f"Invalid satellite: {rec['satellite']}"

    sample = records[0]
    print(f"  [OK] Sample Fire Record:\n{json.dumps(sample, indent=4)}")
    print("\nAll NASA FIRMS fire ingestion checks passed successfully!")


if __name__ == "__main__":
    demo()
