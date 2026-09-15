"""
api/alerts.py — what the measurements justify raising, for one hour. Writes nothing.

The track asks us to "alert authorities for rapid intervention". This module decides
*whether* an hour justifies it; `api/cases.py` turns that into work with an owner, a
deadline and verified closure. (It used to keep its own alert inbox too. Cases replaced
it: an alert nobody owns and nobody has to prove was dealt with is the Green Delhi
failure mode.)

**Triggers are observed conditions, never a prediction.** A day-ahead warning was built
and falsified (TODO.md 2026-09-12b): over 26 nights, "warn after 6 November" beat every
weather rule we could build from genuine 24-hour-lead forecasts.

**Severity never comes from `residual`**, the quantity this project falsified first. It
comes from the observed concentration, how far a locality stands above its surroundings,
and whether the reading is trusted.

- `hyper_local_event` — a *confirmed* event from `api/hotspots.py`: a trusted reading far
  above the robust median of the monitors around it, for at least two hours.
- `regional_episode` — the regional median in the CPCB Severe band.
"""

from __future__ import annotations

import hashlib
import logging
import os

from typing import Any, Dict, List, Optional

from api import hotspots as hotspots_mod

logger = logging.getLogger("vayusetu.api.alerts")

# CPCB Severe for PM2.5. Below this a "rapid intervention" alert is not warranted:
# Very Poor days are most of a Delhi winter, and an alert that fires every day is
# an alert nobody reads.
SEVERE_PM25 = 250.0
EMERGENCY_PM25 = 350.0

# A hyper-local event this many times its surroundings is an emergency even below the
# regional Severe line, because the exposure is concentrated and the cause is local.
EMERGENCY_RATIO = 3.0

SEVERITIES = ("watch", "warning", "emergency")


def _alert_id(tenant: str, kind: str, key: str, hour: str) -> str:
    """
    Deterministic, so re-scanning the same hour updates rather than duplicates.

    An inbox that grows a new copy of the same alert every time someone reloads is
    worse than useless during an episode.
    """
    raw = f"{tenant}|{kind}|{key}|{hour}"
    return "alert_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _local_severity(pm25: float, times_regional: Optional[float]) -> str:
    if pm25 >= EMERGENCY_PM25 or (times_regional or 0) >= EMERGENCY_RATIO:
        return "emergency"
    if pm25 >= SEVERE_PM25:
        return "warning"
    return "watch"


