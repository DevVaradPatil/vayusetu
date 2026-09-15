"""
api/evidence.py — Assemble real source-attribution evidence from BigQuery.

This is the product's core. Estimation and forecasting both lost to simple
baselines on real data (TODO.md 2026-09-08b/c), but attribution held: upwind fire
count correlates +0.55 with city PM2.5 and boundary-layer height -0.42. Those are
the drivers this module measures, per episode, from real observations.

Nothing here predicts anything. It measures what happened and assembles the numbers
that explain it, so Gemini can turn them into a brief an official can act on
(AGENTS.md R5: Gemini reasons over supplied evidence, never invents a measurement).
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vayusetu.api.evidence")

UPWIND_SECTOR_DEG = 30.0
UPWIND_RADIUS_KM = 100.0
FIRE_WINDOW_H = 48

# CPCB National AQI bands for PM2.5 (docs/DATA_CONTRACTS.md §6).
AQI_BANDS = [
    (30, "Good"), (60, "Satisfactory"), (90, "Moderate"),
    (120, "Poor"), (250, "Very Poor"), (float("inf"), "Severe"),
]


def aqi_band(pm25: float) -> str:
    for threshold, name in AQI_BANDS:
        if pm25 <= threshold:
            return name
    return "Severe"


@dataclass
class Evidence:
    """Everything measured about one episode. Passed verbatim to Gemini."""
    tenant: str
    ts: str
    city_pm25: float
    aqi_band: str
    n_stations_reporting: int
    worst_station: Dict[str, Any]
    wind: Dict[str, Any]
    boundary_layer_m: Optional[float]
    upwind_fires: Dict[str, Any]
    comparison: Dict[str, Any]
    population_exposed: Optional[int]
    missing_fields: List[str] = field(default_factory=list)
    # Monitors reporting this hour whose readings failed api/integrity.py. Not in the
    # city average and never the worst station.
    monitors_excluded_as_faulty: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _angular_gap(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, wrapped through 360."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def assemble(
    ts: datetime,
    tenant: str = "ncr",
    project: Optional[str] = None,
) -> Evidence:
    """
    Build the evidence payload for one hour from real BigQuery observations.

    Every number returned is measured. Anything unavailable is named in
    `missing_fields` rather than defaulted, so the brief can disclose it.
    """
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    dataset = f"vayusetu_{tenant}"
    client = bigquery.Client(project=project)
    missing: List[str] = []

    ts_str = ts.strftime("%Y-%m-%d %H:00:00")

    # --- Stations at this hour ------------------------------------------------
    stations = list(client.query(f"""
        SELECT station_id, station_name, lat, lon, AVG(value) AS pm25
        FROM `{project}.{dataset}.raw_stations`
        WHERE pollutant = 'pm25' AND value IS NOT NULL
          AND ts = TIMESTAMP('{ts_str}')
        GROUP BY station_id, station_name, lat, lon
        ORDER BY pm25 DESC
    """).result())

    if not stations:
        raise ValueError(f"No station observations at {ts_str} for tenant {tenant}")

    # Only readings that pass the integrity gate count. Without this the hero episode's
    # "worst monitor" — the anchor for the whole upwind-fire analysis and the brief
    # Gemini writes from it — was Arya Nagar at 768.9, inside a run of 642, 161, 587,
    # 769, 0, 741. The worst trusted monitor that hour was Rohini at 710. Faulty zeros
    # also dragged the city average down. Excluded monitors are named, not dropped
    # silently, so the brief can say the network was degraded.
    from api import integrity
    trusted = [s for s in stations if integrity.is_trusted(s.station_id, ts, tenant, project)]
    excluded = [s.station_name for s in stations if s not in trusted]
    if not trusted:
        raise ValueError(f"No trusted station observations at {ts_str} for tenant {tenant}")
    stations = trusted

    city_pm25 = sum(float(s.pm25) for s in stations) / len(stations)
    worst = stations[0]

    # --- Meteorology at the worst-affected station's cell ---------------------
    # Meteorology for the worst-affected station's own cell, not an arbitrary one:
    # wind direction drives the upwind sector, so it must be local to that station.
    met = list(client.query(f"""
        SELECT m.wind_dir, m.wind_speed, m.blh
        FROM `{project}.{dataset}.raw_meteorology` m
        JOIN (
          SELECT cell_id FROM `{project}.{dataset}.raw_stations`
          WHERE station_id = '{worst.station_id}' LIMIT 1
        ) s USING (cell_id)
        WHERE m.is_forecast = FALSE AND m.ts = TIMESTAMP('{ts_str}')
        LIMIT 1
    """).result())

    if met and met[0].wind_dir is not None:
        wind_dir = float(met[0].wind_dir)
        wind_speed = float(met[0].wind_speed or 0.0)
        blh = float(met[0].blh) if met[0].blh is not None else None
    else:
        wind_dir, wind_speed, blh = None, None, None
        missing.append("meteorology (no reanalysis row for this hour)")

    if blh is None and "meteorology" not in " ".join(missing):
        missing.append("boundary_layer_m")

    # --- Fires in the preceding window, sectored by wind ---------------------
    fires = list(client.query(f"""
        SELECT lat, lon, frp, acq_ts, confidence
        FROM `{project}.vayusetu_shared.raw_fires`
        WHERE acq_ts > TIMESTAMP_SUB(TIMESTAMP('{ts_str}'), INTERVAL {FIRE_WINDOW_H} HOUR)
          AND acq_ts <= TIMESTAMP('{ts_str}')
    """).result())

    wlat, wlon = float(worst.lat), float(worst.lon)
    upwind, nearby = [], []
    for f in fires:
        d = _haversine_km(wlat, wlon, float(f.lat), float(f.lon))
        if d > UPWIND_RADIUS_KM:
            continue
        nearby.append(d)
        if wind_dir is None:
            continue
        # wind_dir is the direction the wind comes FROM, so a fire is upwind when
        # the bearing to it sits within the sector centred on wind_dir.
        if _angular_gap(_bearing_deg(wlat, wlon, float(f.lat), float(f.lon)), wind_dir) <= UPWIND_SECTOR_DEG:
            upwind.append({"dist_km": round(d, 1), "frp": float(f.frp or 0.0)})

    transport_h = None
    if upwind and wind_speed and wind_speed > 0.1:
        mean_km = sum(u["dist_km"] for u in upwind) / len(upwind)
        transport_h = round(mean_km / (wind_speed * 3.6), 1)   # m/s -> km/h

    # --- Context: how does this hour compare to the window's normal? ---------
    ctx = list(client.query(f"""
        SELECT AVG(value) AS mean_pm25
        FROM `{project}.{dataset}.raw_stations`
        WHERE pollutant = 'pm25' AND value IS NOT NULL
          AND ts BETWEEN TIMESTAMP_SUB(TIMESTAMP('{ts_str}'), INTERVAL 14 DAY)
                     AND TIMESTAMP('{ts_str}')
    """).result())
    baseline = float(ctx[0].mean_pm25) if ctx and ctx[0].mean_pm25 else None
    if baseline is None:
        missing.append("14-day baseline")

    # --- Population exposed in the worst cell --------------------------------
    pop = list(client.query(f"""
        SELECT population FROM `{project}.vayusetu_shared.grid_cells`
        WHERE cell_id = (
          SELECT cell_id FROM `{project}.{dataset}.raw_stations`
          WHERE station_id = '{worst.station_id}' LIMIT 1)
    """).result())
    population = int(pop[0].population) if pop and pop[0].population else None
    if population is None:
        missing.append("population_exposed")

    return Evidence(
        tenant=tenant,
        ts=ts.isoformat(),
        city_pm25=round(city_pm25, 1),
        aqi_band=aqi_band(city_pm25),
        n_stations_reporting=len(stations),
        monitors_excluded_as_faulty=excluded,
        worst_station={
            "name": worst.station_name,
            "pm25": round(float(worst.pm25), 1),
            "aqi_band": aqi_band(float(worst.pm25)),
            "lat": wlat,
            "lon": wlon,
        },
        wind={
            "from_bearing_deg": wind_dir,
            "speed_ms": wind_speed,
            "note": "bearing is the direction the wind comes FROM",
        },
        boundary_layer_m=blh,
        upwind_fires={
            "sector_deg": UPWIND_SECTOR_DEG,
            "radius_km": UPWIND_RADIUS_KM,
            "window_h": FIRE_WINDOW_H,
            "count": len(upwind),
            "total_frp_mw": round(sum(u["frp"] for u in upwind), 1),
            "nearest_km": round(min((u["dist_km"] for u in upwind), default=0.0), 1) if upwind else None,
            "farthest_km": round(max((u["dist_km"] for u in upwind), default=0.0), 1) if upwind else None,
            "transport_time_h": transport_h,
            "total_fires_within_radius": len(nearby),
        },
        comparison={
            "baseline_14d_mean_pm25": round(baseline, 1) if baseline else None,
            "ratio_to_baseline": round(city_pm25 / baseline, 2) if baseline else None,
        },
        population_exposed=population,
        missing_fields=missing,
    )


def to_event(evidence: Dict[str, Any], brief: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Render one episode in the open interchange format (spec/hotspot-event.schema.json).

    This is the federation boundary: a consuming city gets the observation, the
    measured drivers, and the reasoning that connects them — enough to re-derive the
    conclusion without trusting our model, or knowing we have one.

    Deliberately omits `residual_pm25` and friends. They are optional in schema 2.0.0
    and we have no estimator that beats IDW, so publishing a residual here would be
    publishing model error as a finding (TODO.md 2026-09-08b).
    """
    w = evidence["worst_station"]
    fires = evidence.get("upwind_fires") or {}
    wind = evidence.get("wind") or {}
    brief = brief or {}

    lat, lon = float(w["lat"]), float(w["lon"])
    ts = evidence["ts"]

    # Drop unmeasured drivers rather than emitting nulls: the schema types them as
    # numbers, and a consumer must be able to tell "no fires" from "we didn't look".
    drivers = {
        "upwind_fire_count": fires.get("count", 0),
        "upwind_sector_deg": fires.get("sector_deg"),
        "upwind_radius_km": fires.get("radius_km"),
        "fire_window_hours": fires.get("window_h"),
        "total_frp_mw": fires.get("total_frp_mw"),
        "boundary_layer_m": evidence.get("boundary_layer_m"),
        "wind_from_bearing_deg": wind.get("from_bearing_deg"),
        "wind_speed_ms": wind.get("speed_ms"),
        "ratio_to_baseline": (evidence.get("comparison") or {}).get("ratio_to_baseline"),
    }
    drivers = {k: v for k, v in drivers.items() if v is not None}

    return {
        "event_id": f"{evidence['tenant']}-{ts}-{w['name']}".replace(" ", "_"),
        "tenant": evidence["tenant"],
        "cell_id": f"{evidence['tenant']}-{math.floor(lat / 0.01):d}-{math.floor(lon / 0.01):d}",
        "timestamp": ts,
        "latitude": lat,
        "longitude": lon,
        "observed_pm25": w["pm25"],
        "aqi_band": w["aqi_band"],
        "n_stations_reporting": evidence["n_stations_reporting"],
        **({"population_exposed": evidence["population_exposed"]}
           if evidence.get("population_exposed") is not None else {}),
        "attribution": {
            "cause": brief.get("cause", ""),
            "cause_category": brief.get("cause_category", "unknown"),
            "confidence": brief.get("confidence", 0.0),
            "narrative": brief.get("narrative", ""),
            "evidence_cited": brief.get("evidence_cited") or ["upwind_fires.count"],
            "caveats": (brief.get("caveats") or []) + evidence.get("missing_fields", []),
            "drivers": drivers,
        },
        **({"recommended_actions": brief["recommended_actions"]}
           if brief.get("recommended_actions") else {}),
        **({"public_advisory": brief["public_advisory"]}
           if brief.get("public_advisory") else {}),
        "schema_version": "2.0.0",
    }


