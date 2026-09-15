"""
api/hotspots.py — Hyper-local pollution events, measured.

The track asks for "hidden pollution hotspots". The original plan defined a hotspot
as model estimate minus station interpolation, and that was falsified (TODO.md
2026-09-08b): a positive residual was mostly model error. Nothing here uses a model.

What is detected instead: a locality reading far above the regional field in the
same hour, on a monitor whose readings can be trusted, for long enough to act on. On 30
October, NSIT Dwarka read 629 and then 507 µg/m³ for three hours while the median across
the region's monitors was 123 — four times the number every dashboard displayed, in a
square kilometre where about 24,500 people live. The reading was public the whole time.
It was hidden by the average, which is the number GRAP decisions are taken on.

**The first version of this detector ranked a broken sensor as its worst event.** Arya
Nagar in Bahadurgarh "read 918" on 16 November — inside a run of 717, 31, 559, 33, 500, 0,
886, 4, 918, 19, 557, 0, 0, 0 while every monitor within 25 km held near 250-300. 22 of
the 40 top-ranked events had faults like that nearby. So every outlier now passes
`api/integrity.py` first, and must persist for two consecutive hours to be *confirmed*.
Across the window that leaves 111 confirmed event-hours in 26 localities on 21 days, and
excludes 51 outliers as sensor faults — which are reported, not hidden.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from api import integrity

logger = logging.getLogger("vayusetu.api.hotspots")

# A locality is flagged when it is both statistically unusual against its own city
# AND high enough to matter for health. 3.5 is the conventional robust-outlier cut.
# The absolute floors stop a clean day producing "hotspots" 20 ug/m3 above a low
# median. Before the integrity gate these gave 251 station-hours across 48 localities;
# after it, 197 trusted and 111 confirmed (>= 2 h) across 26 localities on 21 days.
STATION_ROBUST_Z = 3.5
STATION_MIN_EXCESS = 50.0      # ug/m3 above the regional median
STATION_MIN_VALUE = 90.0       # at least CPCB "Moderate"; below this nobody needs sending

_MAD_TO_SIGMA = 1.4826         # MAD -> standard-deviation equivalent for a normal

# An enforcement visit is sent for something that is still happening, not a one-hour
# blip. A local event is *confirmed* when the same monitor was a trusted outlier for at
# least this many consecutive hours. Single-hour outliers are still listed, marked
# unconfirmed, and never raise an alert. Measured: the one-hour survivors of the integrity
# gate included Pusa at 89 -> 254 -> 15, the pattern a sub-threshold glitch produces.
CONFIRM_HOURS = 2

METHOD = (f"A monitor is flagged when its robust z is at least {STATION_ROBUST_Z}, it is "
          f"at least {STATION_MIN_EXCESS} ug/m3 above the regional median, it reads at "
          f"least {STATION_MIN_VALUE} ug/m3, and the reading passes the integrity gate "
          f"(no stuck values, dead zeros or one-hour spikes at that monitor within 3 hours). "
          f"Median and MAD are taken over every monitor reporting in that hour. Measurement "
          f"only: no model, no interpolation.")

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


def _persistent_hours(station_id: str, at: datetime, tenant: str, project: Optional[str]) -> int:
    """Consecutive hours, through `at`, that this monitor was a trusted outlier."""
    series, _, regional, flags = integrity._data(tenant, project)
    s, f = series.get(station_id, {}), flags.get(station_id, {})

    def outlier(h: datetime) -> bool:
        if h not in s or h not in regional:
            return False
        med, mad = regional[h]
        excess = s[h] - med
        return (mad > 0 and excess / (mad * _MAD_TO_SIGMA) >= STATION_ROBUST_Z
                and excess >= STATION_MIN_EXCESS and s[h] >= STATION_MIN_VALUE
                and integrity.trusted(f, h))

    def distinct(a: datetime, b: datetime) -> bool:
        # An exact repeat is not a second observation: a logger re-sending its last value
        # would otherwise "confirm" itself. Mandir Marg read 472.0, 472.0, then 120.
        return abs(s[a] - s[b]) > integrity.STUCK_TOLERANCE

    if not outlier(at):
        return 0
    hour, n = timedelta(hours=1), 1
    cur = at
    while outlier(cur - hour) and distinct(cur - hour, cur):
        n, cur = n + 1, cur - hour
    cur = at
    while outlier(cur + hour) and distinct(cur + hour, cur):
        n, cur = n + 1, cur + hour
    return n


def _gate(entry: Dict[str, Any], at: datetime, tenant: str, project: Optional[str]) -> Dict[str, Any]:
    """A statistical outlier is a hotspot only if the reading passes the integrity gate."""
    ok = integrity.is_trusted(entry["station_id"], at, tenant, project)
    entry["trusted"] = ok
    entry["integrity_flags"] = integrity.reading_flags(entry["station_id"], at, tenant, project)
    entry["outlier_but_untrusted"] = entry["is_hotspot"] and not ok
    entry["is_hotspot"] = entry["is_hotspot"] and ok
    entry["persistent_hours"] = (_persistent_hours(entry["station_id"], at, tenant, project)
                                 if entry["is_hotspot"] else 0)
    entry["confirmed"] = entry["persistent_hours"] >= CONFIRM_HOURS
    return entry


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
    at = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    field: List[Dict[str, Any]] = [
        _gate(_row_to_entry(r, median, mad * _MAD_TO_SIGMA), at, tenant, project) for r in rows
    ]

    return {
        "ts": ts_str,
        "tenant": tenant,
        "regional_median": median,
        "spread_mad": round(mad, 1),
        "n_reporting": len(field),
        "method": METHOD,
        "hotspots": [f for f in field if f["is_hotspot"]],
        # Statistical outliers the integrity gate refused. Shown, not hidden: a monitor
        # that looks like the worst pollution in the region but is broken is itself a
        # finding an official needs, and it explains why a visible spike raised nothing.
        "excluded_as_sensor_fault": [f for f in field if f["outlier_but_untrusted"]],
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
    """
    rows = list(client.query(sql).result())

    events, excluded = [], 0
    for r in rows:
        e = _row_to_entry(r, float(r.regional_median), float(r.mad) * _MAD_TO_SIGMA)
        e = _gate(e, r.ts, tenant, project)
        if not e["is_hotspot"]:
            excluded += 1
            continue
        e["ts"] = r.ts.strftime("%Y-%m-%d %H:00:00")
        e["regional_median"] = float(r.regional_median)
        e["n_reporting"] = int(r.n_reporting)
        events.append(e)

    return {
        "tenant": tenant,
        "method": METHOD,
        "events": events[:limit],
        "trusted_events": len(events),
        "excluded_as_sensor_fault": excluded,
    }


