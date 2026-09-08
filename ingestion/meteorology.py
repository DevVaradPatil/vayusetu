"""
ingestion/meteorology.py — Open-Meteo & ERA5 Meteorological Data Ingestion Module.

Fetches forecast and observed weather variables (wind speed, wind direction, boundary layer height,
temperature, relative humidity, precipitation) for tenant grid cells.

Calculates wind u/v components enforcing meteorological wind convention (direction wind comes FROM)
strictly per docs/DATA_CONTRACTS.md §2.
"""

import json
import logging
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ingestion.common import resolve_as_of, get_cell_id, retry_with_backoff

logger = logging.getLogger("vayusetu.ingestion.meteorology")

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"


def calculate_wind_components(wind_speed_ms: float, wind_dir_deg: float) -> Tuple[float, float]:
    """
    Calculates (wind_u, wind_v) components from speed and meteorological wind direction (FROM bearing).
    
    wind_u = - wind_speed * sin(rad(wind_dir))  (eastward component)
    wind_v = - wind_speed * cos(rad(wind_dir))  (northward component)
    """
    rad = math.radians(wind_dir_deg)
    wind_u = round(-wind_speed_ms * math.sin(rad), 2)
    wind_v = round(-wind_speed_ms * math.cos(rad), 2)
    return wind_u, wind_v


@retry_with_backoff(max_retries=3, initial_delay=1.0)
def fetch_open_meteo_forecast(
    lat: float,
    lon: float,
    as_of: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Queries Open-Meteo REST API for hourly forecast variables.
    """
    as_of_dt = resolve_as_of(as_of)
    start_date = as_of_dt.strftime("%Y-%m-%d")
    end_date = (as_of_dt + timedelta(days=3)).strftime("%Y-%m-%d")

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,boundary_layer_height",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "UTC"
    }

    url = f"{OPEN_METEO_BASE_URL}?" + urllib.parse.urlencode(params)
    logger.info(f"Fetching Open-Meteo forecast for ({lat}, {lon})")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "VayuSetu/1.0 (CleanAirCommunity)")

    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"Open-Meteo API HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARS = (
    "temperature_2m,relative_humidity_2m,precipitation,"
    "wind_speed_10m,wind_direction_10m,boundary_layer_height"
)


@retry_with_backoff(max_retries=3, initial_delay=2.0)
def fetch_open_meteo_archive(
    lat: float,
    lon: float,
    date_from: datetime,
    date_to: datetime,
) -> Dict[str, Any]:
    """
    Historical reanalysis for [date_from, date_to] from Open-Meteo's archive API.

    This is the training-data path for meteorology, and it matters because it
    removes a hard dependency: the plan called for ERA5 via Earth Engine, which
    needs a registered EE project. The archive API is the same underlying ERA5
    reanalysis, over plain HTTP, with no key and no registration — so Model A can
    be trained on real meteorology while Earth Engine access is still pending.

    Earth Engine is still needed for the satellite layer (MAIAC AOD, S5P). This
    only unblocks the meteorological features.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_VARS,
        "start_date": date_from.strftime("%Y-%m-%d"),
        "end_date": date_to.strftime("%Y-%m-%d"),
        "timezone": "UTC",
    }
    url = f"{OPEN_METEO_ARCHIVE_URL}?" + urllib.parse.urlencode(params)
    logger.info("Fetching Open-Meteo archive for (%s, %s) %s..%s",
                lat, lon, params["start_date"], params["end_date"])

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "VayuSetu/1.0 (CleanAirCommunity)")
    with urllib.request.urlopen(req, timeout=90) as response:
        if response.status != 200:
            raise RuntimeError(f"Open-Meteo archive HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def parse_meteorology_records(
    open_meteo_response: Dict[str, Any],
    tenant: str,
    cell_id: str,
    as_of: Optional[datetime] = None,
    is_forecast: bool = True
) -> List[Dict[str, Any]]:
    """
    Parses Open-Meteo hourly response arrays into `raw_meteorology` records.
    """
    as_of_dt = resolve_as_of(as_of)
    issued_at = as_of_dt.isoformat() if is_forecast else None
    ingested_at = datetime.now(timezone.utc).isoformat()

    hourly = open_meteo_response.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    rhs = hourly.get("relative_humidity_2m", [])
    precips = hourly.get("precipitation", [])
    speeds_kmh = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])
    blhs = hourly.get("boundary_layer_height", [])

    records = []
    for idx, t_str in enumerate(times):
        dt_obj = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)

        # Open-Meteo returns wind speed in km/h or m/s depending on unit settings. Default is km/h.
        speed_kmh = float(speeds_kmh[idx]) if idx < len(speeds_kmh) and speeds_kmh[idx] is not None else 0.0
        speed_ms = round(speed_kmh / 3.6, 2)
        wind_dir = float(dirs[idx]) if idx < len(dirs) and dirs[idx] is not None else 0.0

        wind_u, wind_v = calculate_wind_components(speed_ms, wind_dir)

        temp_c = float(temps[idx]) if idx < len(temps) and temps[idx] is not None else None
        rh = float(rhs[idx]) if idx < len(rhs) and rhs[idx] is not None else None
        precip_mm = float(precips[idx]) if idx < len(precips) and precips[idx] is not None else 0.0

        # Boundary layer height fallback: if missing from API, estimate ~300m winter BLH
        blh = float(blhs[idx]) if idx < len(blhs) and blhs[idx] is not None else 320.0

        records.append({
            "cell_id": cell_id,
            "ts": dt_obj.isoformat(),
            "is_forecast": is_forecast,
            "issued_at": issued_at,
            "wind_u": wind_u,
            "wind_v": wind_v,
            "wind_speed": speed_ms,
            "wind_dir": wind_dir,
            "blh": blh,
            "temp_c": temp_c,
            "rh": rh,
            "precip_mm": precip_mm,
            "ingested_at": ingested_at
        })

    return records


