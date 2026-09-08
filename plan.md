# VayuSetu — Build Plan
### Track 02: Clean Air & Climate Resilience | Build with AI: Code for Communities

> **One-liner (submission field):** VayuSetu explains India's air pollution episodes — fusing government station readings, NASA fire detections, satellite aerosol data and meteorology to tell officials *why* the air is bad right now, which upwind district to act on, and to deliver the public advisory in ten Indian languages.

> ## ⚠️ THESIS REVISED — 2026-09-08
>
> This document's original thesis was the **residual**: model-estimated PM2.5 minus
> station interpolation, with a large positive residual signalling a hotspot the
> official network is blind to.
>
> **That thesis was tested on real data and failed.** Model A loses to IDW at every
> network density from 5 to 67 stations; satellite AOD does not explain where IDW
> errs (r = +0.04); and Model B loses to diurnal persistence at every horizon. The
> evidence is in `TODO.md` findings 2026-09-08, 08b and 08c.
>
> **The product is now attribution-first**: what happened, *why* it happened, and
> who should act. That pillar was measured and holds — upwind fire count correlates
> +0.55 with city PM2.5 and boundary-layer height -0.42 over the real November 2025
> episode.
>
> Sections below that describe the residual layer, the gridded hotspot map, or
> Model A/B as validated products are **superseded**. The architecture, data
> contracts, ingestion design and federation plan all still stand.

---

## 0. The thesis (read this before anything else)

Delhi-NCR has roughly 40 continuous ambient air quality monitoring stations inside Delhi and around 80 across the wider NCR, covering a population above 30 million. A station represents its immediate surroundings; between stations there are blind spots several kilometres wide. A brick kiln cluster, a construction site, a landfill fire or a waste-burning pocket can push local PM2.5 far above what the nearest official monitor reports, and nothing in the current system notices.

**That gap is the product.** We are not building another AQI display. We are building the thing that says:

> *"Grid cell 28.63N/77.31E is at an estimated PM2.5 of 310 µg/m³ right now. The nearest official station reads 180. 84,000 people live in this cell. The likely cause is 47 active fire pixels 22 km upwind in Sonipat with a 310° wind at 11 km/h. Confidence: 0.78. Three citizen photos in the last hour independently report heavy haze."*

Everything in this plan exists to make that paragraph true, verifiable, and reproducible in any Indian city.

**Why this wins on the rubric:** it is the only shape of solution on this track where (a) all the input data is real and free, (b) the AI has a genuinely hard job rather than being an API wrapper, and (c) the demo has a single moment — official says fine, we say hotspot, and we can prove who is right — that a judge will remember.

---

## 1. Non-negotiable design decisions

These are decided. Do not relitigate them mid-build.

| Decision | Choice | Why |
|---|---|---|
| Deep corridor | Delhi-NCR (Delhi, Gurugram, Noida, Ghaziabad, Faridabad) | Densest station coverage, strongest fire signal, instantly legible to judges |
| Federation partner city | Lucknow | Different state, different pollution profile, still has CPCB stations. Proves cross-state transfer, not just cross-city |
| Grid resolution | 1 km × 1 km | Matches MAIAC AOD native resolution. Finer is fake precision |
| Hero demo mode | **Replay of a real historical episode** | Deterministic, reproducible, works in any month. Disclosed openly in the deck |
| Mobile strategy | PWA, not a native app | Camera + geolocation work fine in a browser. A native app buys nothing and costs a week |
| Model type | Gradient boosting (LightGBM), not deep learning | Tabular data, modest sample, needs to train in minutes. A neural net here is a worse model and a slower build |
| Auth | Firebase Auth — anonymous for citizens, email for officials | Citizens must not face a signup wall |

### The replay-mode decision, explained

Stubble burning peaks in October–November. If you demo in another month the hero scenario is dead. So build a **replay mode** from day one: every ingestion module takes an `as_of` timestamp, and the whole system can be driven from archived BigQuery data for a chosen historical date range.

This is not a cheat and must not be presented as one. Say plainly in the video and the deck: *"This is a replay of the real 4–8 November 2024 Delhi episode using archived data. The live pipeline runs on the same code path — here it is running on today's data."* Then show the live view for ten seconds. Judges reward this kind of honesty; they punish teams who get caught faking it.

It also gives you something more valuable: a **backtest**. You can show the model's forecast against what actually happened, which is the single most credible thing in the entire submission.

---

## 2. Architecture