def evaluate(ts_str: str, tenant: str = "ncr",
             project: Optional[str] = None) -> Dict[str, Any]:
    """
    What the measurements would raise for one hour. Pure: writes nothing.

    Returns the candidate alerts plus, when nothing fires, the reason — "no trigger
    met" is information an officer needs, and a silent empty list looks like a fault.
    """
    hs = hotspots_mod.station_hotspots(ts_str, tenant, project)
    hour = ts_str
    candidates: List[Dict[str, Any]] = []

    # Confirmed only: a trusted reading that persisted. A one-hour outlier is listed on
    # the hotspots panel but never dispatches anyone (api/hotspots.py CONFIRM_HOURS).
    for h in (x for x in hs["hotspots"] if x["confirmed"]):
        sev = _local_severity(h["pm25"], h["times_regional"])
        where = h["name"].rsplit(" - ", 1)[0]
        candidates.append({
            "alert_id": _alert_id(tenant, "hyper_local_event", h["station_id"], hour),
            "tenant": tenant,
            "trigger_kind": "hyper_local_event",
            "severity": sev,
            "ts_hour": hour,
            "location_name": where,
            "station_id": h["station_id"],
            "monitor_name": h["name"],
            "lat": h["lat"],
            "lon": h["lon"],
            "cell_id": None,
            "observed_pm25": h["pm25"],
            "population_exposed": h["population_in_cell"],
            "headline": (
                f"{where} is at {h['pm25']:.0f} ug/m3, "
                f"{h['times_regional']} times the monitors around it"
            ),
            # Measured numbers only. No Gemini call: an alert must not depend on a
            # rate-limited service, and everything here is already computed.
            "evidence": {
                "observed_pm25": h["pm25"],
                "regional_median": hs["regional_median"],
                "excess_over_median": h["excess_over_median"],
                "times_regional": h["times_regional"],
                "robust_z": h["robust_z"],
                "n_monitors_compared": hs["n_reporting"],
                "method": hs["method"],
            },
        })

    median = hs["regional_median"]
    if median is not None and median >= SEVERE_PM25:
        candidates.append({
            "alert_id": _alert_id(tenant, "regional_episode", tenant, hour),
            "tenant": tenant,
            "trigger_kind": "regional_episode",
            "severity": "emergency" if median >= EMERGENCY_PM25 else "warning",
            "ts_hour": hour,
            "location_name": "Region-wide",
            "lat": None,
            "lon": None,
            "cell_id": None,
            "observed_pm25": median,
            "population_exposed": None,
            "headline": (
                f"Region-wide Severe air: {hs['n_reporting']} monitors at a median of "
                f"{median:.0f} ug/m3"
            ),
            "evidence": {
                "regional_median": median,
                "spread_mad": hs["spread_mad"],
                "n_monitors_compared": hs["n_reporting"],
                "severe_threshold": SEVERE_PM25,
            },
        })

    reason = None
    if not candidates:
        if median is None:
            reason = "No monitors reported in this hour."
        else:
            # Say exactly why nothing fired. "No monitor stood out" is false when one did
            # but was a one-hour blip or a faulty instrument, and an officer who can see
            # a spike on the map needs to know which.
            parts = [f"No trigger met. {hs['n_reporting']} monitors reporting, regional median "
                     f"{median:.0f} ug/m3, below the Severe line of {SEVERE_PM25:.0f}."]
            unconfirmed = [h for h in hs["hotspots"] if not h["confirmed"]]
            faulty = hs["excluded_as_sensor_fault"]
            if unconfirmed:
                parts.append(f"{', '.join(h['name'].rsplit(' - ', 1)[0] for h in unconfirmed)} "
                             "stood out for one hour only, which is not enough to send anyone.")
            if faulty:
                parts.append(f"{', '.join(h['name'].rsplit(' - ', 1)[0] for h in faulty)} "
                             "read high, but the instrument was faulty within 3 hours.")
            if not unconfirmed and not faulty:
                parts.append("No monitor stands far enough above its neighbours to flag.")
            reason = " ".join(parts)

    return {"ts": ts_str, "tenant": tenant, "candidates": candidates, "no_trigger_reason": reason}


def demo() -> None:
    """Fires on a confirmed local event, never on a faulty sensor or a one-hour blip."""
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    local = evaluate("2025-10-30 08:00:00")
    print(f"30 Oct 13:30 IST — {len(local['candidates'])} trigger(s)")
    for c in local["candidates"]:
        print(f"  [{c['severity']:9s}] {c['headline']}")
    dwarka = [c for c in local["candidates"] if c["location_name"].startswith("NSIT Dwarka")]
    assert dwarka and dwarka[0]["severity"] == "emergency" and dwarka[0]["station_id"], dwarka

    faulty = evaluate("2025-11-16 06:00:00")
    print(f"\n16 Nov 11:30 IST — {len(faulty['candidates'])} trigger(s)\n  {faulty['no_trigger_reason']}")
    assert not [c for c in faulty["candidates"] if c["trigger_kind"] == "hyper_local_event"]
    assert "Arya Nagar" in faulty["no_trigger_reason"] and "one hour only" in faulty["no_trigger_reason"]

    regional = evaluate("2025-11-11 20:00:00")
    print(f"\n12 Nov 01:30 IST — {len(regional['candidates'])} trigger(s)")
    assert {c["trigger_kind"] for c in regional["candidates"]} == {"regional_episode"}

    quiet = evaluate("2025-10-29 10:00:00")
    print(f"\n29 Oct 15:30 IST — {len(quiet['candidates'])} trigger(s)\n  {quiet['no_trigger_reason']}")
    assert not quiet["candidates"] and quiet["no_trigger_reason"]

    print("\n[OK] confirmed local event fires; faulty sensor and one-hour blip do not, with reasons; "
          "one region-wide trigger for a blanket; silent with a reason when clean")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
