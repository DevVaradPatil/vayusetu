"""
ml/evaluate_forecast.py — Model B evaluation against the two mandatory baselines.

Completes BACKLOG W2.6. The train-and-evaluate skill requires that any reported
forecast number is accompanied by:

  1. Persistence  — "the value stays where it is". Deceptively strong for air
     quality, and the baseline a forecaster must beat to be worth having.
  2. Climatology  — the seasonal mean for that hour.

Beating persistence at +24h is genuinely hard. A 15-25% MAE improvement is a real
result; anything far above that on real data deserves suspicion before celebration.

Also reports interval calibration: roughly 80% of actuals should fall inside
[p10, p90]. If coverage is near 50% the band is too narrow, and every downstream
confidence value computed from it (docs/DATA_CONTRACTS.md §6) is wrong — which
matters because confidence gates the hotspot test.

NOTE ON DATA SOURCE: runs on ml/train_forecast.py synthetic data until ingestion
has real keys (TODO.md). Metrics are tagged SYNTHETIC and are not reportable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

import numpy as np

from ml.evaluate import DATA_SOURCE_SYNTHETIC, compute_metrics
from ml.train_forecast import (
    FORECAST_FEATURES,
    HORIZONS_H,
    generate_synthetic_forecast_data,
    train_model_b,
)

logger = logging.getLogger("vayusetu.ml.evaluate_forecast")

# Index of pm25_lag_1h in FORECAST_FEATURES — the current observation, which is exactly
# what a persistence forecast predicts for every horizon.
LAG_1_IDX = FORECAST_FEATURES.index("pm25_lag_1h")


def _split_temporal(n: int, train_frac: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """
    Time-ordered split: train on the earlier portion, test on the later.

    Random-splitting a time series leaks the future into the past. The synthetic
    rows here are i.i.d. rather than a true series, so this split is structural
    rather than protective — but it is the shape the real pipeline must use, and
    encoding it now means the harness is already correct when real data lands.
    """
    cut = int(n * train_frac)
    idx = np.arange(n)
    return idx[:cut], idx[cut:]


def evaluate_forecast() -> Dict[str, Any]:
    """Per-horizon evaluation of Model B against persistence and climatology."""
    X_dict, y_dict = generate_synthetic_forecast_data(n_samples=2000)

    # train_model_b trains every horizon in one call, so slice first and train once.
    train_idx, test_idx = _split_temporal(len(y_dict[HORIZONS_H[0]]))
    trained = train_model_b(
        {h: X_dict[h][train_idx] for h in HORIZONS_H},
        {h: y_dict[h][train_idx] for h in HORIZONS_H},
    )

    per_horizon: Dict[str, Any] = {}

    for h in HORIZONS_H:
        X, y = X_dict[h], y_dict[h]
        models = trained[h]

        X_test, y_test = X[test_idx], y[test_idx]

        p10 = models["p10"].predict(X_test)
        p50 = models["p50"].predict(X_test)
        p90 = models["p90"].predict(X_test)

        # Baseline 1: persistence — carry the current observation forward.
        persistence = X_test[:, LAG_1_IDX]

        # Baseline 2: climatology — the training-period mean.
        climatology = np.full(len(y_test), float(np.mean(y[train_idx])))

        model_m = compute_metrics(y_test, p50)
        pers_m = compute_metrics(y_test, persistence)
        clim_m = compute_metrics(y_test, climatology)

        coverage = float(np.mean((y_test >= p10) & (y_test <= p90)))
        improvement = (pers_m["mae"] - model_m["mae"]) / pers_m["mae"] * 100.0

        per_horizon[f"+{h}h"] = {
            "model": model_m,
            "baselines": {"persistence": pers_m, "climatology": clim_m},
            "beats_persistence": bool(model_m["mae"] < pers_m["mae"]),
            "mae_improvement_vs_persistence_pct": round(improvement, 1),
            "interval_coverage_80": round(coverage, 3),
            "n_test": int(len(y_test)),
        }
        logger.info(
            "forecast.horizon h=%d mae=%.2f persistence=%.2f coverage=%.3f",
            h, model_m["mae"], pers_m["mae"], coverage,
        )

    return {
        "data_source": DATA_SOURCE_SYNTHETIC,
        "evaluation_method": "temporal_holdout",
        "train_frac": 0.8,
        "horizons": per_horizon,
        "caveats": [
            "The synthetic target is generated as lag_1 * decay + fire_effect + noise, so "
            "persistence carries a systematic bias the model learns trivially. The "
            "improvement-over-persistence figures here are therefore inflated and tell you "
            "nothing about real skill. On real data, expect 15-25% at +24h, and treat "
            "anything much higher as a leak to investigate rather than a result.",
        ],
    }


def _print_report(r: Dict[str, Any]) -> None:
    print("\n--- Model B forecast evaluation (AGENTS.md R2) ---")
    print(f"  Data source : {r['data_source']}")
    print(f"  Method      : {r['evaluation_method']} (train on first {int(r['train_frac']*100)}%)\n")

    print(f"  {'Horizon':<9} {'Model':>8} {'Persist':>8} {'Clim':>8} {'vs Persist':>11} {'80% cov':>9}")
    print(f"  {'-'*9} {'-'*8} {'-'*8} {'-'*8} {'-'*11} {'-'*9}")

    for horizon, d in r["horizons"].items():
        m = d["model"]["mae"]
        p = d["baselines"]["persistence"]["mae"]
        c = d["baselines"]["climatology"]["mae"]
        imp = d["mae_improvement_vs_persistence_pct"]
        cov = d["interval_coverage_80"]
        flag = "" if d["beats_persistence"] else "  <-- LOSES to persistence"
        print(f"  {horizon:<9} {m:>8.2f} {p:>8.2f} {c:>8.2f} {imp:>10.1f}% {cov:>9.3f}{flag}")

    print()
    for horizon, d in r["horizons"].items():
        cov = d["interval_coverage_80"]
        if not 0.70 <= cov <= 0.90:
            print(f"  WARNING {horizon}: 80% interval covers {cov:.1%} of actuals.")
            print(f"          Confidence values derived from this band are unreliable.")
        if not d["beats_persistence"]:
            print(f"  WARNING {horizon}: does not beat persistence. Say so rather than shipping it.")
    print()


def main() -> None:
    print("=== Model B — 72h forecast evaluation ===")
    print(f"!! {DATA_SOURCE_SYNTHETIC}")

    results = evaluate_forecast()
    _print_report(results)

    out = Path(__file__).parent / "artifacts" / "forecast_metrics.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"  Written: {out}")
    print("  These numbers are NOT reportable. Re-run on real data before quoting.\n")


def demo() -> None:
    """Self-check: both baselines present and computed independently of the model."""
    r = evaluate_forecast()

    assert set(r["horizons"]) == {f"+{h}h" for h in HORIZONS_H}, "every horizon must be evaluated"

    for horizon, d in r["horizons"].items():
        assert "persistence" in d["baselines"], f"{horizon} missing persistence baseline"
        assert "climatology" in d["baselines"], f"{horizon} missing climatology baseline"
        # Persistence must be a real forward-carry of lag_1, not derived from y.
        assert d["baselines"]["persistence"]["mae"] > 1.0, (
            f"{horizon} persistence MAE implausibly low — is it derived from the labels?"
        )
        assert 0.0 <= d["interval_coverage_80"] <= 1.0

    # Error should grow with horizon. If +72h beats +6h, something is wrong.
    mae_6 = r["horizons"]["+6h"]["model"]["mae"]
    mae_72 = r["horizons"]["+72h"]["model"]["mae"]
    assert mae_72 > mae_6, f"+72h MAE ({mae_72}) should exceed +6h ({mae_6})"

    print(f"[OK] {len(r['horizons'])} horizons, each with persistence + climatology")
    print(f"[OK] error grows with horizon: +6h {mae_6} -> +72h {mae_72}")
    print(f"[OK] interval coverage reported per horizon")


if __name__ == "__main__":
    main()