```
                          ┌──────────────────────────────────┐
   Cloud Scheduler ──────▶│  Ingestion Jobs (Cloud Run Jobs) │
   (hourly / daily)       │  stations · fires · satellite ·  │
                          │  meteorology · population        │
                          └────────────────┬─────────────────┘
                                           │
                                    ┌──────▼───────┐
                                    │   BigQuery   │  raw_* → features_* → predictions_*
                                    └──────┬───────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
          ┌─────────▼─────────┐  ┌─────────▼─────────┐  ┌─────────▼──────────┐
          │  Vertex AI        │  │  Inference Job    │  │  Federated Model   │
          │  Training +       │  │  (Cloud Run Job)  │  │  Registry (GCS +   │
          │  Model Registry + │  │  grid + forecast  │  │  BigQuery + spec)  │
          │  Endpoint         │  │  + hotspot rules  │  │                    │
          └───────────────────┘  └─────────┬─────────┘  └────────────────────┘
                                           │
                                  ┌────────▼─────────┐
                                  │    Firestore     │  live state, hotspots,
                                  │                  │  alerts, citizen reports
                                  └────────┬─────────┘
                                           │
       ┌───────────────────────────────────┼───────────────────────────────┐
       │                                   │                               │
┌──────▼────────┐              ┌───────────▼───────────┐        ┌──────────▼─────────┐
│ FastAPI       │◀────────────▶│  React Dashboard      │        │  Citizen PWA       │
│ (Cloud Run)   │              │  (Vite + Maps + deck) │        │  (same React app)  │
│ + Gemini agent│              └───────────────────────┘        └──────────┬─────────┘
└───────┬───────┘                                                          │
        │                                                    photo upload  │
        │           ┌──────────────────────────────┐                       │
        └──────────▶│  Gemini 2.5 (Flash + Pro)    │◀──────────────────────┘
                    │  vision triage · source      │
                    │  briefs · agent · advisories │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ Translation API + Cloud TTS  │  10 Indian languages, voice-first
                    └──────────────────────────────┘
```

### Google services used, and what each one actually does

Nothing here is decorative. If a service cannot be justified in one sentence, it is not in the build.

| Service | Job it does | Rubric line it serves |
|---|---|---|
| **Gemini 2.5 Flash** (multimodal) | Grades citizen photos: haze severity, visibility estimate, visible source classification, validity gate | AI execution |
| **Gemini 2.5 Pro** | Writes grounded source-attribution briefs; powers the "Ask Vayu" function-calling agent | AI execution |
| **Vertex AI** | Custom training job, Model Registry, versioned endpoints for both models | AI execution, deployability |
| **Earth Engine** | Sentinel-5P NO₂ / aerosol index, MAIAC AOD, ERA5 meteorology, WorldCover, GHSL population | AI execution, reach |
| **BigQuery** | Every raw observation, feature table, prediction, backtest. National-scale by construction | Reach, deployability |
| **Firestore** | Live state the dashboard subscribes to; citizen reports; alert inbox | Deployability |
| **Cloud Run + Jobs + Scheduler** | All compute. Scales to zero, costs nothing idle | Deployability |
| **Maps Platform** (Maps JS, Geocoding) | Base map, grid overlay, geocoding of citizen reports | Fit |
| **Translation API + Cloud TTS** | 10-language advisories, spoken output for low-literacy users | Reach |
| **Cloud Storage** | Citizen photos, exported model artifacts, federation registry payloads | Deployability |
| **Firebase Auth** | Anonymous citizen sessions, official accounts | Deployability |

**Deliberately not used:** Vertex AI Vision (Gemini multimodal already covers it — two vision stacks is waste), Dialogflow (Gemini function calling is strictly better here), AutoML (LightGBM trains in two minutes and you control the features).

---

## 3. Data sources — exact, with the gotchas

| Source | What it gives | Access | Cadence | Gotcha |
|---|---|---|---|---|
| **OpenAQ v3** | CPCB station PM2.5, PM10, NO₂, SO₂, CO, O₃ | REST, needs free `X-API-Key` | Hourly | Stations drop out for hours or days. Never assume a station reported |
| **CPCB CAAQMS portal** | Same data, authoritative | Scrape / official API | Hourly | Backup only. Use OpenAQ as primary |
| **NASA FIRMS** | VIIRS 375 m active fire pixels, near-real-time | REST, free `MAP_KEY` | ~3 h latency | This is your stubble-burning signal. Highest-value single feed |
| **Sentinel-5P** | NO₂ column, UV aerosol index | Earth Engine: `COPERNICUS/S5P/NRTI/L3_NO2`, `COPERNICUS/S5P/OFFL/L3_AER_AI` | Daily, ~13:30 local overpass | ~7 km resolution — good for regional plumes, not street level |
| **MODIS MAIAC AOD** | Aerosol optical depth at 1 km | Earth Engine: `MODIS/061/MCD19A2_GRANULES` | Daily | Cloud-masked. Winter Delhi has cloud and fog gaps — you will have missing days |
| **ERA5-Land** | Historical wind, temperature, humidity | Earth Engine: `ECMWF/ERA5_LAND/HOURLY` | Hourly, ~5 day lag | Training features only, never live |
| **Open-Meteo** | Forecast wind speed/direction, temp, RH, boundary layer height | REST, no key | Hourly, 7-day forecast | Free, no auth, generous limits. Your live meteorology |
| **GHSL population** | Population per grid cell | Earth Engine: `JRC/GHSL/P2023A/GHS_POP` | Static | Powers the exposure metric — the number that makes impact concrete |
| **ESA WorldCover** | Land use class (built-up, cropland, industrial proxy) | Earth Engine: `ESA/WorldCover/v200` | Static | Strong feature. Built-up fraction correlates hard with PM2.5 |

