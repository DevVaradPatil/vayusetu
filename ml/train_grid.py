"""
ml/train_grid.py — Model A: Gridded PM2.5 Quantile Estimator Training Script.

Trains LightGBM / Gradient Boosting regressors at quantiles alpha = 0.1, 0.5, 0.9
to estimate PM2.5 at 1 km grid cells with uncertainty bounds per plan.md §4.
"""

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ml import synthetic

logger = logging.getLogger("vayusetu.ml.train_grid")

# Attempt LightGBM import, fallback to sklearn GradientBoostingRegressor
try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
    logger.info("LightGBM available for Model A training.")
except ImportError:
    from sklearn.ensemble import GradientBoostingRegressor
    HAS_LIGHTGBM = False
    logger.info("LightGBM not installed. Falling back to sklearn GradientBoostingRegressor.")


FEATURE_COLUMNS = synthetic.FEATURE_COLUMNS


def train_model_a(X: np.ndarray, y: np.ndarray, feature_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Trains quantile regressors for alpha = 0.1, 0.5, 0.9.

    `feature_names` must match X's column count. It is optional because the real
    feature set is narrower than the synthetic one — Earth Engine columns are
    dropped at load time (ml/realdata.py) — so a hardcoded name list breaks on real
    data. When omitted, LightGBM names the columns itself.
    """
    logger.info(f"Training Model A on {X.shape[0]} samples across {X.shape[1]} features")

    models = {}
    quantiles = [0.1, 0.5, 0.9]

    if HAS_LIGHTGBM:
        for q in quantiles:
            params = {
                "objective": "quantile",
                "alpha": q,
                "metric": "quantile",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "verbosity": -1,
                "random_state": 42
            }
            names = feature_names if feature_names and len(feature_names) == X.shape[1] else "auto"
            dtrain = lgb.Dataset(X, label=y, feature_name=names)
            model = lgb.train(params, dtrain, num_boost_round=100)
            models[f"p{int(q*100)}"] = model
    else:
        for q in quantiles:
            gbr = GradientBoostingRegressor(
                loss="quantile",
                alpha=q,
                n_estimators=100,
                learning_rate=0.05,
                random_state=42
            )
            gbr.fit(X, y)
            models[f"p{int(q*100)}"] = gbr

    logger.info("Model A quantile regressors trained successfully.")
    return models


def predict_model_a(models: Dict[str, Any], X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Predicts (p10, p50/median, p90) for feature matrix X.
    """
    if HAS_LIGHTGBM:
        p10 = models["p10"].predict(X)
        p50 = models["p50"].predict(X)
        p90 = models["p90"].predict(X)
    else:
        p10 = models["p10"].predict(X)
        p50 = models["p50"].predict(X)
        p90 = models["p90"].predict(X)

    return p10, p50, p90


def main():
    print("=== Training Model A: 1 km Grid PM2.5 Estimator ===")
    print(f"!! {synthetic.__name__}: placeholder data, not a result. See TODO.md")
    ds = synthetic.generate(n_stations=12, n_hours=240)
    X, y = ds.X, ds.y
    models = train_model_a(X, y)

    p10, p50, p90 = predict_model_a(models, X[:5])
    print("\n  [OK] Model A Predictions Sample (First 5 rows):")
    for i in range(5):
        print(f"   Row {i+1}: Target={y[i]:.1f} | Predicted P50={p50[i]:.1f} (P10={p10[i]:.1f}, P90={p90[i]:.1f})")

    # Save model artifact
    models_dir = Path(__file__).parent / "artifacts"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / "model_a.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(models, f)
    print(f"\n  [OK] Model A artifact exported to: {model_path}")


if __name__ == "__main__":
    main()