def demo() -> None:
    """Assemble evidence for the frozen hero episode."""
    # The frozen hero episode: 2025-11-11 20:00Z = 01:30 IST, the peak of the real
    # November 2025 Delhi smog event. 63 trusted stations, city mean 407.3 ug/m3.
    ev = assemble(datetime(2025, 11, 11, 20, 0, tzinfo=timezone.utc))

    assert ev.city_pm25 > 0
    assert ev.n_stations_reporting > 0
    assert ev.worst_station["pm25"] >= ev.city_pm25 * 0.5

    print(f"[OK] {ev.ts[:16]}  city PM2.5 {ev.city_pm25} ({ev.aqi_band}), "
          f"{ev.n_stations_reporting} stations")
    print(f"[OK] worst: {ev.worst_station['name'][:34]} at {ev.worst_station['pm25']}")
    print(f"[OK] wind from {ev.wind['from_bearing_deg']}deg, BLH {ev.boundary_layer_m} m")
    print(f"[OK] upwind fires: {ev.upwind_fires['count']} of "
          f"{ev.upwind_fires['total_fires_within_radius']} within {UPWIND_RADIUS_KM:.0f} km")
    if ev.missing_fields:
        print(f"[OK] disclosed missing: {ev.missing_fields}")

    # The federation claim is only real if what we emit validates against the schema
    # we publish. Checked without Gemini so it runs on every change, not just when
    # quota allows.
    import json
    import pathlib
    import jsonschema

    schema = json.loads(
        (pathlib.Path(__file__).parent.parent / "spec" / "hotspot-event.schema.json")
        .read_text(encoding="utf-8")
    )
    event = to_event(ev.to_dict())
    jsonschema.validate(event, schema)
    assert "residual_pm25" not in event, "we have no estimator that beats IDW"
    print(f"[OK] event validates against spec/hotspot-event.schema.json "
          f"({len(event['attribution']['drivers'])} drivers)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    import pathlib
    for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    demo()
