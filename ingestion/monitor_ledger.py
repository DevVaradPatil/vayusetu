"""
ingestion/monitor_ledger.py — can India's air monitors be trusted? State by state.

The integrity gate (`api/integrity.py`) was built after our own headline hotspot turned
out to be a broken sensor. It is not a Delhi problem: in 2025 only 270 of India's 562
real-time monitors gave stable data, 13 of Haryana's 31 went dark as the smog built, and
Panipat read a flat 183-187 for ten days. Every state board runs a network it has little
independent means of auditing, and every dashboard built on those numbers inherits the
faults.

So this job runs the same four checks over **every CPCB monitor OpenAQ carries**, for the
same 25 Oct - 20 Nov 2025 window as the Delhi replay, and writes one row per monitor to
`vayusetu_shared.monitor_ledger`: status, uptime, fault rate, flag counts, and one stretch
of raw readings as evidence.

Two things make the national run different from the tenant one:

- **Peers are per state.** A monitor is judged against the monitors around it, and a median
  of Kerala and Delhi together is not "around". Each state's series are flagged against
  that state's own hourly median, via the pure `integrity.health`.
- **A state is only a peer group if it has enough monitors.** Below
  `integrity.MIN_MONITORS_FOR_MEDIAN` reporting in an hour there is no median, so the two
  rules that need one (dead zeros during dirty air, implausibly low during an episode)
  cannot fire. Those states still get stuck-value and spike checks, and the row records
  how many peers it had, so a clean result in a thin state is not read as proof.

States come from FAO GAUL 2015 level-1 polygons, assigned once per monitor by
point-in-polygon — OpenAQ's own `state` field is the country name.

Run: `python -m ingestion.monitor_ledger` after the national backfill
(`python backfill_stations.py --tenant india --from 2025-10-25 --to 2025-11-21
--providers CPCB,caaqm --pollutants pm25`). Needs Earth Engine and shapely.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from api import integrity

logger = logging.getLogger("vayusetu.ingestion.monitor_ledger")

WINDOW_DAYS = 27                    # the whole replay window, not a rolling week
TENANT = "india"


def states_for(meta: Dict[str, dict]) -> Dict[str, str]:
    """station_id -> state, by point-in-polygon against GAUL level 1."""
    import ee
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    ee.Initialize(project=os.environ["GCP_PROJECT_ID"])
    fc = (ee.FeatureCollection("FAO/GAUL/2015/level1")
          .filter(ee.Filter.eq("ADM0_NAME", "India"))
          .map(lambda f: f.simplify(1000))).getInfo()
    polys = [(shape(f["geometry"]), f["properties"]["ADM1_NAME"]) for f in fc["features"]]
    tree = STRtree([p for p, _ in polys])

    out = {}
    for sid, m in meta.items():
        pt = Point(m["lon"], m["lat"])
        out[sid] = next((polys[i][1] for i in tree.query(pt) if polys[i][0].contains(pt)), "Unknown")
    return out


def build(project: str | None = None) -> List[dict]:
    project = project or os.environ["GCP_PROJECT_ID"]
    series, meta, _, _ = integrity._load(TENANT, project)
    if not series:
        raise LookupError(f"vayusetu_{TENANT}.raw_stations is empty; run the national backfill first")
    state_of = states_for(meta)

    by_state: Dict[str, List[str]] = defaultdict(list)
    for sid in series:
        by_state[state_of[sid]].append(sid)

    now = datetime.now(timezone.utc).isoformat()
    rows: List[dict] = []
    for state, sids in sorted(by_state.items()):
        sub = {sid: series[sid] for sid in sids}
        regional = integrity.regional_stats(sub.values())        # this state's own field
        flags = {sid: integrity.flag_series(s, regional) for sid, s in sub.items()}
        h = integrity.health(sub, {sid: meta[sid] for sid in sids}, regional, flags, days=WINDOW_DAYS)
        if not h["monitors"]:
            continue
        # Hours where this state had enough monitors reporting to have a median at all.
        peer_hours = len(regional)
        for m in h["monitors"]:
            rows.append({
                "station_id": m["station_id"], "name": m["name"], "state": state,
                "lat": m["lat"], "lon": m["lon"], "status": m["status"],
                "uptime": m["uptime"], "fault_rate": m["fault_rate"],
                "hours_expected": m["hours_expected"], "hours_reported": m["hours_reported"],
                "stuck_hours": m["flag_counts"]["stuck"], "dead_zero_hours": m["flag_counts"]["dead_zero"],
                "spike_hours": m["flag_counts"]["spike"], "low_in_episode_hours": m["flag_counts"]["low_in_episode"],
                "dark_during_severe_hours": m["dark_during_severe_hours"],
                "state_monitors": len(sids), "state_peer_hours": peer_hours,
                "example": json.dumps(m["example"]) if m["example"] else None,
                "window_start": h["window"][0], "window_end": h["window"][1],
                "computed_at": now,
            })
        logger.info("%-22s %3d monitors, %3d not trustworthy, peer hours %d",
                    state, len(sids), h["summary"]["faulty"] + h["summary"]["offline"], peer_hours)
    return rows


def write(rows: List[dict], project: str) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    schema = [bigquery.SchemaField(n, t) for n, t in [
        ("station_id", "STRING"), ("name", "STRING"), ("state", "STRING"), ("lat", "FLOAT64"),
        ("lon", "FLOAT64"), ("status", "STRING"), ("uptime", "FLOAT64"), ("fault_rate", "FLOAT64"),
        ("hours_expected", "INT64"), ("hours_reported", "INT64"), ("stuck_hours", "INT64"),
        ("dead_zero_hours", "INT64"), ("spike_hours", "INT64"), ("low_in_episode_hours", "INT64"),
        ("dark_during_severe_hours", "INT64"), ("state_monitors", "INT64"), ("state_peer_hours", "INT64"),
        ("example", "STRING"), ("window_start", "TIMESTAMP"), ("window_end", "TIMESTAMP"),
        ("computed_at", "TIMESTAMP")]]
    job = client.load_table_from_json(rows, f"{project}.vayusetu_shared.monitor_ledger",
                                      job_config=bigquery.LoadJobConfig(
                                          schema=schema, write_disposition="WRITE_TRUNCATE"))
    job.result()
    logger.info("wrote %d rows", len(rows))


def demo() -> None:
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    rows = build()
    by_state = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_state[r["state"]][r["status"]] += 1
        by_state[r["state"]]["n"] += 1
    print(f"\n{len(rows)} monitors in {len(by_state)} states")
    print(f"{'state':22s} {'n':>4s} {'faulty':>7s} {'offline':>8s} {'suspect':>8s} {'healthy':>8s}")
    for s, c in sorted(by_state.items(), key=lambda kv: -(kv[1]["faulty"] + kv[1]["offline"])):
        print(f"{s:22s} {c['n']:4d} {c['faulty']:7d} {c['offline']:8d} {c['suspect']:8d} {c['healthy']:8d}")
    untrusted = sum(1 for r in rows if r["status"] in ("faulty", "offline"))
    print(f"\n{untrusted} of {len(rows)} monitors ({untrusted / len(rows):.0%}) could not be trusted in the window")

    assert len(rows) > 200, len(rows)
    assert any(r["state"] == "Delhi" for r in rows), sorted({r["state"] for r in rows})
    # Monitors whose coordinates fall outside every polygon are labelled, never dropped.
    assert sum(1 for r in rows if r["state"] == "Unknown") < 0.05 * len(rows)
    assert all(r["hours_reported"] <= r["hours_expected"] for r in rows)
    # Every faulty monitor carries the readings that convict it.
    assert all(r["example"] for r in rows if r["status"] == "faulty")
    write(rows, os.environ["GCP_PROJECT_ID"])
    print("[OK] national monitor ledger written")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
