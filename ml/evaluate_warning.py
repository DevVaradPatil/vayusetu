"""
ml/evaluate_warning.py — can we warn a day ahead that tonight will be Severe?

The track asks us to forecast air-quality spikes. This is the harness that tested it
and the reason no forecast endpoint ships. Findings: TODO.md 2026-09-12b.

Three things make this evaluation honest, and each one costs the rule skill:

1. **Real forecasts, not hindsight.** The `is_forecast=TRUE` rows in BigQuery cover
   September 2026 and do not overlap the November 2025 window, so they cannot be
   scored. Using the window's *observed* weather instead would grade the rule as if
   it had a perfect weather forecast. So the features come from Open-Meteo's archived
   model runs (`_previous_day1`): the same valid hour as it was predicted 24 hours
   earlier. Boundary layer height — our strongest driver — is NULL in that archive,
   which is itself a finding.

2. **Fair baselines.** Against nothing, any rule looks skilful. It is scored against
   always-warn (climatology), persistence (tonight was Severe), and the calendar
   ("warn after day k"). The calendar baseline is the one that matters: over 26
   consecutive days of a seasonal ramp, "it is mid-November" is a strong predictor,
   and a weather rule has to beat it to have shown anything.

3. **Thresholds fitted out of sample.** Leave-one-out: the threshold for each held-out
   night is chosen on the other 25 only. An in-sample threshold on 26 points would
   report roughly double the skill it has.

Run it: `python -m ml.evaluate_warning`
"""

from __future__ import annotations

import json
import logging
import os
import random
import statistics as st
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Sequence, Tuple

logger = logging.getLogger("vayusetu.ml.evaluate_warning")

# Delhi city centre. One point, because the target is a city-wide night, and the
# stagnation proxies vary little across 65 cells of one basin.
LAT, LON = 28.63, 77.31
WINDOW = ("2025-10-25", "2025-11-20")

# CPCB "Severe" for PM2.5. The night mean over 00:00-06:00 IST, which is when a
# collapsed inversion does its worst.
SEVERE = 250.0
NIGHT_HOURS = range(0, 7)

# Forecastable 24h ahead in the Open-Meteo archive. boundary_layer_height is
# deliberately absent: `boundary_layer_height_previous_day1` is NULL for every hour
# of the window, so the one driver with a clean physical mechanism cannot be used.
FIELDS = [
    "dew_point_2m", "relative_humidity_2m", "temperature_2m",
    "wind_speed_10m", "wind_direction_10m", "surface_pressure", "cloud_cover",
]

ARCHIVE = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def fetch_day_ahead(lead_days: int = 1) -> Dict[str, Dict[str, float]]:
    """Night-mean forecast features per IST date, as issued `lead_days` earlier."""
    suffix = f"_previous_day{lead_days}"
    params = {
        "latitude": LAT, "longitude": LON,
        "hourly": ",".join(f + suffix for f in FIELDS),
        "start_date": WINDOW[0], "end_date": WINDOW[1],
        "timezone": "Asia/Kolkata",
    }
    with urllib.request.urlopen(f"{ARCHIVE}?{urllib.parse.urlencode(params)}", timeout=90) as r:
        hourly = json.load(r)["hourly"]

    buckets: Dict[str, Dict[str, List[float]]] = {}
    for i, stamp in enumerate(hourly["time"]):
        date, clock = stamp.split("T")
        if int(clock[:2]) not in NIGHT_HOURS:
            continue
        night = buckets.setdefault(date, {f: [] for f in FIELDS})
        for f in FIELDS:
            v = hourly[f + suffix][i]
            if v is not None:
                night[f].append(v)
    return {d: {f: st.mean(v) for f, v in fs.items() if v} for d, fs in buckets.items()}


