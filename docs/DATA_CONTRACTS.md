# Data Contracts — FROZEN

These are the interfaces that separate workstreams. They are frozen so that people and agents working in parallel do not build incompatible halves.

**Changing anything in this document requires agreement from whoever owns the affected workstreams.** If you think a contract is wrong, say so — but stop and raise it rather than editing around it.

Contract version: `1.0`

---

## 1. Grid cell identity

The single most important shared primitive. Everything spatial keys off this.

### Definition

A cell is a `0.01° × 0.01°` box on a fixed global lattice.

```
lat_idx = floor(lat / 0.01)
lon_idx = floor(lon / 0.01)
cell_id = f"{tenant}-{lat_idx}-{lon_idx}"
```

Cell centre is `((lat_idx + 0.5) * 0.01, (lon_idx + 0.5) * 0.01)`.

Example: `28.6315°N, 77.3102°E` in the `ncr` tenant → `ncr-2863-7731`.

### Why 0.01° and not a projected 1 km grid

At 28.5°N, 0.01° is about **1.11 km north–south** and **0.98 km east–west**. Close enough to the 1 km MAIAC AOD resolution we are matching, and it avoids reprojection maths in every single module. This is a deliberate simplification — state it as "approximately 1 km" in the UI and deck, never as exactly 1 km.

The lattice is global and tenant-independent, so two tenants whose bounding boxes overlap produce consistent geometry. The tenant prefix exists for partitioning and access control, not geometry.

### Tenant bounding boxes

| Tenant | Name | Bounds (lat_min, lon_min, lat_max, lon_max) | Approx cells |
|---|---|---|---|
| `ncr` | Delhi-NCR | 28.20, 76.80, 28.95, 77.60 | ~6,000 |
| `lko` | Lucknow | 26.70, 80.80, 26.99, 81.10 | ~870 |

---

## 2. BigQuery tables

Dataset per tenant: `vayusetu_{tenant}`. Shared tables live in `vayusetu_shared`.

All timestamps are **UTC**. All times displayed to users are IST. Convert at the presentation layer only — never store IST.

PM2.5 and PM10 are always **µg/m³**. Never store AQI as a stored value; AQI is derived at read time from PM2.5 using the CPCB National AQI breakpoints (see §6).

### `raw_stations`
Partition by `DATE(ts)`, cluster by `station_id`.
```sql
station_id    STRING    NOT NULL   -- stable id from source, prefixed: "openaq:12345"
station_name  STRING
city          STRING
state         STRING
lat           FLOAT64   NOT NULL
lon           FLOAT64   NOT NULL
cell_id       STRING    NOT NULL   -- derived, see §1
ts            TIMESTAMP NOT NULL   -- observation time, UTC, floored to the hour
pollutant     STRING    NOT NULL   -- pm25|pm10|no2|so2|co|o3
value         FLOAT64              -- NULL means the station reported nothing
unit          STRING    NOT NULL
source        STRING    NOT NULL   -- openaq|cpcb
ingested_at   TIMESTAMP NOT NULL
```
Primary key for upsert: `(station_id, ts, pollutant)`.

### `raw_fires`
Partition by `DATE(acq_ts)`.
```sql
fire_id       STRING    NOT NULL   -- "{satellite}:{lat}:{lon}:{acq_ts}" hashed
lat           FLOAT64   NOT NULL
lon           FLOAT64   NOT NULL
acq_ts        TIMESTAMP NOT NULL
confidence    STRING               -- low|nominal|high (VIIRS)
frp           FLOAT64              -- fire radiative power, MW
satellite     STRING               -- VIIRS_SNPP|VIIRS_NOAA20|MODIS
ingested_at   TIMESTAMP NOT NULL
```
Not tenant-scoped — fires 100 km upwind of NCR are often outside its bbox. Lives in `vayusetu_shared`. Ingest a 200 km buffer around every active tenant.

