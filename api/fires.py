"""
api/fires.py — the farm fire ledger: where fire counts undercount the burning.

Reads `vayusetu_shared.fire_ledger` (built by `ingestion/fire_ledger.py`: burned area from
MODIS MCD64A1 against VIIRS daytime detections, per district per season) and turns it into
what an enforcement officer needs: which districts burn far more land per satellite alert
than they used to, and how differently districts rank by burned land than by alert counts.

The comparison is each district against its own 2020-21 seasons, not an absolute hectare
figure: both products have known biases (500 m pixels, overpass timing), and a ratio
against the same district's own past cancels most of what does not change year to year.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Optional

BASELINE_SEASONS = (2020, 2021)
# Below these, a ratio is noise: a district with 12 alerts can swing 5× on one field.
MIN_BASELINE_DETECTIONS = 50
MIN_BURNED_KM2 = 25.0
# A district warrants a verification notice to its state board when its burning is both
# large and far out of step with its own alert count. 2025: nine districts, eight in Punjab.
NOTICE_MIN_FACTOR = 8.0
NOTICE_MIN_KM2 = 200.0


def _ratio(burned: float, det: int) -> Optional[float]:
    return burned / det if det else None


def build_ledger(rows: List[dict], season: Optional[int] = None) -> Dict:
    """Pure: ledger rows -> state trend and district table for one season (default latest)."""
    seasons = sorted({r["season"] for r in rows})
    season = season or seasons[-1]

    trend: Dict[str, List[dict]] = {}
    for state in sorted({r["state"] for r in rows}):
        for s in seasons:
            sub = [r for r in rows if r["state"] == state and r["season"] == s]
            burned = sum(r["burned_km2"] for r in sub)
            day = sum(r["day_detections"] for r in sub)
            trend.setdefault(state, []).append({
                "season": s, "burned_km2": round(burned, 1), "day_detections": day,
                "night_detections": sum(r["night_detections"] for r in sub),
                "km2_per_detection": round(_ratio(burned, day), 2) if day else None,
            })

    districts = []
    for (state, district) in sorted({(r["state"], r["district"]) for r in rows}):
        mine = {r["season"]: r for r in rows if r["state"] == state and r["district"] == district}
        now = mine.get(season)
        if not now:
            continue
        base_b = sum(mine[s]["burned_km2"] for s in BASELINE_SEASONS if s in mine)
        base_d = sum(mine[s]["day_detections"] for s in BASELINE_SEASONS if s in mine)
        base = _ratio(base_b, base_d) if base_d >= MIN_BASELINE_DETECTIONS else None
        cur = _ratio(now["burned_km2"], now["day_detections"])
        comparable = base is not None and now["burned_km2"] >= MIN_BURNED_KM2 and now["day_detections"] > 0
        districts.append({
            "state": state, "district": district,
            "burned_km2": round(now["burned_km2"], 1),
            "day_detections": now["day_detections"],
            "night_detections": now["night_detections"],
            "km2_per_detection": round(cur, 2) if cur is not None else None,
            "baseline_km2_per_detection": round(base, 2) if base is not None else None,
            "undercount_factor": round(cur / base, 1) if comparable else None,
            # Alerts this much burning would have raised at the district's own 2020-21 rate.
            "alerts_expected_at_baseline": round(now["burned_km2"] / base) if comparable else None,
        })

    by_det = sorted(districts, key=lambda d: -d["day_detections"])
    by_area = sorted(districts, key=lambda d: -d["burned_km2"])
    for i, d in enumerate(by_det):
        d["rank_by_detections"] = i + 1
    for i, d in enumerate(by_area):
        d["rank_by_burned_area"] = i + 1
        d["warrants_notice"] = bool(d["undercount_factor"] and d["undercount_factor"] >= NOTICE_MIN_FACTOR
                                    and d["burned_km2"] >= NOTICE_MIN_KM2)

    return {
        "season": season, "seasons": seasons, "baseline_seasons": list(BASELINE_SEASONS),
        "notice_rule": {"min_undercount_factor": NOTICE_MIN_FACTOR, "min_burned_km2": NOTICE_MIN_KM2},
        "trend": trend, "districts": by_area,
        "sources": {
            "burned_area": "NASA MODIS MCD64A1 burn scars, 500 m, 1 Oct - 30 Nov (Google Earth Engine)",
            "detections": "NASA FIRMS VIIRS S-NPP active fires, science archive, 1 Oct - 30 Nov",
            "boundaries": "FAO GAUL 2015 districts",
        },
        "caveats": [
            "Relative indicators, not hectares: 500 m burn scars misestimate small fields, and "
            "statewide totals sit below Sentinel-2 estimates.",
            "The burn-scar product is partly seeded by the same midday satellites, so fires set "
            "after the overpass can be under-mapped too; the true gap is likely larger.",
            "District boundaries are from 2015: Sangrur includes today's Barnala, and newer "
            "districts are folded into their parents.",
            "Not used for the smoke attribution on this site, which still relies on detections "
            "and so undercounts recent seasons' burning.",
        ],
    }


@lru_cache(maxsize=2)
def _rows(project: str) -> tuple:
    from google.cloud import bigquery

    q = f"""SELECT state, district, season, burned_km2, day_detections, night_detections
            FROM `{project}.vayusetu_shared.fire_ledger`"""
    return tuple(dict(r) for r in bigquery.Client(project=project).query(q).result())


def ledger(season: Optional[int] = None, project: Optional[str] = None) -> Dict:
    rows = list(_rows(project or os.environ["GCP_PROJECT_ID"]))
    if not rows:
        raise LookupError("fire ledger is empty; run python -m ingestion.fire_ledger")
    if season and season not in {r["season"] for r in rows}:
        raise LookupError(f"no ledger for season {season}")
    return build_ledger(rows, season)


def demo() -> None:
    def row(d, s, b, day, st="Punjab"):
        return {"state": st, "district": d, "season": s, "burned_km2": b, "day_detections": day, "night_detections": 1}

    rows = [
        row("Hidden", 2020, 1000, 4000), row("Hidden", 2021, 1000, 4000), row("Hidden", 2025, 800, 160),
        row("Counted", 2020, 300, 1000), row("Counted", 2021, 300, 1000), row("Counted", 2025, 280, 900),
        row("Tiny", 2020, 5, 10), row("Tiny", 2021, 5, 10), row("Tiny", 2025, 30, 2),
    ]
    out = build_ledger(rows)
    d = {x["district"]: x for x in out["districts"]}
    assert out["season"] == 2025
    assert d["Hidden"]["undercount_factor"] == 20.0, d["Hidden"]        # 5.0 vs 0.25 km²/alert
    assert d["Hidden"]["alerts_expected_at_baseline"] == 3200
    assert d["Counted"]["rank_by_detections"] == 1 and d["Counted"]["rank_by_burned_area"] == 2
    assert d["Hidden"]["rank_by_detections"] == 2 and d["Hidden"]["rank_by_burned_area"] == 1
    assert d["Tiny"]["undercount_factor"] is None                        # too few baseline alerts
    assert d["Hidden"]["warrants_notice"] and not d["Counted"]["warrants_notice"] and not d["Tiny"]["warrants_notice"]
    assert out["trend"]["Punjab"][-1]["day_detections"] == 1062
    print("[OK] fire ledger: ratio against own baseline, ranks disagree, small districts withheld")


if __name__ == "__main__":
    demo()