### The satellite cadence problem — handle it honestly

Satellites pass overhead roughly once a day. Stations report hourly. This means:

- The **1 km gridded PM2.5 estimate is a daily product**, anchored to the satellite overpass window, with hourly refinement from stations and meteorology.
- The **72-hour forecast is hourly**, driven by station history plus meteorological forecast plus upwind fire counts.

Do not claim hourly 1 km satellite truth. State the real cadence in the deck. A judge who knows remote sensing will check, and being right about your own limitations is worth more than an inflated claim.

---

## 4. The models

### Model A — Gridded PM2.5 estimator ("the hotspot engine")

**The task:** learn PM2.5 as a function of satellite and meteorological variables at locations where a station exists, then predict at the ~3,000 grid cells where no station exists.

**Training data:** for every (station, hour) pair over the past 18–24 months, join:

| Feature group | Features |
|---|---|
| Satellite | MAIAC AOD, S5P NO₂ column, S5P aerosol index (same-day, nearest valid) |
| Meteorology | wind u/v components, wind speed, boundary layer height, temperature, RH, surface pressure, precipitation |
| Fire | count of FIRMS pixels within 25/50/100 km, and specifically the count within a ±30° upwind sector at each radius, summed over the last 24 and 48 h |
| Static | built-up fraction, cropland fraction, elevation, population density, distance to nearest major road |
| Temporal | hour of day, day of week, day of year (as sin/cos), is_diwali_window, is_stubble_season |

**Label:** station PM2.5 for that hour.

**Model:** LightGBM regressor. Roughly 200k–400k training rows.

**Validation — and this matters more than the model:** use **spatial leave-one-station-out cross-validation**, not a random split. A random split leaks: neighbouring hours at the same station are nearly identical, and you will report a fake R² of 0.95. Hold out entire stations, train on the rest, predict the held-out station. That number is the honest one, and it is exactly the generalisation you are claiming when you predict at cells with no station.

Expect something like MAE 25–40 µg/m³ and R² 0.6–0.75 under LOSO. **Report the real number.** A team showing an honest 0.68 with correct methodology beats a team showing 0.97 from a leaked split, because one of the judges will ask.

**Hotspot definition:** a cell is a hotspot when

```
predicted_pm25(cell) − idw_interpolation_from_stations(cell) > threshold
AND predicted_pm25(cell) > 150 µg/m³
AND model_confidence > 0.6
```

That first line is the entire pitch in one expression: *what our model sees, minus what the existing station network would have told you.* The positive residual is the blind spot. Rank hotspots by `severity × population_exposed`.

### Model B — 72-hour AQI forecaster

**The task:** per station (and per city aggregate), predict PM2.5 at t+1 … t+72 hours.

**Features:** lagged PM2.5 (1, 2, 3, 6, 12, 24, 48, 72 h), rolling means and standard deviations, meteorological *forecast* for the target hour (this is the key — you have real forecast winds from Open-Meteo), upwind fire count in the last 24 h, hour/day/season encodings, and the same-day satellite AOD.

**Model:** LightGBM, direct multi-horizon (one model per horizon bucket: +6 h, +24 h, +48 h, +72 h). Simpler than recursive, no error compounding, trains fast.

**Baseline you must beat and must show:** persistence (tomorrow equals today) and a 7-day seasonal climatology. Put a bar chart of your MAE against both baselines in the dashboard and the deck. Beating persistence at +24 h is genuinely hard for air quality; if you beat it by 15–25% you have a real model, and showing the comparison proves you know that.

**Spike alert:** fire an alert when `P(AQI crosses into Severe within 72h) > 0.6`, computed from the quantile-regression spread across the LightGBM quantile models (train at α = 0.1, 0.5, 0.9 to get a confidence band nearly free).

### Model C — Gemini vision triage

Every citizen photo goes to Gemini 2.5 Flash with a **strict JSON schema response**. This contract is load-bearing — the frontend, the fusion logic and the dashboard all depend on it, so freeze it early:

```json
{
  "is_valid_outdoor_photo": true,
  "rejection_reason": null,
  "estimated_visibility_km": 1.2,
  "haze_severity": 4,
  "visible_sources": ["crop_residue_burning", "vehicular_smoke"],
  "sky_condition": "heavy_haze",
  "confidence": 0.81,
  "notes": "Dense grey-brown haze, sun disc visible through smoke, horizon obscured beyond ~1 km"
}
```

