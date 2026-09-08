---
name: train-and-evaluate
description: Train and honestly evaluate a VayuSetu model using leave-one-station-out cross-validation and the required baselines. Use before reporting ANY model metric, and whenever training, retraining, or validating the grid estimator or the forecaster.
---

# Train and evaluate

**Run this before reporting any model number.** The protocol below is the difference between a metric that means something and one that doesn't.

## Why this exists

The obvious approach — shuffle the rows, hold out 20% — is catastrophically wrong on this data. Consecutive hours at one station are nearly identical, so a random split puts near-duplicate rows on both sides. You will get an R² above 0.95, feel great, and have measured nothing except that the model can memorise a station.

What we actually claim is: *"we can estimate PM2.5 at a location with no monitor."* The evaluation must mirror that claim exactly. Hold out **entire stations**.

## Protocol — Model A (gridded estimator)

### 1. Build the feature table
```bash
bq query --use_legacy_sql=false < ml/features.sql
```
Check the assertions printed at the end. If null rates jumped or row counts dropped since the last run, **stop and investigate before training.** A join that silently drops 60% of rows looks exactly like a join that works.

### 2. Leave-one-station-out CV
```bash
python ml/evaluate.py --model grid --cv loso
```

The protocol, if you are implementing or reviewing it:
```
for each station s in stations:
    train on all rows where station_id != s
    predict rows where station_id == s
    record MAE, RMSE, R², bias on those predictions
report mean and standard deviation across stations, plus the per-station table
```

Use `GroupKFold(groups=station_id)` if you want folds instead of full LOSO — that is acceptable and faster. `train_test_split`, `shuffle=True`, or `KFold` without groups is **not**.

### 3. Compare against baselines — mandatory
| Baseline | What it is |
|---|---|
| IDW interpolation | 4 nearest stations, power 2, max 50 km — from `ml/common.py` |
| Station mean | Per-station historical mean |

If the model does not beat IDW at held-out stations, it has no reason to exist. Say so rather than shipping it.

### 4. Look at the per-station table, not just the mean
A model with mean MAE 30 that has one station at MAE 90 is telling you something — usually that the station sits in a land-use class underrepresented in training. Note it in the model card. This kind of observation reads as real work.

## Protocol — Model B (forecaster)

### 1. Time-based split, never random
Train on everything before a cutoff, test after it. Random splitting a time series leaks the future into the past.

```bash
python ml/evaluate.py --model forecast --split temporal --cutoff 2025-06-01
```

### 2. Baselines — mandatory
| Baseline | What it is |
|---|---|
| Persistence | Value at t+h equals value at t |
| Climatology | 7-day seasonal mean for that hour |

Beating persistence at +24h is genuinely hard for air quality. 15–25% improvement is a real result. Report per-horizon (+6, +24, +48, +72) — performance degrades with horizon and hiding that behind an average is dishonest.

### 3. Calibration of the confidence band
Check that roughly 80% of actuals fall inside `[p10, p90]`. If it is 50%, the band is too narrow and every downstream confidence number is wrong.

## Expected ranges — a sanity check, not a target

| Metric | Expected |
|---|---|
| Model A LOSO MAE | 25–40 µg/m³ |
| Model A LOSO R² | 0.60–0.75 |
| Model B +24h MAE improvement over persistence | 15–25% |
| p10–p90 coverage | ~80% |

**If you see R² above 0.90 on Model A, you have a leak.** Do not celebrate it. Go find it — the usual culprits are a random split, a station id left in the features, or a target-derived feature such as a lagged value of the label at the same station.

## Recording the result

Every trained model gets a model card conforming to `spec/model-card.schema.json`, containing the **LOSO** numbers, not in-sample ones, plus the baseline comparison. Register it in Vertex AI Model Registry. A prediction that cannot be traced to a model card is not usable as evidence.

## The reporting rule

Report the honest number. An R² of 0.68 with correct methodology beats a 0.97 from a leaked split, because at least one judge will ask how we split — and being able to answer that question well is worth more than any single metric.
