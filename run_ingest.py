#!/usr/bin/env python3
"""
run_ingest.py — Run one full ingestion cycle against the live APIs into BigQuery.

This is what Cloud Scheduler will invoke hourly (BACKLOG W1.10). Until the
schedulers are registered it is also the way to run the pipeline by hand:

    python run_ingest.py                     # live, now
    REPLAY_AS_OF=2024-11-05T09:00:00Z python run_ingest.py

Every write is an idempotent MERGE on the documented primary key, so re-running
this never duplicates rows.
"""

import argparse
import os
import pathlib
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

# Load .env before importing anything that reads os.environ at import time.
_ENV = pathlib.Path(__file__).parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from ingestion import common, fires, meteorology, stations  # noqa: E402

NCR_BBOX = (28.20, 76.80, 28.95, 77.60)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="ncr")
    ap.add_argument("--dataset", default=None, help="Override target dataset")
    ap.add_argument("--local", action="store_true", help="Write to data/raw/ instead of BigQuery")
    args = ap.parse_args()

    tenant = args.tenant
    dataset = None if args.local else (args.dataset or f"vayusetu_{tenant}")
    shared = None if args.local else "vayusetu_shared"
    as_of = common.resolve_as_of()

    print(f"=== VayuSetu ingestion | tenant={tenant} as_of={as_of.isoformat()} ===")
    print(f"    sink: {'local data/raw/' if args.local else 'BigQuery ' + os.environ.get('GCP_PROJECT_ID', '?')}\n")

    # --- stations -----------------------------------------------------------
    locs = stations.fetch_openaq_stations(tenant, NCR_BBOX, as_of)
    recs = stations.parse_and_clean_measurements(locs, tenant, as_of)
    if recs:
        c = common.write_records("raw_stations", recs, ["station_id", "ts", "pollutant"], as_of, dataset=dataset)
        print(f"stations      {c['received']:5d} received  {c['inserted']:5d} new  {c['updated']:5d} updated")
    else:
        print("stations          0 received  (no station reported within the freshness window)")

    # --- fires (200 km buffer, shared dataset) ------------------------------
    raw_f = fires.fetch_firms_fires(NCR_BBOX, as_of=as_of, day_range=3)
    frecs = fires.parse_and_clean_fires(raw_f, as_of=as_of)
    if frecs:
        c = common.write_records("raw_fires", frecs, ["fire_id"], as_of, dataset=shared)
        print(f"fires         {c['received']:5d} received  {c['inserted']:5d} new  {c['updated']:5d} updated")
    else:
        print("fires             0 received  (no detections — expected outside Oct-Nov)")

    # --- meteorology, for cells that have a station -------------------------
    # Only station cells for now: a full 6,000-cell sweep needs the grid built
    # (W1.5) and would be 6,000 Open-Meteo calls.
    seen, mrecs = set(), []
    for r in recs:
        if r["cell_id"] in seen:
            continue
        seen.add(r["cell_id"])
        resp = meteorology.fetch_open_meteo_forecast(r["lat"], r["lon"], as_of)
        mrecs += meteorology.parse_meteorology_records(resp, tenant, r["cell_id"], as_of, is_forecast=True)
    if mrecs:
        c = common.write_records(
            "raw_meteorology", mrecs, ["cell_id", "ts", "is_forecast", "issued_at"], as_of, dataset=dataset
        )
        print(f"meteorology   {c['received']:5d} received  {c['inserted']:5d} new  {c['updated']:5d} updated")

    print("\nDone.")


if __name__ == "__main__":
    main()