`haze_severity` is 0–5. `visible_sources` is a closed enum: `crop_residue_burning`, `waste_burning`, `construction_dust`, `industrial_plume`, `vehicular_smoke`, `dust_storm`, `fog_only`, `none_visible`.

**The validity gate is a trust boundary, not a nicety.** Citizen submissions are untrusted input and this system issues alerts to authorities. Reject indoor shots, screenshots, memes, and photos where the sky is not visible. Also enforce server-side: reject if EXIF/geotag is absent or outside the corridor bounding box, and rate-limit per anonymous session. Never let an unverified citizen photo alone trigger an authority alert — it must corroborate a model signal, never substitute for one.

**Fusion rule:** citizen reports raise a cell's confidence score, they do not set its PM2.5 value. Three independent reports of `haze_severity >= 4` within a cell in one hour raises that cell's confidence by a fixed increment and flags it for review. This keeps the system robust to both noise and deliberate manipulation.

### Model D — Source attribution (this is the differentiator)

When a hotspot or forecast spike fires, assemble structured evidence:

1. Wind vector at the cell for the relevant hours (from Open-Meteo).
2. Trace a simple upwind sector 100 km back — a ±30° cone along the reverse wind bearing. Not full HYSPLIT back-trajectory modelling; a wind-sector cone is the honest, buildable approximation. Say so.
3. Count FIRMS fire pixels inside that cone in the last 24–48 h.
4. Pull S5P NO₂ anomaly versus the 30-day mean for that cell (NO₂ points at combustion and traffic rather than dust).
5. Pull citizen `visible_sources` votes in the cell.
6. Check land use — is the cell industrial or under heavy construction?

Feed **only that structured evidence** to Gemini 2.5 Pro and have it produce the brief. The prompt must forbid inventing numbers and require every claim to cite a field from the evidence payload. Output:

```
CAUSE: Long-range transport of crop residue smoke from Sonipat–Panipat belt
CONFIDENCE: 0.78
EVIDENCE: 47 active fire pixels detected 18–34 km upwind (bearing 310°, wind
  310° at 11 km/h — transport time ~2.5 h); NO₂ column 2.1× the 30-day mean;
  4 citizen reports naming crop residue burning; cell land use 82% cropland-adjacent
RECOMMENDED ACTION: Notify Sonipat district agriculture officer for field
  verification; issue localised advisory to 84,000 residents; consider GRAP
  Stage III triggers for Sector 12–18 if levels sustain 6 h
```

This is what converts a dashboard into a decision-support tool, and it is the answer to "is Google AI doing meaningful work?" — Gemini is reasoning over fused multi-source evidence to produce an actionable, grounded, auditable conclusion.

---

## 5. The federation layer (the Digital Public Good half)

The brief explicitly asks for interoperability so cities and states can *share predictive models and coordinate resources*. Most teams will hand-wave this. Build it small but real.

### What a "tenant" is

A tenant is a city or state deployment. Each tenant has its own BigQuery dataset, its own trained model versions, and its own dashboard scope. Delhi-NCR and Lucknow are both tenants in the demo.

### The three artifacts a tenant publishes

**1. Model card + weights** — pushed to a public GCS bucket with a BigQuery index:

```json
{
  "model_id": "delhi-ncr/grid-pm25/v3",
  "tenant": "delhi-ncr",
  "task": "gridded_pm25_estimation",
  "trained_on": {"from": "2024-01-01", "to": "2025-09-01", "n_rows": 312847},
  "features": ["aod_maiac", "s5p_no2", "wind_u", "wind_v", "blh", "..."],
  "performance": {"loso_mae": 31.4, "loso_r2": 0.71, "baseline_idw_mae": 48.2},
  "climate_zone": "indo_gangetic_plain_winter",
  "artifact_uri": "gs://vayusetu-registry/delhi-ncr/grid-pm25/v3/model.txt",
  "license": "Apache-2.0",
  "schema_version": "1.0"
}
```

**2. Hotspot event schema** — the open spec any city or system can emit and consume. Publish it as a JSON Schema in the repo. This is the actual digital public good: the *format*, not just the code.

**3. Public API** — read-only endpoints serving current hotspots and forecasts per tenant, so a state dashboard or a third-party app can consume without touching your database.

### The transfer demo — 90 seconds that wins the reach criterion

Lucknow is a new tenant with no trained model. In the dashboard:

1. Show Lucknow with stations only, no grid — "a new city, cold start."
2. Click **Import model** → registry lists Delhi-NCR's model, filtered to matching climate zone (`indo_gangetic_plain_winter`).
3. Import it. Grid predictions appear immediately for Lucknow using Delhi's weights.
4. Show the honest performance drop: Delhi LOSO MAE 31 → Lucknow zero-shot MAE ~45.
5. Click **Fine-tune on local data** → a short Vertex AI job on Lucknow's own station history → MAE recovers to ~35.
6. Publish Lucknow's model back to the registry.

