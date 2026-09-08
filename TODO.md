# Human TODO — VayuSetu

Updated 2026-09-07 after the first live API run. Items are ordered by what blocks
the most downstream work.

---

## BLOCKING

### ~~Gemini API~~ — RESOLVED 2026-09-08
Both `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite` verified working. Held
back from the pipeline for now by request.

### ~~Earth Engine~~ — RESOLVED 2026-09-08
Nothing further was needed. The API was already enabled and the existing ADC
credentials carry the Earth Engine scope, so `ee.Initialize(project=...)` works
without a separate `earthengine authenticate`. Verified against real data:
595 MAIAC images and 85 Sentinel-5P images for the hero window.

Backfilled: 1,755 cell-days of satellite (80% AOD coverage) and 66 cells of static
layers (GHSL population, WorldCover built-up/cropland, SRTM elevation).

`dist_major_road_m` stays NULL — Earth Engine has no free global roads layer; it
would need OSM, which is not worth adding for one feature.

### (historical) Gemini API — prepayment credits depleted

The key in `.env` is valid (it lists 54 models, and both
`gemini-3.1-flash-lite` and `gemini-3.5-flash-lite` exist). But every
`generateContent` call returns:

```
429: Your prepayment credits are depleted. Please go to AI Studio
     at https://ai.studio/projects to manage your project and billing.
```

