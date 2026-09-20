"""
api/national.py — the national monitor ledger, read for the desk.

`ingestion/monitor_ledger.py` runs the integrity checks over every CPCB monitor OpenAQ
carries and writes one row per monitor. This reads them back as a state table: how many
monitors a state runs, how many of them a system should refuse to act on, and the worst
offenders with the raw readings that convict them.

It is the same gate that caught our own headline hotspot, applied to the whole country —
the part of this project that is useful to a state board that will never look at Delhi.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

UNTRUSTED = ("faulty", "offline")
WORST_PER_STATE = 3


@lru_cache(maxsize=2)
def _rows(project: str) -> tuple:
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    q = f"SELECT * FROM `{project}.vayusetu_shared.monitor_ledger`"
    try:
        return tuple(dict(r) for r in bigquery.Client(project=project).query(q).result())
    except NotFound:                      # the batch job has never run in this project
        return ()


def build(rows: List[dict]) -> Dict[str, Any]:
    """Pure: ledger rows -> national totals and a state table, worst states first."""
    states: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        s = states.setdefault(r["state"], {
            "state": r["state"], "monitors": 0, "faulty": 0, "offline": 0, "suspect": 0,
            "healthy": 0, "peer_hours": r.get("state_peer_hours") or 0, "worst": [],
        })
        s["monitors"] += 1
        s[r["status"]] += 1
        if r["status"] in UNTRUSTED or r["status"] == "suspect":
            s["worst"].append({
                "station_id": r["station_id"], "name": r["name"], "status": r["status"],
                "uptime": r["uptime"], "fault_rate": r["fault_rate"],
                "flag_counts": {k: r[f"{k}_hours"] for k in ("stuck", "dead_zero", "spike", "low_in_episode")},
                "example": json.loads(r["example"]) if r.get("example") else None,
            })

    for s in states.values():
        s["untrusted"] = s["faulty"] + s["offline"]
        s["untrusted_share"] = round(s["untrusted"] / s["monitors"], 3)
        # A state with too few monitors reporting in an hour has no median to compare
        # against, so two of the four checks never fire there. Say so rather than
        # reporting a clean network.
        s["peer_group"] = s["peer_hours"] > 0
        s["worst"] = sorted(s["worst"], key=lambda m: (m["status"] != "faulty", -m["fault_rate"], m["uptime"]))[:WORST_PER_STATE]

    table = sorted(states.values(), key=lambda s: (-s["untrusted"], -s["untrusted_share"]))
    total = len(rows)
    untrusted = sum(s["untrusted"] for s in states.values())
    return {
        "window": [rows[0]["window_start"].isoformat() if hasattr(rows[0]["window_start"], "isoformat")
                   else rows[0]["window_start"],
                   rows[0]["window_end"].isoformat() if hasattr(rows[0]["window_end"], "isoformat")
                   else rows[0]["window_end"]],
        "summary": {
            "monitors": total, "states": len(states), "untrusted": untrusted,
            "untrusted_share": round(untrusted / total, 3) if total else 0.0,
            "faulty": sum(s["faulty"] for s in states.values()),
            "offline": sum(s["offline"] for s in states.values()),
            "suspect": sum(s["suspect"] for s in states.values()),
            "healthy": sum(s["healthy"] for s in states.values()),
            "states_without_peer_group": sum(1 for s in states.values() if not s["peer_group"]),
        },
        "states": table,
        "source": "CPCB monitors via OpenAQ, hourly PM2.5; checks in api/integrity.py, ledger in ingestion/monitor_ledger.py",
        "caveats": [
            "Coverage is what OpenAQ republishes from CPCB, not the full CAAQMS list.",
            "A state with too few monitors reporting in an hour has no peer median, so the "
            "dead-zero and low-in-episode checks cannot fire there; only stuck values and "
            "spikes are caught.",
            "The checks catch faults, not bias: smooth calibration drift or a badly sited "
            "monitor still reads plausibly.",
            "One replay window (25 October - 20 November 2025). A monitor healthy then may "
            "be dark now.",
        ],
    }


def national(project: Optional[str] = None) -> Dict[str, Any]:
    rows = list(_rows(project or os.environ["GCP_PROJECT_ID"]))
    if not rows:
        raise LookupError("monitor ledger is empty; run python -m ingestion.monitor_ledger")
    return build(rows)


def demo() -> None:
    def row(state, sid, status, peers=600, **kw):
        base = {"station_id": sid, "name": sid, "state": state, "status": status, "uptime": 0.9,
                "fault_rate": 0.0, "state_peer_hours": peers, "example": None,
                "stuck_hours": 0, "dead_zero_hours": 0, "spike_hours": 0, "low_in_episode_hours": 0,
                "window_start": "2025-10-25T00:00:00+00:00", "window_end": "2025-11-20T23:00:00+00:00"}
        return {**base, **kw}

    rows = [row("Delhi", "a", "faulty", fault_rate=0.4), row("Delhi", "b", "offline", uptime=0.2),
            row("Delhi", "c", "healthy"), row("Kerala", "d", "healthy", peers=0),
            row("Kerala", "e", "suspect", peers=0), row("Punjab", "f", "faulty", fault_rate=0.1)]
    out = build(rows)
    d = {s["state"]: s for s in out["states"]}
    assert out["states"][0]["state"] == "Delhi", out["states"]
    assert d["Delhi"]["untrusted"] == 2 and d["Delhi"]["untrusted_share"] == 0.667
    assert d["Kerala"]["peer_group"] is False and d["Punjab"]["peer_group"] is True
    assert d["Delhi"]["worst"][0]["station_id"] == "a", "faulty before offline"
    assert out["summary"]["untrusted"] == 3 and out["summary"]["states_without_peer_group"] == 1
    print("[OK] national ledger: worst states first, thin states marked as having no peer group")


if __name__ == "__main__":
    demo()