That is a complete, working, honestly-measured federation loop. **Say plainly that this is federated *model sharing*, not federated *learning* with differential privacy** — you are sharing model weights and schemas, not doing secure aggregation over private gradients. Overclaiming here is the fastest way to lose a technical judge. The DP-federated version is your roadmap slide.

---

## 6. Dashboard specification

Two audiences, one codebase, different routes.

### A. Official console (`/console`) — desktop, the demo hero

**Screen 1 — Live Map** *(the landing view; this is what is on screen for most of the video)*

- Google Maps base, dark theme, NCR bounds.
- Toggleable layers, all rendered with deck.gl over the Maps canvas:
  - **Stations** — circles coloured by AQI band, sized by data freshness. Greyed out when a station has not reported in 3 h. Showing the gaps is part of the argument.
  - **Predicted grid** — 1 km cells, AQI colour ramp, adjustable opacity.
  - **Residual layer** *(the key one)* — cells coloured by `prediction − station_interpolation`. Red where the official network is blind. This single layer is the product.
  - **Fire pixels** — FIRMS points, sized by fire radiative power.
  - **Wind field** — animated particle vectors. Costs an afternoon and makes the transport story legible instantly.
  - **Citizen reports** — photo pins, click to see the image and its Gemini analysis side by side.
- **Time slider** spanning −72 h to +72 h. Past shows observed, future shows forecast with the confidence band. Dragging across the boundary is the single most impressive interaction in the build — prioritise it.
- **Cell inspector** — click any cell: predicted vs nearest-station value, population exposed, feature contributions (LightGBM SHAP values render as a clean bar chart), source-attribution brief, citizen photos in that cell.

**Screen 2 — Hotspots** — ranked table: rank, cell, predicted PM2.5, official nearest reading, delta, population exposed, likely source, confidence, evidence chips (satellite / citizen / meteorological / fire), and a **Dispatch alert** action. Filterable by district. This is the screen a real pollution control board would live in.

**Screen 3 — Forecast** — per-city 72 h chart with confidence band, threshold crossings marked, and a model performance panel showing MAE against persistence and climatology baselines plus a backtest of a past episode. Put the honest numbers on screen; it reads as confidence, not weakness.

**Screen 4 — Alerts** — issued alerts, recipient, channel, timestamp, acknowledgement status, response time. For the demo, recipients are mock accounts inside the app. **Never wire this to real officials' contact details.**

**Screen 5 — Federation** — tenant map of India with active cities lit up, the model registry table with model cards, import and fine-tune flows, and a cross-city comparison chart.

**Screen 6 — Ask Vayu** — a chat panel powered by Gemini function calling. Tools exposed: `get_current_aqi(city)`, `get_forecast(city, horizon)`, `list_hotspots(district, limit)`, `get_fires_upwind(lat, lon, hours)`, `explain_cell(cell_id)`, `compare_cities(a, b, metric)`. Every answer must cite the tool results it used. Scripted demo question: *"Why is Gurugram worse than Delhi today, and will it get better by Thursday?"*

### B. Citizen PWA (`/`) — mobile-first

- Big current AQI for detected location, plain-language health advice, colour-coded.
- **Report** — camera → photo → instant Gemini result rendered as a card ("Heavy haze detected, visibility ~1.2 km, likely crop residue burning"). Instant feedback is what drives repeat contribution; a report that vanishes into a void gets submitted once.
- **Language selector** — 10 languages: Hindi, Punjabi, Bengali, Marathi, Tamil, Telugu, Kannada, Gujarati, Odia, English. Translation API for text, Cloud TTS for a spoken advisory with a play button.
- **Alerts** — opt-in local spike warnings.
- Works offline for the last-known reading; queues photo uploads when connectivity returns. Cheap with a service worker, and it matters for the audience you are claiming to serve.

### Design direction

Dark console, high-contrast data ink, one accent colour for alerts. Use the AQI standard palette for anything AQI-coloured — inventing your own colours for a standardised index is a real usability error, not a style choice. Make sure the map is legible at video compression: thicker strokes and larger labels than feel right on your monitor.

---

## 7. Repository layout

