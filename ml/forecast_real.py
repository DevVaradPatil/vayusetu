"""
ml/forecast_real.py — Model B (72h PM2.5 forecast) on real observations.

Builds the forecast panel from `raw_stations` + `raw_meteorology`, evaluates it
against the two mandatory baselines (persistence and climatology), and reports
per-horizon so degradation with lead time is visible rather than averaged away.

Three things this file is careful about:

1. **Lags respect wall-clock time, not row position.** Stations drop out for hours;
   indexing back N rows would silently pair a reading with one from days earlier and
   call it "lag_1h". Every lag is looked up by timestamp and the sample is dropped
   if the required history is missing.

2. **Temporal split, never random.** Training on later hours and testing on earlier
   ones leaks the future into the past. Train is the earlier fraction of the window.

3. **The perfect-forecast assumption is measured, not hidden.** We only have ERA5
   reanalysis for the target hour, so using it means assuming the weather forecast
   is exactly right — which real operations never get. `use_future_met=False`
   reruns with only meteorology known at issue time, and the difference between the
   two is the honest upper bound on how much of the skill is borrowed from perfect
   weather knowledge.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("vayusetu.ml.forecast_real")

LAG_HOURS = [1, 2, 3, 6, 12, 24, 48, 72]
HORIZONS = [6, 24, 48, 72]

MET_FIELDS = ["wind_u", "wind_v", "wind_speed", "blh", "temp_c", "rh"]


def load_panel(
    project: Optional[str] = None,
    dataset: str = "vayusetu_ncr",
    date_from: str = "2025-10-25",
    date_to: str = "2025-11-21",
) -> Tuple[Dict[str, Dict[datetime, float]], Dict[str, Dict[datetime, Dict[str, float]]]]:
    """Return {station: {ts: pm25}} and {cell: {ts: met fields}}."""
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    pm: Dict[str, Dict[datetime, float]] = defaultdict(dict)
    cell_of: Dict[str, str] = {}
    q1 = f"""
        SELECT station_id, cell_id, ts, AVG(value) AS v
        FROM `{project}.{dataset}.raw_stations`
        WHERE pollutant = 'pm25' AND value IS NOT NULL
          AND ts >= TIMESTAMP('{date_from}') AND ts < TIMESTAMP('{date_to}')
        GROUP BY station_id, cell_id, ts
    """
    for r in client.query(q1).result():
        pm[r.station_id][r.ts] = float(r.v)
        cell_of[r.station_id] = r.cell_id

    met: Dict[str, Dict[datetime, Dict[str, float]]] = defaultdict(dict)
    q2 = f"""
        SELECT cell_id, ts, {', '.join(MET_FIELDS)}
        FROM `{project}.{dataset}.raw_meteorology`
        WHERE is_forecast = FALSE
          AND ts >= TIMESTAMP('{date_from}') AND ts < TIMESTAMP('{date_to}')
    """
    for r in client.query(q2).result():
        met[r.cell_id][r.ts] = {f: (float(r[f]) if r[f] is not None else np.nan) for f in MET_FIELDS}

    logger.info("panel stations=%d met_cells=%d", len(pm), len(met))
    return pm, met, cell_of


def build_samples(
    pm: Dict[str, Dict[datetime, float]],
    met: Dict[str, Dict[datetime, Dict[str, float]]],
    cell_of: Dict[str, str],
    horizon_h: int,
    use_future_met: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """
    One sample per (station, issue time t) where the label at t+h and all lags exist.

    Returns X, y, persistence, diurnal-persistence, target timestamps, feature names.
    """
    names = [f"pm25_lag_{h}h" for h in LAG_HOURS] + [
        "pm25_roll_mean_24h", "pm25_roll_std_24h",
    ] + [f"met_{f}" for f in MET_FIELDS] + [
        "target_hour_of_day", "target_dow", "horizon_h",
    ]

    X: List[List[float]] = []
    y: List[float] = []
    pers: List[float] = []
    diur: List[float] = []
    tgt_ts: List[datetime] = []

    for station, series in pm.items():
        cell = cell_of.get(station)
        mm = met.get(cell, {})
        for t, v_now in series.items():
            target = t + timedelta(hours=horizon_h)
            label = series.get(target)
            if label is None:
                continue

            lags = [series.get(t - timedelta(hours=h)) for h in LAG_HOURS]
            if any(l is None for l in lags):
                continue

            window = [series.get(t - timedelta(hours=k)) for k in range(24)]
            window = [w for w in window if w is not None]
            if len(window) < 12:
                continue

            # Meteorology: at the TARGET hour assumes a perfect weather forecast;
            # at the ISSUE hour is what an operational system truly knows.
            met_at = mm.get(target if use_future_met else t)
            if met_at is None:
                continue
            met_vals = [met_at[f] for f in MET_FIELDS]
            if any(np.isnan(x) for x in met_vals):
                continue

            # Diurnal persistence: the value at the same clock hour one day before
            # the target. PM2.5 has a strong daily cycle, so plain persistence is
            # unfairly weak at horizons that cross it (a 6h-ahead forecast from
            # 09:00 is compared against a 15:00 value). Beating plain persistence at
            # +6h while losing to this one would be a strawman win, so it is
            # measured explicitly.
            diurnal = series.get(target - timedelta(hours=24))
            if diurnal is None:
                continue

            X.append(
                [float(l) for l in lags]
                + [float(np.mean(window)), float(np.std(window))]
                + met_vals
                + [float(target.hour), float(target.weekday()), float(horizon_h)]
            )
            y.append(float(label))
            pers.append(float(v_now))       # persistence: carry the current value forward
            diur.append(float(diurnal))
            tgt_ts.append(target)

    order = np.argsort(np.array(tgt_ts))
    return (
        np.array(X)[order],
        np.array(y)[order],
        np.array(pers)[order],
        np.array(diur)[order],
        np.array(tgt_ts)[order],
        names,
    )


def evaluate(
    date_from: str = "2025-10-25",
    date_to: str = "2025-11-21",
    train_frac: float = 0.7,
    use_future_met: bool = True,
) -> Dict[str, Any]:
    """Per-horizon evaluation against persistence and climatology."""
    from ml.evaluate import compute_metrics
    from ml.train_grid import predict_model_a, train_model_a

    pm, met, cell_of = load_panel(date_from=date_from, date_to=date_to)
    out: Dict[str, Any] = {}

    for h in HORIZONS:
        X, y, pers, diur, ts, names = build_samples(pm, met, cell_of, h, use_future_met)
        if len(y) < 500:
            logger.warning("horizon %dh has only %d samples; skipping", h, len(y))
            continue

        cut = int(len(y) * train_frac)          # time-ordered, so this is a real split
        Xtr, ytr = X[:cut], y[:cut]
        Xte, yte, pte, dte = X[cut:], y[cut:], pers[cut:], diur[cut:]

        models = train_model_a(Xtr, ytr, names)
        p10, p50, p90 = predict_model_a(models, Xte)

        clim = np.full(len(yte), float(np.mean(ytr)))

        m = compute_metrics(yte, p50)
        b_pers = compute_metrics(yte, pte)
        b_diur = compute_metrics(yte, dte)
        b_clim = compute_metrics(yte, clim)
        coverage = float(np.mean((yte >= p10) & (yte <= p90)))

        out[f"+{h}h"] = {
            "n_train": int(cut),
            "n_test": int(len(yte)),
            "model": m,
            "baselines": {
                "persistence": b_pers,
                "diurnal_persistence": b_diur,
                "climatology": b_clim,
            },
            "beats_persistence": bool(m["mae"] < b_pers["mae"]),
            "beats_diurnal": bool(m["mae"] < b_diur["mae"]),
            "improvement_vs_diurnal_pct": round((b_diur["mae"] - m["mae"]) / b_diur["mae"] * 100, 2),
            "improvement_vs_persistence_pct": round((b_pers["mae"] - m["mae"]) / b_pers["mae"] * 100, 2),
            "interval_coverage_80": round(coverage, 3),
        }
        logger.info("horizon=%dh model=%.2f persistence=%.2f", h, m["mae"], b_pers["mae"])

    return {
        "data_source": "REAL",
        "evaluation_method": "temporal_holdout",
        "train_frac": train_frac,
        "use_future_met": use_future_met,
        "met_note": (
            "Target-hour ERA5 reanalysis used as the weather forecast — assumes a "
            "perfect forecast and therefore overstates operational skill."
            if use_future_met else
            "Only meteorology known at issue time. Operationally realistic."
        ),
        "window": [date_from, date_to],
        "horizons": out,
    }


def _print(r: Dict[str, Any]) -> None:
    print(f"\n--- Model B on REAL data ({'perfect-forecast met' if r['use_future_met'] else 'issue-time met only'}) ---")
    print(f"  {'Horizon':<9} {'model':>8} {'persist':>8} {'diurnal':>8} {'clim':>8} {'vs diurnal':>11} {'80% cov':>8}")
    print(f"  {'-'*9} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*11} {'-'*8}")
    for k, d in r["horizons"].items():
        flag = "" if d["beats_diurnal"] else "   <-- LOSES to diurnal"
        print(f"  {k:<9} {d['model']['mae']:8.2f} "
              f"{d['baselines']['persistence']['mae']:8.2f} "
              f"{d['baselines']['diurnal_persistence']['mae']:8.2f} "
              f"{d['baselines']['climatology']['mae']:8.2f} "
              f"{d['improvement_vs_diurnal_pct']:+10.1f}% {d['interval_coverage_80']:8.3f}{flag}")


def demo() -> None:
    r = evaluate()
    _print(r)
    assert r["horizons"], "no horizon produced samples"
    for k, d in r["horizons"].items():
        assert d["baselines"]["persistence"]["mae"] > 0
        assert 0.0 <= d["interval_coverage_80"] <= 1.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
