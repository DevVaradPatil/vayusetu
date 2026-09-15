"""
api/cases.py — from a trusted measurement to a closed, verified case.

Detection is not where India's air quality response fails. It fails at closure. The
Green Delhi app took 84,765 pollution complaints in 2024; 10,656 were overdue, no
department met its deadlines, and one department saw 99 of the 183 complaints it
"resolved" reopened. CAQM's flying squads keep reporting "unsatisfactory compliance".
A case marked resolved with nothing behind it is the failure this module is built
against.

A case is work for a named agency, with a deadline:

| Kind | Raised when | Goes to | Deadline |
|---|---|---|---|
| `local_event` | A confirmed hyper-local event (trusted, ≥ 2 h) | The town's municipal body, copied to the state board | 24 h |
| `monitor_fault` | A monitor is faulty or offline (`api/integrity.py`) | The monitor's operator — read from its name | 72 h |
| `regional_episode` | Regional median in the CPCB Severe band | The state board, copied to CAQM | 12 h |
| `fire_verification` | A district's burn scars far outrun its fire alerts (`api/fires.py`) | That state's board, copied to CAQM | 7 days |

The last is the cross-state notice, and it is deliberately **not** "Punjab caused Delhi's
Severe day". That was tested: Punjab fires carried toward Delhi by the wind explain at
most r = +0.32 of Delhi's daily PM2.5 once the seasonal trend is removed (23 days), which
cannot name a state as the cause of a given day. What the data does show is that a
district's fire count no longer measures its burning, so the notice asks the state board
to verify on the ground in named districts. Whether it worked is measured by the next
season's burn scars; until then such a notice can only close as `closed_unverified`.

Every monitor's name already carries its operator ("NSIT Dwarka, Delhi - CPCB",
"Arya Nagar, Bahadurgarh - HSPCB") and its town, so routing needs no lookup service.

**Closing a case takes two independent checks, decided in code, never by the model:**

1. *A photo.* Gemini describes it (`api/gemini/closure.py`): is it a genuine site photo,
   is an active source still visible, is monitoring equipment in frame. The upload must
   also come from within 1 km of the case location.
2. *The measurement.* What the monitor recorded afterwards. If the local excess, the
   fault, or the Severe episode is still in the data, the closure is refused — however
   good the photo looks. If there is no trusted data to judge by, the case closes as
   `closed_unverified`, never as verified.

In the replay, "afterwards" is the 24 recorded hours after the event; in live operation
it is the hours after the closure is submitted. The UI says which.

Overdue and escalation are computed when a case is read, from its deadline, so there is
no scheduler to fail silently.

**R6.** Agencies are demo accounts: a key and a display name, no contact details of any
kind. **R4.** No case is raised from a photo; photos only serve as closure evidence, and
are not stored — only their SHA-256 and Gemini's description are kept.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import fires, hotspots, integrity

logger = logging.getLogger("vayusetu.api.cases")

SLA_HOURS = {"local_event": 24, "monitor_fault": 72, "regional_episode": 12, "fire_verification": 168}
OUTCOME_WINDOW_HOURS = 24
OUTCOME_TAIL_HOURS = 3          # judge by the last hours of the window, not its start
MAX_UPLOAD_DISTANCE_KM = 1.0
MONITOR_RECOVERED_UPTIME = 0.8

# R6: display names only. Every one is a demo account inside this app.
OPERATORS = {
    "DPCC": "Demo: Delhi Pollution Control Committee",
    "HSPCB": "Demo: Haryana State Pollution Control Board",
    "UPPCB": "Demo: Uttar Pradesh Pollution Control Board",
    "RSPCB": "Demo: Rajasthan State Pollution Control Board",
    "CPCB": "Demo: Central Pollution Control Board",
    "IMD": "Demo: India Meteorological Department",
    "IITM": "Demo: IITM Pune (SAFAR)",
}
STATE_BOARD = {
    "Delhi": "Demo: Delhi Pollution Control Committee",
    "Haryana": "Demo: Haryana State Pollution Control Board",
    "Uttar Pradesh": "Demo: Uttar Pradesh Pollution Control Board",
    "Rajasthan": "Demo: Rajasthan State Pollution Control Board",
    "Punjab": "Demo: Punjab Pollution Control Board",
}
TOWN_STATE = {
    "Delhi": "Delhi", "New Delhi": "Delhi",
    "Gurugram": "Haryana", "Faridabad": "Haryana", "Bahadurgarh": "Haryana",
    "Manesar": "Haryana", "Ballabgarh": "Haryana", "Panchgaon": "Haryana",
    "Sonipat": "Haryana", "Panipat": "Haryana", "Rohtak": "Haryana", "Jhajjar": "Haryana",
    "Noida": "Uttar Pradesh", "Greater Noida": "Uttar Pradesh", "Ghaziabad": "Uttar Pradesh",
    "Bhiwadi": "Rajasthan",
}
MUNICIPAL = {
    "Delhi": "Demo: Municipal Corporation of Delhi, enforcement",
    "New Delhi": "Demo: New Delhi Municipal Council, enforcement",
    "Gurugram": "Demo: Municipal Corporation Gurugram",
    "Faridabad": "Demo: Municipal Corporation Faridabad",
    "Noida": "Demo: Noida Authority",
    "Greater Noida": "Demo: Greater Noida Authority",
    "Ghaziabad": "Demo: Ghaziabad Municipal Corporation",
}
ESCALATION = "Demo: Commission for Air Quality Management (CAQM)"

# Anyone acting on a case acts as one of these, and the audit log records which.
ACTORS = {
    "mock_municipal": "Demo: municipal enforcement officer",
    "mock_spcb": "Demo: state pollution control board officer",
    "mock_monitor_technician": "Demo: monitoring contractor technician",
    "mock_caqm": "Demo: CAQM duty officer",
}


# --------------------------------------------------------------------- routing

def parse_monitor_name(name: str) -> Tuple[str, Optional[str], Optional[str]]:
    """'NSIT Dwarka, Delhi - CPCB' -> ('NSIT Dwarka, Delhi', 'Delhi', 'CPCB')."""
    place, _, operator = name.rpartition(" - ")
    if not place:
        place, operator = name, ""
    town = place.rsplit(",", 1)[-1].strip() if "," in place else None
    # Some names put the town first ('Sector - 62, Noida, UP'); take the known town.
    parts = [p.strip() for p in place.replace(" - ", ",").split(",")]
    known = next((p for p in reversed(parts) if p in TOWN_STATE), None)
    return place.strip(), known or town, (operator.strip() or None)


def route(kind: str, monitor_name: Optional[str]) -> Dict[str, Any]:
    """Who owns a case, who is copied, who it escalates to."""
    if kind == "regional_episode":
        return {"owner": STATE_BOARD["Delhi"], "copied": [ESCALATION], "escalates_to": ESCALATION}
    if kind == "fire_verification":             # monitor_name carries the state here
        return {"owner": STATE_BOARD.get(monitor_name or "", "Demo: State Pollution Control Board"),
                "copied": [ESCALATION], "escalates_to": ESCALATION}
    place, town, operator = parse_monitor_name(monitor_name or "")
    state = TOWN_STATE.get(town or "")
    board = STATE_BOARD.get(state or "", "Demo: State Pollution Control Board")
    if kind == "monitor_fault":
        owner = OPERATORS.get(operator or "", board)
        return {"owner": owner, "copied": [board] if board != owner else [], "escalates_to": ESCALATION}
    owner = MUNICIPAL.get(town or "", f"Demo: municipal body, {town or place}")
    return {"owner": owner, "copied": [board], "escalates_to": ESCALATION}


# -------------------------------------------------------------- outcome checks

@dataclass
class Outcome:
    verdict: str                        # resolved | persisting | unknown
    summary: str
    hours: List[Dict[str, Any]]


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def outcome_local_event(series: Dict[datetime, float], flags: Dict[datetime, set],
                        regional: Dict[datetime, Tuple[float, float]], event_hour: datetime,
                        min_excess: float, min_z: float, min_value: float) -> Outcome:
    """Did the monitor's excess over the region subside in the hours after the event?"""
    hours, trusted_rows = [], []
    for k in range(1, OUTCOME_WINDOW_HOURS + 1):
        h = event_hour + timedelta(hours=k)
        v, rm = series.get(h), regional.get(h)
        ok = v is not None and rm is not None and integrity.trusted(flags, h)
        out = False
        if ok and rm[1] > 0:
            ex = v - rm[0]
            out = ex >= min_excess and ex / (rm[1] * 1.4826) >= min_z and v >= min_value
        row = {"at": h.isoformat(), "value": round(v, 1) if v is not None else None,
               "regional_median": round(rm[0], 1) if rm else None, "trusted": ok, "elevated": out}
        hours.append(row)
        if ok:
            trusted_rows.append(row)
    tail = trusted_rows[-OUTCOME_TAIL_HOURS:]
    if len(tail) < OUTCOME_TAIL_HOURS:
        return Outcome("unknown", f"Only {len(trusted_rows)} trusted readings in the "
                       f"{OUTCOME_WINDOW_HOURS} h after — not enough to judge.", hours)
    if any(r["elevated"] for r in tail):
        return Outcome("persisting", "The monitor still reads far above the region at the end "
                       "of the check window.", hours)
    first_clear = next((i + 1 for i, r in enumerate(hours) if r["trusted"] and not r["elevated"]), None)
    return Outcome("resolved", f"The local excess had subsided {first_clear} h after the event "
                   "and stayed down.", hours)


