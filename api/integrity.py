"""
api/integrity.py — can this monitor's reading be trusted at this hour?

Every downstream decision in VayuSetu — a hotspot, an alert, a case sent to an agency —
starts from one number on one monitor. This module is the gate in front of all of them.

It exists because the gate was missing and it mattered. Our own headline hotspot, Arya
Nagar in Bahadurgarh at 918 µg/m³ on 16 November 2025, was a broken instrument: its hourly
readings ran 717, 31, 559, 33, 500, 0, 886, 4, 918, 19, 557, 0, 0, 0 while every monitor
within 25 km held steady near 250-300. Of the 40 "sharpest local events" the detector
ranked, 22 had readings like that nearby. A hotspot detector with no integrity gate ranks
broken sensors as the worst pollution in the region, and would send an enforcement team to
a faulty box.

It is also a national problem, not a quirk of our data. In 2025 only 270 of India's 562
real-time monitors gave stable data (Airvoice); 13 of Haryana's 31 stations went dark as
October's smog built; Panipat read a flat 183-187 for ten days while neighbours were
Severe; water tankers were filmed spraying around the Anand Vihar monitor. A monitor that
reads implausibly — too steady, zero, or far below its neighbours during an episode — is
itself something an official needs to act on.

Four checks, each a pattern real PM2.5 does not produce, with thresholds set from the
distribution of 35,602 station-hours in the NCR window rather than chosen in advance:

| Flag | Rule | Measured basis |
|---|---|---|
| `stuck` | Same hourly value (±0.05) for 3+ consecutive hours | 34,875 runs of 1 h, 302 of 2 h, then 8 of 3 h: a clean break |
| `dead_zero` | Below 5 µg/m³ while the regional median is ≥ 60 | 310 readings below 2, only 36 more up to 10: bimodal |
| `spike` | Up ≥ 200 from the previous hour AND down ≥ 200 to the next | 39 cases; 99% of hourly changes are under 161 |
| `low_in_episode` | Robust z ≤ −3.5 while the regional median is Severe (≥ 250) | The sprinkler / bad-siting signature. A *suspicion*, not proof |

The first three are instrument faults. The fourth is labelled suspect, because a monitor
in a genuinely cleaner pocket can read low; it is surfaced for inspection, never used to
discard data silently.

A reading is **trusted** when neither it nor any reading within ±3 hours at the same
monitor carries a fault flag: an instrument misbehaving an hour ago is not trustworthy now.
"""

from __future__ import annotations

import logging
import os
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

logger = logging.getLogger("vayusetu.api.integrity")

STUCK_HOURS = 3
STUCK_TOLERANCE = 0.05
DEAD_ZERO_BELOW = 5.0
DEAD_ZERO_WHEN_MEDIAN_AT_LEAST = 60.0
SPIKE_JUMP = 200.0
LOW_Z = -3.5
SEVERE_MEDIAN = 250.0
TRUST_WINDOW_HOURS = 3
MIN_MONITORS_FOR_MEDIAN = 10

FAULT_FLAGS = {"stuck", "dead_zero", "spike"}
SUSPECT_FLAGS = {"low_in_episode"}

_MAD_TO_SIGMA = 1.4826
_HOUR = timedelta(hours=1)

Series = Mapping[datetime, float]


def flag_series(series: Series, regional: Mapping[datetime, Tuple[float, float]]) -> Dict[datetime, Set[str]]:
    """
    Flags for every hour of one monitor.

    `series` is hour -> PM2.5. `regional` is hour -> (median, MAD) across all monitors.
    Pure, so every rule is checkable without a database.
    """
    flags: Dict[datetime, Set[str]] = defaultdict(set)
    hours = sorted(series)

    # stuck: runs of identical values over consecutive hours.
    run: List[datetime] = hours[:1]
    for prev, cur in zip(hours, hours[1:]):
        same = (cur - prev == _HOUR and series[cur] > 0
                and abs(series[cur] - series[prev]) <= STUCK_TOLERANCE)
        if same:
            run.append(cur)
        else:
            if len(run) >= STUCK_HOURS:
                for h in run:
                    flags[h].add("stuck")
            run = [cur]
    if len(run) >= STUCK_HOURS:
        for h in run:
            flags[h].add("stuck")

    for h in hours:
        v = series[h]
        med_mad = regional.get(h)

        if med_mad and v < DEAD_ZERO_BELOW and med_mad[0] >= DEAD_ZERO_WHEN_MEDIAN_AT_LEAST:
            flags[h].add("dead_zero")

        before, after = series.get(h - _HOUR), series.get(h + _HOUR)
        if before is not None and after is not None and v - before >= SPIKE_JUMP and v - after >= SPIKE_JUMP:
            flags[h].add("spike")

        if med_mad and med_mad[0] >= SEVERE_MEDIAN and med_mad[1] > 0:
            z = (v - med_mad[0]) / (med_mad[1] * _MAD_TO_SIGMA)
            if z <= LOW_Z and "dead_zero" not in flags[h]:
                flags[h].add("low_in_episode")

    return {h: f for h, f in flags.items() if f}


