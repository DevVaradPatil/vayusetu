#!/usr/bin/env python3
"""Train and honestly evaluate Model A on REAL data. Writes ml/artifacts/evaluation_metrics.json."""
import json, os, pathlib, warnings
warnings.filterwarnings("ignore")
for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

import logging; logging.basicConfig(level=logging.WARNING)
from ml import realdata
from ml.evaluate import evaluate_loso_cv, _print_report

ds = realdata.load_from_bigquery(date_from="2025-10-25", date_to="2025-11-21")
summary = realdata.summarize(ds)
print(f"Loaded REAL data: {summary['n_rows']} rows, {summary['n_stations']} stations, "
      f"{summary['n_features']} features")
print(f"Window: {summary['ts_from'][:16]} -> {summary['ts_to'][:16]}\n")

results = evaluate_loso_cv(ds)
results["dataset"] = summary
_print_report(results)

out = pathlib.Path("ml/artifacts/evaluation_metrics.json")
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(f"  Written: {out}")