def outcome_monitor_fault(series: Dict[datetime, float], flags: Dict[datetime, set],
                          event_hour: datetime) -> Outcome:
    """Is the monitor reporting cleanly again?"""
    hours = []
    for k in range(1, OUTCOME_WINDOW_HOURS + 1):
        h = event_hour + timedelta(hours=k)
        f = sorted(flags.get(h, set()) & integrity.FAULT_FLAGS)
        hours.append({"at": h.isoformat(), "value": round(series[h], 1) if h in series else None,
                      "faults": f})
    reported = [r for r in hours if r["value"] is not None]
    uptime = len(reported) / len(hours)
    recent_faults = [r for r in hours[-12:] if r["faults"]]
    if uptime < 0.5:
        return Outcome("persisting", f"Still dark: reported {uptime:.0%} of hours.", hours)
    if recent_faults:
        return Outcome("persisting", f"Still faulty: {len(recent_faults)} faulty hours in the last 12.", hours)
    if uptime < MONITOR_RECOVERED_UPTIME:
        return Outcome("unknown", f"No faults, but reported only {uptime:.0%} of hours.", hours)
    return Outcome("resolved", f"Reporting {uptime:.0%} of hours with no faults in the last 12.", hours)


def outcome_regional(regional: Dict[datetime, Tuple[float, float]], event_hour: datetime,
                     severe: float) -> Outcome:
    hours = []
    for k in range(1, OUTCOME_WINDOW_HOURS + 1):
        h = event_hour + timedelta(hours=k)
        rm = regional.get(h)
        hours.append({"at": h.isoformat(), "regional_median": round(rm[0], 1) if rm else None})
    known = [r for r in hours if r["regional_median"] is not None][-OUTCOME_TAIL_HOURS:]
    if len(known) < OUTCOME_TAIL_HOURS:
        return Outcome("unknown", "Not enough regional readings to judge.", hours)
    if any(r["regional_median"] >= severe for r in known):
        return Outcome("persisting", f"The region is still Severe: median {known[-1]['regional_median']:.0f}.", hours)
    return Outcome("resolved", f"The region is out of Severe: median {known[-1]['regional_median']:.0f}.", hours)


