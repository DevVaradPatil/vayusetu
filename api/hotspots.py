"""
api/hotspots.py — Hyper-local pollution events, measured.

The track asks for "hidden pollution hotspots". The original plan defined a hotspot
as model estimate minus station interpolation, and that was falsified (TODO.md
2026-09-08b): a positive residual was mostly model error. Nothing here uses a model.

What is detected instead: a locality reading far above the regional field in the
same hour. On 16 November, Arya Nagar in Bahadurgarh read 918 ug/m3 while the median
across 60-odd monitors was 207 — 4.4 times the number every dashboard displayed for
that region. The reading was public the whole time. It was hidden by the average,
which is the number GRAP decisions are actually taken on.

Robust statistics (median and median absolute deviation) rather than mean and
standard deviation, so one extreme locality cannot inflate the baseline it is being
compared against.

Reporting zero hotspots is a real answer, not a failure. During the peak of the
November episode every monitor was severe at once: median 457, MAD 110, nothing
above 3.5 sigma. A regional blanket and a local plume need different responses, and
conflating them would send an enforcement team to the wrong place.

**Satellite NO2 was tried as a second detector and dropped.** It was the one signal
that could have flagged a place with no monitor. Two measurements killed it:
`cloud_fraction` is NULL in all 1755 satellite rows we ingest, so cloudy retrievals
cannot be screened out; and no NO2 anomaly in the window is spatially isolated — on
19 November, 48 cells cleared z >= 2 while the mean z across every other cell that
day was 2.51, i.e. the whole grid rose together. A detector that cannot separate a
plume from a region-wide day, and cannot rule out a cloud artefact, has no business
telling an officer where to go. The consequence is a stated limitation: this finds
hotspots hidden by the average, not hotspots hidden from the monitoring network.

Thresholds are judgement calls, stated in the constants below, and every hotspot
carries the numbers it was judged on so a reader can disagree.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vayusetu.api.hotspots")

# A locality is flagged when it is both statistically unusual against its own city
# AND high enough to matter for health. 3.5 is the conventional robust-outlier cut.
# The absolute floors stop a clean day producing "hotspots" 20 ug/m3 above a low
# median. Measured over the 26-day window these give 251 station-hours across 48
# localities on all 26 days, so the rule is neither vacuous nor indiscriminate.
STATION_ROBUST_Z = 3.5
STATION_MIN_EXCESS = 50.0      # ug/m3 above the regional median
STATION_MIN_VALUE = 90.0       # at least CPCB "Moderate"; below this nobody needs sending

_MAD_TO_SIGMA = 1.4826         # MAD -> standard-deviation equivalent for a normal

METHOD = (f"A monitor is flagged when its robust z is at least {STATION_ROBUST_Z}, it is "
          f"at least {STATION_MIN_EXCESS} ug/m3 above the regional median, and it reads at "
          f"least {STATION_MIN_VALUE} ug/m3. Median and MAD are taken over every monitor "
          f"reporting in that hour. Measurement only: no model, no interpolation.")

# Shared by both entry points: per-hour median and MAD over the reporting monitors.
_ROBUST_SQL = """
        WITH obs AS (
          SELECT ts, station_id, ANY_VALUE(station_name) AS station_name,
                 ANY_VALUE(lat) AS lat, ANY_VALUE(lon) AS lon,
                 ANY_VALUE(cell_id) AS cell_id, AVG(value) AS pm25
          FROM `{project}.vayusetu_{tenant}.raw_stations`
          WHERE pollutant = 'pm25' AND value IS NOT NULL AND {ts_filter}
          GROUP BY ts, station_id
        ),
        med AS (
          SELECT ts, APPROX_QUANTILES(pm25, 2)[OFFSET(1)] AS m, COUNT(*) AS n
          FROM obs GROUP BY ts
        ),
        spread AS (
          SELECT o.ts, APPROX_QUANTILES(ABS(o.pm25 - m.m), 2)[OFFSET(1)] AS mad
          FROM obs o JOIN med m USING (ts) GROUP BY o.ts
        )