This is a **billing** state, not a rate limit — the 500 rpd free allowance is not
active on the project the key belongs to. Note the key was created under
`varadpatilgdscrit@gmail.com`; the AI Studio project behind it is separate from the
GCP project and needs its own billing/free-tier check at
[ai.studio/projects](https://ai.studio/projects).

Blocks all four Gemini features: photo triage, source attribution, Ask Vayu,
multilingual advisories.

### 2. Earth Engine registration

`earthengine-api` is installed and the GCP project now works, but the project still
needs registering at [earthengine.google.com](https://earthengine.google.com/) plus
`earthengine authenticate`. Gates the satellite backfill (W1.9) that Model A needs.

---

## RESOLVED 2026-09-07

### ~~No usable GCP project~~ — FIXED

`gcloud projects list` for `varadapatil123@gmail.com` shows neither project:

| Project | Where it came from | Status |
|---|---|---|
| `vayusetu-507904` | `.env` `GCP_PROJECT_ID` | **Not in the account's project list** |
| `civicpulse-v2s-01` | `gcloud config` + ADC quota project | **Permission denied / does not exist** |

Application Default Credentials authenticate fine, but every BigQuery call fails
because the quota project is unresolvable.

`vayusetu-507904` is now accessible. ADC quota project set, BigQuery/Storage APIs
enabled, all three datasets and 16 tables created, and real data landed.

---

## WORKING — verified live on 2026-09-07

| Source | Status |
|---|---|
| OpenAQ v3 | Working. 118 NCR stations found, real PM2.5 values ingested |
| NASA FIRMS | Working. 3 detections over NCR+200 km in 2 days (September, not stubble season) |
| Open-Meteo | Working, no key needed. `boundary_layer_height` confirmed available |
| Maps JS key | Present in `.env`, not yet exercised in the browser |

---

## FINDING 2026-09-08c — Model B also loses; attribution is the pillar that holds

### Model B (forecasting) — fails against the fair baseline

First run looked like a win: +42% over persistence at +6h, and the perfect-forecast
inflation was small (+46.6% with target-hour reanalysis vs +42.1% with issue-time
only), so the skill was not borrowed from assuming perfect weather.

**But plain persistence is a strawman at +6h.** A 6-hour-ahead forecast issued at
09:00 targets 15:00, and PM2.5 has a strong diurnal cycle — so "the value 6 hours
ago" is a bad guess for structural reasons, not because forecasting is hard. The
fair baseline is *diurnal persistence*: the same clock hour one day earlier.

Against it (issue-time meteorology only, operationally realistic):

| Horizon | Model | Persistence | **Diurnal** | vs diurnal |
|---|---|---|---|---|
| +6h | 57.77 | 93.15 | **54.75** | **-5.5%** |
| +24h | 64.10 | 53.30 | 53.30 | -20.3% |
| +48h | 84.63 | 66.70 | 55.87 | -51.5% |
| +72h | 95.60 | 75.10 | 59.78 | -59.9% |

**The model loses at every horizon.** Interval coverage is also 0.56-0.70 against a
0.80 target, so the confidence bands are too narrow and any downstream confidence
score built on them would be overconfident.

### Where that leaves the ML claims

| Component | Verdict |
|---|---|
| Model A — gridded estimation | Loses to IDW at every density (5-67 stations) |
| Model B — forecasting | Loses to diurnal persistence at every horizon |
| Satellite AOD explaining IDW error | r = +0.04. No signal |
| **Fire-based source attribution** | **Holds — see below** |

On this data the *predictive* ML does not beat simple baselines. That is the result.

### Attribution — the pillar that survives

Daily city-mean PM2.5 against the physical drivers, 26 days of the real stubble
season:

```
corr(PM2.5, upwind fire count)      = +0.547
corr(PM2.5, boundary layer height)  = -0.420
corr(PM2.5, wind speed)             = +0.041
```

The mechanism is visible in the raw data:

| Date | PM2.5 | Upwind fires | BLH |
|---|---|---|---|
| 2025-11-02 | 167.9 | 1.0 | 470 m |
| 2025-11-06 | 180.8 | 16.5 | 401 m |
| **2025-11-10** | **299.4** | 12.9 | **107 m** |
| **2025-11-18** | **245.4** | 11.4 | **102 m** |

Fires upwind plus a collapsed boundary layer produce the severe episodes. Correct
signs, meaningful magnitudes, real data.

**This is what the product should be built on.** Attribution explains *why* a spike
happened and *who to call* — and unlike estimation and forecasting, it never needed
to beat a statistical baseline to be useful. It is also the half no AQI app offers.

### Do not

- Do not report the +42%-over-persistence figure. It was a strawman baseline and is
  superseded by the diurnal comparison.
- Do not present forecast confidence bands as calibrated; coverage is 0.56-0.70.

---

## FINDING 2026-09-08b — the blind-spot thesis is not supported by this data

Option A was to test whether the model earns its place in *sparse* networks. It
does not. Two independent tests, both negative.

### Test 1 — density sweep (controlled)

Subsampled NCR to simulate sparser networks, holding data, geography and period
fixed. Both model and IDW are handicapped equally as N falls. 3 random draws each.

| Stations | Median nearest neighbour | Gap vs IDW |
|---|---|---|
| 5 | 16.4 km | **-13.1%** |
| 8 | 6.7 km | -7.1% |
| 12 | 4.6 km | -7.5% |
| 67 (full) | 2.8 km | -3.3% |

The model loses at **every** density, and loses *worse* as the network sparsifies —
fewer stations means less training data, and that hurts the model more than it
hurts interpolation. The sparse-network hypothesis is dead.

### Test 2 — does satellite explain where IDW is wrong?

If AOD saw local pollution the ground network misses, it should correlate with IDW's
error. Tested at AOD's native daily cadence (1,683 station-days):

```
corr(daily IDW error, AOD)         = +0.024
corr(daily IDW error, AOD anomaly) = +0.042

mean IDW error where AOD anomaly HIGH: +4.5 ug/m3
mean IDW error where AOD anomaly LOW : -1.2 ug/m3
```

Directionally correct, practically useless: 5.7 ug/m3 of separation against a
~53 ug/m3 error.

### Conclusion

**On Delhi-NCR winter data, neither a trained model nor satellite AOD improves on
interpolation between ground stations.** The residual (`pred - idw`) is not a
validated hotspot signal, at any network density.

Plausible physical reason: winter NCR PM2.5 is dominated by a regional smog blanket.
Genuine within-city variation exists but is driven by very local sources — traffic,
construction, waste burning — that neither 1 km column AOD nor 10 m land use
resolves. With stations ~2.8 km apart, IDW already captures the field about as well
as the available data allows.

### What this means for the submission

The "we find hotspots the official network is blind to" claim **cannot be made** on
this evidence. It must be dropped or replaced, not softened.

What survives, and is untouched by this result:
- **Source attribution** — real FIRMS fires + wind + NO2 explaining *why* a spike
  happened. Novel, operationally useful, and it never depended on beating IDW.
- **Forecasting (Model B)** — a different task. Untested on real data.
- **Alerting, multilingual advisory, federation** — operational layers.

### Do not

- Do not keep tuning for a win. Three feature sets and six network densities have
  now been tested; the pattern is stable and the effect size is not marginal.
- Do not present the residual map. It is not a validated signal.
- Do not quote the one +4.5% subsample as evidence; it is one draw of three at N=12
  and the mean for that size is -7.5%.

---

## FINDING 2026-09-08 — satellite features did NOT fix the gap

Earth Engine unblocked, MAIAC AOD + Sentinel-5P + GHSL population + WorldCover
land use all backfilled and joined. The hypothesis was that per-cell spatial
features would let Model A beat IDW. **It was wrong.**

| Feature set | MAE | vs IDW |
|---|---|---|
| 18 (meteorology + fires) | 54.57 | -3.1% |
| 20 (+ lat/lon) | 53.81 | -1.7% |
| **27 (+ AOD, NO2, population, land use)** | **54.68** | **-3.3%** |

Adding the satellite and static layers made it slightly *worse*. More features, more
overfitting to training stations' idiosyncrasies, no better transfer.

### Second hypothesis, also wrong

Next guess: LOSO with 66 remaining stations is the easiest case for IDW (median
nearest-neighbour distance 2.8 km, 20 stations within 2 km, some co-located), so
maybe the model wins where stations are sparse — the case the product is actually
about. Stratifying the same run by distance to nearest station:

| Nearest station | n | Model MAE | IDW MAE | Delta |
|---|---|---|---|---|
| 0-2 km | 20 | 54.07 | 57.96 | **+6.7%** |
| 2-5 km | 33 | 53.90 | 50.08 | -7.6% |
| >5 km | 14 | 65.71 | 59.11 | **-11.2%** |

The opposite. The model is **worst exactly where the product needs it most** —
isolated locations. Isolated stations sit in regimes underrepresented in training
(peri-urban, different emission profile), and a tree model cannot extrapolate to
them.

### The honest conclusion

**On dense-network NCR data, the gridded model does not add value over
interpolation.** IDW is the better estimator here, and that is a real result, not a
tuning failure.

This matters strategically, because the residual (`pred - idw`) is the product. If
the model is not better than IDW, a positive residual is mostly *model error*, not
a discovered hotspot. The core claim needs re-examining before any residual map is
presented as validated.

### What is NOT established

- That the approach fails in sparse networks. NCR has 67 stations in ~80 km; most
  Indian cities have a handful. IDW degrades fast below ~2 stations within 50 km
  (`compute_idw_baseline` returns None), and that is where a satellite model should
  earn its place. Untested — this is what the Lucknow transfer should measure.
- That Model B (forecasting) fails. Different task, untested on real data, and
  temporal prediction does not depend on beating spatial interpolation.

### Do not

- Do not present a residual hotspot map as validated. It is not.
- Do not tune features until the number flips; three feature sets have now been
  tried and the pattern is stable.
- Do not quote the +6.7% dense-band figure in isolation. It is one band of a
  stratification that is negative overall, and post-hoc.

---

## FINDING 2026-09-07 — Model A does not beat IDW on real data

First honest evaluation on real observations. Reported as-is per AGENTS.md R2.

| | MAE | RMSE | R2 |
|---|---|---|---|
| Model A (20 features) | **53.81** | 78.47 | 0.5285 |
| IDW baseline | **52.93** | 80.81 | 0.5000 |
| Station mean | 90.73 | 114.65 | -0.0064 |

67 stations, 35,198 rows, leave-one-station-out, 2025-10-25..2025-11-19.
**The model is 1.7% worse than interpolation on MAE.** It wins on RMSE and R2, but
MAE is the headline and it loses. `publish_model_card()` refuses it — the R2 guard
fires exactly as designed, so this model cannot reach the registry.

### Why — measured, not guessed

| | |
|---|---|
| Real PM2.5 variation across stations **within one hour** | **61.5 ug/m3** |
| Variation the model's features can see | ~7.5 |
| Temporal features (hour, day, season) across stations | **exactly 0** |

Every NCR station shares essentially the same meteorology at a given hour, so the
model cannot distinguish one location from another and predicts near the regional
mean. IDW at least uses spatial proximity.

Adding lat/lon (the only spatial signal available without Earth Engine) moved the
gap from -3.1% to -1.7%. Real improvement, not enough. Coordinates say *where* a
station is but nothing about *what is there*.

### What this means

The features that differ between locations are **exactly the Earth Engine ones**:
per-cell MAIAC AOD, population, built-up fraction, land use, road distance. Their
absence is not incidental to this result — it is the cause.

**Earth Engine registration is therefore the critical path, not a nice-to-have.**
It is the difference between a gridded model that justifies its existence and one
that does not.

The residual layer still functions — it is defined against IDW regardless. What is
unproven is that the model's estimate is *better* than IDW's own error, which is
the claim the product rests on.

### Do not

- Do not swap the headline metric to RMSE or R2 because MAE is unflattering.
- Do not train on more months and quote an improvement without re-running LOSO.
- Do not present a residual map as validated until the model beats IDW.

---

## HERO EPISODE FROZEN 2026-09-07 — 10-13 November 2025

Chosen from the real backfill rather than assumed. Daily city means with >=20
stations reporting:

| Date | Stations | Mean PM2.5 | Peak |
|---|---|---|---|
| **2025-11-10** | 68 | **299.4** | 665.0 |
| **2025-11-11** | 68 | 271.3 | 768.9 |
| **2025-11-12** | 68 | 254.7 | 932.6 |
| **2025-11-13** | 67 | 241.4 | 750.0 |

A genuine Severe episode with dense coverage — 68 of ~70 stations reporting, which
is the densest the network gets. Set `REPLAY_AS_OF` inside this window for the demo.

Contrast for the video: the same pipeline running live today sees 7 stations and
~50 ug/m3. The replay is disclosed as a replay, per AGENTS.md R7.

---

## DECISION MADE 2026-09-07 — historical backfill, replay-first

The "only 7 live stations" problem turned out to be a **live-view problem only**.
Checking historical availability changed the picture entirely:

| | |
|---|---|
| pm25 sensors in NCR | 167 |
| Spanning Oct-Nov 2025 (last stubble season) | **116** |
| Reporting within 72h right now | 7 |

`/v3/sensors/{id}/measurements` accepts `datetime_from`/`datetime_to` with
pagination, so months of real history are available for stations that are quiet
today. None of the three options originally listed were needed:

- Adding CPCB's own API would buy live density we do not need for the demo.
- Widening the bbox would add stations, not history.

**Decision: build the historical backfill and run the product replay-first.**

Why this is the right call rather than a workaround:

1. **Model A needs history regardless.** Training on `/latest` was never possible —
   it returns one reading per sensor. The backfill was required work, not a detour.
2. **The demo was always going to be a replay** (plan.md §1). Replay against 116
   stations is a far better demo than live against 7.
3. **It makes the IDW baseline real.** `compute_idw_baseline` needs >=2 stations
   within 50 km; with 116 that is comfortably satisfied, so the residual — the
   product — is measured against a genuine baseline.
4. **It costs nothing extra.** No new API, no new key, no new architecture.

The live path still runs (`run_ingest.py`) and still shows 7 stations. That is
honest and stays in the UI as the live view, greyed where stale. The console's
default view is the replay window.

Implementation: `backfill_stations.py`, plus `fetch_sensor_measurements()` and
`measurements_to_hourly()` in `ingestion/stations.py`. Sub-hourly CPCB readings
(~15-minute cadence) are averaged into the hourly rows the contract specifies.

---|---|
| 3 hours | **7** |
| 72 hours | 7 |
| 7 days | 79 |

Seven stations are live right now; ~72 more went silent 4-7 days ago, which looks
like a stalled CPCB→OpenAQ feed rather than mass hardware failure.

Historical data is fine — `/v3/sensors/{id}/measurements` returns paginated history
(verified back to Feb 2025), so **model training is unaffected**.

What it does affect:
- The IDW baseline gets weaker (needs >=2 stations within 50 km).
- A live demo on 7 points will look sparse.

Options, roughly in order of preference:
1. **Lean on replay mode** for the demo, as already planned, and treat the live
   view as a secondary tab. Cheapest, and already the plan of record.
2. **Add CPCB's own API** as a second source alongside OpenAQ. More live stations,
   more ingestion work.
3. **Widen the bbox** to include more of the NCR periphery. Marginal gain.

This is a product call, not a technical one — worth deciding before the demo script
is written.
