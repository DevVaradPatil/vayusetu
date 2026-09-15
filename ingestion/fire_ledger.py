"""
ingestion/fire_ledger.py — how much burning does each satellite fire alert stand for?

India counts farm fires with polar-orbiting satellites (MODIS, VIIRS) that pass over
Punjab and Haryana between about 10:30 and 13:30. Farmers have moved burning later: an
iFOREST analysis of geostationary SEVIRI data found 90% of large Punjab fires happened
after 3 PM in 2024-25, against 3% in 2021; ISRO's Space Applications Centre reported the
same shift. Official fire counts fell ~90% while burned area did not.

This job measures that per district, per season, from two independent products:

- **Active fire detections** — VIIRS S-NPP, science-processed archive (FIRMS
  `VIIRS_SNPP_SP`), 1 Oct - 30 Nov, split day and night. This is the kind of count
  enforcement and progress claims are built on.
- **Burned area** — MODIS MCD64A1 burn scars (500 m, Earth Engine), same months. A scar
  is there whatever time of day the field burned.

Measured result (Punjab): daytime detections fell 74,975 → 3,936 from 2020 to 2025 (−95%)
while burned area fell 17,565 → 8,965 km² (−49%). Burned km² per detection rose
**0.23 → 2.28, a 10× change**; Haryana 0.33 → 1.39. Night detections stay flat (82-136 a
season), so the 01:30 night pass does not catch evening fires either.

What it is good for: ranking districts. Amritsar has the most detections in 2025 but ranks
10th by burned area; Sangrur, Mansa and Faridkot burn 16-22× more land per alert than in
2020-21. A queue ordered by fire counts sends inspectors to the wrong districts.

Limits, stated because the numbers are relative indicators, not hectares:
- MCD64A1 is 500 m, so fragmented fields are misestimated both ways, and its statewide
  totals sit below iFOREST's Sentinel-2 figures (Punjab 2025: 8,965 vs ~20,000 km²).
- MCD64A1 uses MODIS active fires to seed its classification, so fires that dodge the
  overpass can be under-mapped here too — the true undercount is, if anything, larger.
- Districts are FAO GAUL 2015 boundaries: Sangrur there includes today's Barnala.
- Thick smog can blind optical burn-scar mapping, so late-season scars may be missed.

Writes `vayusetu_shared.fire_ledger`: one row per (state, district, season).

Run: `python -m ingestion.fire_ledger` (about 10 minutes: ~70 FIRMS requests, 6 Earth
Engine reductions). Needs FIRMS_MAP_KEY, Earth Engine access and shapely.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

logger = logging.getLogger("vayusetu.ingestion.fire_ledger")

STATES = ["Punjab", "Haryana"]
SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
SEASON_START, SEASON_END = (10, 1), (12, 1)       # 1 Oct inclusive, 1 Dec exclusive
BBOX = (73.8, 27.6, 77.7, 32.6)                   # W, S, E, N — Punjab and Haryana
FIRMS_SOURCE = "VIIRS_SNPP_SP"
FIRMS_MAX_DAYS = 5                                # the area API rejects day_range > 5


def _districts() -> list:
    import ee
    return (ee.FeatureCollection("FAO/GAUL/2015/level2")
            .filter(ee.Filter.eq("ADM0_NAME", "India"))
            .filter(ee.Filter.inList("ADM1_NAME", STATES))
            .map(lambda f: f.simplify(300)))


def burned_area(season: int, districts) -> Dict[str, float]:
    """Burned km² per district from MCD64A1, 1 Oct - 30 Nov."""
    import ee
    img = (ee.ImageCollection("MODIS/061/MCD64A1")
           .filterDate(f"{season}-{SEASON_START[0]:02d}-{SEASON_START[1]:02d}",
                       f"{season}-{SEASON_END[0]:02d}-{SEASON_END[1]:02d}")
           .select("BurnDate").max().gt(0))
    res = (ee.Image.pixelArea().divide(1e6).updateMask(img)
           .reduceRegions(collection=districts, reducer=ee.Reducer.sum(), scale=500).getInfo())
    return {f["properties"]["ADM2_NAME"]: float(f["properties"].get("sum") or 0.0) for f in res["features"]}


def detections(season: int, key: str) -> List[dict]:
    """Every VIIRS S-NPP detection in the box for the season, from the FIRMS archive."""
    rows: List[dict] = []
    d, end = date(season, *SEASON_START), date(season, *SEASON_END)
    while d < end:
        n = min(FIRMS_MAX_DAYS, (end - d).days)
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{FIRMS_SOURCE}/"
               f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}/{n}/{d.isoformat()}")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    text = r.read().decode()
                break
            except Exception as e:                               # transient timeouts happen
                logger.warning("FIRMS retry %d for %s: %s", attempt + 1, d, e)
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(f"FIRMS failed for {d}")
        if not text.startswith("latitude"):
            raise RuntimeError(f"FIRMS returned an error for {d}: {text[:120]}")
        rows += list(csv.DictReader(io.StringIO(text)))
        d += timedelta(days=n)
        time.sleep(1)
    return rows


def assign(rows: List[dict], geojson: dict) -> Dict[str, Dict[str, int]]:
    """Count day and night detections per district by point-in-polygon."""
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    polys = [(shape(f["geometry"]), f["properties"]["ADM2_NAME"]) for f in geojson["features"]]
    tree = STRtree([p for p, _ in polys])
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"day": 0, "night": 0})
    for r in rows:
        pt = Point(float(r["longitude"]), float(r["latitude"]))
        for i in tree.query(pt):
            if polys[i][0].contains(pt):
                out[polys[i][1]]["day" if r.get("daynight") == "D" else "night"] += 1
                break
    return out


def build(seasons=SEASONS) -> List[dict]:
    import ee

    ee.Initialize(project=os.environ["GCP_PROJECT_ID"])
    key = os.environ["FIRMS_MAP_KEY"]
    districts = _districts()
    geojson = districts.getInfo()
    state_of = {f["properties"]["ADM2_NAME"]: f["properties"]["ADM1_NAME"] for f in geojson["features"]}

    records = []
    now = datetime.now(timezone.utc).isoformat()
    for season in seasons:
        burned = burned_area(season, districts)
        rows = detections(season, key)
        counts = assign(rows, geojson)
        logger.info("season %d: %d detections, %.0f km² burned", season, len(rows), sum(burned.values()))
        for district, state in state_of.items():
            c = counts.get(district, {"day": 0, "night": 0})
            records.append({
                "state": state, "district": district, "season": season,
                "burned_km2": round(burned.get(district, 0.0), 2),
                "day_detections": c["day"], "night_detections": c["night"],
                "burned_source": "MODIS/061/MCD64A1 BurnDate > 0, 500 m, 1 Oct - 30 Nov",
                "detection_source": f"FIRMS {FIRMS_SOURCE}, 1 Oct - 30 Nov",
                "boundaries": "FAO GAUL 2015 level 2",
                "computed_at": now,
            })
    return records


def write(records: List[dict], project: str) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table = f"{project}.vayusetu_shared.fire_ledger"
    schema = [
        bigquery.SchemaField("state", "STRING", "REQUIRED"),
        bigquery.SchemaField("district", "STRING", "REQUIRED"),
        bigquery.SchemaField("season", "INT64", "REQUIRED"),
        bigquery.SchemaField("burned_km2", "FLOAT64"),
        bigquery.SchemaField("day_detections", "INT64"),
        bigquery.SchemaField("night_detections", "INT64"),
        bigquery.SchemaField("burned_source", "STRING"),
        bigquery.SchemaField("detection_source", "STRING"),
        bigquery.SchemaField("boundaries", "STRING"),
        bigquery.SchemaField("computed_at", "TIMESTAMP"),
    ]
    # The whole ledger is recomputed from archives each run, so replace rather than merge.
    job = client.load_table_from_json(records, table, job_config=bigquery.LoadJobConfig(
        schema=schema, write_disposition="WRITE_TRUNCATE"))
    job.result()
    logger.info("wrote %d rows to %s", len(records), table)


def demo() -> None:
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    # Point-in-polygon on a toy square, so the counting logic is checked without the network.
    square = {"features": [{"geometry": {"type": "Polygon", "coordinates": [[[75, 30], [76, 30], [76, 31], [75, 31], [75, 30]]]},
                            "properties": {"ADM2_NAME": "Square"}}]}
    toy = assign([{"longitude": "75.5", "latitude": "30.5", "daynight": "D"},
                  {"longitude": "75.5", "latitude": "30.5", "daynight": "N"},
                  {"longitude": "77.0", "latitude": "30.5", "daynight": "D"}], square)
    assert dict(toy) == {"Square": {"day": 1, "night": 1}}, toy

    records = build()
    by = defaultdict(lambda: {"burned": 0.0, "day": 0})
    for r in records:
        by[(r["state"], r["season"])]["burned"] += r["burned_km2"]
        by[(r["state"], r["season"])]["day"] += r["day_detections"]
    for s in STATES:
        for y in SEASONS:
            v = by[(s, y)]
            print(f"  {s:8s} {y}  burned {v['burned']:8.0f} km²  day detections {v['day']:6d}  "
                  f"km²/detection {v['burned'] / v['day'] if v['day'] else float('nan'):5.2f}")
    p = by[("Punjab", 2025)]
    b = [by[("Punjab", y)] for y in (2020, 2021)]
    ratio_now = p["burned"] / p["day"]
    ratio_base = sum(x["burned"] for x in b) / sum(x["day"] for x in b)
    assert ratio_now > 5 * ratio_base, (ratio_now, ratio_base)
    write(records, os.environ["GCP_PROJECT_ID"])
    print(f"[OK] Punjab burned km² per detection {ratio_base:.2f} (2020-21) -> {ratio_now:.2f} (2025); "
          f"{len(records)} ledger rows written")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
