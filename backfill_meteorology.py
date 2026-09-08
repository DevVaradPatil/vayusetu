#!/usr/bin/env python3
"""
backfill_meteorology.py — Historical meteorology for the training window.

Fetches ERA5 reanalysis from Open-Meteo's archive API for every grid cell that has
station observations, and lands it in `raw_meteorology` with `is_forecast=FALSE`.

Run this AFTER backfill_stations.py — it derives its cell list from whatever
stations actually have data, so there is no point fetching weather for cells with
no label to train against.

    python backfill_meteorology.py --from 2025-10-25 --to 2025-11-20

Note on the ERA5 dependency: plan.md called for ERA5 via Earth Engine. The archive
API serves the same reanalysis over plain HTTP with no key, so this path works
while Earth Engine registration is still pending. Earth Engine is still required
for the satellite layer (MAIAC AOD, Sentinel-5P).
"""

import argparse
import os
import pathlib
import time
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

from ingestion import common, meteorology  # noqa: E402


def station_cells(project: str, dataset: str, d_from: datetime, d_to: datetime):
    """Distinct (cell_id, lat, lon) that have station observations in the window."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    q = f"""
        SELECT cell_id, AVG(lat) AS lat, AVG(lon) AS lon, COUNT(*) AS n
        FROM `{project}.{dataset}.raw_stations`
        WHERE ts >= TIMESTAMP('{d_from:%Y-%m-%d}') AND ts < TIMESTAMP('{d_to:%Y-%m-%d}')
        GROUP BY cell_id
        ORDER BY n DESC
    """
    return [(r.cell_id, r.lat, r.lon, r.n) for r in client.query(q).result()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="ncr")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--batch-rows", type=int, default=20000)
    args = ap.parse_args()

    d_from = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d_to = datetime.strptime(args.date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    project = os.environ["GCP_PROJECT_ID"]
    dataset = f"vayusetu_{args.tenant}"

    cells = station_cells(project, dataset, d_from, d_to)
    if args.limit:
        cells = cells[: args.limit]

    print(f"=== Meteorology backfill | {args.date_from} -> {args.date_to} ===")
    print(f"{len(cells)} cells with station data\n")

    buffer, total, written = [], 0, 0
    keys = ["cell_id", "ts", "is_forecast", "issued_at"]

    for i, (cell_id, lat, lon, n_obs) in enumerate(cells, 1):
        try:
            resp = meteorology.fetch_open_meteo_archive(lat, lon, d_from, d_to)
        except Exception as e:
            print(f"  [{i:3d}/{len(cells)}] {cell_id} FAILED: {e}")
            continue

        recs = meteorology.parse_meteorology_records(
            resp, args.tenant, cell_id, d_from, is_forecast=False
        )
        buffer.extend(recs)
        total += len(recs)
        print(f"  [{i:3d}/{len(cells)}] {cell_id}  {len(recs):5d} hours  ({n_obs} station obs)")

        if len(buffer) >= args.batch_rows:
            written += common.write_records("raw_meteorology", buffer, keys, d_from, dataset=dataset)["inserted"]
            buffer.clear()
        time.sleep(args.sleep)

    if buffer:
        written += common.write_records("raw_meteorology", buffer, keys, d_from, dataset=dataset)["inserted"]

    print(f"\n{total} hourly rows | {written} newly inserted")


if __name__ == "__main__":
    main()
