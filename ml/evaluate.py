"""
ml/evaluate.py — Leave-One-Station-Out (LOSO) cross-validation.

Enforces AGENTS.md R1 (spatial CV, never random) and R2 (honest metrics against
real baselines).

The protocol: hold out every row belonging to one station, train on the remaining
stations, predict the held-out station, repeat. This mirrors the claim the product
actually makes — that we can estimate PM2.5 at a location with no monitor.

Two things this file gets right that are easy to get wrong:

1. The holdout must be a real station with its own characteristics. If station ids
   are sprayed across random rows, LOSO degenerates into a random split and
   reports the same inflated R2. See ml/synthetic.py for why the generator is
   built the way it is.

2. The IDW baseline must be a real IDW computation from the *other* stations'
   concurrent readings, via ml.common.compute_idw_baseline. Deriving a baseline
   from the held-out labels (`y_val + noise`) produces a number that is not a
   baseline at all: it is the answer, corrupted, and beating it means nothing.

NOTE ON DATA SOURCE: until ingestion has real API keys (see TODO.md), this runs on
ml/synthetic.py placeholder data. Every metric it emits is tagged SYNTHETIC and
must not be quoted anywhere — not in the deck, the video, the README or a model
card. Re-run against ml/features.sql output before reporting anything.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ml import synthetic
from ml.common import compute_idw_baseline
from ml.train_grid import predict_model_a, train_model_a

logger = logging.getLogger("vayusetu.ml.evaluate")

DATA_SOURCE_SYNTHETIC = "SYNTHETIC — placeholder, not a result. See TODO.md"


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """MAE, RMSE, R2 and signed bias."""
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    bias = float(np.mean(y_pred - y_true))

    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "r2": round(r2, 4),
        "bias": round(bias, 2),
    }


def idw_predict_for_station(
    ds: synthetic.Dataset,
    holdout_station: str,
    val_mask: np.ndarray,
) -> np.ndarray:
    """
    Real IDW baseline: what the existing station network would report at the
    held-out station's location, using only the OTHER stations' readings at the
    same hour.

    This is the number the product's residual is defined against
    (docs/DATA_CONTRACTS.md §6), so it must be computed the same way here as it is
    in production — via ml.common, not reimplemented.

    Hours where IDW cannot be computed (fewer than 2 stations within 50 km) fall
    back to the concurrent regional mean, and are counted so coverage is visible.
    """
    lat, lon = ds.station_coords[holdout_station]
    val_hours = ds.hour_idx[val_mask]

    preds = np.empty(len(val_hours), dtype=float)
    n_fallback = 0

    for i, hour in enumerate(val_hours):
        same_hour = ds.hour_idx == hour
        others = same_hour & (ds.station_ids != holdout_station)

        reporting: List[Dict[str, Any]] = [
            {
                "lat": ds.station_coords[sid][0],
                "lon": ds.station_coords[sid][1],
                "value": float(val),
            }
            for sid, val in zip(ds.station_ids[others], ds.y[others])
        ]

        idw = compute_idw_baseline(lat, lon, reporting)
        if idw is None:
            idw = float(np.mean(ds.y[others])) if others.any() else float(np.mean(ds.y))
            n_fallback += 1
        preds[i] = idw

    if n_fallback:
        logger.info(
            "idw.fallback station=%s hours=%d/%d (no 2 stations within 50km)",
            holdout_station, n_fallback, len(val_hours),
        )
    return preds


def evaluate_loso_cv(ds: synthetic.Dataset) -> Dict[str, Any]:
    """
    Leave-one-station-out CV with the two mandatory baselines.

    Baselines (train-and-evaluate skill): IDW interpolation from the remaining
    stations, and the station-mean of the training set. A model that does not beat
    IDW at held-out stations has no reason to exist, and this function is where
    that gets found out.
    """
    unique_stations = sorted(set(ds.station_ids.tolist()))
    logger.info("loso.start n_stations=%d n_rows=%d", len(unique_stations), len(ds))

    model_preds = np.zeros(len(ds))
    idw_preds = np.zeros(len(ds))
    mean_preds = np.zeros(len(ds))
    per_station: List[Dict[str, Any]] = []

    for holdout in unique_stations:
        val_mask = ds.station_ids == holdout
        train_mask = ~val_mask

        if not val_mask.any() or not train_mask.any():
            continue

        models = train_model_a(ds.X[train_mask], ds.y[train_mask], ds.feature_names)
        _, p50, _ = predict_model_a(models, ds.X[val_mask])
        model_preds[val_mask] = p50

        idw_preds[val_mask] = idw_predict_for_station(ds, holdout, val_mask)
        mean_preds[val_mask] = float(np.mean(ds.y[train_mask]))

        station_metrics = compute_metrics(ds.y[val_mask], p50)
        per_station.append({
            "station_id": holdout,
            "n": int(val_mask.sum()),
            "mae": station_metrics["mae"],
            "r2": station_metrics["r2"],
        })
        logger.info("loso.fold station=%s mae=%.2f", holdout, station_metrics["mae"])

    model_metrics = compute_metrics(ds.y, model_preds)
    idw_metrics = compute_metrics(ds.y, idw_preds)
    mean_metrics = compute_metrics(ds.y, mean_preds)

    station_maes = [s["mae"] for s in per_station]

    return {
        "data_source": DATA_SOURCE_SYNTHETIC if ds.is_synthetic else "REAL",
        "evaluation_method": "leave_one_station_out",
        "n_rows": len(ds),
        "n_stations": len(unique_stations),
        "model_a_loso": model_metrics,
        "baselines": {
            "idw_k4_p2_max50km": idw_metrics,
            "station_mean": mean_metrics,
        },
        "beats_idw": bool(model_metrics["mae"] < idw_metrics["mae"]),
        "mae_std_across_stations": round(float(np.std(station_maes)), 2),
        "per_station": sorted(per_station, key=lambda s: s["mae"], reverse=True),
    }


def _print_report(r: Dict[str, Any]) -> None:
    print("\n--- LOSO evaluation (AGENTS.md R1, R2) ---")
    print(f"  Data source : {r['data_source']}")
    print(f"  Method      : {r['evaluation_method']}")
    print(f"  Rows        : {r['n_rows']} across {r['n_stations']} stations\n")

    m, idw, sm = r["model_a_loso"], r["baselines"]["idw_k4_p2_max50km"], r["baselines"]["station_mean"]
    print(f"  Model A        MAE={m['mae']:>6.2f}  RMSE={m['rmse']:>6.2f}  R2={m['r2']:>7.4f}  bias={m['bias']:+.2f}")
    print(f"  IDW baseline   MAE={idw['mae']:>6.2f}  RMSE={idw['rmse']:>6.2f}  R2={idw['r2']:>7.4f}")
    print(f"  Station mean   MAE={sm['mae']:>6.2f}  RMSE={sm['rmse']:>6.2f}  R2={sm['r2']:>7.4f}")

    verdict = "beats IDW" if r["beats_idw"] else "DOES NOT beat IDW"
    delta = (idw["mae"] - m["mae"]) / idw["mae"] * 100.0
    print(f"\n  Verdict     : {verdict} ({delta:+.1f}% MAE vs IDW)")
    print(f"  Per-station MAE spread (std): {r['mae_std_across_stations']}")

    worst = r["per_station"][0]
    print(f"  Worst station: {worst['station_id']}  MAE={worst['mae']}  (n={worst['n']})")

    if m["r2"] > 0.90:
        print("\n  WARNING: R2 above 0.90 on Model A indicates a leak, not a good model.")
        print("           Check for a random split, station id in features, or a lagged label.")
    print()


def main() -> None:
    print("=== Model A — Leave-One-Station-Out cross-validation ===")
    print(f"!! {DATA_SOURCE_SYNTHETIC}")

    ds = synthetic.generate(n_stations=12, n_hours=240)
    results = evaluate_loso_cv(ds)
    _print_report(results)

    out = Path(__file__).parent / "artifacts" / "evaluation_metrics.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"  Written: {out}")
    print("  These numbers are NOT reportable. Re-run on real data before quoting.\n")


def demo() -> None:
    """Self-check: the protocol must be honest even on easy data."""
    ds = synthetic.generate(n_stations=5, n_hours=60, seed=11)
    r = evaluate_loso_cv(ds)

    assert r["evaluation_method"] == "leave_one_station_out"
    assert r["n_stations"] == 5
    assert len(r["per_station"]) == 5, "every station must be held out exactly once"

    # The IDW baseline must be derived from other stations, never from the labels.
    # A label-derived baseline lands implausibly close to the truth; a real one on
    # correlated regional data lands in a believable band.
    idw_mae = r["baselines"]["idw_k4_p2_max50km"]["mae"]
    assert idw_mae > 3.0, f"IDW MAE {idw_mae} is suspiciously low — is it derived from y?"

    # Station-mean must be the weakest of the three; if it wins, something is wrong.
    assert r["baselines"]["station_mean"]["mae"] > r["model_a_loso"]["mae"]

    print(f"[OK] LOSO ran {len(r['per_station'])} folds, one per station")
    print(f"[OK] model MAE {r['model_a_loso']['mae']} vs real IDW {idw_mae}")
    print(f"[OK] R2 {r['model_a_loso']['r2']} (>0.90 would signal a leak)")


if __name__ == "__main__":
    main()