def outcome_fire_verification(rows: Sequence[dict], state: str, district: str, season: int) -> Outcome:
    """Did a later season's burning per alert fall back below the notice threshold?"""
    later = sorted({r["season"] for r in rows if r["season"] > season})
    if not later:
        return Outcome("unknown", f"Only the {season + 1} season's burn scars can show whether burning "
                       "came down; there is no later season yet.", [])
    d = next((x for x in fires.build_ledger(list(rows), later[-1])["districts"]
              if x["state"] == state and x["district"] == district), None)
    if d is None or d["undercount_factor"] is None:
        return Outcome("unknown", f"Too little burning in {later[-1]} to compare.", [])
    if d["undercount_factor"] >= fires.NOTICE_MIN_FACTOR:
        return Outcome("persisting", f"In {later[-1]} {district} still burned {d['undercount_factor']}× "
                       "its 2020-21 land per fire alert.", [])
    return Outcome("resolved", f"In {later[-1]} {district} burned {d['undercount_factor']}× its 2020-21 "
                   "land per alert, below the notice threshold.", [])


def fire_candidates(project: Optional[str] = None) -> List[Dict[str, Any]]:
    """Verification notices the latest fire ledger justifies. Pure read; writes nothing."""
    ledger = fires.ledger(project=project)
    season, out = ledger["season"], []
    for d in ledger["districts"]:
        if not d["warrants_notice"]:
            continue
        out.append({
            "kind": "fire_verification", "severity": "warning",
            "title": f"{d['district']}, {d['state']}: {d['burned_km2']:,.0f} km² burned against "
                     f"{d['day_detections']:,} fire alerts",
            "detail": (f"Burn scars show {d['undercount_factor']}× more land burned per satellite fire alert "
                       f"than in {ledger['baseline_seasons'][0]}-{str(ledger['baseline_seasons'][-1])[2:]}: "
                       f"at the old rate this burning would have raised about "
                       f"{d['alerts_expected_at_baseline']:,} alerts. Fire counts no longer measure burning "
                       "here, and most large fires are now set after the midday satellite pass. Verify on "
                       "the ground, including evenings, and report the measures taken. The next season's "
                       "burn scars will show whether they worked."),
            "station_id": f"district:{d['state']}:{d['district']}",
            "location_name": f"{d['district']}, {d['state']}",
            "lat": None, "lon": None, "event_hour": f"{season}-12-01 00:00:00",
            "evidence": {"season": season, **d, "sources": ledger["sources"]},
            **route("fire_verification", d["state"]),
        })
    return out


