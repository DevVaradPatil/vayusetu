"""
api/alerts.py — alerts on what is measured, dispatched to mock accounts only.

The track asks us to "alert authorities for rapid intervention". Two design decisions
shape everything here, and both are consequences of things we measured.

**Alerts fire on observed conditions, never on a prediction.** A day-ahead warning was
built and falsified (TODO.md 2026-09-12b): over 26 nights, "warn after 6 November" beat
every weather rule we could build from genuine 24-hour-lead forecasts. An official who
evacuates a school district on a warning we cannot demonstrate — or who stops trusting
the system after two false alarms — is worse off than with no warning. So a trigger is
always a thing that is happening: a Severe hour now, or a locality running far above its
neighbours now.

**The previous engine keyed severity off `residual`** — model estimate minus
interpolation — which is the quantity the project falsified first. It was deleted rather
than ported. Severity here comes from the observed concentration, how far above its
surroundings a locality is, and how many people live there.

Two triggers, both measurement:

- `hyper_local_event` — a monitor flagged by `api/hotspots.py`: far above the robust
  median of the monitors around it, in the same hour. Actionable at one address.
- `regional_episode` — the city-wide mean in the CPCB Severe band. No single address to
  send anyone to; this is a region-wide response.

**R6: recipients are mock accounts inside this app.** There is deliberately no address
field of any kind — no email, no phone, no webhook — so there is no string in this
codebase that could be pasted into a mailer or mistaken for a real contact. A recipient
is a role key and a display name, and dispatch means "it appears in the in-app inbox".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api import hotspots as hotspots_mod

logger = logging.getLogger("vayusetu.api.alerts")

# R6. Role keys and display names only — no contact details, by construction.
MOCK_RECIPIENTS: Dict[str, str] = {
    "mock_district_officer": "Demo: District Environment Officer",
    "mock_pollution_board": "Demo: State Pollution Control Board",
    "mock_municipal": "Demo: Municipal Corporation",
    "mock_traffic_police": "Demo: Traffic Police Control Room",
}

# Who sees which trigger. A local plume is an enforcement visit to one address, so it
# goes to the people who can make that visit; a regional blanket is a policy measure.
ROUTING: Dict[str, List[str]] = {
    "hyper_local_event": ["mock_district_officer", "mock_municipal"],
    "regional_episode": ["mock_pollution_board", "mock_district_officer", "mock_traffic_police"],
}

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
            "lat": h["lat"],
            "lon": h["lon"],
            "cell_id": None,
            "observed_pm25": h["pm25"],
            "population_exposed": h["population_in_cell"],
            "headline": (
                f"{where} is at {h['pm25']:.0f} ug/m3, "
                f"{h['times_regional']} times the monitors around it"
            ),
            "recipients": ROUTING["hyper_local_event"],
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
            "recipients": ROUTING["regional_episode"],
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


def dispatch(ts_str: str, tenant: str = "ncr", project: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluate one hour and record what fired, to the mock inbox.

    MERGE on the deterministic id, so scanning the same hour twice is a no-op rather
    than a duplicate, and an acknowledgement already made is never reset.
    """
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    result = evaluate(ts_str, tenant, project)
    if not result["candidates"]:
        return {**result, "dispatched": 0, "recipients": MOCK_RECIPIENTS}

    client = bigquery.Client(project=project)
    table = f"{project}.vayusetu_{tenant}.alerts"

    # DML rather than streaming inserts: rows written by the streaming API cannot be
    # UPDATEd for up to 30 minutes, and acknowledging an alert seconds after it is
    # raised is the normal case here.
    for c in result["candidates"]:
        client.query(
            f"""
            MERGE `{table}` T
            USING (SELECT @alert_id AS alert_id) S
            ON T.alert_id = S.alert_id
            WHEN NOT MATCHED THEN INSERT (
              alert_id, tenant, cell_id, city, alert_type, issued_at, severity,
              population_exposed, attribution, recipients, trigger_kind, headline,
              location_name, lat, lon, observed_pm25, ts_hour
            ) VALUES (
              @alert_id, @tenant, @cell_id, @city, @trigger_kind, CURRENT_TIMESTAMP(),
              @severity, @population, PARSE_JSON(@evidence), @recipients, @trigger_kind,
              @headline, @location_name, @lat, @lon, @observed_pm25, TIMESTAMP(@ts_hour)
            )
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("alert_id", "STRING", c["alert_id"]),
                bigquery.ScalarQueryParameter("tenant", "STRING", c["tenant"]),
                bigquery.ScalarQueryParameter("cell_id", "STRING", c["cell_id"]),
                bigquery.ScalarQueryParameter("city", "STRING", c["location_name"]),
                bigquery.ScalarQueryParameter("trigger_kind", "STRING", c["trigger_kind"]),
                bigquery.ScalarQueryParameter("severity", "STRING", c["severity"]),
                bigquery.ScalarQueryParameter("population", "INT64", c["population_exposed"]),
                bigquery.ScalarQueryParameter("evidence", "STRING", json.dumps(c["evidence"])),
                bigquery.ArrayQueryParameter("recipients", "STRING", c["recipients"]),
                bigquery.ScalarQueryParameter("headline", "STRING", c["headline"]),
                bigquery.ScalarQueryParameter("location_name", "STRING", c["location_name"]),
                bigquery.ScalarQueryParameter("lat", "FLOAT64", c["lat"]),
                bigquery.ScalarQueryParameter("lon", "FLOAT64", c["lon"]),
                bigquery.ScalarQueryParameter("observed_pm25", "FLOAT64", c["observed_pm25"]),
                bigquery.ScalarQueryParameter("ts_hour", "STRING", c["ts_hour"]),
            ]),
        ).result()

    logger.info("dispatched %d alert(s) for %s to the mock inbox", len(result["candidates"]), ts_str)
    return {**result, "dispatched": len(result["candidates"]), "recipients": MOCK_RECIPIENTS}


def inbox(tenant: str = "ncr", status: Optional[str] = None, limit: int = 50,
          project: Optional[str] = None) -> Dict[str, Any]:
    """Every alert raised for this tenant, newest first."""
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    where = {
        "open": "AND acknowledged_at IS NULL AND resolved_at IS NULL",
        "acknowledged": "AND acknowledged_at IS NOT NULL AND resolved_at IS NULL",
        "resolved": "AND resolved_at IS NOT NULL",
    }.get(status or "", "")

    rows = list(client.query(
        f"""
        SELECT alert_id, trigger_kind, severity, headline, location_name, lat, lon,
               observed_pm25, population_exposed, recipients, attribution,
               issued_at, ts_hour, acknowledged_at, acknowledged_by,
               resolved_at, resolved_by
        FROM `{project}.vayusetu_{tenant}.alerts`
        WHERE tenant = @tenant {where}
        ORDER BY issued_at DESC, severity
        LIMIT @limit
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("tenant", "STRING", tenant),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]),
    ).result())

    def state(r: Any) -> str:
        if r.resolved_at:
            return "resolved"
        return "acknowledged" if r.acknowledged_at else "open"

    return {
        "tenant": tenant,
        "recipients": MOCK_RECIPIENTS,
        "alerts": [{
            "alert_id": r.alert_id,
            "trigger_kind": r.trigger_kind,
            "severity": r.severity,
            "state": state(r),
            "headline": r.headline,
            "location_name": r.location_name,
            "lat": r.lat,
            "lon": r.lon,
            "observed_pm25": r.observed_pm25,
            "population_exposed": r.population_exposed,
            "recipients": [MOCK_RECIPIENTS.get(k, k) for k in (r.recipients or [])],
            # A JSON column comes back already parsed; older clients hand back a string.
            "evidence": (json.loads(r.attribution) if isinstance(r.attribution, str)
                         else r.attribution),
            "issued_at": r.issued_at.isoformat() if r.issued_at else None,
            "ts_hour": r.ts_hour.isoformat() if r.ts_hour else None,
            "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            "acknowledged_by": r.acknowledged_by,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "resolved_by": r.resolved_by,
        } for r in rows],
    }


