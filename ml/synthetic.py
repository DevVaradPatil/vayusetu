"""
ml/synthetic.py — Station-structured synthetic data generator.

PLACEHOLDER DATA. Every number produced here is fabricated. It exists so the
training and evaluation harness can be developed and tested before API keys are
available (see TODO.md). Nothing produced by this module may be quoted as a
result. `ml/features.sql` against real BigQuery tables is the real source.

Why this file exists at all, rather than a simpler generator:

The evaluation protocol we depend on (leave-one-station-out, AGENTS.md R1) only
means something if the synthetic data has genuine *spatial* structure. If station
ids are assigned round-robin to random rows, every station is statistically
identical, holding one out is equivalent to holding out a random 10% of rows, and
LOSO reports the same inflated number a random split would. The costume fits but
the leak is still there.

So each station here gets:
  - a real coordinate inside the NCR bbox,
  - static attributes drawn once (built-up fraction, population, road distance),
  - a hidden local emission offset that is only PARTLY explainable from those
    static attributes.

That unexplainable remainder is the point. It is what a model cannot know about a
station it has never seen, and it is what makes LOSO honest. Regional
meteorology is shared across stations at each timestep, because in reality
nearby monitors rise and fall together — which is also what makes IDW a genuinely
strong baseline rather than a strawman.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import numpy as np

logger = logging.getLogger("vayusetu.ml.synthetic")

# Back-compat alias: the container is no longer synthetic-specific.
# (assigned after the class definition below)

# Delhi-NCR bounding box, per docs/DATA_CONTRACTS.md §1
NCR_LAT_MIN, NCR_LON_MIN, NCR_LAT_MAX, NCR_LON_MAX = 28.20, 76.80, 28.95, 77.60

FEATURE_COLUMNS = [
    "aod_maiac", "s5p_no2", "s5p_aer_ai", "cloud_fraction",
    "wind_u", "wind_v", "wind_speed", "wind_dir", "blh", "temp_c", "rh", "precip_mm",
    "population", "builtup_frac", "cropland_frac", "elevation_m", "dist_major_road_m",
    "hour_of_day", "day_of_week", "day_of_year_sin", "day_of_year_cos", "is_stubble_season",
]

# Fraction of each station's local emission level that its static features cannot
# explain. Raise it and LOSO degrades; lower it and LOSO flatters the model.
# Real stations sit somewhere in this range — micro-siting, nearby kilns, a
# landfill two streets over. None of that is in our feature set.
UNEXPLAINED_LOCAL_SIGMA = 18.0


@dataclass(frozen=True)
class Dataset:
    """Feature matrix plus the metadata LOSO and IDW need.

    Source-agnostic: `is_synthetic` says whether it came from this module or from
    real observations (ml/realdata.py). Everything downstream keys off that flag,
    never off which module built it.
    """
    X: np.ndarray                       # (n_rows, n_features)
    y: np.ndarray                       # (n_rows,) PM2.5 ug/m3
    station_ids: np.ndarray             # (n_rows,) str
    hour_idx: np.ndarray                # (n_rows,) int, shared clock across stations
    timestamps: np.ndarray              # (n_rows,) datetime64
    station_coords: Dict[str, Tuple[float, float]]
    feature_names: List[str]
    is_synthetic: bool = True

    def __len__(self) -> int:
        return len(self.y)


def generate(
    n_stations: int = 12,
    n_hours: int = 240,
    seed: int = 42,
    start: datetime | None = None,
) -> Dataset:
    """
    Build a station-structured synthetic panel: n_stations x n_hours rows.

    Every station observes the same regional weather at a given hour (with a small
    local perturbation) but carries its own emission baseline. That is the shape of
    real monitoring data, and it is what makes the LOSO holdout meaningful.
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2024, 10, 20, 0, 0, tzinfo=timezone.utc)

    # --- Per-station statics, drawn once -------------------------------------
    lats = rng.uniform(NCR_LAT_MIN + 0.05, NCR_LAT_MAX - 0.05, n_stations)
    lons = rng.uniform(NCR_LON_MIN + 0.05, NCR_LON_MAX - 0.05, n_stations)
    builtup = rng.uniform(0.10, 0.90, n_stations)
    cropland = np.clip(1.0 - builtup - rng.uniform(0.05, 0.30, n_stations), 0.02, 0.80)
    population = rng.uniform(1_000, 50_000, n_stations)
    elevation = rng.uniform(200, 240, n_stations)
    road_dist = rng.uniform(100, 10_000, n_stations)

    # Local emission level: the learnable part is a function of features the model
    # actually sees; the rest is station identity the model cannot recover.
    explainable = 40.0 * builtup + 0.0004 * population - 0.0020 * road_dist
    unexplainable = rng.normal(0.0, UNEXPLAINED_LOCAL_SIGMA, n_stations)
    local_offset = explainable + unexplainable

    station_ids = np.array([f"openaq:{1001 + i}" for i in range(n_stations)])
    station_coords = {
        sid: (float(lats[i]), float(lons[i])) for i, sid in enumerate(station_ids)
    }

    # --- Regional conditions per hour, shared across stations ----------------
    aod_r = rng.uniform(0.30, 1.80, n_hours)
    no2_r = rng.uniform(0.0001, 0.0004, n_hours)
    aer_ai_r = rng.uniform(1.0, 3.0, n_hours)
    cloud_r = rng.uniform(0.0, 0.30, n_hours)
    wind_speed_r = rng.uniform(1.0, 8.0, n_hours)
    wind_dir_r = rng.uniform(0.0, 360.0, n_hours)
    blh_r = rng.uniform(150.0, 800.0, n_hours)
    temp_r = rng.uniform(12.0, 32.0, n_hours)
    rh_r = rng.uniform(40.0, 95.0, n_hours)

    timestamps_r = np.array([start + timedelta(hours=int(h)) for h in range(n_hours)])
    doy_r = np.array([t.timetuple().tm_yday for t in timestamps_r])
    hour_of_day_r = np.array([t.hour for t in timestamps_r])
    dow_r = np.array([t.weekday() + 1 for t in timestamps_r])
    is_stubble_r = ((doy_r >= 288) & (doy_r <= 335)).astype(float)

    rows: List[np.ndarray] = []
    targets: List[float] = []
    row_station: List[str] = []
    row_hour: List[int] = []
    row_ts: List[datetime] = []

    for s in range(n_stations):
        # Small per-station perturbation of the regional field. Monitors a few km
        # apart do not read identically, but they read close.
        aod = np.clip(aod_r * rng.normal(1.0, 0.06, n_hours), 0.05, 3.0)
        blh = np.clip(blh_r * rng.normal(1.0, 0.05, n_hours), 50.0, 1500.0)
        wind_speed = np.clip(wind_speed_r * rng.normal(1.0, 0.08, n_hours), 0.2, 20.0)
        wind_dir = (wind_dir_r + rng.normal(0.0, 5.0, n_hours)) % 360.0
        # Meteorological convention: direction the wind comes FROM.
        wind_u = -wind_speed * np.sin(np.radians(wind_dir))
        wind_v = -wind_speed * np.cos(np.radians(wind_dir))
        temp = temp_r + rng.normal(0.0, 0.8, n_hours)
        rh = np.clip(rh_r + rng.normal(0.0, 3.0, n_hours), 5.0, 100.0)
        precip = np.zeros(n_hours)

        X_s = np.column_stack([
            aod, no2_r, aer_ai_r, cloud_r,
            wind_u, wind_v, wind_speed, wind_dir, blh, temp, rh, precip,
            np.full(n_hours, population[s]),
            np.full(n_hours, builtup[s]),
            np.full(n_hours, cropland[s]),
            np.full(n_hours, elevation[s]),
            np.full(n_hours, road_dist[s]),
            hour_of_day_r, dow_r,
            np.sin(2 * np.pi * doy_r / 365.0),
            np.cos(2 * np.pi * doy_r / 365.0),
            is_stubble_r,
        ])

        # Target physics: regional drivers + this station's own emission level.
        y_s = (
            60.0
            + aod * 90.0
            + (1000.0 - blh) * 0.15
            + local_offset[s]
            + is_stubble_r * 65.0
            + rng.normal(0.0, 12.0, n_hours)
        )
        y_s = np.clip(y_s, 10.0, 600.0)

        rows.append(X_s)
        targets.append(y_s)
        row_station.extend([station_ids[s]] * n_hours)
        row_hour.extend(range(n_hours))
        row_ts.extend(timestamps_r)

    ds = Dataset(
        X=np.vstack(rows),
        y=np.concatenate(targets),
        station_ids=np.array(row_station),
        hour_idx=np.array(row_hour),
        timestamps=np.array(row_ts),
        station_coords=station_coords,
        feature_names=list(FEATURE_COLUMNS),
    )
    logger.info(
        "synthetic.generate n_rows=%d n_stations=%d n_hours=%d",
        len(ds), n_stations, n_hours,
    )
    return ds


