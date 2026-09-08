#!/usr/bin/env python3
"""
backfill_static.py — Populate `grid_cells` static layers from Earth Engine (W1.5).

The second half of the spatial signal Model A was missing. AOD says how much
aerosol is overhead right now; these say what is on the ground and never changes:

  population        JRC/GHSL/P2023A/GHS_POP    persons per cell
  builtup_frac      ESA/WorldCover/v200        class 50 (built-up)
  cropland_frac     ESA/WorldCover/v200        class 40 (cropland)
  elevation_m       USGS/SRTMGL1_003
  dist_major_road_m left NULL — no free global roads layer in EE; would need OSM

Together with AOD these are what let a model distinguish a dense Noida cell from a
peri-urban Gurugram one. Without them every station looked identical at a given
hour (TODO.md finding, 2026-09-07).

    python backfill_static.py
"""

import argparse
import os
import pathlib
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

_ENV = pathlib.Path(__file__).parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from ingestion import common  # noqa: E402

WORLDCOVER_BUILTUP = 50
WORLDCOVER_CROPLAND = 40
CELL_DEG = 0.01  # docs/DATA_CONTRACTS.md §1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="ncr")
    args = ap.parse_args()

    import ee
    from google.cloud import bigquery

    project = os.environ["GCP_PROJECT_ID"]
    dataset = f"vayusetu_{args.tenant}"
    ee.Initialize(project=project)
    client = bigquery.Client(project=project)

    cells = [
        (r.cell_id, r.lat, r.lon)
        for r in client.query(f"""
            SELECT cell_id, AVG(lat) AS lat, AVG(lon) AS lon
            FROM `{project}.{dataset}.raw_stations` GROUP BY cell_id
        """).result()
    ]
    print(f"=== Static layers for {len(cells)} cells ===\n")

    # Reduce over the cell's actual footprint, not a point: population is a count
    # per area, and land-use fractions are meaningless at a single pixel.
    half = CELL_DEG / 2.0
    fc = ee.FeatureCollection([
        ee.Feature(
            ee.Geometry.Rectangle([lon - half, lat - half, lon + half, lat + half]),
            {"cell_id": cid},
        )
        for cid, lat, lon in cells
    ])

    out = {cid: {"cell_id": cid, "tenant": args.tenant, "lat": lat, "lon": lon}
           for cid, lat, lon in cells}

    pop = ee.Image("JRC/GHSL/P2023A/GHS_POP/2020").rename("population")
    for f in pop.reduceRegions(fc, ee.Reducer.sum(), 100).getInfo()["features"]:
        v = f["properties"].get("sum")
        out[f["properties"]["cell_id"]]["population"] = int(v) if v is not None else None
    print("  [OK] GHSL population")

    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    for cls, col in [(WORLDCOVER_BUILTUP, "builtup_frac"), (WORLDCOVER_CROPLAND, "cropland_frac")]:
        frac = wc.eq(cls).rename(col)
        for f in frac.reduceRegions(fc, ee.Reducer.mean(), 10).getInfo()["features"]:
            v = f["properties"].get("mean")
            out[f["properties"]["cell_id"]][col] = round(float(v), 4) if v is not None else None
        print(f"  [OK] WorldCover {col}")

    dem = ee.Image("USGS/SRTMGL1_003").select("elevation")
    for f in dem.reduceRegions(fc, ee.Reducer.mean(), 30).getInfo()["features"]:
        v = f["properties"].get("mean")
        out[f["properties"]["cell_id"]]["elevation_m"] = round(float(v), 1) if v is not None else None
    print("  [OK] SRTM elevation")

    records = []
    for cid, d in out.items():
        d.setdefault("population", None)
        d.setdefault("builtup_frac", None)
        d.setdefault("cropland_frac", None)
        d.setdefault("elevation_m", None)
        d["dist_major_road_m"] = None   # no free global roads layer in EE
        d["district"] = None
        d["geom"] = f"POINT({d['lon']} {d['lat']})"
        d["has_station"] = True
        records.append(d)

    counts = common.write_records("grid_cells", records, ["cell_id"], datetime.now(timezone.utc),
                                  dataset="vayusetu_shared")
    print(f"\n{counts}")

    sample = sorted(records, key=lambda r: -(r["builtup_frac"] or 0))[:5]
    print("\nMost built-up cells:")
    for r in sample:
        print(f"  {r['cell_id']:18s} builtup={r['builtup_frac']:.2f} "
              f"crop={r['cropland_frac']:.2f} pop={r['population']}")


if __name__ == "__main__":
    main()