```
vayusetu/
├── README.md                    # architecture, setup, honest limitations
├── LICENSE                      # Apache-2.0 (DPG requirement)
├── spec/
│   ├── hotspot-event.schema.json
│   ├── model-card.schema.json
│   └── README.md                # the open spec, written for outside adopters
├── infra/
│   ├── terraform/               # or gcloud scripts — either, but committed
│   └── schedulers.yaml
├── ingestion/
│   ├── stations.py              # OpenAQ → BigQuery
│   ├── fires.py                 # FIRMS → BigQuery
│   ├── satellite.py             # Earth Engine → BigQuery
│   ├── meteorology.py           # Open-Meteo → BigQuery
│   ├── static_layers.py         # population, land use, roads (one-shot)
│   └── common.py                # as_of handling, retries, idempotent upserts
├── ml/
│   ├── features.sql             # the feature table, as SQL. Readable = auditable
│   ├── train_grid.py
│   ├── train_forecast.py
│   ├── evaluate.py              # LOSO CV, baselines, backtest
│   └── registry.py              # publish/import model cards
├── api/
│   ├── main.py                  # FastAPI
│   ├── routes/                  # hotspots, forecast, reports, federation, agent
│   ├── gemini/
│   │   ├── vision.py            # photo triage
│   │   ├── attribution.py       # source briefs
│   │   └── agent.py             # function-calling tools
│   └── alerts.py
├── web/
│   ├── src/console/             # official dashboard
│   ├── src/citizen/             # PWA
│   └── src/shared/
├── notebooks/
│   └── backtest_nov2024.ipynb   # the evidence for your accuracy claims
└── docs/
    ├── DEPLOYMENT.md            # how a city onboards — this is a scoring document
    └── DATA_SOURCES.md
```

`docs/DEPLOYMENT.md` is not filler. "Could this be piloted within a ministry in weeks?" is 20% of the score, and a written onboarding runbook — what a new city needs, which APIs to enable, what it costs per month, who operates it — is the most direct possible answer.

---

## 8. Core BigQuery schema

Freeze these early; everything else depends on them.

```sql
-- raw_stations: one row per station per hour per pollutant
station_id STRING, station_name STRING, city STRING, state STRING,
lat FLOAT64, lon FLOAT64, ts TIMESTAMP, pollutant STRING,
value FLOAT64, unit STRING, source STRING, ingested_at TIMESTAMP

-- raw_fires: FIRMS detections
lat FLOAT64, lon FLOAT64, acq_ts TIMESTAMP, confidence STRING,
frp FLOAT64, satellite STRING, ingested_at TIMESTAMP

-- raw_satellite: per grid cell per day
cell_id STRING, date DATE, aod_maiac FLOAT64, s5p_no2 FLOAT64,
s5p_aer_ai FLOAT64, cloud_fraction FLOAT64, ingested_at TIMESTAMP

-- raw_meteorology: per cell per hour (observed and forecast)
cell_id STRING, ts TIMESTAMP, is_forecast BOOL, wind_u FLOAT64,
wind_v FLOAT64, wind_speed FLOAT64, wind_dir FLOAT64, blh FLOAT64,
temp_c FLOAT64, rh FLOAT64, precip_mm FLOAT64, ingested_at TIMESTAMP

-- grid_cells: static, one row per 1km cell
cell_id STRING, tenant STRING, lat FLOAT64, lon FLOAT64,
geom GEOGRAPHY, population INT64, builtup_frac FLOAT64,
cropland_frac FLOAT64, elevation_m FLOAT64, dist_major_road_m FLOAT64

-- predictions_grid
cell_id STRING, ts TIMESTAMP, model_version STRING,
pm25_pred FLOAT64, pm25_lower FLOAT64, pm25_upper FLOAT64,
idw_baseline FLOAT64, residual FLOAT64, confidence FLOAT64,
is_hotspot BOOL, created_at TIMESTAMP

-- predictions_forecast
station_id STRING, city STRING, issued_at TIMESTAMP,
target_ts TIMESTAMP, horizon_h INT64, model_version STRING,
pm25_p10 FLOAT64, pm25_p50 FLOAT64, pm25_p90 FLOAT64

-- citizen_reports
report_id STRING, session_id STRING, cell_id STRING, ts TIMESTAMP,
lat FLOAT64, lon FLOAT64, photo_uri STRING, gemini_analysis JSON,
is_valid BOOL, haze_severity INT64, visible_sources ARRAY<STRING>

-- alerts
alert_id STRING, tenant STRING, cell_id STRING, issued_at TIMESTAMP,
severity STRING, population_exposed INT64, attribution JSON,
recipients ARRAY<STRING>, acknowledged_at TIMESTAMP
```

Partition every time-series table by date and cluster by `cell_id` or `station_id`. Cheap to do now, and it lets you say "national scale" with a straight face.

---

## 9. Four-week schedule

Organised by workstream with weekly gates. Streams can run in parallel wherever hands allow; the gates are what matter.

### Week 1 — Data foundation and a map that shows something real

**Goal: real Delhi-NCR data flowing into BigQuery, and a map rendering it.**

- Enable APIs, create the project, set up service accounts and secrets.
- Build the 1 km grid for NCR (~3,000 cells) and load static layers: GHSL population, WorldCover land use, elevation, road distance.
- Ingestion for stations (OpenAQ), fires (FIRMS), meteorology (Open-Meteo). All with `as_of` support and idempotent upserts from the first commit — retrofitting replay mode later is painful.
- Earth Engine extraction for MAIAC AOD and S5P, backfilled 18–24 months for the corridor.
- Scaffold FastAPI and the React app. Get the Maps base map rendering with live station points.
- Write `spec/hotspot-event.schema.json` now, while the data model is fresh.

