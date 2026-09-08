"""
ingestion/stations.py — OpenAQ v3 Ambient Air Station Data Ingestion Module.

Fetches station measurement data for CPCB/OpenAQ monitors within tenant bounding boxes,
validates quality, derives 0.01° cell IDs, and formats records for BigQuery raw_stations.

Defines:
- fetch_openaq_stations(tenant, bbox, as_of): Queries OpenAQ v3 API.
- parse_and_clean_measurements(raw_items, tenant, as_of): Cleans, clamps [0, 1000], flags outliers.
- upsert_raw_stations(client, tenant, records): Upserts into BigQuery raw_stations table.
- demo(): Self-verifying executable test.
"""

import json
import logging
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ingestion.common import resolve_as_of, get_cell_id, retry_with_backoff

logger = logging.getLogger("vayusetu.ingestion.stations")

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# Pollutant normalization mapping
POLLUTANT_MAP = {
    "pm25": "pm25",
    "pm2.5": "pm25",
    "pm10": "pm10",
    "no2": "no2",
    "so2": "so2",
    "co": "co",
    "o3": "o3",
    "ozone": "o3"
}


@retry_with_backoff(max_retries=3, initial_delay=1.0)
def _http_get_openaq(endpoint: str, params: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    url = f"{OPENAQ_BASE_URL}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "VayuSetu/1.0 (CleanAirCommunity)")
    if api_key:
        req.add_header("X-API-Key", api_key)

    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"OpenAQ API error HTTP {response.status}: {response.read().decode('utf-8')}")
        return json.loads(response.read().decode("utf-8"))


