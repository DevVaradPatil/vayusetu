"""
ml/train_forecast.py — Model B: 72-hour Direct Multi-Horizon AQI Forecaster.

Trains direct multi-horizon quantile regressors (horizons: +6h, +24h, +48h, +72h)
at quantiles alpha = 0.1, 0.5, 0.9 per plan.md §4.
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np

logger = logging.getLogger("vayusetu.ml.train_forecast")

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    from sklearn.ensemble import GradientBoostingRegressor
    HAS_LIGHTGBM = False

HORIZONS_H = [6, 24, 48, 72]

FORECAST_FEATURES = [
    "pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h", "pm25_lag_48h",
    "pm25_rolling_mean_24h", "pm25_rolling_std_24h",
    "forecast_wind_u", "forecast_wind_v", "forecast_wind_speed", "forecast_blh", "forecast_temp_c", "forecast_rh",
    "upwind_fire_count_24h", "upwind_fire_frp_24h",
    "hour_of_day", "day_of_week", "day_of_year_sin", "day_of_year_cos"
]


def generate_synthetic_forecast_data(n_samples: int = 2000) -> Tuple[Dict[int, np.ndarray], Dict[int, np.ndarray]]:
    """
    Generates realistic lag & meteorological forecast features for t+6h, t+24h, t+48h, t+72h.
    """
    np.random.seed(42)

    X_dict = {}
    y_dict = {}

    for h in HORIZONS_H:
        lag_1 = np.random.uniform(50, 400, n_samples)
        lag_3 = lag_1 + np.random.normal(0, 15, n_samples)
        lag_6 = lag_1 + np.random.normal(0, 25, n_samples)
        lag_12 = lag_1 + np.random.normal(0, 35, n_samples)
        lag_24 = lag_1 + np.random.normal(0, 45, n_samples)
        lag_48 = lag_1 + np.random.normal(0, 55, n_samples)

        roll_mean = (lag_1 + lag_6 + lag_12 + lag_24) / 4.0
        roll_std = np.abs(lag_1 - roll_mean) + 5.0

        w_speed = np.random.uniform(1.0, 7.0, n_samples)
        w_dir = np.random.uniform(0, 360, n_samples)
        w_u = -w_speed * np.sin(np.radians(w_dir))
        w_v = -w_speed * np.cos(np.radians(w_dir))
        blh = np.random.uniform(180, 750, n_samples)
        temp = np.random.uniform(14, 30, n_samples)
        rh = np.random.uniform(45, 90, n_samples)

        fire_cnt = np.random.poisson(15, n_samples)
        fire_frp = fire_cnt * np.random.uniform(5.0, 15.0, n_samples)

        hour = np.random.randint(0, 24, n_samples)
        dow = np.random.randint(1, 8, n_samples)
        doy = np.random.randint(280, 340, n_samples)
        doy_sin = np.sin(2 * np.pi * doy / 365.0)
        doy_cos = np.cos(2 * np.pi * doy / 365.0)

        X = np.column_stack([
            lag_1, lag_3, lag_6, lag_12, lag_24, lag_48,
            roll_mean, roll_std,
            w_u, w_v, w_speed, blh, temp, rh,
            fire_cnt, fire_frp,
            hour, dow, doy_sin, doy_cos
        ])

        # Target t+h PM2.5 physics (persistence + meteorological advection)
        decay = 1.0 - (h / 200.0)
        y = lag_1 * decay + fire_cnt * 3.5 + np.random.normal(0, 15.0 + h * 0.4, n_samples)
        y = np.clip(y, 15.0, 550.0)

        X_dict[h] = X
        y_dict[h] = y

    return X_dict, y_dict


def train_model_b(X_dict: Dict[int, np.ndarray], y_dict: Dict[int, np.ndarray]) -> Dict[int, Dict[str, Any]]:
    """
    Trains separate quantile models (p10, p50, p90) for each forecast horizon.
    """
    logger.info("Training Model B 72h Multi-Horizon Forecaster")
    horizon_models = {}

    for h in HORIZONS_H:
        X = X_dict[h]
        y = y_dict[h]
        models = {}
        quantiles = [0.1, 0.5, 0.9]

        if HAS_LIGHTGBM:
            for q in quantiles:
                params = {
                    "objective": "quantile",
                    "alpha": q,
                    "learning_rate": 0.05,
                    "num_leaves": 31,
                    "verbosity": -1,
                    "random_state": 42
                }
                dtrain = lgb.Dataset(X, label=y, feature_name=FORECAST_FEATURES)
                models[f"p{int(q*100)}"] = lgb.train(params, dtrain, num_boost_round=80)
        else:
            for q in quantiles:
                gbr = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=80, random_state=42)
                gbr.fit(X, y)
                models[f"p{int(q*100)}"] = gbr

        horizon_models[h] = models
        logger.info(f"  ✓ Trained horizon t+{h}h quantile models")

    return horizon_models


def main():
    print("=== Training Model B: 72-Hour AQI Multi-Horizon Forecaster ===")
    X_dict, y_dict = generate_synthetic_forecast_data(n_samples=2000)
    horizon_models = train_model_b(X_dict, y_dict)

    # Validate predictions across horizons
    print("\n  [OK] Model B Multi-Horizon Forecast Sample (t+6h, t+24h, t+48h, t+72h):")
    sample_row = X_dict[6][:1]

    for h in HORIZONS_H:
        m = horizon_models[h]
        p10 = m["p10"].predict(sample_row)[0]
        p50 = m["p50"].predict(sample_row)[0]
        p90 = m["p90"].predict(sample_row)[0]
        print(f"   Horizon +{h:02d}h: Target={y_dict[h][0]:.1f} | Predicted P50={p50:.1f} (P10={p10:.1f}, P90={p90:.1f})")

    # Export artifact
    artifacts_dir = Path(__file__).parent / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    model_path = artifacts_dir / "model_b.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(horizon_models, f)
    print(f"\n  [OK] Model B artifact exported to: {model_path}")


if __name__ == "__main__":
    main()
