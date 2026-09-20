#!/usr/bin/env python3
"""
backfill_stations.py — Historical station backfill (BACKLOG W1.4 training path).

Pulls months of real PM2.5 history for every station in a tenant bbox and lands it
in `raw_stations`. This is what Model A trains on, and what replay mode plays back.

Why this exists: the live path (`run_ingest.py`) sees only ~7 stations reporting
within the freshness window, because OpenAQ's CPCB feed lags. History is a different
story — 116 pm25 sensors have continuous data across the Oct-Nov 2025 stubble
season. So the thin live network is a live-view problem only; training and the demo
both run off this backfill.

    python backfill_stations.py --from 2025-10-25 --to 2025-11-20
    python backfill_stations.py --from 2025-11-01 --to 2025-11-08 --limit 10 --local
"""

import argparse
import os
import pathlib
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

_ENV = pathlib.Path(__file__).parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from ingestion import common, stations  # noqa: E402

NCR_BBOX = (28.20, 76.80, 28.95, 77.60)
POLLUTANTS = {"pm25", "pm10"}


def _bbox(tenant: str):
    """The tenant's own bounds, so a national run is a --tenant flag, not an edit."""
    import yaml
    cfg = yaml.safe_load((pathlib.Path(__file__).parent / "infra" / "tenants.yaml").read_text())
    b = (cfg.get("tenants") or {}).get(tenant, {}).get("bounds")
    return (b["lat_min"], b["lon_min"], b["lat_max"], b["lon_max"]) if b else NCR_BBOX


def _flush(buffer, d_from, dataset) -> int:
    """Write one batch and report how many rows were genuinely new."""
    counts = common.write_records(
        "raw_stations", buffer, ["station_id", "ts", "pollutant"], d_from, dataset=dataset
    )
    print(f"      -> flushed {counts['received']} rows: {counts['inserted']} new, {counts['updated']} updated")
    return counts["inserted"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="ncr")
    ap.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD inclusive")
    ap.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD exclusive")
    ap.add_argument("--limit", type=int, default=None, help="Cap sensors, for a quick trial run")
    ap.add_argument("--local", action="store_true", help="Write to data/raw/ instead of BigQuery")
    ap.add_argument("--sleep", type=float, default=0.2, help="Pause between sensors, to be polite")
    ap.add_argument("--workers", type=int, default=3, help="Parallel sensor fetches; keep the rate under 60/min")
    ap.add_argument("--batch-rows", type=int, default=20000, help="Flush to the sink every N rows")
    ap.add_argument("--providers", default=None,
                    help="Comma-separated OpenAQ providers to keep, e.g. CPCB,caaqm. Default: all")
    ap.add_argument("--pollutants", default=None, help="Comma-separated, default pm25,pm10")
    args = ap.parse_args()

    d_from = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d_to = datetime.strptime(args.date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dataset = None if args.local else f"vayusetu_{args.tenant}"
    api_key = os.environ.get("OPENAQ_API_KEY")

    print(f"=== Backfill {args.tenant} | {args.date_from} -> {args.date_to} ===")
    print(f"    sink: {'local data/raw/' if args.local else 'BigQuery ' + os.environ.get('GCP_PROJECT_ID', '?')}\n")

    # Station metadata, unfiltered by liveness: a station that stopped reporting
    # last week still has valid history for the window we are asking about.
    lat_min, lon_min, lat_max, lon_max = _bbox(args.tenant)
    providers = {p.strip().lower() for p in args.providers.split(",")} if args.providers else None
    wanted = {p.strip() for p in args.pollutants.split(",")} if args.pollutants else POLLUTANTS
    locations, page = [], 1
    while True:                                  # India needs two pages; NCR one
        data = stations._http_get_openaq(
            "locations",
            {"bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}", "limit": 1000, "page": page},
            api_key,
        )
        got = data.get("results", [])
        locations += got
        if len(got) < 1000 or page >= 10:
            break
        page += 1
    if providers:
        locations = [l for l in locations if ((l.get("provider") or {}).get("name") or "").lower() in providers]

    def _utc(loc, key):
        raw = (loc.get(key) or {}).get("utc")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    # Only query stations whose reporting range actually overlaps the window.
    # A quarter of the NCR bbox last reported in 2018; asking them about 2025 is
    # ~30 wasted round-trips and an empty result each.
    targets = []
    seen = set()
    n_out_of_range = 0
    for loc in locations:
        first, last = _utc(loc, "datetimeFirst"), _utc(loc, "datetimeLast")
        overlaps = not (first is None or last is None or first >= d_to or last <= d_from)
        for sensor in loc.get("sensors", []):
            name = sensor.get("parameter", {}).get("name", "").lower()
            pollutant = stations.POLLUTANT_MAP.get(name)
            if pollutant not in wanted:
                continue
            if not overlaps:
                n_out_of_range += 1
                continue
            if (loc["id"], pollutant) in seen:
                continue
            seen.add((loc["id"], pollutant))
            targets.append((loc, sensor, pollutant))

    if args.limit:
        targets = targets[: args.limit]

    print(f"{len(locations)} locations, {len(targets)} target sensors\n")

    total_rows = 0
    total_written = 0
    stations_with_data = 0
    buffer: list = []

    # One sensor is ~3 API round-trips of a few seconds each. Serially, a national run
    # (526 sensors) takes about three hours, almost all of it waiting. A small pool keeps
    # the request rate inside OpenAQ's 60/min while cutting that to well under an hour;
    # the writes stay on this thread, so batching and ordering are unchanged.
    def _one(job):
        i, (loc, sensor, pollutant) = job
        raw = stations.fetch_sensor_measurements(sensor["id"], d_from, d_to, api_key)
        if not raw:
            return i, loc, pollutant, 0, []
        unit = sensor.get("parameter", {}).get("units", "µg/m³")
        recs = stations.measurements_to_hourly(raw, loc, pollutant, args.tenant, unit)
        time.sleep(args.sleep)
        return i, loc, pollutant, len(raw), recs

    pool = ThreadPoolExecutor(max_workers=args.workers)
    for i, loc, pollutant, n_raw, recs in pool.map(_one, enumerate(targets, 1)):
        if not recs:
            continue

        stations_with_data += 1
        total_rows += len(recs)
        buffer.extend(recs)

        print(
            f"  [{i:3d}/{len(targets)}] {loc.get('name','?')[:28]:28s} {pollutant:5s} "
            f"{n_raw:5d} raw -> {len(recs):4d} hourly"
        )

        # Each BigQuery write is a load job plus a MERGE — roughly ten seconds
        # regardless of size. Writing per sensor would spend ~40 minutes on
        # round-trips for a month-long backfill, so flush in batches instead.
        if len(buffer) >= args.batch_rows:
            total_written += _flush(buffer, d_from, dataset)
            buffer.clear()

    if buffer:
        total_written += _flush(buffer, d_from, dataset)

    print(f"\n{stations_with_data} sensors had data | {total_rows} hourly rows | {total_written} newly inserted")


if __name__ == "__main__":
    main()