### `raw_satellite`
Partition by `date`, cluster by `cell_id`.
```sql
cell_id         STRING NOT NULL
date            DATE   NOT NULL
aod_maiac       FLOAT64            -- NULL when cloud-masked. Expect many NULLs in winter
s5p_no2         FLOAT64            -- mol/m², tropospheric column
s5p_aer_ai      FLOAT64            -- UV aerosol index, dimensionless
cloud_fraction  FLOAT64
ingested_at     TIMESTAMP NOT NULL
```
Primary key: `(cell_id, date)`.

### `raw_meteorology`
Partition by `DATE(ts)`, cluster by `cell_id`.
```sql
cell_id      STRING    NOT NULL
ts           TIMESTAMP NOT NULL
is_forecast  BOOL      NOT NULL   -- TRUE = Open-Meteo forecast, FALSE = ERA5 reanalysis
issued_at    TIMESTAMP            -- forecast issue time; NULL when is_forecast=FALSE
wind_u       FLOAT64              -- m/s, eastward
wind_v       FLOAT64              -- m/s, northward
wind_speed   FLOAT64              -- m/s
wind_dir     FLOAT64              -- degrees, meteorological convention: direction wind comes FROM
blh          FLOAT64              -- boundary layer height, metres
temp_c       FLOAT64
rh           FLOAT64              -- %
precip_mm    FLOAT64
ingested_at  TIMESTAMP NOT NULL
```
Primary key: `(cell_id, ts, is_forecast, issued_at)`.

**`wind_dir` is the direction the wind comes FROM** (meteorological convention). Upwind bearing is therefore `wind_dir` itself, not `wind_dir + 180`. Getting this backwards inverts every source attribution — if fires never line up with plumes, check this first.

### `grid_cells`
Static, one row per cell per tenant. In `vayusetu_shared`, filtered by tenant.
```sql
cell_id            STRING    NOT NULL
tenant             STRING    NOT NULL
lat                FLOAT64   NOT NULL   -- cell centre
lon                FLOAT64   NOT NULL
geom               GEOGRAPHY NOT NULL
district           STRING
population         INT64                -- GHSL, persons in cell
builtup_frac       FLOAT64              -- 0..1, ESA WorldCover
cropland_frac      FLOAT64              -- 0..1
elevation_m        FLOAT64
dist_major_road_m  FLOAT64
has_station        BOOL      NOT NULL
```

### `predictions_grid`
Partition by `DATE(ts)`, cluster by `cell_id`.
```sql
cell_id        STRING    NOT NULL
tenant         STRING    NOT NULL
ts             TIMESTAMP NOT NULL
model_version  STRING    NOT NULL   -- must match a model_id in the registry
pm25_pred      FLOAT64   NOT NULL
pm25_p10       FLOAT64
pm25_p90       FLOAT64
idw_baseline   FLOAT64   NOT NULL   -- IDW from stations, k=4, power=2. See §6
residual       FLOAT64   NOT NULL   -- pm25_pred - idw_baseline. THE product
confidence     FLOAT64   NOT NULL   -- 0..1, see §6
is_hotspot     BOOL      NOT NULL
citizen_support INT64    NOT NULL   -- count of corroborating valid reports, last 1h
created_at     TIMESTAMP NOT NULL
```

### `predictions_forecast`
```sql
station_id    STRING    NOT NULL   -- or "city:{name}" for city aggregates
tenant        STRING    NOT NULL
issued_at     TIMESTAMP NOT NULL
target_ts     TIMESTAMP NOT NULL
horizon_h     INT64     NOT NULL   -- 6|24|48|72
model_version STRING    NOT NULL
pm25_p10      FLOAT64   NOT NULL
pm25_p50      FLOAT64   NOT NULL
pm25_p90      FLOAT64   NOT NULL
created_at    TIMESTAMP NOT NULL
```
Never overwrite a forecast row. Keeping every issued forecast is what makes the backtest possible.