def trusted(flags: Mapping[datetime, Set[str]], at: datetime) -> bool:
    """No fault flag at this hour or within ±TRUST_WINDOW_HOURS at the same monitor."""
    for k in range(-TRUST_WINDOW_HOURS, TRUST_WINDOW_HOURS + 1):
        if flags.get(at + k * _HOUR, set()) & FAULT_FLAGS:
            return False
    return True


def regional_stats(all_series: Iterable[Series]) -> Dict[datetime, Tuple[float, float]]:
    """Hour -> (median, MAD) over every monitor reporting, where enough are reporting."""
    by_hour: Dict[datetime, List[float]] = defaultdict(list)
    for s in all_series:
        for h, v in s.items():
            by_hour[h].append(v)
    out = {}
    for h, vs in by_hour.items():
        if len(vs) >= MIN_MONITORS_FOR_MEDIAN:
            m = st.median(vs)
            out[h] = (m, st.median(abs(v - m) for v in vs))
    return out


@lru_cache(maxsize=8)
def _load(tenant: str, project: str) -> Tuple[Dict[str, Dict[datetime, float]], Dict[str, dict],
                                               Dict[datetime, Tuple[float, float]],
                                               Dict[str, Dict[datetime, Set[str]]]]:
    """
    Every monitor's hourly series for the tenant, flagged once.

    ponytail: loads the whole window into memory (35k rows for NCR, ~2 MB). Cached per
    process because the replay window never changes; a live deployment would flag
    incrementally per ingested hour instead.
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    rows = client.query(f"""
        SELECT station_id, ANY_VALUE(station_name) AS name, ANY_VALUE(lat) AS lat,
               ANY_VALUE(lon) AS lon, ts, AVG(value) AS v
        FROM `{project}.vayusetu_{tenant}.raw_stations`
        WHERE pollutant = 'pm25' AND value IS NOT NULL
        GROUP BY station_id, ts
    """).result()

    series: Dict[str, Dict[datetime, float]] = defaultdict(dict)
    meta: Dict[str, dict] = {}
    for r in rows:
        series[r.station_id][r.ts] = float(r.v)
        meta[r.station_id] = {"name": r.name, "lat": float(r.lat), "lon": float(r.lon)}

    regional = regional_stats(series.values())
    flags = {sid: flag_series(s, regional) for sid, s in series.items()}
    return dict(series), meta, regional, flags


def _data(tenant: str, project: Optional[str]):
    return _load(tenant, project or os.environ["GCP_PROJECT_ID"])


def _utc(at: datetime) -> datetime:
    # BigQuery hands back timezone-aware UTC keys. A naive datetime would match none of
    # them, find no flags, and silently trust every reading — so normalise here, once.
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)


def is_trusted(station_id: str, at: datetime, tenant: str = "ncr", project: Optional[str] = None) -> bool:
    _, _, _, flags = _data(tenant, project)
    return trusted(flags.get(station_id, {}), _utc(at))


def reading_flags(station_id: str, at: datetime, tenant: str = "ncr",
                  project: Optional[str] = None) -> List[str]:
    _, _, _, flags = _data(tenant, project)
    return sorted(flags.get(station_id, {}).get(_utc(at), set()))


def network_health(tenant: str = "ncr", project: Optional[str] = None,
                   at: Optional[datetime] = None, days: int = 7) -> Dict[str, Any]:
    """
    Health of every monitor over the `days` before `at` (default: the end of the data).

    Status is the thing an official acts on:
      - `faulty`   — fault flags on ≥ 5% of reported hours: send the maintenance contractor
      - `offline`  — reported < 50% of hours: the monitor is dark
      - `suspect`  — read far below neighbours during Severe hours: inspect the siting
      - `healthy`  — otherwise
    """
    series, meta, regional, flags = _data(tenant, project)
    all_hours = sorted(regional)
    if not all_hours:
        return {"tenant": tenant, "monitors": [], "summary": {}}
    end = at or all_hours[-1]
    start = end - timedelta(days=days)
    window = [h for h in all_hours if start < h <= end]
    severe = [h for h in window if regional[h][0] >= SEVERE_MEDIAN]

    monitors = []
    for sid, s in series.items():
        f = flags.get(sid, {})
        reported = [h for h in window if h in s]
        counts = {k: sum(1 for h in reported if k in f.get(h, set()))
                  for k in ("stuck", "dead_zero", "spike", "low_in_episode")}
        fault_hours = sum(1 for h in reported if f.get(h, set()) & FAULT_FLAGS)
        uptime = len(reported) / len(window) if window else 0.0
        dark_in_severe = sum(1 for h in severe if h not in s)
        fault_rate = fault_hours / len(reported) if reported else 0.0

        if uptime < 0.5:
            status = "offline"
        elif fault_rate >= 0.05:
            status = "faulty"
        elif counts["low_in_episode"] >= 2:
            status = "suspect"
        else:
            status = "healthy"

        # The single most telling stretch of readings, so the claim can be checked by eye.
        example = None
        bad = sorted(h for h in reported if f.get(h, set()) & (FAULT_FLAGS | SUSPECT_FLAGS))
        if bad:
            h0 = bad[len(bad) // 2]
            example = {
                "at": h0.isoformat(),
                "flags": sorted(f[h0]),
                "readings": [round(s[h0 + k * _HOUR], 1) if (h0 + k * _HOUR) in s else None
                             for k in range(-3, 4)],
                "regional_median": [round(regional[h0 + k * _HOUR][0], 1)
                                    if (h0 + k * _HOUR) in regional else None
                                    for k in range(-3, 4)],
            }

        monitors.append({
            "station_id": sid,
            **meta[sid],
            "status": status,
            "uptime": round(uptime, 3),
            "fault_rate": round(fault_rate, 3),
            "hours_expected": len(window),
            "hours_reported": len(reported),
            "dark_during_severe_hours": dark_in_severe,
            "severe_hours": len(severe),
            "flag_counts": counts,
            "example": example,
        })

    order = {"faulty": 0, "offline": 1, "suspect": 2, "healthy": 3}
    monitors.sort(key=lambda m: (order[m["status"]], -m["fault_rate"], m["uptime"]))
    summary = {k: sum(1 for m in monitors if m["status"] == k) for k in order}
    return {
        "tenant": tenant,
        "window": [start.isoformat(), end.isoformat()],
        "method": ("stuck: identical value 3+ h; dead_zero: < 5 µg/m³ while regional median ≥ 60; "
                   "spike: up and back down ≥ 200 in one hour; low_in_episode: robust z ≤ -3.5 "
                   "while regional median ≥ 250. Faulty at ≥ 5% flagged hours, offline below "
                   "50% uptime."),
        "summary": summary,
        "monitors": monitors,
    }


def demo() -> None:
    """Each rule on a synthetic series, then the real network."""
    t0 = datetime(2025, 11, 16)
    hours = [t0 + k * _HOUR for k in range(12)]
    regional = {h: (250.0, 30.0) for h in hours}

    # A healthy monitor tracking the region with ordinary noise raises nothing.
    healthy = {h: 250.0 + (7 * k % 11) for k, h in enumerate(hours)}
    assert flag_series(healthy, regional) == {}, flag_series(healthy, regional)

    # The Arya Nagar pattern: flip-flops and zeros.
    arya = dict(zip(hours, [717, 31, 559, 33, 500, 0, 44, 886, 442, 4, 50, 918]))
    fa = flag_series(arya, regional)
    assert "spike" in fa[hours[2]] and "dead_zero" in fa[hours[5]], fa
    assert not trusted(fa, hours[7]), "a monitor flip-flopping around this hour is not trusted"

    # Alipur: stuck at one value.
    stuck = {h: (161.0 if 3 <= k <= 8 else 150.0 + k) for k, h in enumerate(hours)}
    fs = flag_series(stuck, regional)
    assert all("stuck" in fs[hours[k]] for k in range(3, 9)) and hours[2] not in fs, fs

    # Two identical hours is coincidence, not a fault.
    twice = {h: (161.0 if k in (4, 5) else 150.0 + k) for k, h in enumerate(hours)}
    assert flag_series(twice, regional) == {}, "a 2-hour repeat must not flag"

    # Reading far below a Severe region is suspect, and suspicion alone does not distrust.
    low = {h: 40.0 + k for k, h in enumerate(hours)}
    fl = flag_series(low, regional)
    assert all(f == {"low_in_episode"} for f in fl.values()) and trusted(fl, hours[6]), fl

    # A genuine sustained local event — high, steady, not flip-flopping — stays trusted.
    plume = {h: 250.0 + (340 if 4 <= k <= 8 else 0) + k for k, h in enumerate(hours)}
    fp = flag_series(plume, regional)
    assert not (set().union(*fp.values()) & FAULT_FLAGS) if fp else True, fp
    print("[OK] rules: healthy clean, flip-flop and zeros faulted, stuck ≥3 h faulted, "
          "2 h repeat allowed, low-in-episode suspect only, sustained plume trusted")

    import pathlib
    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    from datetime import timezone
    arya_hour = datetime(2025, 11, 16, 6, tzinfo=timezone.utc)
    series, meta, _, _ = _data("ncr", None)
    arya_id = next(sid for sid, m in meta.items() if m["name"].startswith("Arya Nagar"))
    assert not is_trusted(arya_id, arya_hour), "the 918 reading must not be trusted"
    print(f"[OK] Arya Nagar 918 at 16 Nov 06:00 UTC: flags {reading_flags(arya_id, arya_hour)}, not trusted")

    h = network_health(days=27)
    print(f"\nNetwork over the whole window: {h['summary']}")
    for m in h["monitors"][:8]:
        ex = m["example"]
        print(f"  {m['status']:8s} {m['name'][:36]:36s} uptime {m['uptime']:.0%}  "
              f"faults {m['fault_rate']:.0%}  {m['flag_counts']}")
        if ex:
            print(f"           e.g. {ex['at'][5:16]} {ex['flags']}: {ex['readings']} "
                  f"(region {ex['regional_median'][3]})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