def set_state(alert_id: str, action: str, actor: str, tenant: str = "ncr",
              project: Optional[str] = None) -> Dict[str, Any]:
    """
    Acknowledge or resolve one alert.

    `actor` must be a mock recipient key (R6): the audit trail records who acted, and
    the only actors that exist in this system are the demo accounts.
    """
    from google.cloud import bigquery

    if action not in ("acknowledge", "resolve"):
        raise ValueError(f"unknown action {action!r}")
    if actor not in MOCK_RECIPIENTS:
        raise ValueError(f"unknown actor {actor!r}; alerts are dispatched to mock accounts only")

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    # Acknowledging also stamps the acknowledgement when someone resolves an alert
    # nobody had picked up: a resolved-but-never-acknowledged row is a gap in the trail.
    if action == "acknowledge":
        sets = "acknowledged_at = CURRENT_TIMESTAMP(), acknowledged_by = @actor"
    else:
        sets = ("resolved_at = CURRENT_TIMESTAMP(), resolved_by = @actor, "
                "acknowledged_at = IFNULL(acknowledged_at, CURRENT_TIMESTAMP()), "
                "acknowledged_by = IFNULL(acknowledged_by, @actor)")

    job = client.query(
        f"""
        UPDATE `{project}.vayusetu_{tenant}.alerts`
        SET {sets}
        WHERE alert_id = @alert_id AND tenant = @tenant
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id),
            bigquery.ScalarQueryParameter("tenant", "STRING", tenant),
            bigquery.ScalarQueryParameter("actor", "STRING", actor),
        ]),
    )
    job.result()
    if not job.num_dml_affected_rows:
        raise KeyError(alert_id)
    return {"alert_id": alert_id, "action": action, "by": MOCK_RECIPIENTS[actor]}


def demo() -> None:
    """
    An alert must fire on a real local event, stay silent on a quiet hour, never
    duplicate, and never name a real person.
    """
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    # R6, checked in code rather than trusted: nothing here may look like a contact.
    for key, name in MOCK_RECIPIENTS.items():
        assert "@" not in key and "@" not in name, (key, name)
        assert not any(ch.isdigit() for ch in name), f"{name} looks like it carries a number"
        assert name.startswith("Demo:"), name

    local = evaluate("2025-10-30 08:00:00")
    print(f"30 Oct 13:30 IST — {len(local['candidates'])} alert(s)")
    for c in local["candidates"]:
        print(f"  [{c['severity']:9s}] {c['headline']}")
        print(f"              to: {', '.join(MOCK_RECIPIENTS[r] for r in c['recipients'])}")
    dwarka = [c for c in local["candidates"] if c["location_name"].startswith("NSIT Dwarka")]
    assert dwarka, "a confirmed local event on a healthy monitor must raise a local alert"
    assert dwarka[0]["severity"] == "emergency", dwarka  # 507 at 4.1x its surroundings

    # The broken sensor and the one-hour blip raise nothing locally.
    faulty = evaluate("2025-11-16 06:00:00")
    print(f"\n16 Nov 11:30 IST — {len(faulty['candidates'])} alert(s) "
          "(Arya Nagar 918 is a sensor fault; Mandir Marg 472 is one unconfirmed hour)")
    assert not [c for c in faulty["candidates"] if c["trigger_kind"] == "hyper_local_event"], \
        "a faulty sensor or an unconfirmed hour must never dispatch anyone"

    regional = evaluate("2025-11-11 20:00:00")
    print(f"\n12 Nov 01:30 IST — {len(regional['candidates'])} alert(s)")
    for c in regional["candidates"]:
        print(f"  [{c['severity']:9s}] {c['headline']}")
    assert {c["trigger_kind"] for c in regional["candidates"]} == {"regional_episode"}, \
        "a uniform Severe blanket is one region-wide alert, not a pile of local ones"

    quiet = evaluate("2025-10-29 10:00:00")
    print(f"\n29 Oct 15:30 IST — {len(quiet['candidates'])} alert(s)")
    print(f"  {quiet['no_trigger_reason']}")
    assert not quiet["candidates"], "a clean hour must raise nothing"
    assert quiet["no_trigger_reason"], "silence has to come with a reason"

    # Ids are deterministic, so a second scan of the same hour cannot duplicate.
    again = evaluate("2025-10-30 08:00:00")
    assert ([c["alert_id"] for c in local["candidates"]]
            == [c["alert_id"] for c in again["candidates"]]), "ids must be stable"

    print("\n[OK] fires locally, once; one region-wide alert for a blanket; "
          "silent with a reason when clean; mock recipients carry no contact details")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