### `citizen_reports`
```sql
report_id       STRING    NOT NULL
tenant          STRING    NOT NULL
session_id      STRING    NOT NULL   -- Firebase anonymous uid
cell_id         STRING    NOT NULL
ts              TIMESTAMP NOT NULL
lat             FLOAT64   NOT NULL
lon             FLOAT64   NOT NULL
photo_uri       STRING    NOT NULL   -- gs://
gemini_analysis JSON      NOT NULL   -- exactly the §3 schema
is_valid        BOOL      NOT NULL
haze_severity   INT64                -- 0..5, NULL when invalid
visible_sources ARRAY<STRING>
created_at      TIMESTAMP NOT NULL
```

### `alerts`
```sql
alert_id          STRING    NOT NULL
tenant            STRING    NOT NULL
cell_id           STRING
city              STRING               -- set for forecast-spike alerts
alert_type        STRING    NOT NULL   -- hotspot|forecast_spike
issued_at         TIMESTAMP NOT NULL
severity          STRING    NOT NULL   -- moderate|poor|very_poor|severe
population_exposed INT64
attribution       JSON                 -- exactly the §4 schema
recipients        ARRAY<STRING>        -- MOCK ACCOUNTS ONLY. See AGENTS.md R6
acknowledged_at   TIMESTAMP
acknowledged_by   STRING
```

---

## 3. Gemini vision triage — response schema

`api/gemini/vision.py`. Sent to Gemini 2.5 Flash with `response_mime_type: application/json` and this schema enforced. **Frozen — the PWA, the fusion logic and the console all parse this.**

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

| Field | Type | Notes |
|---|---|---|
| `is_valid_outdoor_photo` | bool | Gate. False → every other field except `rejection_reason` is null |
| `rejection_reason` | string \| null | Enum: `indoor`, `no_sky_visible`, `screenshot_or_graphic`, `too_dark`, `blurred`, `not_a_photo`, `other` |
| `estimated_visibility_km` | float \| null | 0.1 – 50.0 |
| `haze_severity` | int \| null | 0 = clear, 5 = extreme |
| `visible_sources` | string[] | Closed enum, see below. Empty array allowed |
| `sky_condition` | string \| null | `clear`, `light_haze`, `moderate_haze`, `heavy_haze`, `fog`, `overcast`, `night` |
| `confidence` | float | 0.0 – 1.0 |
| `notes` | string | ≤ 200 chars, human-readable, shown in the console |

`visible_sources` closed enum — do not extend without bumping the contract version:
`crop_residue_burning`, `waste_burning`, `construction_dust`, `industrial_plume`, `vehicular_smoke`, `dust_storm`, `fog_only`, `none_visible`

### Server-side validation, applied after Gemini and independent of it

Gemini's gate is one layer. These are mandatory and non-negotiable:

1. Reject if geotag is absent or outside the tenant bounding box.
2. Reject if the photo timestamp is more than 2 hours old or in the future.
3. Rate limit: 10 reports per `session_id` per hour, 3 per cell per session per hour.
4. Reject files above 10 MB or not `image/jpeg` / `image/png` / `image/webp`.
5. Strip all EXIF except timestamp and GPS before storing.

### Fusion rule — how a report affects a cell

```
valid reports in cell with haze_severity >= 4, within the last hour:
  0        → confidence unchanged
  1–2      → confidence += 0.05 each, cell flagged for_review
  3+       → confidence += 0.15 total, cell flagged corroborated
confidence is clamped to [0, 1]
```

A citizen report **never** writes `pm25_pred`. A cell with `citizen_support > 0` but `pm25_pred` below the hotspot threshold is **not** a hotspot. See `AGENTS.md` R4.

---

## 4. Source attribution — evidence payload and output

`api/gemini/attribution.py`. The evidence payload is assembled from real queries and passed to Gemini 2.5 Pro. **Gemini never queries anything itself here and never invents a number.**