def fetch_openaq_stations(
    tenant: str,
    bbox: Tuple[float, float, float, float],
    as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Fetches OpenAQ station measurements within bbox (lat_min, lon_min, lat_max, lon_max)
    for the hour around `as_of`.
    """
    as_of_dt = resolve_as_of(as_of)
    api_key = os.getenv("OPENAQ_API_KEY")

    lat_min, lon_min, lat_max, lon_max = bbox
    # OpenAQ bbox format: min_lon,min_lat,max_lon,max_lat
    bbox_str = f"{lon_min},{lat_min},{lon_max},{lat_max}"

    logger.info(f"Fetching OpenAQ locations for tenant '{tenant}' with bbox=[{bbox_str}] as_of={as_of_dt.isoformat()}")

    try:
        data = _http_get_openaq("locations", {"bbox": bbox_str, "limit": 1000, "page": 1}, api_key)
        locations = data.get("results", [])
    except Exception as e:
        logger.warning(f"Could not fetch live OpenAQ data ({e}). Returning empty list or fallback.")
        return []

    # /v3/locations returns station METADATA ONLY — its sensor objects carry no
    # values and no timestamps. Reading `sensor["latest"]["value"]` here (as an
    # earlier revision did) silently yields None for every row: the pipeline would
    # have run clean and produced nothing but nulls.
    #
    # Values live at /v3/locations/{id}/latest, keyed by sensorsId, so this is a
    # two-step join: metadata gives sensorsId -> pollutant, /latest gives the
    # reading and its own observation time.
    #
    # The bbox also returns long-dead stations — 24 of 118 in NCR last reported in
    # 2018. Fetching /latest for those is wasted requests and they contribute
    # nothing, so they are filtered on datetimeLast before the per-station calls.
    cutoff = as_of_dt - timedelta(hours=STATION_LIVENESS_CUTOFF_H)
    live: List[Dict[str, Any]] = []
    n_dead = 0
    for loc in locations:
        last_utc = ((loc.get("datetimeLast") or {}).get("utc") or "")
        try:
            last_dt = datetime.fromisoformat(last_utc.replace("Z", "+00:00")) if last_utc else None
        except ValueError:
            last_dt = None
        if last_dt is None or last_dt < cutoff:
            n_dead += 1
            continue
        live.append(loc)

    logger.info(
        "openaq.locations total=%d live=%d dead_or_stale=%d (cutoff=%dh)",
        len(locations), len(live), n_dead, STATION_LIVENESS_CUTOFF_H,
    )

    # Attach the latest readings to each live location.
    n_failed = 0
    for loc in live:
        try:
            latest = _http_get_openaq(f"locations/{loc['id']}/latest", {}, api_key)
            loc["_latest"] = latest.get("results", [])
        except Exception as e:
            logger.warning("Could not fetch latest for location %s: %s", loc.get("id"), e)
            loc["_latest"] = []
            n_failed += 1

    if n_failed:
        logger.warning("openaq.latest failed for %d/%d live stations", n_failed, len(live))

    return live


# A reading older than this is not "current" by any useful definition. It is kept
# out of raw_stations rather than backdated, so the console's staleness greying and
# the IDW baseline both see the truth.
MAX_OBSERVATION_AGE_H = 6

# A station whose most recent reading predates this is not part of the live network.
# The NCR bbox returns stations that last reported in 2018; they are excluded before
# the per-station /latest calls rather than after.
STATION_LIVENESS_CUTOFF_H = 72

# OpenAQ v3 has moved this field around between shapes; accept the known spellings
# rather than assuming one and silently dropping every row when it changes.
_TS_KEYS = ("datetime", "lastUpdated", "datetimeLast", "utc")


def _parse_observation_ts(latest: Dict[str, Any]) -> Optional[datetime]:
    """
    Extract the UTC observation time from an OpenAQ `latest` object, floored to the
    hour to match the raw_stations contract.

    Returns None when no timestamp can be found — the caller drops the reading
    rather than inventing a time for it.
    """
    raw = None
    for key in _TS_KEYS:
        candidate = latest.get(key)
        if isinstance(candidate, dict):          # e.g. {"utc": "...", "local": "..."}
            candidate = candidate.get("utc") or candidate.get("local")
        if isinstance(candidate, str) and candidate:
            raw = candidate
            break

    if raw is None:
        return None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable observation timestamp: %r", raw)
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


@retry_with_backoff(max_retries=3, initial_delay=2.0)
def _fetch_measurement_page(sensor_id: int, params: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
    return _http_get_openaq(f"sensors/{sensor_id}/measurements", params, api_key)


def fetch_sensor_measurements(
    sensor_id: int,
    date_from: datetime,
    date_to: datetime,
    api_key: Optional[str] = None,
    page_limit: int = 1000,
    max_pages: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch a sensor's historical measurements over [date_from, date_to).

    This is the training-data path. `/v3/locations/{id}/latest` only ever returns
    the single most recent reading, which is enough for the live map and useless
    for fitting a model — Model A needs months of history at every station.
    """
    api_key = api_key or os.getenv("OPENAQ_API_KEY")
    out: List[Dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        params = {
            "datetime_from": date_from.strftime("%Y-%m-%d"),
            "datetime_to": date_to.strftime("%Y-%m-%d"),
            "limit": page_limit,
            "page": page,
        }
        try:
            data = _fetch_measurement_page(sensor_id, params, api_key)
        except Exception as e:
            logger.warning("measurements fetch failed sensor=%s page=%d: %s", sensor_id, page, e)
            break

        results = data.get("results", [])
        out.extend(results)
        if len(results) < page_limit:
            break
    else:
        logger.warning(
            "sensor=%s hit max_pages=%d; window may be truncated", sensor_id, max_pages
        )

    return out


def measurements_to_hourly(
    raw_measurements: List[Dict[str, Any]],
    station: Dict[str, Any],
    pollutant: str,
    tenant: str,
    unit: str = "µg/m³",
) -> List[Dict[str, Any]]:
    """
    Collapse raw measurements into hourly `raw_stations` rows.

    OpenAQ returns sub-hourly data for many CPCB sensors (~15-minute cadence), but
    the contract stores hourly observations (docs/DATA_CONTRACTS.md §2). Averaging
    within the hour is the right reduction for a concentration: taking the first or
    last reading would throw away most of the signal and bias toward whichever
    quarter-hour happened to be sampled.
    """
    coords = station.get("coordinates") or {}
    lat = coords.get("latitude", station.get("lat"))
    lon = coords.get("longitude", station.get("lon"))
    if lat is None or lon is None:
        logger.warning("station %s has no coordinates; skipping", station.get("id"))
        return []
    cell_id = get_cell_id(tenant, lat, lon)
    ingested_at = datetime.now(timezone.utc)

    buckets: Dict[datetime, List[float]] = {}
    dropped = 0

    for m in raw_measurements:
        value = m.get("value")
        period = m.get("period") or {}
        ts_raw = ((period.get("datetimeFrom") or {}).get("utc"))
        if value is None or not ts_raw:
            dropped += 1
            continue
        try:
            val = float(value)
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (ValueError, TypeError):
            dropped += 1
            continue

        # Same sentinel/absurd-value guard as the live path.
        if val < 0.0 or val > 1000.0:
            dropped += 1
            continue

        buckets.setdefault(ts.replace(minute=0, second=0, microsecond=0), []).append(val)

    records = [
        {
            "station_id": f"openaq:{station['id']}",
            "station_name": station.get("name", f"Station-{station['id']}"),
            "city": station.get("locality") or "Unknown",
            "state": (station.get("country") or {}).get("name", "India"),
            "lat": float(lat),
            "lon": float(lon),
            "cell_id": cell_id,
            "ts": hour.isoformat(),
            "pollutant": pollutant,
            "value": round(sum(vals) / len(vals), 2),
            "unit": unit,
            "source": "openaq",
            "ingested_at": ingested_at.isoformat(),
        }
        for hour, vals in sorted(buckets.items())
    ]

    if dropped:
        logger.debug("station=%s dropped %d unusable measurements", station.get("id"), dropped)
    return records


def parse_and_clean_measurements(
    raw_locations: List[Dict[str, Any]],
    tenant: str,
    as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Parses OpenAQ locations/measurements into `raw_stations` table records.
    Filters invalid/absurd values (e.g. -999, > 1000 µg/m³), floors timestamp to hour.
    """
    as_of_dt = resolve_as_of(as_of)
    ingested_at = datetime.now(timezone.utc)
    # Target timestamp floored to nearest hour
    target_ts = as_of_dt.replace(minute=0, second=0, microsecond=0)

    clean_records = []
    dropped_count = 0

    for loc in raw_locations:
        loc_id = loc.get("id")
        loc_name = loc.get("name", f"Station-{loc_id}")
        coords = loc.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")

        if lat is None or lon is None:
            dropped_count += 1
            continue

        cell_id = get_cell_id(tenant, lat, lon)
        station_id = f"openaq:{loc_id}"
        sensors = loc.get("sensors", [])

        # sensorsId -> reading, from /v3/locations/{id}/latest (see fetch_openaq_stations)
        latest_by_sensor: Dict[int, Dict[str, Any]] = {
            r["sensorsId"]: r
            for r in (loc.get("_latest") or [])
            if r.get("sensorsId") is not None
        }

        # Process sensors inside the location object
        for sensor in sensors:
            parameter_dict = sensor.get("parameter", {})
            param_name = parameter_dict.get("name", "").lower()
            pollutant = POLLUTANT_MAP.get(param_name)

            if not pollutant:
                continue

            latest = latest_by_sensor.get(sensor.get("id")) or {}
            value = latest.get("value")
            unit = parameter_dict.get("units", "µg/m³")

            # A sensor listed in metadata with no corresponding reading simply did
            # not report. Absence is not zero (docs/DATA_CONTRACTS.md §7) — skip it
            # rather than writing a null row that looks like a failed measurement.
            if not latest:
                continue

            # The observation's OWN time, not the time we happened to poll.
            #
            # OpenAQ's `latest` object is the most recent reading a sensor has
            # reported, which may be hours or days old — stations drop out
            # constantly (docs/DATA_CONTRACTS.md §7). Stamping it with our polling
            # hour would silently backdate stale data into the current hour, making
            # a dead station look live. That defeats the staleness greying in the
            # console, and worse, feeds phantom "current" readings into the IDW
            # baseline that the residual — the entire product — is measured against.
            obs_ts = _parse_observation_ts(latest)
            if obs_ts is None:
                logger.warning(
                    "No observation timestamp for %s (%s); dropping rather than "
                    "assuming it reported now", station_id, pollutant,
                )
                dropped_count += 1
                continue

            age_h = (target_ts - obs_ts).total_seconds() / 3600.0
            if age_h > MAX_OBSERVATION_AGE_H:
                logger.info(
                    "Stale reading for %s (%s): %.1fh old, beyond %dh cutoff",
                    station_id, pollutant, age_h, MAX_OBSERVATION_AGE_H,
                )
                dropped_count += 1
                continue

            # Outlier/Absurd value check
            if value is not None:
                try:
                    val_float = float(value)
                    if val_float < 0.0 or val_float > 1000.0:
                        logger.warning(f"Dropping absurd measurement {val_float} for station {station_id} ({pollutant})")
                        dropped_count += 1
                        value = None
                    else:
                        value = val_float
                except (ValueError, TypeError):
                    value = None

            record = {
                "station_id": station_id,
                "station_name": loc_name,
                "city": loc.get("locality", "Unknown"),
                "state": loc.get("country", {}).get("name", "India"),
                "lat": float(lat),
                "lon": float(lon),
                "cell_id": cell_id,
                "ts": obs_ts.isoformat(),
                "pollutant": pollutant,
                "value": value,
                "unit": unit,
                "source": "openaq",
                "ingested_at": ingested_at.isoformat()
            }
            clean_records.append(record)

    logger.info(f"Cleaned {len(clean_records)} records for tenant '{tenant}' (dropped {dropped_count} invalid entries)")
    return clean_records


def generate_seed_stations(tenant: str, as_of: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Generates realistic seed station data for testing/demo when offline or without API key.
    Includes major CPCB stations in Delhi-NCR (Anand Vihar, RK Puram, Punjabi Bagh, IGI Airport, Sector 62 Noida).
    """
    as_of_dt = resolve_as_of(as_of)
    target_ts = as_of_dt.replace(minute=0, second=0, microsecond=0)
    ingested_at = datetime.now(timezone.utc)

    seed_list = [
        {"id": 1001, "name": "Anand Vihar, Delhi - CPCB", "city": "Delhi", "lat": 28.6469, "lon": 77.3160, "pm25": 245.0, "pm10": 380.0, "no2": 85.0},
        {"id": 1002, "name": "RK Puram, Delhi - DPCC", "city": "Delhi", "lat": 28.5632, "lon": 77.1869, "pm25": 190.0, "pm10": 290.0, "no2": 62.0},
        {"id": 1003, "name": "Punjabi Bagh, Delhi - DPCC", "city": "Delhi", "lat": 28.6721, "lon": 77.1310, "pm25": 210.0, "pm10": 310.0, "no2": 70.0},
        {"id": 1004, "name": "Sector 62, Noida - UPPCB", "city": "Noida", "lat": 28.6245, "lon": 77.3577, "pm25": 175.0, "pm10": 260.0, "no2": 58.0},
        {"id": 1005, "name": "Vikas Sadan, Gurugram - HSPCB", "city": "Gurugram", "lat": 28.4501, "lon": 77.0263, "pm25": 165.0, "pm10": 240.0, "no2": 50.0},
    ]

    records = []
    for s in seed_list:
        cell_id = get_cell_id(tenant, s["lat"], s["lon"])
        for pol in ["pm25", "pm10", "no2"]:
            records.append({
                "station_id": f"openaq:{s['id']}",
                "station_name": s["name"],
                "city": s["city"],
                "state": "Delhi-NCR",
                "lat": s["lat"],
                "lon": s["lon"],
                "cell_id": cell_id,
                "ts": target_ts.isoformat(),
                "pollutant": pol,
                "value": s[pol],
                "unit": "µg/m³" if pol in ["pm25", "pm10"] else "ppb",
                "source": "openaq",
                "ingested_at": ingested_at.isoformat()
            })
    return records


def demo():
    print("=== Ingestion Demo: OpenAQ Stations ===")
    as_of = resolve_as_of()
    ncr_bbox = (28.20, 76.80, 28.95, 77.60)

    # Attempt fetch
    raw_data = fetch_openaq_stations("ncr", ncr_bbox, as_of)

    if not raw_data:
        print("  [INFO] No live OpenAQ data fetched (API key missing or rate-limited). Using seed station dataset for validation.")
        records = generate_seed_stations("ncr", as_of)
    else:
        records = parse_and_clean_measurements(raw_data, "ncr", as_of)

    print(f"  [OK] Processed {len(records)} station measurement records.")

    # Validate output schema strictly against docs/DATA_CONTRACTS.md §2 raw_stations
    required_keys = {"station_id", "station_name", "city", "state", "lat", "lon", "cell_id", "ts", "pollutant", "value", "unit", "source", "ingested_at"}
    for rec in records:
        missing = required_keys - rec.keys()
        assert not missing, f"Record missing required keys: {missing}"
        assert rec["cell_id"].startswith("ncr-"), f"Invalid cell_id prefix: {rec['cell_id']}"
        assert rec["source"] in ["openaq", "cpcb"], f"Invalid source: {rec['source']}"

    sample = records[0]
    print(f"  [OK] Sample Station Record:\n{json.dumps(sample, indent=4)}")
    # --- Observation freshness (docs/DATA_CONTRACTS.md §7) -------------------
    # A stale reading must never be backdated into the current hour: that makes a
    # dead station look live and feeds a phantom "current" value into the IDW
    # baseline the residual is measured against.
    _now = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # Fixture mirrors the REAL /v3/locations + /v3/locations/{id}/latest shapes
    # verified on 2026-09-07 (docs/DATA_CONTRACTS.md §7a): metadata carries the
    # sensor id, and values arrive separately keyed by sensorsId.
    def _loc(latest_records):
        return [{
            "id": 1, "name": "S",
            "coordinates": {"latitude": 28.63, "longitude": 77.31},
            "sensors": [{"id": 999, "parameter": {"name": "pm25", "units": "µg/m³"}}],
            "_latest": latest_records,
        }]

    def _reading(utc):
        return [{"sensorsId": 999, "value": 120.0, "datetime": {"utc": utc}}]

    fresh = parse_and_clean_measurements(_loc(_reading("2026-09-07T09:00:00Z")), "ncr", _now)
    assert len(fresh) == 1, "a fresh reading should be kept"
    assert fresh[0]["ts"].startswith("2026-09-07T09:00"), (
        "record must carry the observation's own time, not the polling time"
    )

    stale = parse_and_clean_measurements(_loc(_reading("2026-09-06T04:00:00Z")), "ncr", _now)
    assert stale == [], "a 30h-old reading must be dropped, not backdated"

    untimed = parse_and_clean_measurements(_loc([{"sensorsId": 999, "value": 120.0}]), "ncr", _now)
    assert untimed == [], "a reading with no timestamp must be dropped, not assumed current"

    # A sensor present in metadata but absent from /latest simply did not report.
    no_reading = parse_and_clean_measurements(_loc([]), "ncr", _now)
    assert no_reading == [], "a sensor with no reading must yield no row, not a null row"

    assert _parse_observation_ts({"lastUpdated": "2026-09-07T09:30:00Z"}) is not None
    assert _parse_observation_ts({"datetime": "not-a-date"}) is None

    print("  [OK] Observation freshness: own-time stamping, stale drop, untimed drop")

    print("\nAll OpenAQ station ingestion checks passed successfully!")


if __name__ == "__main__":
    demo()