def fetch_nights(project: str, tenant: str = "ncr") -> Dict[str, float]:
    """Observed night-mean PM2.5 per IST date, the thing a warning would be about."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    rows = client.query(f"""
        SELECT CAST(DATE(ts, 'Asia/Kolkata') AS STRING) AS d, AVG(value) AS pm
        FROM `{project}.vayusetu_{tenant}.raw_stations`
        WHERE pollutant = 'pm25' AND value IS NOT NULL
          AND EXTRACT(HOUR FROM DATETIME(ts, 'Asia/Kolkata')) BETWEEN 0 AND 6
        GROUP BY d
    """).result()
    return {r.d: float(r.pm) for r in rows}


def contingency(pred: Dict[str, bool], truth: Dict[str, bool],
                days: Sequence[str]) -> Tuple[int, int, int, int, float, float, float]:
    """hits, misses, false alarms, correct negatives, POD, FAR, Peirce skill score."""
    hits = sum(1 for d in days if pred[d] and truth[d])
    misses = sum(1 for d in days if not pred[d] and truth[d])
    false = sum(1 for d in days if pred[d] and not truth[d])
    correct = sum(1 for d in days if not pred[d] and not truth[d])
    pod = hits / (hits + misses) if hits + misses else 0.0
    far = false / (false + correct) if false + correct else 0.0
    # Peirce (Hanssen-Kuipers): POD - FAR. Zero for always-warn AND never-warn, which
    # is exactly why it is used here: both of those are useless and both score 0.
    return hits, misses, false, correct, pod, far, pod - far


def loo_threshold_rule(value: Callable[[str], float], truth: Dict[str, bool],
                       days: Sequence[str]) -> Dict[str, bool]:
    """
    Warn when `value(day) <= threshold`, with the threshold fitted leave-one-out.

    Fitting on all 26 nights and scoring on the same 26 is how a 26-point dataset
    reports skill it does not have.
    """
    pred: Dict[str, bool] = {}
    for held in days:
        train = [d for d in days if d != held]
        best_th, best_score = None, float("-inf")
        for th in sorted({round(value(d), 2) for d in train}):
            trial = {d: value(d) <= th for d in train}
            score = contingency(trial, truth, train)[6]
            if score > best_score:
                best_th, best_score = th, score
        pred[held] = value(held) <= best_th
    return pred


def demo() -> None:
    import pathlib

    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    feats = fetch_day_ahead(1)
    feats48 = fetch_day_ahead(2)
    nights = fetch_nights(os.environ["GCP_PROJECT_ID"])
    days = [d for d in sorted(feats) if d in nights]
    truth = {d: nights[d] >= SEVERE for d in days}
    order = {d: i for i, d in enumerate(days)}
    n_sev = sum(truth.values())

    print(f"{len(days)} nights, {n_sev} Severe (>= {SEVERE:.0f} ug/m3), "
          f"base rate {n_sev / len(days):.0%}")
    print("Warning issued a day ahead, from archived model runs (a real 24h lead).\n")

    # The confound first, because it decides how to read everything after it.
    def corr(xs: Sequence[float], ys: Sequence[float]) -> float:
        mx, my = st.mean(xs), st.mean(ys)
        sx, sy = st.pstdev(xs), st.pstdev(ys)
        if not sx or not sy:
            return 0.0
        return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (len(xs) * sx * sy)

    def detrend(xs: Sequence[float], ts: Sequence[float]) -> List[float]:
        mt, mx = st.mean(ts), st.mean(xs)
        slope = (sum((t - mt) * (x - mx) for t, x in zip(ts, xs))
                 / sum((t - mt) ** 2 for t in ts))
        return [x - (mx + slope * (t - mt)) for t, x in zip(ts, xs)]

    pm = [nights[d] for d in days]
    idx = [float(order[d]) for d in days]
    print(f"The calendar alone: r = {corr(idx, pm):+.3f} with night PM2.5. "
          "Anything that trends with the season inherits this.\n")
    print(f"  {'predictor (24h lead)':24s} {'r':>7} {'r vs day':>9} {'partial':>9}")
    pm_detrended = detrend(pm, idx)
    for f in FIELDS:
        xs = [feats[d][f] for d in days]
        print(f"  {f:24s} {corr(xs, pm):+7.3f} {corr(xs, idx):+9.3f} "
              f"{corr(detrend(xs, idx), pm_detrended):+9.3f}")

    persistence = {d: (truth[days[order[d] - 1]] if order[d] else False) for d in days}
    rules = [
        ("always warn (climatology)", {d: True for d in days}),
        ("never warn", {d: False for d in days}),
        ("persistence: tonight was Severe", persistence),
        ("forecast dew point low (LOO)",
         loo_threshold_rule(lambda d: feats[d]["dew_point_2m"], truth, days)),
        ("forecast humidity low (LOO)",
         loo_threshold_rule(lambda d: feats[d]["relative_humidity_2m"], truth, days)),
        ("same, 48h lead (LOO)",
         loo_threshold_rule(lambda d: feats48[d]["dew_point_2m"], truth, days)),
        ("calendar only: warn after day k (LOO)",
         loo_threshold_rule(lambda d: -float(order[d]), truth, days)),
    ]

    print(f"\n  {'rule':38s} {'hit':>4} {'miss':>5} {'false':>6} {'POD':>6} {'FAR':>6} {'Peirce':>8}")
    scores = {}
    for name, pred in rules:
        h, m, fa, _, pod, far, pss = contingency(pred, truth, days)
        scores[name] = pss
        print(f"  {name:38s} {h:4d} {m:5d} {fa:6d} {pod:6.2f} {far:6.2f} {pss:+8.2f}")

    weather = scores["forecast dew point low (LOO)"]
    calendar = scores["calendar only: warn after day k (LOO)"]
    persist = scores["persistence: tonight was Severe"]

    # Does the weather rule's edge over persistence survive resampling? With 10 events
    # a two-night difference is not a result.
    random.seed(7)
    dew = dict(rules[3][1])
    gaps = []
    for _ in range(4000):
        sample = [random.choice(days) for _ in days]
        gaps.append(contingency(dew, truth, sample)[6] - contingency(persistence, truth, sample)[6])
    gaps.sort()
    lo, hi = gaps[200], gaps[3800]

    print(f"\nforecast minus persistence: {weather - persist:+.2f} "
          f"(bootstrap 90% CI {lo:+.2f} .. {hi:+.2f})")

    assert calendar >= weather, (
        "The calendar baseline no longer wins. That would be a real result — check "
        "whether the window now spans more than one seasonal ramp before believing it."
    )
    assert lo < 0 < hi, "the CI no longer straddles zero; re-read the finding"

    print("\n[FALSIFIED] 'warn after day k' scores "
          f"{calendar:+.2f} against the weather rule's {weather:+.2f}: the apparent skill "
          "is the seasonal ramp, and the edge over persistence straddles zero.")
    print("            No forecast endpoint ships. Alerts fire on observed conditions.")
    print("            See TODO.md 2026-09-12b.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    demo()