def decide_closure(kind: str, outcome: Outcome, photo: Optional[Dict[str, Any]],
                   distance_km: Optional[float], note: str) -> Tuple[str, List[str]]:
    """
    The whole closure policy, in one pure function.

    Returns (result, reasons). result is `closed_verified`, `closed_unverified` or
    `rejected`. Rejection keeps the case open and the reasons go in the audit log.
    """
    reasons: List[str] = []

    if kind in ("local_event", "monitor_fault"):
        if photo is None:
            reasons.append("A photo of the site is required.")
        else:
            if not photo.get("is_genuine_site_photo"):
                reasons.append(f"The photo is not a genuine site photo ({photo.get('rejection_reason') or 'rejected'}).")
            if kind == "local_event" and photo.get("active_sources_visible"):
                reasons.append("The photo still shows: " + ", ".join(photo["active_sources_visible"]).replace("_", " ") + ".")
            if kind == "monitor_fault" and not photo.get("shows_monitoring_equipment"):
                reasons.append("The photo does not show the monitoring equipment.")
        if distance_km is None:
            reasons.append("The upload has no location.")
        elif distance_km > MAX_UPLOAD_DISTANCE_KM:
            reasons.append(f"The photo was uploaded {distance_km:.1f} km from the case location (limit {MAX_UPLOAD_DISTANCE_KM:.0f} km).")
    elif len(note.strip()) < 20:
        reasons.append("Describe the measures taken (at least 20 characters).")

    if outcome.verdict == "persisting":
        reasons.append("The measurements still show the problem: " + outcome.summary)

    if reasons:
        return "rejected", reasons
    if outcome.verdict == "unknown":
        return "closed_unverified", ["Evidence accepted, but there is no trusted measurement to confirm it: " + outcome.summary]
    return "closed_verified", [outcome.summary]


def effective_status(status: str, due_at: datetime, now: datetime) -> Dict[str, Any]:
    """Overdue and escalation, computed on read."""
    closed = status.startswith("closed")
    overdue = not closed and now > due_at
    left = (due_at - now).total_seconds() / 3600
    return {"closed": closed, "overdue": overdue, "hours_left": round(left, 1),
            "escalated": overdue}


# ------------------------------------------------------------------ storage

_TABLES_READY: set = set()


def _client(project: str):
    from google.cloud import bigquery
    return bigquery.Client(project=project)


def _ensure_tables(client, project: str, tenant: str) -> None:
    key = (project, tenant)
    if key in _TABLES_READY:
        return
    ds = f"`{project}.vayusetu_{tenant}`"
    client.query(f"""
        CREATE TABLE IF NOT EXISTS {ds}.cases (
          case_id STRING NOT NULL, tenant STRING NOT NULL, kind STRING NOT NULL,
          status STRING NOT NULL, severity STRING, title STRING, detail STRING,
          station_id STRING, location_name STRING, lat FLOAT64, lon FLOAT64,
          event_hour TIMESTAMP, owner STRING, copied ARRAY<STRING>, escalates_to STRING,
          opened_at TIMESTAMP, due_at TIMESTAMP, evidence JSON, closure JSON,
          closed_at TIMESTAMP, closed_by STRING
        );
        CREATE TABLE IF NOT EXISTS {ds}.case_events (
          case_id STRING NOT NULL, event_at TIMESTAMP NOT NULL, actor STRING, action STRING NOT NULL,
          note STRING, detail JSON
        );
    """).result()
    _TABLES_READY.add(key)


def _case_id(tenant: str, kind: str, key: str, hour: str) -> str:
    return "case_" + hashlib.sha1(f"{tenant}|{kind}|{key}|{hour}".encode()).hexdigest()[:16]


def _log(client, project: str, tenant: str, case_id: str, actor: Optional[str], action: str,
         note: str = "", detail: Optional[dict] = None) -> None:
    from google.cloud import bigquery
    client.query(
        f"INSERT INTO `{project}.vayusetu_{tenant}.case_events` (case_id, event_at, actor, action, note, detail) "
        "VALUES (@id, CURRENT_TIMESTAMP(), @actor, @action, @note, PARSE_JSON(@detail))",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("id", "STRING", case_id),
            bigquery.ScalarQueryParameter("actor", "STRING", actor),
            bigquery.ScalarQueryParameter("action", "STRING", action),
            bigquery.ScalarQueryParameter("note", "STRING", note),
            bigquery.ScalarQueryParameter("detail", "STRING", json.dumps(detail or {})),
        ]),
    ).result()