def generate_seed_meteorology(
    tenant: str,
    cell_id: str,
    as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Generates realistic seed meteorology for testing/replay when offline.
    North-westerly winter wind (wind_dir ~ 310°, coming FROM Sonipat towards Delhi).
    """
    as_of_dt = resolve_as_of(as_of)
    base_ts = as_of_dt.replace(minute=0, second=0, microsecond=0)
    ingested_at = datetime.now(timezone.utc).isoformat()

    records = []
    for h in range(24):
        ts = (base_ts + timedelta(hours=h)).isoformat()
        wind_speed_ms = round(3.0 + (h % 5) * 0.4, 2)
        wind_dir = 310.0  # North-Westerly stubble plume direction
        wind_u, wind_v = calculate_wind_components(wind_speed_ms, wind_dir)

        records.append({
            "cell_id": cell_id,
            "ts": ts,
            "is_forecast": True,
            "issued_at": base_ts.isoformat(),
            "wind_u": wind_u,
            "wind_v": wind_v,
            "wind_speed": wind_speed_ms,
            "wind_dir": wind_dir,
            "blh": 280.0 + (h % 8) * 35.0,
            "temp_c": round(18.5 + (h % 12) * 0.8, 1),
            "rh": round(65.0 - (h % 10) * 2.0, 1),
            "precip_mm": 0.0,
            "ingested_at": ingested_at
        })
    return records


def demo():
    print("=== Ingestion Demo: Open-Meteo Meteorology ===")
    as_of = resolve_as_of()
    lat, lon = 28.6315, 77.3102
    cell_id = get_cell_id("ncr", lat, lon)

    # Test wind vector math
    u_n, v_n = calculate_wind_components(10.0, 0.0)    # Wind FROM North -> blows South (v < 0)
    assert u_n == 0.0 and v_n == -10.0, f"North wind math failed: ({u_n}, {v_n})"
    
    u_w, v_w = calculate_wind_components(10.0, 270.0)  # Wind FROM West -> blows East (u > 0)
    assert u_w == 10.0 and v_w == 0.0, f"West wind math failed: ({u_w}, {v_w})"
    print("  [OK] Meteorological wind vector math verified.")

    try:
        data = fetch_open_meteo_forecast(lat, lon, as_of)
        records = parse_meteorology_records(data, "ncr", cell_id, as_of)
        print(f"  [OK] Fetched live Open-Meteo forecast: {len(records)} hourly records.")
    except Exception as e:
        print(f"  [INFO] Live Open-Meteo fetch offline ({e}). Using seed meteorology dataset.")
        records = generate_seed_meteorology("ncr", cell_id, as_of)
        print(f"  [OK] Generated seed meteorology: {len(records)} hourly records.")

    # Validate schema strictly against docs/DATA_CONTRACTS.md §2 raw_meteorology
    required_keys = {"cell_id", "ts", "is_forecast", "issued_at", "wind_u", "wind_v", "wind_speed", "wind_dir", "blh", "temp_c", "rh", "precip_mm", "ingested_at"}
    for rec in records:
        missing = required_keys - rec.keys()
        assert not missing, f"Missing keys in raw_meteorology: {missing}"
        assert 0 <= rec["wind_dir"] <= 360, f"Invalid wind_dir: {rec['wind_dir']}"

    sample = records[0]
    print(f"  [OK] Sample Meteorology Record:\n{json.dumps(sample, indent=4)}")
    print("\nAll Open-Meteo meteorology ingestion checks passed successfully!")


if __name__ == "__main__":
    demo()
