"""
ml/realdata.py — Load the real feature table from BigQuery into a Dataset.

Builds exactly the same container `ml/synthetic.py` produces, so `evaluate_loso_cv`
runs unchanged over real observations. The only difference visible downstream is
`is_synthetic=False`, which flips every artifact's `data_source` tag from
SYNTHETIC to REAL.

Feature selection is dynamic on purpose. Earth Engine is still pending, so
`aod_maiac`, `s5p_*` and the static grid layers are entirely NULL. Rather than
feeding a model columns that are 100% missing — which teaches it nothing and
invites a silent all-NaN split — columns above a null threshold are dropped, and
the ones actually used are recorded on the Dataset so the model card can state the
real feature set rather than the aspirational one.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ml.synthetic import Dataset

logger = logging.getLogger("vayusetu.ml.realdata")

# Candidate features, in the order the model sees them. Anything unavailable is
# dropped at load time (see MAX_NULL_FRACTION).
CANDIDATE_FEATURES = [
    # Location. Cheap, always available, and the only spatial signal in the feature
    # set while Earth Engine is pending. A tree cannot extrapolate beyond the
    # training stations' coordinate range, but it interpolates between them — which
    # is the behaviour we want at unmonitored cells inside the network's footprint.
    "lat", "lon",
    # Satellite — NULL until Earth Engine lands.
    "aod_maiac", "s5p_no2", "s5p_aer_ai", "cloud_fraction",
    # Meteorology — available now.
    "wind_u", "wind_v", "wind_speed", "wind_dir", "blh", "temp_c", "rh", "precip_mm",
    # Static grid layers — NULL until Earth Engine lands.
    "population", "builtup_frac", "cropland_frac", "elevation_m", "dist_major_road_m",
    # Fires — available now.
    "fire_count_25km_48h", "fire_count_50km_48h", "fire_count_100km_48h",
    "fire_count_upwind_100km_48h", "fire_frp_upwind_100km_48h",
    # Temporal — always available.
    "hour_of_day", "day_of_week", "day_of_year_sin", "day_of_year_cos", "is_stubble_season",
]

# A column missing more than this fraction of values carries no usable signal.
MAX_NULL_FRACTION = 0.5


def load_from_bigquery(
    project: Optional[str] = None,
    dataset: str = "vayusetu_ncr",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_rows_per_station: int = 100,
) -> Dataset:
    """
    Load `features_training` into a Dataset ready for LOSO evaluation.

    `min_rows_per_station` drops stations with only a handful of observations.
    LOSO holds out one station at a time, so a station with 3 rows contributes a
    fold whose metric is dominated by noise, and it distorts the mean across folds.
    """
    from google.cloud import bigquery

    project = project or os.environ["GCP_PROJECT_ID"]
    client = bigquery.Client(project=project)

    where = ["target_pm25 IS NOT NULL"]
    if date_from:
        where.append(f"ts >= TIMESTAMP('{date_from}')")
    if date_to:
        where.append(f"ts < TIMESTAMP('{date_to}')")

    cols = ", ".join(CANDIDATE_FEATURES)
    sql = f"""
        WITH counted AS (
            SELECT station_id, COUNT(*) AS n
            FROM `{project}.{dataset}.features_training`
            WHERE {' AND '.join(where)}
            GROUP BY station_id
            HAVING n >= {min_rows_per_station}
        )
        SELECT f.station_id, f.ts, f.lat, f.lon, f.target_pm25, {cols}
        FROM `{project}.{dataset}.features_training` f
        JOIN counted c USING (station_id)
        WHERE {' AND '.join(f'f.{w}' if w.startswith('t') else w for w in where)}
        ORDER BY f.ts, f.station_id
    """
    rows = list(client.query(sql).result())
    if not rows:
        raise RuntimeError(
            "features_training returned no rows. Build it first: run ml/features.sql."
        )

    logger.info("realdata.loaded rows=%d", len(rows))

    # --- Drop columns that are mostly or entirely missing ---------------------
    usable: List[str] = []
    dropped: Dict[str, float] = {}
    for name in CANDIDATE_FEATURES:
        col = np.array([r[name] for r in rows], dtype=object)
        null_frac = float(np.mean([v is None for v in col]))
        if null_frac > MAX_NULL_FRACTION:
            dropped[name] = round(null_frac, 3)
        else:
            usable.append(name)

    if dropped:
        logger.info("realdata.dropped_features %s", dropped)

    X = np.array(
        [[float(r[name]) if r[name] is not None else np.nan for name in usable] for r in rows],
        dtype=float,
    )
    # LightGBM handles NaN natively; the sklearn fallback does not, so fill the
    # residual gaps with the column median rather than dropping whole rows.
    for j in range(X.shape[1]):
        col = X[:, j]
        if np.isnan(col).any():
            col[np.isnan(col)] = float(np.nanmedian(col)) if not np.isnan(col).all() else 0.0

    y = np.array([float(r["target_pm25"]) for r in rows], dtype=float)
    station_ids = np.array([r["station_id"] for r in rows])
    timestamps = np.array([r["ts"] for r in rows])

    # A shared integer clock across stations, so the IDW baseline can find each
    # station's concurrent neighbours the same way it does for synthetic data.
    unique_ts = sorted(set(timestamps.tolist()))
    ts_index = {t: i for i, t in enumerate(unique_ts)}
    hour_idx = np.array([ts_index[t] for t in timestamps])

    station_coords: Dict[str, Tuple[float, float]] = {}
    for r in rows:
        station_coords.setdefault(r["station_id"], (float(r["lat"]), float(r["lon"])))

    ds = Dataset(
        X=X,
        y=y,
        station_ids=station_ids,
        hour_idx=hour_idx,
        timestamps=timestamps,
        station_coords=station_coords,
        feature_names=usable,
        is_synthetic=False,
    )
    logger.info(
        "realdata.dataset rows=%d stations=%d features=%d hours=%d",
        len(ds), len(station_coords), len(usable), len(unique_ts),
    )
    return ds


def summarize(ds: Dataset) -> Dict[str, Any]:
    """Human-readable summary, for the model card and the console."""
    return {
        "n_rows": len(ds),
        "n_stations": len(ds.station_coords),
        "n_features": len(ds.feature_names),
        "features_used": list(ds.feature_names),
        "pm25_min": round(float(ds.y.min()), 1),
        "pm25_max": round(float(ds.y.max()), 1),
        "pm25_mean": round(float(ds.y.mean()), 1),
        "ts_from": str(min(ds.timestamps)),
        "ts_to": str(max(ds.timestamps)),
    }


def demo() -> None:
    ds = load_from_bigquery(date_from="2025-10-25", date_to="2025-11-21")
    s = summarize(ds)

    assert not ds.is_synthetic, "real loader must not be flagged synthetic"
    assert len(ds) > 0
    assert len(ds.station_coords) >= 2, "IDW needs at least two stations"
    assert not np.isnan(ds.X).any(), "feature matrix must not contain NaN after fill"
    assert ds.X.shape == (len(ds), len(ds.feature_names))
    # Satellite and static layers must have been dropped while EE is pending.
    assert "aod_maiac" not in ds.feature_names, "AOD is 100% null; it should be dropped"

    print(f"[OK] {s['n_rows']} rows, {s['n_stations']} stations, {s['n_features']} features")
    print(f"[OK] PM2.5 {s['pm25_min']}..{s['pm25_max']} (mean {s['pm25_mean']})")
    print(f"[OK] features: {', '.join(s['features_used'])}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