**Gate:** stations, fires and meteorology are updating on a schedule; 18 months of satellite history is in BigQuery; the map shows live station AQI. If satellite backfill is not done by end of week 1, it is the only thing anyone works on until it is — Model A cannot start without it.

### Week 2 — Models

**Goal: both models trained, honestly evaluated, and serving from Vertex AI.**

- Build `features.sql` — the joined training table. This is the highest-risk single artifact; the joins across differing time resolutions (hourly stations, daily satellite, hourly meteorology) are where subtle bugs hide. Sanity-check row counts and null rates at every join.
- Train Model A. Run leave-one-station-out CV. Record the honest number.
- Train Model B with quantile outputs at α = 0.1/0.5/0.9. Benchmark against persistence and climatology.
- Register both in Vertex AI Model Registry, deploy endpoints, wire the inference job.
- Build the Gemini vision triage endpoint with the frozen JSON schema, plus the validity gate and rate limiting.
- Dashboard: predicted grid layer and the residual layer rendering from real predictions.

**Gate:** a real hotspot appears on the map, defensible from real data, with an honest LOSO metric written down. This is the midpoint. If it does not happen this week the project is in trouble — cut the federation layer before cutting model quality.

### Week 3 — Intelligence and reach

**Goal: the system explains itself, speaks ten languages, and federates.**

- Source attribution: upwind wind-cone logic, evidence assembly, Gemini brief generation.
- Alerting: rules, dispatch, the inbox screen, acknowledgement flow.
- The "Ask Vayu" agent with its six function-calling tools.
- Citizen PWA: camera capture, upload, instant Gemini feedback, offline queue.
- Multilingual: Translation API across the ten languages, Cloud TTS voice advisories.
- Federation: onboard Lucknow as a second tenant, build the registry publish/import flow and the fine-tune job, measure and record the honest transfer performance drop and recovery.
- Time slider spanning observed and forecast.

**Gate:** the full end-to-end story runs without anyone touching a terminal: citizen photo → hotspot → attribution → alert → multilingual advisory, plus the Lucknow import.

### Week 4 — Prove it, ship it, tell it

**Goal: deployed, backtested, filmed, and submitted with two days to spare.**

- Backtest notebook against a real historical episode. Forecast versus actual, on a chart. This is your credibility.
- Deploy everything to production URLs. Test on a phone on mobile data, not office wifi.
- Load-test lightly; make sure a judge clicking around does not hit a cold-start timeout. Set Cloud Run min instances to 1 for demo week.
- Write `DEPLOYMENT.md` including a real monthly cost estimate for a city-scale deployment.
- Record the demo video.
- Build the deck.
- **Freeze code 48 hours before the deadline.** Use the remaining time for the video, the deck and the README. Every hackathon team that codes until the deadline submits a broken link.

---

## 10. Demo video structure (4 minutes)

The video is what most judges will actually experience. Script it, do multiple takes, record clean audio.

| Time | Content |
|---|---|
| 0:00–0:25 | **The gap.** Delhi map, 40 official stations lit up. Zoom into the space between them. "30 million people. This is everything the official network can see. Here is what it cannot." |
| 0:25–1:15 | **Live map.** Residual layer on. A red cell far from any station. Click it: predicted 310 vs official 180, 84,000 people exposed, feature contributions. |
| 1:15–1:50 | **Attribution.** Wind field animates on, fire pixels appear upwind. The Gemini brief writes itself out. "Not just that it is bad — why, from where, and who to call." |
| 1:50–2:20 | **Citizen loop.** Phone in hand, photograph the sky, Gemini result in three seconds, cell confidence ticks up on the console beside it. Then the Hindi voice advisory plays. |
| 2:20–2:50 | **Forecast + proof.** 72 h forecast, then the backtest chart: our forecast versus what actually happened in November 2024, next to the persistence baseline. State the real MAE out loud. |
| 2:50–3:30 | **Federation.** Lucknow cold, import Delhi's model, grid appears, honest metric drop shown, fine-tune, publish back. "Any Indian city, in an afternoon." |
| 3:30–4:00 | **Scale and honesty.** India map with tenants. Costs per city per month. One clear sentence on what is real, what is replayed, and what is roadmap. |

That last beat is not modesty, it is strategy. Judges have watched twenty demos overclaiming. The team that draws its own boundary is the team they trust.

---

## 11. Deck outline (11 slides)

