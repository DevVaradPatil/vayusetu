#!/usr/bin/env python3
"""
experiments/density_sweep.py — Does the model's value depend on network density?

The 2026-09-08 finding: on full NCR (67 stations, median nearest neighbour 2.8 km)
Model A loses to IDW. The open question is whether that is a property of the
approach or a property of *dense networks*, where interpolation is already close to
optimal and there is little left to add.

This isolates the variable. Lucknow would confound density with city differences —
different airshed, emissions, seasonality. Subsampling NCR changes only the number
of stations, holding data, geography and period fixed.

Protocol, for each subsample size N:
  - draw N stations at random (several seeds, so one unlucky draw cannot decide it)
  - run the normal leave-one-station-out CV within that subsample
  - the model trains on N-1 stations; IDW interpolates from the same N-1
  - report model MAE, IDW MAE, and the gap

Both methods are handicapped equally as N falls, which is what makes the comparison
fair: a sparse city has both fewer training stations and fewer neighbours to
interpolate from.

    python experiments/density_sweep.py --sizes 5,8,12,20,35 --seeds 3
"""

import argparse
import json
import os
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_ENV = _ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import numpy as np  # noqa: E402

from ml import realdata  # noqa: E402
from ml.common import haversine_distance_km  # noqa: E402
from ml.evaluate import evaluate_loso_cv  # noqa: E402
from ml.synthetic import Dataset  # noqa: E402


def subsample(ds: Dataset, stations: list) -> Dataset:
    """A Dataset restricted to `stations`, with the shared clock left intact."""
    keep = np.isin(ds.station_ids, stations)
    return Dataset(
        X=ds.X[keep],
        y=ds.y[keep],
        station_ids=ds.station_ids[keep],
        hour_idx=ds.hour_idx[keep],
        timestamps=ds.timestamps[keep],
        station_coords={s: ds.station_coords[s] for s in stations},
        feature_names=ds.feature_names,
        is_synthetic=False,
    )


def median_nn_km(coords: dict) -> float:
    if len(coords) < 2:
        return float("nan")
    out = []
    for s, (la, lo) in coords.items():
        out.append(min(
            haversine_distance_km(la, lo, b[0], b[1])
            for t, b in coords.items() if t != s
        ))
    return float(np.median(out))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="5,8,12,20,35")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--from", dest="date_from", default="2025-10-25")
    ap.add_argument("--to", dest="date_to", default="2025-11-21")
    args = ap.parse_args()

    ds = realdata.load_from_bigquery(date_from=args.date_from, date_to=args.date_to)
    all_stations = sorted(ds.station_coords)
    print(f"Full network: {len(all_stations)} stations, {len(ds)} rows, "
          f"{len(ds.feature_names)} features")
    print(f"Median nearest-neighbour distance: {median_nn_km(ds.station_coords):.1f} km\n")

    sizes = [int(s) for s in args.sizes.split(",") if int(s) <= len(all_stations)]
    results = []

    print(f"  {'N':>3s} {'seed':>4s} {'medNN':>6s} {'model':>7s} {'IDW':>7s} {'gap':>8s}")
    print(f"  {'-'*3} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*8}")

    for n in sizes:
        per_size = []
        for seed in range(args.seeds):
            rng = np.random.default_rng(1000 + seed)
            picked = sorted(rng.choice(all_stations, size=n, replace=False).tolist())
            sub = subsample(ds, picked)

            r = evaluate_loso_cv(sub)
            m = r["model_a_loso"]["mae"]
            i = r["baselines"]["idw_k4_p2_max50km"]["mae"]
            gap = (i - m) / i * 100.0
            nn = median_nn_km(sub.station_coords)

            per_size.append({"seed": seed, "median_nn_km": round(nn, 2),
                             "model_mae": m, "idw_mae": i, "gap_pct": round(gap, 2)})
            print(f"  {n:3d} {seed:4d} {nn:6.1f} {m:7.2f} {i:7.2f} {gap:+7.1f}%")

        gaps = [p["gap_pct"] for p in per_size]
        results.append({
            "n_stations": n,
            "median_nn_km": round(float(np.mean([p["median_nn_km"] for p in per_size])), 2),
            "mean_gap_pct": round(float(np.mean(gaps)), 2),
            "std_gap_pct": round(float(np.std(gaps)), 2),
            "runs": per_size,
        })
        print(f"  {'':3s} {'mean':>4s} {'':6s} {'':7s} {'':7s} {np.mean(gaps):+7.1f}%  "
              f"(sd {np.std(gaps):.1f})\n")

    print("\n=== Summary: does the gap close as the network sparsifies? ===")
    print(f"  {'N':>3s} {'medNN km':>9s} {'gap vs IDW':>12s}")
    for r in results:
        verdict = "MODEL WINS" if r["mean_gap_pct"] > 0 else ""
        print(f"  {r['n_stations']:3d} {r['median_nn_km']:9.1f} {r['mean_gap_pct']:+11.1f}%  {verdict}")

    out = _ROOT / "ml" / "artifacts" / "density_sweep.json"
    out.write_text(json.dumps({
        "data_source": "REAL",
        "note": "Subsampled Delhi-NCR. Isolates network density from city differences.",
        "window": [args.date_from, args.date_to],
        "full_network_stations": len(all_stations),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    main()
