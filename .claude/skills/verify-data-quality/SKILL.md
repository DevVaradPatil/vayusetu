---
name: verify-data-quality
description: Run the data quality checks across VayuSetu's BigQuery tables — coverage, null rates, join integrity, unit sanity, and freshness. Use after any ingestion change, before training, and before the demo.
---

# Verify data quality

Silent data corruption is the most likely way this project produces a confidently wrong number on stage. This is the check that catches it.

Run it: after any ingestion change, before every training run, and the morning of the demo.

```bash
python ml/verify_data.py --tenant ncr --window 30d
```

## What it checks, and what a failure means

### 1. Coverage
| Check | Healthy | Failure means |
|---|---|---|
| Stations reporting in the last 3h | ≥ 70% of known stations | Ingestion broken, or OpenAQ having a bad day. Check which before assuming |
| Hours with any station data, last 30d | ≥ 95% | Scheduler gaps |
| Cells with satellite data, last 7d | ≥ 50% | Winter cloud is normal; below 30% suggests an extraction bug |
| Meteorology cell-hours, last 7d | ≥ 99% | Open-Meteo is reliable. A gap here is our bug |

### 2. Null rates per column
Compare against the previous run and flag any column whose null rate moved more than 10 percentage points. A sudden jump almost always means an upstream schema change or a broken join, and it is invisible in a map.

### 3. Join integrity — the important one
This is where the project most plausibly fails silently. After each join in `ml/features.sql`, assert:

- Row count is within 5% of expected — `n_stations × n_hours × n_pollutants` for the window.
- No join multiplied rows. If the count went **up**, a key is not unique and you now have duplicate training rows weighting some stations more than others.
- The satellite join (daily → hourly) fans out correctly: each station-hour gets exactly one satellite row for its date, not zero and not several.

A join that quietly drops 60% of rows looks exactly like a join that works. Only the count tells you.

### 4. Unit and range sanity
| Field | Valid range | Note |
|---|---|---|
| `pm25` | 0–1000 µg/m³ | Sentinel values like -999 and 9999 are common in CPCB feeds |
| `pm10` | 0–2000 µg/m³ | Should be ≥ pm25 at the same station-hour; flag violations |
| `wind_speed` | 0–150 m/s | Above 40 in NCR is almost certainly a unit error (km/h vs m/s) |
| `wind_dir` | 0–360° | |
| `blh` | 10–5000 m | Below 50 m happens in winter inversions and is real, not a bug |
| `rh` | 0–100 % | If you see 0–1, someone stored a fraction |
| `aod_maiac` | 0–5 | Unscaled MODIS values come as integers in the thousands — check the scale factor |
| `frp` | 0–10000 MW | |

### 5. Freshness
Every table gets a max `ingested_at`. Anything staler than twice its expected cadence is a failure. Print the table, not just a pass/fail — seeing "satellite last updated 31h ago" is more useful than a red cross.

### 6. Wind convention check
The one that silently inverts every source attribution: pick 20 hours with high PM2.5 and high upwind fire counts, and confirm the fires are actually **upwind**, not downwind. If attribution never lines up, this is the first thing to check. `wind_dir` is the direction wind comes **from**.

### 7. Duplicate detection
Assert primary-key uniqueness on every raw table (keys in `docs/DATA_CONTRACTS.md` §2). Ingestion jobs get retried; a non-idempotent upsert shows up here first.

## Output

Print a table of check, status, value, threshold. Exit non-zero on any failure so it can gate a training run.

Do not auto-fix anything. A check that quietly repairs data is a check that hides the bug that produced it.

## Before the demo

Run with `--strict`, which additionally fails on:
- Any station stale beyond 6h in the demo tenant
- Any null in `predictions_grid.residual` or `.confidence`
- Any `model_version` in predictions that does not match a registry model card
- Any alert row whose `recipients` contains something that is not a known mock account
