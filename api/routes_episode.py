"""
api/routes_episode.py — The attribution-first API.

Serves what the evidence actually supports: what happened, why it happened, and who
should act. Estimation and forecasting were falsified against simple baselines
(TODO.md 2026-09-08b/c), so there is deliberately no endpoint here that serves a
predicted hotspot map.

Briefs are cached by (tenant, hour). Gemini generation is the slow and rate-limited
step, the inputs for a past hour never change, and a demo hits the same episode
repeatedly — so regenerating would burn quota to produce the same paragraph.

The hotspot routes serve `api/hotspots.py`, which is measurement only: a monitor
standing above the robust median of the monitors around it. They replaced two
endpoints that ranked cells by a Gaussian plume invented in Python.

Cases are split into `preview` (a GET that writes nothing) and `raise` (a POST).
Loading a page must never be able to assign work to anyone — the agencies here are all
demo accounts, but the shape of the code is what keeps that true after the next change.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile

from api import evidence as evidence_mod
from api import alerts as alerts_mod
from api import cases as cases_mod
from api import fires as fires_mod
from api import hotspots as hotspots_mod
from api import integrity as integrity_mod
from api import live as live_mod
from api import national as national_mod

logger = logging.getLogger("vayusetu.api.episode")

def _check_tenant(tenant: str = Path(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")) -> None:
    """
    The tenant key is interpolated into BigQuery dataset names (vayusetu_{tenant})
    on every route below, so it is a trust boundary. Anything that could not be a
    dataset suffix is rejected before it reaches a query.
    """


router = APIRouter(prefix="/api/v1", tags=["episode"], dependencies=[Depends(_check_tenant)])

# (tenant, iso-hour) -> {"evidence":..., "brief":...}
_BRIEF_CACHE: Dict[tuple, Dict[str, Any]] = {}

# Endpoints are sync, so FastAPI runs them in a threadpool: without this, a page load
# that fires three requests, or two judges refreshing at once, each miss the cache and
# each start their own Gemini call for the identical hour. Gemini is capped at 500
# requests/day, so that is the one resource worth serialising.
# ponytail: one global lock, not per-key — generation is ~10s and the demo is a
# handful of hours; make it per-key if concurrent distinct episodes ever matter.
_GENERATION_LOCK = threading.Lock()


def _parse_ts(ts: Optional[str]) -> datetime:
    if not ts:
        raise HTTPException(400, "ts is required, e.g. ts=2025-11-11T20:00:00Z")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"unparseable ts: {ts!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


@router.get("/{tenant}/episode", summary="Measured evidence plus a verified attribution brief")
def get_episode(
    tenant: str,
    ts: str = Query(..., description="UTC hour, ISO 8601"),
    explain: bool = Query(True, description="Generate the Gemini brief"),
) -> Dict[str, Any]:
    """
    The product's core call. Returns the measured evidence for one hour and, when
    `explain` is set, a Gemini brief that reasons over it.

    Every number in `evidence` is observed. Every claim in `brief` is checked
    against those numbers before it is returned (AGENTS.md R5).
    """
    at = _parse_ts(ts)
    key = (tenant, at.isoformat())

    if key in _BRIEF_CACHE:
        cached = dict(_BRIEF_CACHE[key])
        cached["cached"] = True
        return cached

    with _GENERATION_LOCK:
        # Re-check: whoever held the lock may have just generated this exact hour.
        if key in _BRIEF_CACHE:
            cached = dict(_BRIEF_CACHE[key])
            cached["cached"] = True
            return cached
        return _build_episode(tenant, at, key, explain)


def _build_episode(tenant: str, at: datetime, key: tuple, explain: bool) -> Dict[str, Any]:
    """Assemble and explain one episode. Callers hold _GENERATION_LOCK."""
    try:
        ev = evidence_mod.assemble(at, tenant=tenant)
    except ValueError as e:
        raise HTTPException(404, str(e))

    out: Dict[str, Any] = {"evidence": ev.to_dict(), "cached": False}

    if explain:
        from api.gemini import brief as brief_mod
        try:
            out["brief"] = brief_mod.generate(ev.to_dict())
        except Exception as e:
            # Surface the failure rather than substituting prose. A brief that
            # silently degrades is indistinguishable from a real one.
            logger.warning("brief generation failed: %s", e)
            out["brief"] = None
            out["brief_error"] = str(e)

    if out.get("brief"):
        _BRIEF_CACHE[key] = out
    return out


@router.get("/{tenant}/event", summary="The episode in the open interchange format")
def get_event(
    tenant: str,
    ts: str = Query(...),
) -> Dict[str, Any]:
    """
    The same episode as `/episode`, shaped as `spec/hotspot-event.schema.json` v2.0.0
    so another city, a state dashboard or a third-party app can consume it without
    knowing anything about how we produced it.

    This is the Digital Public Good surface: observation, measured drivers, and the
    reasoning that connects them.
    """
    ep = get_episode(tenant, ts, explain=True)
    return evidence_mod.to_event(ep["evidence"], ep.get("brief"))


@router.get("/{tenant}/timeline", summary="Daily PM2.5 against its physical drivers")
def get_timeline(
    tenant: str,
    # Validated, because both are interpolated into the SQL below.
    date_from: str = Query("2025-10-25", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query("2025-11-21", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> Dict[str, Any]:
    """
    The chart behind the product's central claim: fires upwind and a collapsing
    boundary layer track PM2.5. On these India-time days r = +0.58 and -0.48; the
    UTC-day analysis in TODO.md gave +0.55 and -0.42, the same finding grouped
    differently. Recompute the console's note if the window or grouping changes.
    """
    import os
    from google.cloud import bigquery

    project = os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)
    # Indian calendar days, so the bar a reader picks and the date shown for it
    # agree. Grouped by UTC date, the 01:30 IST hero hour sat on the previous
    # day's bar.
    rows = list(client.query(f"""
        SELECT DATE(ts, 'Asia/Kolkata') AS d,
               ROUND(AVG(target_pm25), 1) AS pm25,
               ROUND(MAX(target_pm25), 1) AS peak_pm25,
               ROUND(AVG(fire_count_upwind_100km_48h), 1) AS upwind_fires,
               ROUND(AVG(blh), 0) AS blh,
               COUNT(DISTINCT station_id) AS n_stations
        FROM `{project}.vayusetu_{tenant}.features_training`
        WHERE ts >= TIMESTAMP('{date_from}', 'Asia/Kolkata') AND ts < TIMESTAMP('{date_to}', 'Asia/Kolkata')
        GROUP BY d ORDER BY d
    """).result())

    return {
        "tenant": tenant,
        "window": [date_from, date_to],
        "series": [
            {
                "date": str(r.d),
                "pm25": float(r.pm25) if r.pm25 else None,
                "peak_pm25": float(r.peak_pm25) if r.peak_pm25 else None,
                "upwind_fires": float(r.upwind_fires or 0),
                "blh": float(r.blh) if r.blh else None,
                "aqi_band": evidence_mod.aqi_band(float(r.pm25)) if r.pm25 else None,
                "n_stations": int(r.n_stations),
            }
            for r in rows
        ],
    }


@router.get("/{tenant}/hotspots", summary="Localities standing above the regional field")
def get_hotspots(
    tenant: str,
    ts: str = Query(...),
) -> Dict[str, Any]:
    """
    Hyper-local events for one hour.

    Returns the whole field of reporting monitors, not only the flagged ones: an
    outlier is only meaningful next to what it is an outlier from. An empty
    `hotspots` list during a regional episode is the correct answer.
    """
    at = _parse_ts(ts)
    return hotspots_mod.station_hotspots(at.strftime("%Y-%m-%d %H:00:00"), tenant)


@router.get("/{tenant}/hotspots/top", summary="The worst local events in the window, ranked")
def get_top_events(
    tenant: str,
    limit: int = Query(12, ge=1, le=50),
) -> Dict[str, Any]:
    """Where the worst hyper-local events have been, so the console can jump to one."""
    return hotspots_mod.top_events(tenant, limit)


@router.get("/{tenant}/monitors/health", summary="Which monitors can be trusted, and which need a technician")
def get_monitor_health(
    tenant: str,
    ts: Optional[str] = Query(None, description="End of the window, UTC hour; default: end of the data"),
    days: int = Query(7, ge=1, le=60),
) -> Dict[str, Any]:
    """
    Every monitor's status over the window — faulty, offline, suspect, healthy — with the
    flag counts and one stretch of raw readings as evidence, so a claim that a
    government monitor is broken can be checked by eye before anyone acts on it.
    """
    at = _parse_ts(ts) if ts else None
    return integrity_mod.network_health(tenant, at=at, days=days)


@router.get("/{tenant}/fires/ledger", summary="Districts where fire alerts undercount the burning")
def get_fire_ledger(
    tenant: str,
    season: Optional[int] = Query(None, ge=2020, le=2100, description="Default: latest season"),
) -> Dict[str, Any]:
    """
    Burned land (MODIS burn scars) against satellite fire alerts per Punjab and Haryana
    district, each compared with its own 2020-21 seasons. Shared across tenants: the fields
    burn upwind of every city in the plains.
    """
    try:
        return fires_mod.ledger(season)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tenant}/live/now", summary="Google's modelled air right now, next to our latest measurement")
def get_live_now(tenant: str) -> Dict[str, Any]:
    """
    The honest live view. Our own station feed is stalled, so this puts Google's modelled
    current conditions beside our most recent measured reading and says how old ours is.
    The modelled number is never used by hotspots, cases or the brief.
    """
    try:
        return live_mod.now(tenant)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except live_mod.AirQualityUnavailable as e:
        raise HTTPException(status_code=503, detail=f"Google's air quality model is unavailable: {e}")


@router.get("/{tenant}/national/monitors", summary="Can India's air monitors be trusted? State by state")
def get_national_monitors(tenant: str) -> Dict[str, Any]:
    """
    The same four integrity checks, run over every CPCB monitor OpenAQ carries for the
    replay window, aggregated by state. Shared across tenants: a broken monitor is the
    state board's work wherever the reader sits.
    """
    try:
        return national_mod.national()
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tenant}/cases", summary="The case queue: who owns what, by when, and was it really fixed")
def get_cases(tenant: str) -> Dict[str, Any]:
    """Every case with its owner, deadline, overdue state and audit log. Agencies are demo accounts (R6)."""
    return cases_mod.list_cases(tenant)


@router.get("/{tenant}/cases/preview", summary="What this hour's measurements justify, without opening anything")
def preview_cases(tenant: str, ts: str = Query(...)) -> Dict[str, Any]:
    """
    Candidate cases for one hour, written nowhere.

    Separate from `raise` on purpose: loading a page must never be able to assign work
    to anyone, even when every agency is a demo account. The habit is the point — this
    code would otherwise be one wiring change away from paging a real official on a
    page view.
    """
    at = _parse_ts(ts).strftime("%Y-%m-%d %H:00:00")
    return {"ts": at, "candidates": cases_mod.candidates_for_hour(at, tenant),
            "no_trigger_reason": alerts_mod.evaluate(at, tenant)["no_trigger_reason"]}


@router.post("/{tenant}/cases/raise", summary="Open cases for one hour")
def raise_cases(tenant: str, ts: str = Query(...)) -> Dict[str, Any]:
    """Deliberate and idempotent: open work is never duplicated."""
    return cases_mod.raise_for_hour(_parse_ts(ts).strftime("%Y-%m-%d %H:00:00"), tenant)


@router.post("/{tenant}/cases/raise-fire-notices", summary="Open verification notices for districts the fire ledger flags")
def raise_fire_notices(tenant: str) -> Dict[str, Any]:
    """
    One notice per flagged district, to its state board, copied to CAQM; open work is not
    duplicated. Raised from the seasonal ledger, not from an hour: a daily Punjab-to-Delhi
    link was tested and is too weak to name a state as the cause of a given day.
    """
    try:
        return cases_mod.raise_fire_notices(tenant)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


_CASE_ID = r"^case_[0-9a-f]{16}$"


@router.post("/{tenant}/cases/{case_id}/acknowledge", summary="Take ownership of a case")
def acknowledge_case(
    tenant: str,
    case_id: str = Path(..., pattern=_CASE_ID),
    actor: str = Query(..., description="A demo account key; nothing else exists"),
    note: str = Query("", max_length=500),
) -> Dict[str, Any]:
    try:
        return cases_mod.acknowledge(case_id, actor, note, tenant)
    except KeyError:
        raise HTTPException(404, f"no case {case_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{tenant}/cases/{case_id}/close", summary="Submit closure evidence; closes only if it checks out")
async def close_case(
    tenant: str,
    case_id: str = Path(..., pattern=_CASE_ID),
    actor: str = Form(...),
    note: str = Form("", max_length=1000),
    lat: Optional[float] = Form(None, ge=-90, le=90),
    lon: Optional[float] = Form(None, ge=-180, le=180),
    location_source: str = Form("device", pattern="^(device|demo_case_location)$"),
    photo: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """
    A refused closure returns 200 with `result: rejected` and the reasons: being told
    why is the normal path, not an error. 503 means the photo could not be examined, and
    in that case nothing is closed.
    """
    data, mime = None, None
    if photo is not None:
        data = await photo.read()
        mime = photo.content_type or "image/jpeg"
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "photo larger than 10 MB")
        if not mime.startswith("image/"):
            raise HTTPException(415, "the closure photo must be an image")
    from api.gemini.closure import ClosureCheckUnavailable
    try:
        return cases_mod.submit_closure(case_id, actor, note, data, mime, lat, lon, tenant,
                                        location_source=location_source)
    except KeyError:
        raise HTTPException(404, f"no case {case_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ClosureCheckUnavailable as e:
        raise HTTPException(503, f"The photo could not be checked right now, so nothing was closed: {e}")


@router.get("/{tenant}/map", summary="Stations, fires and wind for one hour")
def get_map(
    tenant: str,
    ts: str = Query(...),
) -> Dict[str, Any]:
    """Everything the map draws for a single hour. All observed, nothing predicted."""
    import os
    from google.cloud import bigquery

    at = _parse_ts(ts)
    ts_str = at.strftime("%Y-%m-%d %H:00:00")
    project = os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    stations = [
        {
            "station_id": r.station_id,
            "name": r.station_name,
            "lat": float(r.lat),
            "lon": float(r.lon),
            "pm25": round(float(r.pm25), 1),
            "aqi_band": evidence_mod.aqi_band(float(r.pm25)),
        }
        for r in client.query(f"""
            SELECT station_id, station_name, lat, lon, AVG(value) AS pm25
            FROM `{project}.vayusetu_{tenant}.raw_stations`
            WHERE pollutant = 'pm25' AND value IS NOT NULL
              AND ts = TIMESTAMP('{ts_str}')
            GROUP BY station_id, station_name, lat, lon
        """).result()
    ]

    fires = [
        {"lat": float(r.lat), "lon": float(r.lon), "frp": float(r.frp or 0),
         "acq_ts": str(r.acq_ts), "confidence": r.confidence}
        for r in client.query(f"""
            SELECT lat, lon, frp, acq_ts, confidence
            FROM `{project}.vayusetu_shared.raw_fires`
            WHERE acq_ts > TIMESTAMP_SUB(TIMESTAMP('{ts_str}'), INTERVAL 48 HOUR)
              AND acq_ts <= TIMESTAMP('{ts_str}')
        """).result()
    ]

    # Deliberately no wind or boundary layer here. This used to return AVG(wind_dir)
    # across every cell, which is wrong twice over: an arithmetic mean of bearings is
    # meaningless (350 and 10 average to 180, the opposite direction), and a city
    # average disagrees with the worst-station bearing that actually selected the
    # upwind fires. The console drew its cone from this while the brief cited the
    # other, showing two different winds for one hour. Meteorology has one source:
    # /episode.
    return {
        "tenant": tenant,
        "ts": at.isoformat(),
        "stations": stations,
        "fires": fires,
    }


# (tenant, iso-hour, lang) -> resident bundle. Only successful translations are
# cached, so a transient Translation outage is retried on the next request instead
# of pinning English for the life of the process.
_RESIDENTS_CACHE: Dict[tuple, Dict[str, Any]] = {}


@router.get("/{tenant}/residents", summary="Everything the resident view shows, in one language")
def get_residents(
    tenant: str,
    ts: str = Query(...),
    lang: str = Query("en", description="ISO code: en, hi, pa, bn, mr, ta, te, kn, ml, gu"),
) -> Dict[str, Any]:
    """
    The resident page, ready to show and translated in one batched call.

    Built here rather than in the browser so the plain-language explanation has a
    single implementation, derived from measured evidence and never generated, and
    so every word a resident reads is in their language, not only the advice.
    """
    from api import residents
    from api.gemini import advisory as adv

    if lang not in adv.SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"unsupported language {lang!r}; "
                                 f"supported: {sorted(adv.SUPPORTED_LANGUAGES)}")

    key = (tenant, _parse_ts(ts).isoformat(), lang)
    if key in _RESIDENTS_CACHE:
        return _RESIDENTS_CACHE[key]

    ep = get_episode(tenant, ts, explain=True)
    out = residents.bundle(ep["evidence"], ep.get("brief"), lang)
    if out["translated"] or lang == "en":
        _RESIDENTS_CACHE[key] = out
    return out


@lru_cache(maxsize=256)
def _speech(text: str, lang: str) -> Optional[str]:
    """Base64 MP3 for one sentence. Cached: the advisory for a past hour never changes."""
    from api.gemini import advisory as adv
    return adv._synthesize_speech(text, adv.TTS_LANGUAGE_CODES.get(lang, "en-IN"))


@router.get("/{tenant}/advisory", summary="Public advisory in an Indian language")
def get_advisory(
    tenant: str,
    ts: str = Query(...),
    lang: str = Query("hi", description="ISO code: en, hi, pa, bn, mr, ta, te, kn, ml, gu"),
    audio: bool = Query(False, description="Also return the sentence spoken, as base64 MP3"),
) -> Dict[str, Any]:
    """
    The citizen-facing half. Reuses the cached brief's `public_advisory` so the
    official and the resident are told the same thing about the same hour.

    `audio` exists for people who will not, or cannot, read a screen. It is spoken
    in the language actually returned: if translation failed and we fell back to
    English, the audio is English too, never a Hindi voice reading English.
    """
    ep = get_episode(tenant, ts, explain=True)
    brief = ep.get("brief")
    if not brief:
        raise HTTPException(503, f"no brief available: {ep.get('brief_error')}")

    import os
    from api.gemini import advisory as adv

    if lang not in adv.SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"unsupported language {lang!r}; "
                                 f"supported: {sorted(adv.SUPPORTED_LANGUAGES)}")

    text = brief["public_advisory"]
    out: Dict[str, Any] = {"lang": "en", "text": text, "translated": False}

    if lang != "en":
        try:
            translated = adv._translate_text(text, lang, os.environ["GCP_PROJECT_ID"])
            # Report the truth: if the mock fired, this is English wearing a label,
            # so return the plain English rather than the tagged mock string.
            if not adv.is_mock_translation(translated):
                out = {"lang": lang, "language_name": adv.SUPPORTED_LANGUAGES[lang],
                       "text": translated, "source_text": text, "translated": True}
        except Exception as e:
            # Fall back to English rather than to an untranslated string labelled as
            # translated. A resident acting on the wrong language is a real failure.
            logger.warning("translation to %s failed: %s", lang, e)
            out["error"] = str(e)

    if audio:
        out["audio_base64"] = _speech(out["text"], out["lang"])
        out["audio_content_type"] = "audio/mpeg"

    return out