### Input (assembled by us)
```json
{
  "cell_id": "ncr-2863-7731",
  "ts": "2024-11-05T09:00:00Z",
  "pm25_pred": 310.4,
  "idw_baseline": 181.2,
  "residual": 129.2,
  "confidence": 0.78,
  "population_exposed": 84000,
  "wind": {"speed_kmh": 11.0, "from_bearing_deg": 310.0, "blh_m": 240},
  "upwind_fires": {
    "sector_deg": 30, "radius_km": 100, "window_h": 48,
    "count": 47, "nearest_km": 18.0, "farthest_km": 34.0,
    "total_frp_mw": 412.5,
    "districts": ["Sonipat", "Panipat"],
    "transport_time_h": 2.5
  },
  "no2_anomaly_ratio": 2.1,
  "aod_anomaly_ratio": 1.8,
  "citizen_reports": {
    "count": 4, "mean_haze_severity": 4.2,
    "source_votes": {"crop_residue_burning": 4, "vehicular_smoke": 1}
  },
  "land_use": {"builtup_frac": 0.11, "cropland_frac": 0.82, "dist_major_road_m": 3100},
  "missing_fields": ["aod_maiac (cloud-masked 2024-11-05)"]
}
```

### Output
```json
{
  "cause": "Long-range transport of crop residue smoke from the Sonipat-Panipat belt",
  "cause_category": "crop_residue_burning",
  "confidence": 0.78,
  "evidence_cited": ["upwind_fires.count", "wind.from_bearing_deg", "no2_anomaly_ratio", "citizen_reports.source_votes"],
  "narrative": "47 active fire pixels detected 18-34 km upwind ...",
  "recommended_actions": [
    {"actor": "Sonipat district agriculture officer", "action": "Field verification of 47 detected fire locations", "urgency": "high"}
  ],
  "caveats": ["MAIAC AOD unavailable for this date due to cloud masking"]
}
```

`cause_category` enum: same as `visible_sources`, plus `secondary_formation`, `meteorological_trapping`, `unknown`.

Prompt requirements, enforced in the prompt and checked in code:
- Every claim in `narrative` must correspond to a field listed in `evidence_cited`.
- Any field present in `missing_fields` must appear in `caveats`.
- If evidence is too thin, return `cause_category: "unknown"` with low confidence. Do not guess.
- Never invent a number that is not in the input payload.

---

## 5. REST API surface