def demo() -> None:
    """
    The detector has to tell a real local event from a regional one AND from a broken
    sensor. All three cases are checked, because getting any of them wrong sends an
    enforcement team to the wrong place — or to a faulty box.
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
        print(f"  {hs['n_reporting']} monitors, regional median {hs['regional_median']} ug/m3, "
              f"{len(hs['hotspots'])} flagged, {len(hs['excluded_as_sensor_fault'])} excluded as sensor faults")
        for f in hs["hotspots"][:6]:
            pop = f"{f['population_in_cell']:,} people" if f["population_in_cell"] else "population unknown"
            print(f"    {f['pm25']:6.1f}  {f['times_regional']}x  z={f['robust_z']:5.1f}  "
                  f"{f['persistent_hours']}h {'confirmed' if f['confirmed'] else 'unconfirmed'}  {pop}  {f['name'][:34]}")
        for f in hs["excluded_as_sensor_fault"]:
            print(f"    EXCLUDED {f['pm25']:6.1f}  flags {f['integrity_flags'] or ['fault nearby']}  {f['name'][:34]}")
        for f in hs["hotspots"]:
            assert f["trusted"] and f["robust_z"] >= STATION_ROBUST_Z
            assert f["excess_over_median"] >= STATION_MIN_EXCESS and f["pm25"] >= STATION_MIN_VALUE

    # A real, sustained local event on a healthy monitor.
    local = station_hotspots("2025-10-30 08:00:00")
    show("Local event, 30 Oct 13:30 IST", local)
    dwarka = next((f for f in local["hotspots"] if f["name"].startswith("NSIT Dwarka")), None)
    assert dwarka, "NSIT Dwarka at 30 Oct 08:00 UTC is a verified local event"
    assert dwarka["confirmed"] and dwarka["persistent_hours"] >= 3, dwarka
    assert dwarka["times_regional"] > 3, dwarka

    # The broken sensor that used to be the headline: an outlier, and refused.
    broken = station_hotspots("2025-11-16 06:00:00")
    show("Faulty sensor, 16 Nov 11:30 IST", broken)
    assert any(f["name"].startswith("Arya Nagar") for f in broken["excluded_as_sensor_fault"]),         "Arya Nagar's 918 must be excluded as a sensor fault"
    assert not any(f["name"].startswith("Arya Nagar") for f in broken["hotspots"])

    # A regional episode: everything severe at once, so nothing is an outlier.
    regional = station_hotspots("2025-11-11 20:00:00")
    show("Regional episode, 12 Nov 01:30 IST", regional)
    assert regional["n_reporting"] > 50 and not regional["hotspots"]
    assert regional["regional_median"] > 250

    top = top_events(limit=6)
    print(f"\nSharpest trusted events ({top['trusted_events']} trusted, "
          f"{top['excluded_as_sensor_fault']} excluded as faults):")
    for e in top["events"]:
        print(f"    {e['ts']}  {e['pm25']:6.1f} vs {e['regional_median']:5.1f}  "
              f"z={e['robust_z']:5.1f}  {e['persistent_hours']}h  {e['name'][:34]}")
    assert top["excluded_as_sensor_fault"] > 0 and all(e["trusted"] for e in top["events"])

    print("\n[OK] confirms a real local event, refuses a broken sensor, stays silent on a regional blanket")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