"""


def _row_to_entry(r: Any, median: float, sigma: float) -> Dict[str, Any]:
    pm25 = float(r.pm25)
    excess = float(r.excess)
    # With a degenerate spread (every monitor identical) there is no outlier to find,
    # so z is left None rather than dividing by zero into infinity.
    z = round(excess / sigma, 2) if sigma > 0 else None
    return {
        "station_id": r.station_id,
        "name": r.station_name,
        "lat": float(r.lat),
        "lon": float(r.lon),
        "pm25": pm25,
        "excess_over_median": excess,
        "times_regional": round(pm25 / median, 2) if median else None,
        "robust_z": z,
        "population_in_cell": int(r.population) if r.population else None,
        "is_hotspot": bool(
            z is not None and z >= STATION_ROBUST_Z
            and excess >= STATION_MIN_EXCESS
            and pm25 >= STATION_MIN_VALUE
        ),
    }


def station_hotspots(ts_str: str, tenant: str = "ncr", project: Optional[str] = None) -> Dict[str, Any]:
    """
    Localities standing above the regional field for one hour.

    `ts_str` is 'YYYY-MM-DD HH:00:00' UTC. Returns every reporting monitor ranked by
    excess with the flagged ones marked, so a caller can show the whole field and not
    only the outliers — the field is what makes an outlier legible.
    """
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    sql = _ROBUST_SQL.format(project=project, tenant=tenant,
                             ts_filter="ts = TIMESTAMP(@ts)") + f"""
        SELECT o.station_id, o.station_name, o.lat, o.lon, o.cell_id,
               ROUND(o.pm25, 1) AS pm25, ROUND(m.m, 1) AS regional_median,
               ROUND(o.pm25 - m.m, 1) AS excess, s.mad AS mad,
               g.population AS population
        FROM obs o JOIN med m USING (ts) JOIN spread s USING (ts)
        LEFT JOIN `{project}.vayusetu_shared.grid_cells` g USING (cell_id)
        ORDER BY excess DESC
    """
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ts", "STRING", ts_str)],
    )).result())

    if not rows:
        return {"ts": ts_str, "tenant": tenant, "regional_median": None, "spread_mad": None,
                "n_reporting": 0, "method": METHOD, "hotspots": [], "field": []}

    median = float(rows[0].regional_median)
    mad = float(rows[0].mad or 0.0)
    field: List[Dict[str, Any]] = [_row_to_entry(r, median, mad * _MAD_TO_SIGMA) for r in rows]

    return {
        "ts": ts_str,
        "tenant": tenant,
        "regional_median": median,
        "spread_mad": round(mad, 1),
        "n_reporting": len(field),
        "method": METHOD,
        "hotspots": [f for f in field if f["is_hotspot"]],
        "field": field,
    }


def top_events(tenant: str = "ncr", limit: int = 12,
               project: Optional[str] = None) -> Dict[str, Any]:
    """
    The worst local events in the ingested window, ranked.

    The hour a user happens to be looking at often has no local event — during a
    regional episode, correctly, none exists. This answers the question an officer
    asks first: where have the worst hyper-local events been? Each entry carries its
    hour so the console can jump the timeline to it.
    """
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    sql = _ROBUST_SQL.format(project=project, tenant=tenant, ts_filter="TRUE") + f"""
        , scored AS (
          SELECT o.ts, o.station_id, o.station_name, o.lat, o.lon, o.cell_id,
                 ROUND(o.pm25, 1) AS pm25, ROUND(m.m, 1) AS regional_median,
                 ROUND(o.pm25 - m.m, 1) AS excess, s.mad AS mad, m.n AS n_reporting,
                 SAFE_DIVIDE(o.pm25 - m.m, s.mad * {_MAD_TO_SIGMA}) AS zs
          FROM obs o JOIN med m USING (ts) JOIN spread s USING (ts)
          WHERE m.n >= 10
        )
        SELECT c.*, g.population AS population
        FROM scored c
        LEFT JOIN `{project}.vayusetu_shared.grid_cells` g USING (cell_id)
        WHERE c.zs >= {STATION_ROBUST_Z} AND c.excess >= {STATION_MIN_EXCESS}
          AND c.pm25 >= {STATION_MIN_VALUE}
        ORDER BY c.zs DESC
        LIMIT @limit
    """
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)],
    )).result())

    events = []
    for r in rows:
        e = _row_to_entry(r, float(r.regional_median), float(r.mad) * _MAD_TO_SIGMA)
        e["ts"] = r.ts.strftime("%Y-%m-%d %H:00:00")
        e["regional_median"] = float(r.regional_median)
        e["n_reporting"] = int(r.n_reporting)
        events.append(e)

    return {"tenant": tenant, "method": METHOD, "events": events}


def demo() -> None:
    """
    The detector has to tell a local event from a regional one. Both cases are
    checked, because getting either wrong sends an enforcement team to the wrong
    place — or sends nobody to a town breathing four times the regional figure.
    """
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    def show(label: str, hs: Dict[str, Any]) -> None:
        print(f"\n{label}")
        print(f"  {hs['n_reporting']} monitors, regional median {hs['regional_median']} "
              f"ug/m3, MAD {hs['spread_mad']}, {len(hs['hotspots'])} flagged")
        for f in hs["hotspots"][:6]:
            pop = f"{f['population_in_cell']:,} people" if f["population_in_cell"] else "population unknown"
            print(f"    {f['pm25']:6.1f}  +{f['excess_over_median']:5.1f} over median  "
                  f"z={f['robust_z']:5.1f}  {f['times_regional']}x  {pop}  {f['name'][:38]}")
        for f in hs["hotspots"]:
            assert f["robust_z"] >= STATION_ROBUST_Z
            assert f["excess_over_median"] >= STATION_MIN_EXCESS
            assert f["pm25"] >= STATION_MIN_VALUE
        assert all(a["excess_over_median"] >= b["excess_over_median"]
                   for a, b in zip(hs["field"], hs["field"][1:])), "field must be ranked"

    # A local event: the region sat at a median of 207 while one town ran at 918.
    local = station_hotspots("2025-11-16 06:00:00")
    show("Local event, 16 Nov 11:30 IST", local)
    assert local["hotspots"], "16 Nov 06:00Z is a known local event and must flag"
    worst = local["hotspots"][0]
    assert worst["robust_z"] > 10, worst
    assert worst["times_regional"] > 3, worst

    # A regional episode: everything is severe at once, so nothing is an outlier.
    # Reporting zero here is the correct answer, not a miss.
    regional = station_hotspots("2025-11-11 20:00:00")
    show("Regional episode, 12 Nov 01:30 IST", regional)
    assert regional["n_reporting"] > 50, regional["n_reporting"]
    assert not regional["hotspots"], "a uniformly severe region has no local outlier"
    assert regional["regional_median"] > 250, "this hour should be severe city-wide"

    top = top_events(limit=8)
    print(f"\nWorst local events in the window ({len(top['events'])}):")
    for e in top["events"]:
        print(f"    {e['ts']}  {e['pm25']:6.1f} vs {e['regional_median']:5.1f} median  "
              f"z={e['robust_z']:5.1f}  {e['times_regional']}x  {e['name'][:38]}")
    assert top["events"], "the window contains known local events"
    assert all(a["robust_z"] >= b["robust_z"]
               for a, b in zip(top["events"], top["events"][1:])), "events must be ranked by z"
    assert len({e["ts"] for e in top["events"]}) > 1, "not all from one hour"

    print("\n[OK] flags the local event, stays silent on the regional one")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