def candidates_for_hour(ts_str: str, tenant: str = "ncr", project: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every case this hour's trusted measurements justify. Pure read; writes nothing."""
    from api import alerts

    at = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    out: List[Dict[str, Any]] = []

    for c in alerts.evaluate(ts_str, tenant, project)["candidates"]:
        kind = "local_event" if c["trigger_kind"] == "hyper_local_event" else "regional_episode"
        station_id = c.get("station_id")
        name = c.get("monitor_name") or c["location_name"]
        out.append({
            "kind": kind, "severity": c["severity"], "title": c["headline"],
            "detail": ("A confirmed local event on a trusted monitor. Inspect the area for an "
                       "active source: open burning, construction dust, garbage fires, idling traffic."
                       if kind == "local_event" else
                       "The whole region is Severe. Apply the GRAP stage measures; no single site "
                       "explains it."),
            "station_id": station_id, "location_name": name,
            "lat": c["lat"], "lon": c["lon"], "event_hour": ts_str,
            "evidence": c["evidence"], **route(kind, name if kind == "local_event" else None),
        })

    health = integrity.network_health(tenant, project, at=at, days=1)
    for m in health["monitors"]:
        if m["status"] not in ("faulty", "offline"):
            continue
        # Government monitors only. OpenAQ also carries community sensors ("Air Check",
        # "GK1 (Oberoi Terrace)"); a state board has no duty to repair a private box, and a
        # case it cannot act on is noise in the queue. They are still excluded as untrusted.
        if parse_monitor_name(m["name"])[2] not in OPERATORS:
            continue
        what = "is dark" if m["status"] == "offline" else "is reporting implausible readings"
        out.append({
            "kind": "monitor_fault", "severity": "warning",
            "title": f"{m['name'].rsplit(' - ', 1)[0]} {what}",
            "detail": ("Readings from this monitor are being excluded from averages, hotspots and "
                       "alerts. Send a technician; the evidence shows the raw readings."),
            "station_id": m["station_id"], "location_name": m["name"],
            "lat": m["lat"], "lon": m["lon"], "event_hour": ts_str,
            "evidence": {"status": m["status"], "uptime": m["uptime"], "fault_rate": m["fault_rate"],
                         "flag_counts": m["flag_counts"], "example": m["example"]},
            **route("monitor_fault", m["name"]),
        })
    return out


def raise_for_hour(ts_str: str, tenant: str = "ncr", project: Optional[str] = None) -> Dict[str, Any]:
    """
    Open cases for everything this hour justifies, without duplicating open work.

    One open case per monitor fault, one per local event within 6 hours at the same
    monitor, one open regional episode: an inbox that fills with copies during an
    episode is unreadable exactly when it matters.
    """
    project = project or os.environ["GCP_PROJECT_ID"]
    return {"ts": ts_str, "opened": _open(candidates_for_hour(ts_str, tenant, project), tenant, project)}


def raise_fire_notices(tenant: str = "ncr", project: Optional[str] = None) -> Dict[str, Any]:
    """Open a verification notice per district the latest ledger flags; one open notice per district."""
    project = project or os.environ["GCP_PROJECT_ID"]
    cands = fire_candidates(project)
    return {"candidates": len(cands), "opened": _open(cands, tenant, project)}


def _open(candidates: List[Dict[str, Any]], tenant: str, project: str) -> int:
    from google.cloud import bigquery

    client = _client(project)
    _ensure_tables(client, project, tenant)
    table = f"`{project}.vayusetu_{tenant}.cases`"
    opened = 0

    for c in candidates:
        ts_str = c["event_hour"]
        cid = _case_id(tenant, c["kind"], c["station_id"] or tenant, ts_str)
        if c["kind"] == "local_event":
            dup = ("T.kind = S.kind AND T.station_id = S.station_id AND NOT STARTS_WITH(T.status, 'closed') "
                   "AND ABS(TIMESTAMP_DIFF(T.event_hour, S.event_hour, HOUR)) <= 6")
        elif c["kind"] in ("monitor_fault", "fire_verification"):
            dup = "T.kind = S.kind AND T.station_id = S.station_id AND NOT STARTS_WITH(T.status, 'closed')"
        else:
            dup = "T.kind = S.kind AND NOT STARTS_WITH(T.status, 'closed')"
        job = client.query(
            f"""
            MERGE {table} T
            USING (SELECT @kind AS kind, @station_id AS station_id, TIMESTAMP(@event_hour) AS event_hour) S
            ON T.tenant = @tenant AND ({dup})
            WHEN NOT MATCHED THEN INSERT (
              case_id, tenant, kind, status, severity, title, detail, station_id, location_name,
              lat, lon, event_hour, owner, copied, escalates_to, opened_at, due_at, evidence
            ) VALUES (
              @case_id, @tenant, @kind, 'open', @severity, @title, @detail, @station_id, @location_name,
              @lat, @lon, TIMESTAMP(@event_hour), @owner, @copied, @escalates_to, CURRENT_TIMESTAMP(),
              TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL @sla HOUR), PARSE_JSON(@evidence)
            )
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("case_id", "STRING", cid),
                bigquery.ScalarQueryParameter("tenant", "STRING", tenant),
                bigquery.ScalarQueryParameter("kind", "STRING", c["kind"]),
                bigquery.ScalarQueryParameter("severity", "STRING", c["severity"]),
                bigquery.ScalarQueryParameter("title", "STRING", c["title"]),
                bigquery.ScalarQueryParameter("detail", "STRING", c["detail"]),
                bigquery.ScalarQueryParameter("station_id", "STRING", c["station_id"]),
                bigquery.ScalarQueryParameter("location_name", "STRING", c["location_name"]),
                bigquery.ScalarQueryParameter("lat", "FLOAT64", c["lat"]),
                bigquery.ScalarQueryParameter("lon", "FLOAT64", c["lon"]),
                bigquery.ScalarQueryParameter("event_hour", "STRING", c["event_hour"]),
                bigquery.ScalarQueryParameter("owner", "STRING", c["owner"]),
                bigquery.ArrayQueryParameter("copied", "STRING", c["copied"]),
                bigquery.ScalarQueryParameter("escalates_to", "STRING", c["escalates_to"]),
                bigquery.ScalarQueryParameter("sla", "INT64", SLA_HOURS[c["kind"]]),
                bigquery.ScalarQueryParameter("evidence", "STRING", json.dumps(c["evidence"], default=str)),
            ]),
        )
        job.result()
        if job.num_dml_affected_rows:
            opened += 1
            basis = (f"the {ts_str[:4]} fire ledger" if c["kind"] == "fire_verification"
                     else f"measurements at {ts_str} UTC")
            _log(client, project, tenant, cid, None, "opened", f"Raised from {basis}; owner {c['owner']}")
    return opened


def list_cases(tenant: str = "ncr", project: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    project = project or os.environ["GCP_PROJECT_ID"]
    client = _client(project)
    _ensure_tables(client, project, tenant)
    from google.cloud import bigquery

    now = now or datetime.now(timezone.utc)
    rows = list(client.query(f"""
        SELECT c.*, ev.events
        FROM `{project}.vayusetu_{tenant}.cases` c
        LEFT JOIN (
          SELECT case_id, ARRAY_AGG(STRUCT(event_at, actor, action, note) ORDER BY event_at) AS events
          FROM `{project}.vayusetu_{tenant}.case_events` GROUP BY case_id
        ) ev USING (case_id)
        WHERE c.tenant = @tenant
        ORDER BY STARTS_WITH(c.status, 'closed'), c.due_at
    """, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("tenant", "STRING", tenant)])).result())

    def js(v):
        return json.loads(v) if isinstance(v, str) else v

    cases = []
    for r in rows:
        eff = effective_status(r.status, r.due_at, now)
        cases.append({
            "case_id": r.case_id, "kind": r.kind, "status": r.status, "severity": r.severity,
            "title": r.title, "detail": r.detail, "station_id": r.station_id,
            "location_name": r.location_name, "lat": r.lat, "lon": r.lon,
            "event_hour": r.event_hour.isoformat() if r.event_hour else None,
            "owner": r.owner, "copied": list(r.copied or []), "escalates_to": r.escalates_to,
            "opened_at": r.opened_at.isoformat(), "due_at": r.due_at.isoformat(),
            "evidence": js(r.evidence), "closure": js(r.closure),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None, "closed_by": r.closed_by,
            "events": [{"at": e["event_at"].isoformat(), "actor": ACTORS.get(e["actor"], e["actor"]),
                        "action": e["action"], "note": e["note"]} for e in (r.events or [])],
            **eff,
        })
    summary = {
        "open": sum(1 for c in cases if not c["closed"]),
        "overdue": sum(1 for c in cases if c["overdue"]),
        "closed_verified": sum(1 for c in cases if c["status"] == "closed_verified"),
        "closed_unverified": sum(1 for c in cases if c["status"] == "closed_unverified"),
        "closure_rejections": sum(1 for c in cases for e in c["events"] if e["action"] == "closure_rejected"),
    }
    return {"tenant": tenant, "summary": summary, "actors": ACTORS, "cases": cases}


def _load_case(client, project: str, tenant: str, case_id: str):
    from google.cloud import bigquery
    rows = list(client.query(
        f"SELECT * FROM `{project}.vayusetu_{tenant}.cases` WHERE case_id = @id AND tenant = @tenant",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("id", "STRING", case_id),
            bigquery.ScalarQueryParameter("tenant", "STRING", tenant)])).result())
    if not rows:
        raise KeyError(case_id)
    return rows[0]


def acknowledge(case_id: str, actor: str, note: str = "", tenant: str = "ncr",
                project: Optional[str] = None) -> Dict[str, Any]:
    from google.cloud import bigquery
    if actor not in ACTORS:
        raise ValueError(f"unknown actor {actor!r}; only demo accounts exist")
    project = project or os.environ["GCP_PROJECT_ID"]
    client = _client(project)
    _ensure_tables(client, project, tenant)
    case = _load_case(client, project, tenant, case_id)
    if case.status != "open":
        raise ValueError(f"case is {case.status}, not open")
    client.query(
        f"UPDATE `{project}.vayusetu_{tenant}.cases` SET status = 'in_progress' WHERE case_id = @id",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", case_id)]),
    ).result()
    _log(client, project, tenant, case_id, actor, "acknowledged", note)
    return {"case_id": case_id, "status": "in_progress"}


def submit_closure(case_id: str, actor: str, note: str, photo: Optional[bytes], mime_type: Optional[str],
                   lat: Optional[float], lon: Optional[float], tenant: str = "ncr",
                   project: Optional[str] = None, location_source: str = "device") -> Dict[str, Any]:
    """Examine the evidence, measure the outcome, and close or refuse."""
    from google.cloud import bigquery
    from api.gemini import closure as closure_mod

    if actor not in ACTORS:
        raise ValueError(f"unknown actor {actor!r}; only demo accounts exist")
    project = project or os.environ["GCP_PROJECT_ID"]
    client = _client(project)
    _ensure_tables(client, project, tenant)
    case = _load_case(client, project, tenant, case_id)
    if case.status.startswith("closed"):
        raise ValueError(f"case is already {case.status}")

    series, _, regional, flags = integrity._data(tenant, project)
    event_hour = case.event_hour
    basis = "replay: the 24 recorded hours after the event"
    if case.kind == "fire_verification":
        _, state, district = case.station_id.split(":", 2)
        outcome = outcome_fire_verification(fires._rows(project), state, district, event_hour.year)
        basis = "burn scars in the following season"
    elif case.kind == "local_event":
        outcome = outcome_local_event(series.get(case.station_id, {}), flags.get(case.station_id, {}), regional,
                                      event_hour, hotspots.STATION_MIN_EXCESS, hotspots.STATION_ROBUST_Z,
                                      hotspots.STATION_MIN_VALUE)
    elif case.kind == "monitor_fault":
        outcome = outcome_monitor_fault(series.get(case.station_id, {}), flags.get(case.station_id, {}), event_hour)
    else:
        outcome = outcome_regional(regional, event_hour, integrity.SEVERE_MEDIAN)

    photo_desc, photo_hash = None, None
    if photo and case.kind in ("local_event", "monitor_fault"):     # other kinds never read one; save the quota
        photo_hash = hashlib.sha256(photo).hexdigest()
        photo_desc = closure_mod.examine(photo, mime_type or "image/jpeg", case.title).model_dump()

    # A demo reviewer is not standing at the site, so the UI can offer the case's own
    # coordinates instead of the device's. That is recorded as `demo_case_location` in
    # the closure and shown in the audit trail, so it can never pass for a field visit.
    if location_source not in ("device", "demo_case_location"):
        raise ValueError(f"unknown location_source {location_source!r}")
    if location_source == "demo_case_location":
        lat, lon = case.lat, case.lon
    distance = None
    if lat is not None and lon is not None and case.lat is not None:
        distance = round(_haversine_km((lat, lon), (case.lat, case.lon)), 2)

    result, reasons = decide_closure(case.kind, outcome, photo_desc, distance, note)
    detail = {"result": result, "reasons": reasons, "outcome": outcome.verdict, "outcome_summary": outcome.summary,
              "outcome_hours": outcome.hours, "photo": photo_desc, "photo_sha256": photo_hash,
              "upload_distance_km": distance, "location_source": location_source, "note": note,
              "outcome_basis": basis}

    if result == "rejected":
        _log(client, project, tenant, case_id, actor, "closure_rejected", "; ".join(reasons), detail)
        return {"case_id": case_id, "status": case.status, **detail}

    client.query(
        f"""UPDATE `{project}.vayusetu_{tenant}.cases`
            SET status = @status, closure = PARSE_JSON(@closure), closed_at = CURRENT_TIMESTAMP(), closed_by = @actor
            WHERE case_id = @id""",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("status", "STRING", result),
            bigquery.ScalarQueryParameter("closure", "STRING", json.dumps(detail, default=str)),
            bigquery.ScalarQueryParameter("actor", "STRING", actor),
            bigquery.ScalarQueryParameter("id", "STRING", case_id)]),
    ).result()
    log_note = "; ".join(reasons)
    if location_source == "demo_case_location":
        log_note += " [location: demo override, not a field visit]"
    _log(client, project, tenant, case_id, actor, result, log_note, detail)
    return {"case_id": case_id, "status": result, **detail}


# ---------------------------------------------------------------------- demo

def demo() -> None:
    t0 = datetime(2025, 10, 30, 8, tzinfo=timezone.utc)
    H = lambda k: t0 + timedelta(hours=k)

    # Routing from the monitor's own name.
    assert parse_monitor_name("NSIT Dwarka, Delhi - CPCB") == ("NSIT Dwarka, Delhi", "Delhi", "CPCB")
    assert route("local_event", "NSIT Dwarka, Delhi - CPCB")["owner"] == MUNICIPAL["Delhi"]
    assert route("monitor_fault", "Arya Nagar, Bahadurgarh - HSPCB")["owner"] == OPERATORS["HSPCB"]
    assert route("local_event", "Sector - 62, Noida, UP - IMD")["owner"] == MUNICIPAL["Noida"]
    for name in list(OPERATORS.values()) + list(MUNICIPAL.values()) + list(ACTORS.values()) + [ESCALATION]:
        assert name.startswith("Demo:") and "@" not in name, name       # R6

    regional = {H(k): (120.0, 20.0) for k in range(-2, 30)}
    subsided = {H(k): (600.0 if k <= 2 else 130.0 + k) for k in range(-2, 30)}
    still_up = {H(k): 600.0 + k for k in range(-2, 30)}
    o_ok = outcome_local_event(subsided, {}, regional, t0, 50, 3.5, 90)
    o_bad = outcome_local_event(still_up, {}, regional, t0, 50, 3.5, 90)
    o_dark = outcome_local_event({}, {}, regional, t0, 50, 3.5, 90)
    assert (o_ok.verdict, o_bad.verdict, o_dark.verdict) == ("resolved", "persisting", "unknown"), (o_ok, o_bad, o_dark)

    good_photo = {"is_genuine_site_photo": True, "active_sources_visible": [], "remediation_visible": ["fire_extinguished"],
                  "shows_monitoring_equipment": False}
    smoky = dict(good_photo, active_sources_visible=["open_burning"])
    screenshot = {"is_genuine_site_photo": False, "rejection_reason": "screenshot_or_graphic",
                  "active_sources_visible": [], "remediation_visible": [], "shows_monitoring_equipment": False}

    assert decide_closure("local_event", o_ok, good_photo, 0.3, "")[0] == "closed_verified"
    assert decide_closure("local_event", o_bad, good_photo, 0.3, "")[0] == "rejected", "measurements override a clean photo"
    assert decide_closure("local_event", o_ok, smoky, 0.3, "")[0] == "rejected", "a visible source blocks closure"
    assert decide_closure("local_event", o_ok, screenshot, 0.3, "")[0] == "rejected"
    assert decide_closure("local_event", o_ok, good_photo, 4.2, "")[0] == "rejected", "uploaded from elsewhere"
    assert decide_closure("local_event", o_ok, None, 0.3, "")[0] == "rejected"
    assert decide_closure("local_event", o_dark, good_photo, 0.3, "")[0] == "closed_unverified", "no data is not proof"

    faulty = {H(k): v for k, v in enumerate([0.0, 700, 1, 800, 0, 900] * 4 + [0.0] * 6)}
    fflags = integrity.flag_series(faulty, {h: (250.0, 30.0) for h in faulty})
    assert outcome_monitor_fault(faulty, fflags, t0).verdict == "persisting"
    assert decide_closure("monitor_fault", outcome_monitor_fault(faulty, fflags, t0),
                          dict(good_photo, shows_monitoring_equipment=True), 0.1, "")[0] == "rejected", \
        "a technician's photo cannot close a monitor that is still broken"

    # Cross-state notice: routed to the source state's board, closable only unverified until a later season exists.
    assert route("fire_verification", "Punjab")["owner"] == STATE_BOARD["Punjab"]
    def lr(s, b, det):
        return {"state": "Punjab", "district": "Sangrur", "season": s, "burned_km2": b, "day_detections": det, "night_detections": 0}
    base = [lr(2020, 1000, 4000), lr(2021, 1000, 4000), lr(2025, 1000, 50)]
    assert outcome_fire_verification(base, "Punjab", "Sangrur", 2025).verdict == "unknown"
    assert outcome_fire_verification(base + [lr(2026, 900, 60)], "Punjab", "Sangrur", 2025).verdict == "persisting"
    assert outcome_fire_verification(base + [lr(2026, 900, 2400)], "Punjab", "Sangrur", 2025).verdict == "resolved"
    unknown = outcome_fire_verification(base, "Punjab", "Sangrur", 2025)
    assert decide_closure("fire_verification", unknown, None, None, "short")[0] == "rejected"
    assert decide_closure("fire_verification", unknown, None, None, "Night patrols in 40 villages, 212 challans")[0] == "closed_unverified"

    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    assert effective_status("open", now - timedelta(hours=1), now)["overdue"]
    assert not effective_status("closed_verified", now - timedelta(hours=1), now)["overdue"]
    assert effective_status("in_progress", now + timedelta(hours=5), now)["hours_left"] == 5.0
    print("[OK] routing by monitor name; closure refused on persisting measurements, visible source, "
          "screenshot, distant upload or missing photo; unverified when there is no data; overdue on read")

    import pathlib
    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    series, meta, reg, flags = integrity._data("ncr", None)
    dwarka = next(s for s, m in meta.items() if m["name"].startswith("NSIT Dwarka"))
    real = outcome_local_event(series[dwarka], flags[dwarka], reg, t0,
                               hotspots.STATION_MIN_EXCESS, hotspots.STATION_ROBUST_Z, hotspots.STATION_MIN_VALUE)
    print(f"\nNSIT Dwarka after 30 Oct 08:00 UTC: {real.verdict} — {real.summary}")
    arya = next(s for s, m in meta.items() if m["name"].startswith("Arya Nagar"))
    arya_out = outcome_monitor_fault(series[arya], flags[arya], datetime(2025, 11, 16, 6, tzinfo=timezone.utc))
    print(f"Arya Nagar monitor after 16 Nov 06:00 UTC: {arya_out.verdict} — {arya_out.summary}")
    sev = outcome_regional(reg, datetime(2025, 11, 11, 20, tzinfo=timezone.utc), integrity.SEVERE_MEDIAN)
    print(f"Region after 12 Nov 01:30 IST: {sev.verdict} — {sev.summary}")

    cands = candidates_for_hour("2025-10-30 08:00:00")
    print(f"\nCases 30 Oct 08:00 UTC would open: {len(cands)}")
    for c in cands:
        print(f"  {c['kind']:17s} {c['severity']:9s} → {c['owner']}  | {c['title'][:60]}")
    assert any(c["kind"] == "local_event" and c["location_name"].startswith("NSIT Dwarka") and c["station_id"] for c in cands)

    notices = fire_candidates()
    print(f"\nFire verification notices the ledger justifies: {len(notices)}")
    for c in notices:
        print(f"  → {c['owner']}  | {c['title']}")
    assert any(c["location_name"] == "Sangrur, Punjab" for c in notices)
    assert not any(c["location_name"].startswith("Amritsar") for c in notices), "most alerts, but they track its burning"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
