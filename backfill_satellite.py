#!/usr/bin/env python3
"""
backfill_satellite.py — MAIAC AOD + Sentinel-5P into `raw_satellite` (BACKLOG W1.8/W1.9).

These are the features Model A is missing. The first real evaluation showed the
model losing to IDW because nothing in its feature set varies between locations at
a given hour (TODO.md finding, 2026-09-07). Per-cell AOD is the fix: it is a direct
satellite observation of column aerosol at each cell, so unlike meteorology it
genuinely differs across the city.

Extraction is per-day, not per-cell: one reduceRegions call evaluates every station
cell at once. 26 days x 2 products is ~52 Earth Engine round-trips instead of
thousands.

    python backfill_satellite.py --from 2025-10-25 --to 2025-11-21

Scale factors matter here. MAIAC Optical_Depth_055 is stored as an integer with a
0.001 scale — raw 1198 means AOD 1.198. Writing the raw integer would put a feature
three orders of magnitude off into the model and look plausible on a chart.
"""

import argparse
import os
import pathlib
import warnings
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore")

_ENV = pathlib.Path(__file__).parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from ingestion import common  # noqa: E402

# MAIAC stores AOD as int16 with this scale. Verified against the band metadata.
MAIAC_SCALE = 0.001
MAIAC_SCALE_M = 1000       # native 1 km resolution
S5P_SCALE_M = 7000         # ~7 km footprint


def cell_points(project: str, dataset: str, date_from: str, date_to: str):
    """Distinct station cells with their centroids, from the observations we have."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    q = f"""
        SELECT cell_id, AVG(lat) AS lat, AVG(lon) AS lon
        FROM `{project}.{dataset}.raw_stations`
        WHERE ts >= TIMESTAMP('{date_from}') AND ts < TIMESTAMP('{date_to}')
        GROUP BY cell_id
    """
    return [(r.cell_id, r.lat, r.lon) for r in client.query(q).result()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="ncr")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--batch-rows", type=int, default=5000)
    args = ap.parse_args()

    import ee

    project = os.environ["GCP_PROJECT_ID"]
    dataset = f"vayusetu_{args.tenant}"
    ee.Initialize(project=project)

    cells = cell_points(project, dataset, args.date_from, args.date_to)
    print(f"=== Satellite backfill | {args.date_from} -> {args.date_to} ===")
    print(f"{len(cells)} station cells\n")

    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([lon, lat]), {"cell_id": cid})
        for cid, lat, lon in cells
    ])

    d_from = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d_to = datetime.strptime(args.date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    buffer, total, written = [], 0, 0
    day = d_from
    while day < d_to:
        nxt = day + timedelta(days=1)
        ds, ns = day.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")

        values = {cid: {} for cid, _, _ in cells}

        # --- MAIAC AOD (1 km) ------------------------------------------------
        try:
            maiac = (ee.ImageCollection("MODIS/061/MCD19A2_GRANULES")
                     .filterDate(ds, ns)
                     .select("Optical_Depth_055"))
            if maiac.size().getInfo() > 0:
                img = maiac.mean().multiply(MAIAC_SCALE).rename("aod_maiac")
                for f in img.reduceRegions(fc, ee.Reducer.mean(), MAIAC_SCALE_M).getInfo()["features"]:
                    v = f["properties"].get("mean")
                    if v is not None:
                        values[f["properties"]["cell_id"]]["aod_maiac"] = round(float(v), 4)
        except Exception as e:
            print(f"  {ds} MAIAC failed: {e}")

        # --- Sentinel-5P NO2 and aerosol index (~7 km) -----------------------
        for coll, band, out in [
            ("COPERNICUS/S5P/OFFL/L3_NO2", "tropospheric_NO2_column_number_density", "s5p_no2"),
            ("COPERNICUS/S5P/OFFL/L3_AER_AI", "absorbing_aerosol_index", "s5p_aer_ai"),
        ]:
            try:
                c = ee.ImageCollection(coll).filterDate(ds, ns).select(band)
                if c.size().getInfo() == 0:
                    continue
                img = c.mean().rename(out)
                for f in img.reduceRegions(fc, ee.Reducer.mean(), S5P_SCALE_M).getInfo()["features"]:
                    v = f["properties"].get("mean")
                    if v is not None:
                        values[f["properties"]["cell_id"]][out] = float(v)
            except Exception as e:
                print(f"  {ds} {out} failed: {e}")

        ingested = datetime.now(timezone.utc).isoformat()
        recs = [
            {
                "cell_id": cid,
                "date": ds,
                "aod_maiac": vals.get("aod_maiac"),
                "s5p_no2": vals.get("s5p_no2"),
                "s5p_aer_ai": vals.get("s5p_aer_ai"),
                "cloud_fraction": None,
                "ingested_at": ingested,
            }
            for cid, vals in values.items() if vals
        ]
        buffer.extend(recs)
        total += len(recs)
        n_aod = sum(1 for r in recs if r["aod_maiac"] is not None)
        print(f"  {ds}  {len(recs):3d} cells  ({n_aod} with AOD)")

        if len(buffer) >= args.batch_rows:
            written += common.write_records("raw_satellite", buffer, ["cell_id", "date"], d_from, dataset=dataset)["inserted"]
            buffer.clear()
        day = nxt

    if buffer:
        written += common.write_records("raw_satellite", buffer, ["cell_id", "date"], d_from, dataset=dataset)["inserted"]

    print(f"\n{total} cell-days | {written} newly inserted")


if __name__ == "__main__":
    main()