1. **Hook** — the blind-spot map. One image, almost no text.
2. **Problem** — sparse monitoring, hyper-local events missed, health cost. Two hard numbers, cited.
3. **Solution** — VayuSetu in one diagram and one sentence.
4. **How it works** — the fusion architecture, kept visual.
5. **AI approach** — the four Gemini/Vertex roles and why each is necessary. This slide is 25% of the score; give it the most care.
6. **Proof** — LOSO metrics, baseline comparison, backtest chart. Real numbers.
7. **Who it serves** — pollution control boards, municipal commissioners, GRAP enforcement, citizens. Name the actual user of each screen.
8. **Federation / DPG** — the registry, the open schema, the Apache licence, the Lucknow transfer result.
9. **Deployability** — the architecture's ops story, cost per city per month, the onboarding runbook, what a 90-day pilot looks like.
10. **Scale across India** — tenant model, which cities have sufficient station density today, and the path for cities with none (satellite-only mode with wider confidence bands).
11. **Limitations and roadmap** — honest list: satellite cadence, cloud gaps, no DP-federated learning yet, low-cost sensor integration next.

---

## 12. Rubric mapping

| Criterion | Weight | What in this build earns it |
|---|---|---|
| **AI / Technical Execution** | 25% | Two trained models with honest spatial CV, Gemini doing four distinct necessary jobs, real multi-source fusion, working end-to-end with a backtest as evidence |
| **Problem-Solution Fit** | 20% | Hits every clause of the brief literally: citizen data ✓, satellite ✓, meteorology ✓, hidden hotspot detection ✓, corridor forecasting ✓, authority alerting ✓, interoperability ✓ |
| **Depth & Reach Across India** | 20% | Multi-tenant from the architecture up, real second-state transfer with measured results, published open schema, 10 languages, voice-first for low-literacy users |
| **Deployability & Scalability** | 20% | Serverless throughout, scales to zero, written onboarding runbook, real cost estimate, no bespoke hardware, uses only data a city already has access to |
| **Impact Potential** | 15% | Population-exposure quantified per hotspot, direct GRAP-style enforcement pathway, works today in every city with CPCB stations, and degrades gracefully in cities without |

---

## 13. Risks and how each is handled

| Risk | Likelihood | Handling |
|---|---|---|
| Feature-join bugs silently corrupt training data | **High** | Null-rate and row-count assertions after every join in `features.sql`. Plot feature distributions before training. This is the most common way these projects quietly fail |
| Random train/test split inflates metrics | **High** | Leave-one-station-out CV, mandated. Assume a judge will ask how you split |
| Satellite cloud gaps in winter | High | Forward-fill up to 48 h with a `data_age` feature; widen confidence bands when stale; show staleness in the UI |
| OpenAQ stations drop out | Certain | Never assume a station reported. Grey out stale stations in the UI — the gaps support the argument |
| No real citizen photos exist yet | Certain | Team photographs 30–50 real skies across NCR at varying conditions with genuine geotags. Real photos you took, honestly labelled as a seed set |
| Demo falls outside burning season | Certain (Sept) | Replay mode, disclosed |
| Earth Engine quota or export slowness | Medium | Backfill in week 1, not week 3. Export to GCS then load to BigQuery rather than pulling through Python |
| Cold-start latency during judging | Medium | `min-instances=1` on Cloud Run for the demo period |
| Scope creep kills the polish | **High** | The cut list below, agreed in advance |

### Cut list — in this order, without debate

1. Animated wind particles (static arrows are fine)
2. Offline PWA support
3. SHAP feature contributions in the cell inspector
4. Languages beyond Hindi + English (keep the selector, add languages if time)
5. Fine-tune step in the federation flow (import alone still proves the point)
6. The "Ask Vayu" agent

**Never cut:** the residual layer, source attribution, honest metrics, the Lucknow import, the deployed link. Those five are the submission.

---

## 14. Open questions to settle in week 1

- Which historical episode is the replay hero? Verify data completeness first — pick a window where stations, FIRMS and MAIAC are all well-populated, then commit.
- Lucknow or Mumbai as tenant two? Lucknow proves cross-state transfer within a similar airshed; Mumbai proves transfer across a genuinely different one and is the harder, more impressive claim if the metrics hold. Decide after seeing Delhi's LOSO numbers.
- Alert recipients in the demo: mock accounts only. Confirm nobody wires a real official's contact into a test dispatch.
- Confirm the exact GA Gemini model IDs in AI Studio at build time rather than trusting any hard-coded string in this document.

---

## 15. First five commits

1. `infra/` — project setup, APIs enabled, service accounts, BigQuery datasets created.
2. `ingestion/common.py` + `stations.py` — OpenAQ pulling into BigQuery with `as_of` support and idempotent upserts.
3. `grid_cells` built and populated with population and land-use static layers.
4. `ingestion/fires.py` + `meteorology.py` on schedulers.
5. `web/` skeleton with the Maps base map rendering live station points from the API.

After commit 5 you have something real on screen, which is worth more to momentum than a week of backend work nobody can see.
