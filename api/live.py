"""
api/live.py — what the air is doing right now, and why our own feed cannot tell you.

Everything else in VayuSetu is a replay of 25 October - 20 November 2025, because the
CPCB-to-OpenAQ feed that supplies our monitors is largely stalled: of ~70 NCR monitors,
a handful have reported in the last week. That is a real and reportable fact about the
public data, not a gap to paper over.

Google's Air Quality API is the second opinion. It is a **model** — satellite, dispersion
and station assimilation — so it is current whether or not any one station is reporting,
and it publishes India's own CPCB NAQI index alongside its universal one. This module
asks it for the tenant's centre and puts that next to our own most recent station
reading, with the age of that reading stated plainly.

What it deliberately does not do:

- It never overwrites or fills in a monitor reading. Everything downstream — hotspots,
  cases, the brief — still runs on measured station values only (R4's reasoning applied
  to a model instead of a photo: an unverified number must not become evidence).
- It is not used to claim our pipeline is live. The label on screen says which number is
  measured and which is modelled, and how old ours is.

Authentication is the runtime service account (Application Default Credentials), so no
API key exists in this codebase or its image.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional

logger = logging.getLogger("vayusetu.api.live")

ENDPOINT = "https://airquality.googleapis.com/v1/currentConditions:lookup"
TIMEOUT_S = 10


class AirQualityUnavailable(RuntimeError):
    """Google's model could not be reached. There is no fallback number."""


def _token() -> str:
    from google.auth import default
    from google.auth.transport.requests import Request

    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


def _lookup(lat: float, lon: float, project: str) -> Dict[str, Any]:
    body = json.dumps({
        "location": {"latitude": lat, "longitude": lon},
        "extraComputations": ["LOCAL_AQI", "POLLUTANT_CONCENTRATION", "DOMINANT_POLLUTANT_CONCENTRATION"],
        "languageCode": "en",
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Authorization": f"Bearer {_token()}",
        "x-goog-user-project": project,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode())
    except Exception as e:                                   # network, auth, quota
        raise AirQualityUnavailable(str(e)) from e


@lru_cache(maxsize=32)
def _cached(lat: float, lon: float, project: str, hour: str) -> Dict[str, Any]:
    """One call per location per hour: the model publishes hourly, and calls are billed."""
    return _lookup(lat, lon, project)


def modelled_now(lat: float, lon: float, project: Optional[str] = None) -> Dict[str, Any]:
    project = project or os.environ["GCP_PROJECT_ID"]
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    raw = _cached(round(lat, 3), round(lon, 3), project, hour)

    idx = {i["code"]: i for i in raw.get("indexes", [])}
    pol = {p["code"]: p for p in raw.get("pollutants", [])}
    cpcb = idx.get("ind_cpcb")
    pm25 = pol.get("pm25", {}).get("concentration", {})
    return {
        "at": raw.get("dateTime"),
        "cpcb_aqi": cpcb.get("aqi") if cpcb else None,
        "cpcb_category": cpcb.get("category") if cpcb else None,
        "universal_aqi": idx.get("uaqi", {}).get("aqi"),
        "dominant_pollutant": (cpcb or idx.get("uaqi", {})).get("dominantPollutant"),
        "pm25": round(pm25["value"], 1) if pm25.get("value") is not None else None,
        "pm25_units": pm25.get("units"),
        "pm10": round(pol.get("pm10", {}).get("concentration", {}).get("value", float("nan")), 1)
                if "pm10" in pol else None,
        "source": "Google Air Quality API (modelled)",
    }


def _our_latest(tenant: str, project: str) -> Dict[str, Any]:
    from google.cloud import bigquery

    rows = list(bigquery.Client(project=project).query(f"""
        WITH last AS (
          SELECT MAX(ts) AS ts FROM `{project}.vayusetu_{tenant}.raw_stations`
          WHERE pollutant = 'pm25' AND value IS NOT NULL
        )
        SELECT last.ts AS ts,
               ROUND(APPROX_QUANTILES(value, 2)[OFFSET(1)], 1) AS median_pm25,
               COUNT(DISTINCT station_id) AS monitors
        FROM `{project}.vayusetu_{tenant}.raw_stations` s, last
        WHERE s.pollutant = 'pm25' AND s.value IS NOT NULL AND s.ts = last.ts
        GROUP BY last.ts
    """).result())
    if not rows or rows[0].ts is None:
        return {"at": None, "median_pm25": None, "monitors": 0, "age_hours": None}
    r = rows[0]
    age = (datetime.now(timezone.utc) - r.ts).total_seconds() / 3600
    return {"at": r.ts.isoformat(), "median_pm25": r.median_pm25, "monitors": r.monitors,
            "age_hours": round(age, 1), "source": "CPCB monitors via OpenAQ (measured)"}


def now(tenant: str = "ncr", project: Optional[str] = None) -> Dict[str, Any]:
    """Google's modelled air for the tenant's centre, next to our own latest measurement."""
    import pathlib

    import yaml

    project = project or os.environ["GCP_PROJECT_ID"]
    cfg = yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent / "infra" / "tenants.yaml").read_text())
    b = (cfg.get("tenants") or {}).get(tenant, {}).get("bounds")
    if not b:
        raise LookupError(f"no bounds for tenant {tenant!r}")
    lat = (b["lat_min"] + b["lat_max"]) / 2
    lon = (b["lon_min"] + b["lon_max"]) / 2

    ours = _our_latest(tenant, project)
    model = modelled_now(lat, lon, project)
    stale_days = round(ours["age_hours"] / 24) if ours["age_hours"] is not None else None
    return {
        "tenant": tenant, "at": [lat, lon],
        "modelled": model,
        "measured": ours,
        "note": ("Google's number is modelled and current; ours is measured and "
                 f"{stale_days} days old, because the CPCB-to-OpenAQ feed is stalled. "
                 "Nothing downstream uses the modelled value: hotspots, cases and the "
                 "brief run on measured readings only."),
    }


def demo() -> None:
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    out = now("ncr")
    m, o = out["modelled"], out["measured"]
    print(f"Google, modelled at {m['at']}: CPCB NAQI {m['cpcb_aqi']} ({m['cpcb_category']}), "
          f"PM2.5 {m['pm25']} µg/m³, dominant {m['dominant_pollutant']}")
    print(f"Ours, measured at {o['at']}: median {o['median_pm25']} µg/m³ from {o['monitors']} "
          f"monitors, {o['age_hours']} h old")
    print(out["note"])

    assert m["pm25"] is not None and m["cpcb_aqi"] is not None, m
    assert m["source"].endswith("(modelled)")
    # The model must never be mistaken for one of our readings.
    assert o["source"].endswith("(measured)") and o["at"] != m["at"]
    # Second call inside the same hour must not spend another billed request.
    before = _cached.cache_info().hits
    modelled_now(28.575, 77.2)
    assert _cached.cache_info().hits == before + 1, "hourly cache is not holding"
    print("[OK] modelled and measured reported side by side, one billed call per hour")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