> **Superseded, kept for the record (2026-09-15).** This is the API as originally
> planned. Several of these endpoints were built as mocks and then deleted because they
> returned invented numbers or depended on falsified models: `/grid`, `/cells`,
> `/forecast`, `/forecast/backtest`, `/stations/current`, `/agent/ask`, and the alert inbox
> (`/alerts`), which was replaced by cases. The API actually served, with the reason for
> each endpoint, is in [`ARCHITECTURE.md` §6](ARCHITECTURE.md#6-the-api); a running
> service also documents itself at `/docs`.

Base: `/api/v1`. JSON everywhere. All errors use RFC 7807 `application/problem+json`.

```
GET  /tenants                                   list active tenants + bounds
GET  /{tenant}/stations/current                 latest reading per station, with staleness
GET  /{tenant}/grid?ts=&bbox=&layer=            grid predictions; layer=pm25|residual
GET  /{tenant}/hotspots?limit=&district=        ranked, highest severity x population first
GET  /{tenant}/cells/{cell_id}?ts=              full inspector payload incl. attribution
GET  /{tenant}/forecast?city=&horizon=          72h forecast with p10/p50/p90
GET  /{tenant}/forecast/backtest?from=&to=      forecast vs actual, with baselines
POST /{tenant}/reports                          citizen photo upload (multipart)
GET  /{tenant}/alerts?status=                   alert inbox
POST /{tenant}/alerts/{alert_id}/ack            acknowledge
GET  /registry/models?task=&climate_zone=       federated model registry
POST /{tenant}/registry/import                  import a model into this tenant
POST /{tenant}/registry/publish                 publish this tenant's model
POST /agent/ask                                 Ask Vayu, Gemini function calling
GET  /healthz                                   liveness, no auth
```

Read endpoints are public and cacheable (`Cache-Control: public, max-age=300`) — that is the point of a digital public good. Write endpoints require Firebase Auth. `/alerts/*/ack` requires an official role claim.

Replay mode: any read endpoint accepts `?as_of=<ISO8601>` and serves data as it stood at that instant.

### Ask Vayu — tool signatures
```
get_current_aqi(tenant, city)
get_forecast(tenant, city, horizon_h)
list_hotspots(tenant, district=None, limit=10)
get_fires_upwind(lat, lon, hours=48, radius_km=100)
explain_cell(tenant, cell_id, ts=None)
compare_cities(tenant_a, city_a, tenant_b, city_b, metric)
```
Every answer must cite the tool calls it made. No free-text speculation about air quality without a tool result behind it.

---

## 6. Shared derived quantities

Implement each of these **once**, in `ml/common.py`, and import everywhere. Two implementations that disagree is a class of bug that is very hard to see on a map.

**IDW baseline** — inverse distance weighting from the 4 nearest stations reporting PM2.5 at that hour, power 2, max radius 50 km. Returns NULL if fewer than 2 stations are available. This is the "what the official network would have told you" number, so it must be computed identically everywhere.

**Confidence** — `0.5 * model_agreement + 0.3 * data_freshness + 0.2 * citizen_support_factor`, clamped to `[0, 1]`, where `model_agreement = 1 - (p90 - p10) / (2 * pm25_pred)` clamped to `[0,1]`, and `data_freshness` decays linearly from 1.0 at 0h to 0.0 at 48h of satellite staleness.

**Hotspot test** — all three must hold:
```
residual > 60 µg/m³   AND   pm25_pred > 150 µg/m³   AND   confidence > 0.6
```

**AQI** — CPCB National AQI breakpoints for PM2.5, 24h rolling mean. Bands: Good 0–30, Satisfactory 31–60, Moderate 61–90, Poor 91–120, Very Poor 121–250, Severe 250+. Use the standard CPCB colours in the UI; do not invent a palette for a standardised index.

**Upwind sector** — a ±30° cone centred on `wind_dir` (the direction wind comes from), extending 100 km. See the warning in §2 about wind convention.

---

## 7. Failure modes each source will actually exhibit

Handle these. They are not edge cases, they happen daily.

| Source | Failure | Required handling |
|---|---|---|
| OpenAQ | Station silent for hours or days | Never assume a row exists. Grey out in UI beyond 3h. Exclude from IDW |
| OpenAQ | Negative or absurd values (-999, 9999) | Clamp to `[0, 1000]`, drop outside. Log the drop |
| OpenAQ | Rate limit 429 | Exponential backoff, max 5 retries, then fail the job loudly |
| FIRMS | ~3h latency, occasional gaps | Treat absence as "no data", never as "no fires". Different things |
| MAIAC AOD | Cloud-masked, many NULL winter days | Forward-fill up to 48h with a `data_age_h` feature. Widen bands. Show staleness |
| Sentinel-5P | Single daily overpass, ~7 km resolution | Never present as street-level. Daily product, say so |
| Open-Meteo | `boundary_layer_height` not in every model | Fall back to a documented proxy; record which was used |
| Earth Engine | Export slowness, quota | Export to GCS then load to BigQuery. Never pull large results through Python |
| Gemini | Malformed JSON despite schema | Validate with pydantic, one retry, then mark report `is_valid=false` with `rejection_reason: "other"` |
| Vertex endpoint | Cold start, timeout | 30s timeout, one retry, serve last cached prediction with staleness flag |

---

## 7a. Measured reality — first live API run, 2026-09-07

The table above was written from documentation. These are the numbers the APIs
actually returned on the first real run. Where they disagree, believe this section.

### OpenAQ v3 — the shape is a two-step join, not one call

**`/v3/locations` returns metadata only.** Its `sensors[]` objects carry `id`,
`name` and `parameter` — **no value and no timestamp**. Code reading
`sensor["latest"]["value"]` returns `None` for every row and the pipeline runs
clean while producing nothing. Values come from `/v3/locations/{id}/latest`,
joined on `sensorsId`:

```
/v3/locations?bbox=...        -> sensors[].id  ->  pollutant, units
/v3/locations/{id}/latest     -> results[].sensorsId, .value, .datetime.utc
```

### Live station coverage in NCR is far thinner than assumed

Measured freshness of 116 NCR stations with a `datetimeLast`:

| Reported within | Stations |
|---|---|
| 3 hours | **7** |
| 24 hours | 7 |
| 72 hours | 7 |
| 7 days | 79 |
| 30 days | 80 |

There is a hard gap between 2.1 h and 82.7 h. Seven stations are genuinely live;
about 72 more went silent 4–7 days ago, which looks like a stalled CPCB→OpenAQ
feed rather than 72 simultaneous hardware failures.

**Consequences, and they matter:**

- The plan assumed ~40 Delhi / ~80 NCR live monitors. The live figure is **7**.
- The *product thesis is unaffected or strengthened* — the monitoring gap is worse
  than we claimed. But the **IDW baseline weakens** (fewer stations to interpolate
  from, and `compute_idw_baseline` needs ≥2 within 50 km), and a live demo built on
  7 points will look sparse.
- **Training is not affected.** See below.

### Historical data is available, so training is viable

`/v3/sensors/{sensor_id}/measurements` returns paginated history — verified 1,000
PM2.5 measurements for sensor at station 17 (R K Puram, DPCC) spanning
2025-02-18 → 2025-03-03, values 17–204 µg/m³, mean 78.1.

So the ingestion split is:
- **Training backfill** → `/v3/sensors/{id}/measurements`, paginated, per sensor.
- **Live/hourly** → `/v3/locations/{id}/latest`, and accept ~7 stations for now.

This also means the replay-mode decision was right for a second reason: replay is
now the only way to demo against a dense station network.

### NASA FIRMS — two bugs, both silent

**1. The 200 km buffer was never applied.** `calculate_expanded_bbox()` existed and
was dead code; `fetch_firms_fires` queried the raw tenant bbox. Since the fires that
drive Delhi's PM2.5 burn in Punjab and Haryana, *outside* that box, source
attribution had nothing to attribute to. Confirmed after the fix: 3 of the 4
detections now returned sit at 29.47N/76.86E — Haryana, ~120 km NW of Delhi, and
invisible without the buffer.

**2. `date` is the START of a window running FORWARD.** The URL form is
`/{day_range}/{start_date}`. Passing `as_of` directly requests a window that is
mostly in the future and returns zero rows:

| Query | Detections |
|---|---|
| `/2/<today>` | **0** |
| `/3` (no date, rolling) | 4 |
| `/3/<today-2>` | 4 |

Back-date the start by `day_range - 1` so the window ends at `as_of`.

Also: a 20 s timeout was too short and produced intermittent `URLError`. Now 90 s.

CSV columns confirmed: `latitude, longitude, bright_ti4, scan, track, acq_date,
acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight`.

### Open-Meteo — and an ERA5 dependency removed

Forecast API works, no key. **`boundary_layer_height` IS available** — the hedge in
§3 can be removed. BLH values as low as 55 m, consistent with a real inversion.

More important: **`archive-api.open-meteo.com/v1/archive` serves the historical ERA5
reanalysis over plain HTTP with no key.** §3 lists ERA5 as an Earth Engine asset
(`ECMWF/ERA5_LAND/HOURLY`), which made historical meteorology depend on Earth Engine
registration. It no longer does — verified 2025-11-01..08 at 28.63/77.31 returning
192 hourly steps with BLH spanning 10–2280 m.

Earth Engine is **still required** for the satellite layer (MAIAC AOD, Sentinel-5P).
This removes it only from the meteorological path, which means Model A can be
trained on real stations + real meteorology while EE access is pending — just
without the satellite features.

Use `ingestion.meteorology.fetch_open_meteo_archive()` for history (`is_forecast=FALSE`)
and `fetch_open_meteo_forecast()` for live (`is_forecast=TRUE`).

---

## 8. Changing a contract

1. Raise it — do not edit around it.
2. If agreed: bump the version at the top, update this file, update `spec/*.schema.json` if the change is in a published schema, and note the change in the PR.
3. Published spec schemas (`spec/`) follow semver. A breaking change is a major bump and needs a migration note, because outside adopters are the entire point of publishing them.