def demo() -> None:
    ds = generate(n_stations=6, n_hours=48, seed=7)

    assert len(ds) == 6 * 48, "row count must be stations x hours"
    assert ds.X.shape[1] == len(FEATURE_COLUMNS), "feature count mismatch"
    assert len(ds.station_coords) == 6

    # The property the whole LOSO protocol depends on: stations must actually
    # differ from one another, otherwise holding one out tests nothing.
    means = [ds.y[ds.station_ids == s].mean() for s in sorted(set(ds.station_ids))]
    spread = float(np.std(means))
    assert spread > 5.0, f"stations are too alike (std={spread:.1f}); LOSO would be vacuous"

    # And they must still co-vary, or IDW becomes a strawman baseline.
    a, b = sorted(set(ds.station_ids))[:2]
    ya = ds.y[ds.station_ids == a]
    yb = ds.y[ds.station_ids == b]
    corr = float(np.corrcoef(ya, yb)[0, 1])
    assert corr > 0.5, f"stations do not co-vary (r={corr:.2f}); IDW baseline would be unfairly weak"

    # Determinism, so evaluation runs are reproducible.
    assert np.allclose(generate(n_stations=6, n_hours=48, seed=7).y, ds.y)

    print(f"[OK] {len(ds)} rows, {len(ds.station_coords)} stations")
    print(f"[OK] between-station mean spread: {spread:.1f} ug/m3")
    print(f"[OK] between-station correlation: {corr:.2f}")
    print("[OK] deterministic for a fixed seed")


if __name__ == "__main__":
    demo()


SyntheticDataset = Dataset  # back-compat alias
