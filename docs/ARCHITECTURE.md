# VayuSetu — How It Works

A complete technical walkthrough: what the system does, what data it uses, what
every component computes, and what we measured. Written to be read start to finish
by someone who has not seen the code.

**Last updated:** 2026-09-10

---

## 1. What the product is, in one paragraph

Every AQI app in India tells you a number and a colour. VayuSetu answers the three
questions that come *after* the number: **what is happening, why is it happening,
and who should act.** It fuses government station readings, NASA fire detections,
and reanalysis meteorology into a measured evidence payload for a single hour, hands
that payload to Gemini, and gets back an operational brief naming the dominant cause,
the confidence, and the offices that should respond — plus one plain sentence for
residents in their own language.

The distinguishing property is that **the AI never sees a number it did not measure**,
and every claim it makes is checked against the evidence in code before it reaches a
screen.

---

## 2. The story: what we set out to build, and what the data said

This matters more than any single component, because it is why the architecture looks
the way it does.

### 2.1 The original thesis

Delhi has ~40 official monitors for 30+ million people. Between stations are blind
spots kilometres wide. The plan was to train a model that estimates PM2.5 on a 1 km
grid from satellite and meteorology, then compute:

```
residual = model_estimate(cell) − interpolation_from_official_stations(cell)
```

A large positive residual would be *pollution the government network cannot see*.
That residual was going to be the product.

### 2.2 We tested it, and it failed

| # | Hypothesis | Test | Result |
|---|---|---|---|
| 1 | The gridded model beats IDW interpolation | Leave-one-station-out CV, 67 stations, 35k rows | **No** — MAE 53.81 vs IDW 52.93 |
| 2 | Satellite features fix the gap | Added MAIAC AOD, Sentinel-5P NO₂, GHSL population, WorldCover land use | **No** — got *worse*, 54.68 |
| 3 | The model wins where stations are sparse | Subsampled the network from 67 → 5 stations, 3 draws each | **No** — loses at every density, and loses *worse* when sparse (−13.1% at 5 stations) |
| 4 | Satellite AOD explains where interpolation is wrong | Correlated daily IDW error against AOD | **No** — r = +0.04 |
| 5 | The 72-hour forecaster beats persistence | Per-horizon backtest | **No** — see below |
| 6 | **Upwind fires + boundary layer explain the episodes** | 26 days of the real stubble season | **Yes** — r = **+0.55**, **−0.42** |

Grouped by UTC day. On the Indian calendar days the website's chart uses, the same data
gives +0.58 and -0.48.

**The most important measurement was one we nearly got wrong.** Model B initially
showed **+42% over persistence** at +6h — a headline result. But plain persistence
("the value 6 hours ago") is a strawman: PM2.5 has a strong daily cycle, so a 6-hour-old
value is a bad guess for structural reasons, not because forecasting is hard. The fair
baseline is *diurnal persistence* — the same clock hour, one day earlier:

| Horizon | Model MAE | Plain persistence | **Diurnal persistence** | vs diurnal |
|---|---|---|---|---|
| +6h  | 57.77 | 93.15 | **54.75** | **−5.5%** |
| +24h | 64.10 | 53.30 | 53.30 | −20.3% |
| +48h | 84.63 | 66.70 | 55.87 | −51.5% |
| +72h | 95.60 | 75.10 | 59.78 | −59.9% |

Against the honest baseline the model loses at **every** horizon. The +42% was dropped.

### 2.3 Why the failure is structural, not a tuning problem

Measured, not guessed:

| Quantity | Value |
|---|---|
| Real PM2.5 variation across stations **within one hour** | **61.5 µg/m³** |
| Variation the model's features can explain | ~7.5 µg/m³ |
| Variation in temporal features (hour, day, season) across stations | **exactly 0** |

Every NCR station shares essentially the same weather at a given hour. The model
therefore cannot tell one location from another and predicts near the regional mean.
IDW at least uses spatial proximity. Physically: winter NCR pollution is a *regional
smog blanket*, and the genuine within-city variation is driven by very local sources —
traffic, construction, waste burning — that neither 1 km column AOD nor 10 m land use
can resolve.

### 2.4 The pivot

Attribution survived because **it never needed to beat a statistical baseline to be
useful.** Nobody has a baseline that says "35 fires are burning 8 km upwind of your
worst station under a 65 m inversion." It is also the half no AQI app offers.

So the product became attribution-first. The ML harnesses stay in the repository so
the result is reproducible, but **no residual map and no forecast is served.**

> `ml/registry.py` enforces this in code: `publish_model_card()` refuses any model
> whose leave-one-station-out MAE is not better than the IDW baseline. It refused ours.
> The registry is empty on purpose.

---

## 3. Data sources

All real. All ingested into BigQuery. Volumes are what is actually landed today.

| Source | What it gives | Cadence | Volume | Key? |
|---|---|---|---|---|
| **CPCB via OpenAQ v3** | Ground-truth PM2.5 per station | ~15 min, averaged to hourly | 35,602 rows, 70 stations | Yes |
| **NASA FIRMS** | Satellite fire detections (VIIRS), lat/lon + fire radiative power | Per satellite overpass | 3,297 detections | Yes |
| **Open-Meteo ERA5 archive** | Wind speed/direction, **boundary layer height**, temperature, humidity | Hourly | 42,120 rows | **No key** |
| **Google Earth Engine** | MAIAC 1 km AOD, Sentinel-5P NO₂, GHSL population, WorldCover land use, SRTM elevation | Daily / static | 1,755 cell-days + 66 static cells | ADC |
| **Gemini 3.5 Flash Lite** | The reasoning step | On demand | — | Yes |
| **Cloud Translation** | Ten Indian languages | On demand | — | ADC |

Two notes worth knowing:

- **Open-Meteo's archive API needs no key** and serves the same ERA5 reanalysis. This
  removed an Earth Engine dependency for all historical meteorology.
- **The live CPCB→OpenAQ feed is largely stalled.** 167 PM2.5 sensors exist in NCR;
  116 have history spanning Oct–Nov 2025; only **7** have reported in the last 72
  hours. This is why the demo is a replay (§9).

### 3.1 The grid

Everything is keyed to a 0.01° lattice:

```
cell_id = {tenant}-{floor(lat / 0.01)}-{floor(lon / 0.01)}
```

At 28.5°N that is ~1.11 km north–south and ~0.98 km east–west. We call it
"approximately 1 km" rather than exactly 1 km — a deliberate simplification that
avoids reprojection in every module.

---

## 4. The core computation: assembling evidence

**File: `api/evidence.py`.** This is the heart of the system. Given one UTC hour, it
produces a payload of measured facts. Nothing here predicts anything.

### Step 1 — What is happening

Query every station reporting PM2.5 in that hour.

```sql
SELECT station_id, station_name, lat, lon, AVG(value) AS pm25
FROM raw_stations
WHERE pollutant = 'pm25' AND ts = <hour>
GROUP BY station_id, station_name, lat, lon
ORDER BY pm25 DESC
```

Gives the city mean, the station count, and — critically — the **worst-affected
station**, which anchors everything that follows.

The value is banded using the CPCB National AQI thresholds for PM2.5:

| ≤30 | ≤60 | ≤90 | ≤120 | ≤250 | >250 |
|---|---|---|---|---|---|
| Good | Satisfactory | Moderate | Poor | Very Poor | **Severe** |

### Step 2 — What the weather was doing

Meteorology is fetched **for the worst station's own grid cell**, not a city average.
This matters: wind direction drives the upwind search, so it has to be local to the
place we are explaining.

Two variables carry the physics:

- **`wind_dir`** — degrees, and by meteorological convention this is the direction
  the wind comes **FROM**. Getting this backwards would point the analysis at exactly
  the wrong districts.
- **`blh`** — boundary layer height in metres. This is the depth of the atmosphere
  that pollution mixes into. When it collapses below ~200 m, the same emissions are
  concentrated into a fraction of the volume, and concentrations multiply *without any
  change in emissions.* In the hero episode it is **65 m**.

### Step 3 — Which fires could actually have reached here

This is the attribution step. For every fire detected in the previous **48 hours**:

1. **Distance filter** — Haversine distance from the worst station; keep fires within
   **100 km**.
2. **Bearing** — compute the initial great-circle bearing from the station to the fire:

   ```
   θ = atan2( sin(Δλ)·cos(φ₂),  cos(φ₁)·sin(φ₂) − sin(φ₁)·cos(φ₂)·cos(Δλ) )
   ```

3. **Sector test** — the fire is upwind if that bearing falls within **±30°** of
   `wind_dir`, using a wrap-safe angular difference:

   ```
   gap = |((a − b + 180) mod 360) − 180|
   ```

   (Naive subtraction breaks across 0°/360°: 350° and 10° are 20° apart, not 340°.)

4. **Transport time** — mean upwind distance ÷ wind speed, reported in hours, so an
   official can judge whether the smoke has plausibly arrived yet.

```
                    ↑ wind FROM 338°
              ╲     │     ╱
               ╲  fires  ╱     ← ±30° cone, out to 100 km
                ╲   ·   ╱
                 ╲ · · ╱
                  ╲ · ╱
                   ╲ ╱
                    ●  worst station (768.9 µg/m³)
```

> **This is a wind-sector cone, not back-trajectory modelling.** It is not HYSPLIT.
> Multi-day and vertically complex transport are out of its reach, and the Gemini
> prompt explicitly forbids describing it otherwise.

### Step 4 — Is this abnormal?

Compare the hour against the trailing **14-day mean** to get `ratio_to_baseline`.
Context prevents a brief from calling a normal winter day an emergency.

### Step 5 — Say what is missing

Anything unavailable goes into **`missing_fields`** rather than being defaulted to
zero. A missing measurement and a measurement of zero are different facts, and
conflating them is how a system quietly lies.

### The output

```json
{
  "tenant": "ncr",
  "ts": "2025-11-11T20:00:00+00:00",
  "city_pm25": 406.6,
  "aqi_band": "Severe",
  "n_stations_reporting": 65,
  "worst_station": { "name": "Arya Nagar, Bahadurgarh - HSPCB",
                     "pm25": 768.9, "lat": 28.6701, "lon": 76.9254 },
  "wind": { "from_bearing_deg": 338.0, "speed_ms": 2.06 },
  "boundary_layer_m": 65.0,
  "upwind_fires": { "count": 35, "total_fires_within_radius": 71,
                    "nearest_km": 8.3, "sector_deg": 30.0,
                    "radius_km": 100.0, "window_h": 48 },
  "comparison": { "baseline_14d_mean_pm25": 176.7, "ratio_to_baseline": 2.3 },
  "population_exposed": 2038,
  "missing_fields": []
}
```

Every one of those numbers came out of a query.

---

## 5. The AI layer

**File: `api/gemini/brief.py`.** Gemini's job is the part nothing else in the stack
can do: decide **which driver dominates**, how confident that conclusion is, and
**which office should act** — then say it in language a district officer can use.

### The prompt contract

The system prompt states six absolute rules, of which the load-bearing ones are:

1. Use **only** numbers present in the payload. Never invent or estimate a measurement.
2. Every claim must correspond to a field listed in `evidence_cited` (dotted paths).
3. Every entry in `missing_fields` **must** appear in the caveats.
4. If the evidence does not support a confident cause, return `unknown` with low
   confidence. *A confident wrong attribution sends officials to the wrong district —
   worse than saying you do not know.*
5. Actions name a **role or office**, never a person and never a contact detail.
6. Do not describe the method as back-trajectory modelling.

Output is constrained by a **response schema** (`response_mime_type: application/json`
plus an explicit `RESPONSE_SCHEMA`), so the shape is guaranteed by the API, not by
parsing hope.

### Verification in code — the part that matters

A prompt is a request, not a guarantee. **`verify()` re-checks every brief against
the evidence before it is allowed out:**

| Check | Why |
|---|---|
| Every path in `evidence_cited` exists in the payload | Catches a hallucinated field name |
| Every `missing_fields` entry appears in the caveats | Stops silent omission of a known gap |
| A brief citing nothing is rejected | Prose that merely sits next to data is not an explanation |
| Actor contains no `@` and no digits | Enforces "office, not person" (rule R6) |
| Confidence is a number in [0, 1] | Catches malformed output |

**On failure it retries once, then raises.** It does not fall back to a template. A
silently-degraded brief is indistinguishable from a real one, which makes it more
dangerous than no brief at all.

### It reasons; it does not template

The same prompt on a different day produces a different *conclusion*, not different
wording:

| | 11 Nov (hero) | 10 Nov |
|---|---|---|
| Upwind fires | 35 | 9 |
| Cause returned | `crop_residue_burning` | **`meteorological_trapping`** |

Gemini reclassified the dominant driver on its own, because the evidence changed.

### Language and speech

`api/residents.py` builds the resident page's text and translates all of it (labels,
health meanings, tips, the plain-language "why" and the advice) in **one batched Cloud
Translation request** per language: English, Hindi, Bengali, Marathi, Telugu, Tamil,
Gujarati, Kannada, Malayalam and Punjabi. If translation fails, the whole page comes back
in English marked `translated: false`, never a mix.

The "why" sentences are not generated. They are templates filled with measured values
("smoke from 35 fires spotted by satellites is blowing in from the north") with coarse
thresholds, so the simplest explanation on the site is the one we can defend line by line.

`/advisory?audio=true` returns the advice spoken by Cloud Text-to-Speech, in the language
actually returned: if translation fell back to English, so does the voice.

### Photo triage

`api/gemini/vision.py` treats a resident's photo as untrusted. Gemini 3.1 Flash Lite first
decides whether it is a genuine outdoor photograph, and only then grades haze. A rejected
photo carries no grade. A photo never sets a PM2.5 value and never triggers an alert on its
own (rule R4), and the resident page tells people so.

> Two silent failures were removed here. The old triage returned a fixed "heavy haze, crop
> burning, 0.81" whenever the Gemini call failed, which on a clean deploy was every call,
> because it imported an end-of-life SDK absent from `requirements.txt`. Spoken advisories
> carried the same `GOOGLE_APPLICATION_CREDENTIALS` gate that had broken translation, so
> they never ran. Verified since: synthetic images are rejected by the real model, and
> audio is produced in all ten languages. Grading of real haze photos is not yet tested.

> A bug worth recording: `_translate_text()` used to gate on
> `GOOGLE_APPLICATION_CREDENTIALS`, an environment variable that Application Default
> Credentials **never sets**. So on exactly the machines where translation worked, it
> short-circuited to a mock — returning English while the endpoint reported
> `translated: true`. For a feature whose entire purpose is reaching non-English
> speakers, that is a real failure. `is_mock_translation()` now makes the caller
> report the truth.

---

## 6. The API

**Files: `api/main.py` (composition), `api/routes_episode.py` (the product).**

| Endpoint | Returns |
|---|---|
| `GET /healthz` | Liveness |
| `GET /api/v1/{tenant}/episode?ts=` | **The core call.** Measured evidence + verified brief |
| `GET /api/v1/{tenant}/timeline?date_from=&date_to=` | Daily PM2.5 against upwind fires and BLH |
| `GET /api/v1/{tenant}/map?ts=` | Stations and fires for one hour, for drawing |
| `GET /api/v1/{tenant}/advisory?ts=&lang=&audio=` | The public sentence, translated, optionally spoken |
| `GET /api/v1/{tenant}/residents?ts=&lang=` | Everything the resident view shows, translated in one batch |
| `POST /api/v1/{tenant}/reports` | A resident's haze photo: upload gates, then Gemini triage |
| `GET /api/v1/{tenant}/event?ts=` | The episode in the **open interchange format** (§8) |

Two design decisions:

**Briefs are cached by `(tenant, hour)`.** The inputs for a past hour never change, a
demo hits the same episode repeatedly, and Gemini is capped at 500 requests/day.
Regenerating would burn quota to produce the same paragraph. Generation is also
serialised behind a lock, so a page load firing three requests — or two judges
refreshing at once — produces **one** Gemini call, not three.

**There is deliberately no endpoint serving a predicted hotspot map or a forecast.**
Those were falsified (§2). The absence is the honest design.

Cold call ≈ 10.7 s (BigQuery + Gemini); cached ≈ instant.

**Inputs that reach SQL are validated at the boundary.** The `{tenant}` path value is
interpolated into BigQuery dataset names and the timeline's dates into its query, so one
router-level dependency restricts the tenant to a dataset-safe key and the dates are
pattern-checked. A backtick tenant or SQL in `date_from` returns 422.

---

## 7. The website

**Files: `web/src/`.** React and Vite, Material 3 tokens (`theme.css`), the Google Maps
JavaScript API, Phosphor icons and self-hosted Roboto. Written to be understood by someone
who has never seen an air quality map.

Two views of the same hour, switched at the top and kept mounted, so returning to the map
does not reload it (each new Google map is a billed load).

**For officials** (`OfficialsView.tsx`)

| Part | What it shows |
|---|---|
| **Summary** | The answer first, in plain words ("Air across Delhi NCR was Severe on 12 November 2025 at 1:30 am"), the measured reasons, and what the level means for health |
| **How to read this page** | A first-visit guide to the circles, the fires and the wind fan, dismissed once |
| **Map** | Monitors coloured by CPCB level, fires sized by heat, the wind fan in geodesic geometry; tap any monitor or fire for its reading |
| **Measurements** | City average, worst monitor, air ceiling (flagged when it traps smoke) and fires upwind, each with an (i) explainer |
| **Why is the air bad?** | Gemini's cause and confidence, the narrative, and the cited measurements written as a person would say them ("Air ceiling: 65 m") |
| **What should be done** | Actions by office and urgency |
| **Advice for the public** | Ten languages, and a Listen button |
| **Four weeks** | Daily PM2.5 bars with the fire count; pick a day, by mouse or keyboard, to re-run everything |

**For residents** (`ResidentsView.tsx`): the level in large type on its own colour, what it
means for health, what to do, why, and the photo report, all in the chosen language. The
photo is shrunk and re-encoded in the browser before upload, which also strips EXIF location
and device data.

Plain language is a design rule, not a tooltip: "air ceiling" rather than boundary layer,
"wind fan" rather than upwind sector, with the technical meaning one (i) away. Colours follow
two locks: blue is the interface, the green-to-red ramp is data only, and band colours appear
as fills with contrast-checked text. Themes follow the device. Timeline days are Indian
calendar days, so the day picked and the time shown always agree. The site installs as an
app (`manifest.webmanifest`, and a service worker that never caches readings) and opens on
the resident view.

The timeline is still the visual argument for the whole product: the tall bars line up with
the fire spikes.

> One bug caught while writing this document: the map header drew its cone from a
> *city-average* wind bearing (322°) while the brief cited the *worst-station* bearing
> (338°) — two different winds for the same hour on the same screen. Worse, the average
> was an arithmetic mean of angles, which is meaningless for circular quantities
> (350° and 10° average to 180° — exactly backwards). Meteorology now has one source.

---

## 8. Federation — the Digital Public Good half

Air pollution crosses administrative boundaries; smoke from Punjab reaches Delhi.
Two open, versioned, Apache-2.0 schemas in `spec/` let independent systems compose.

### `hotspot-event.schema.json` v2.0.0

How you say *"there is an episode here, and this is why"* in a form another city, a
state dashboard, or a third-party app can consume. It carries the observation, the
**measured drivers**, and the attribution — so a consumer can re-derive the conclusion
**without trusting, or even knowing about, the publisher's models.**

> **Version 2.0.0 exists because v1.0.0 was a lie of omission.** It *required*
> `predicted_pm25`, `station_idw_baseline` and `residual_pm25` — three fields the
> product stopped producing when the residual thesis was falsified. Nothing VayuSetu
> emitted could validate against its own published spec, and no code read the file
> either way. v2.0.0 is episode-shaped, and the residual fields are kept but demoted
> to **optional**, so a city whose estimator *does* beat IDW can still publish one.
> `api/evidence.to_event()` produces it, `/event` serves it, and the self-check in
> `api/evidence.py` validates a real assembled episode against the schema file on
> every run.

### `model-card.schema.json`

How a city publishes a trained model so a city with fewer monitors and no data science
team can evaluate and import it. `ml/registry.py` validates against the published file
directly rather than a Python copy — *a spec the implementation does not read is
decoration.*

**This is federated model *sharing*, not federated learning.** No secure aggregation,
no differential privacy, no training across parties without sharing data.

---

## 9. Honesty measures

Seven project rules govern every change (`AGENTS.md` §4). The ones with teeth:

| Rule | Enforcement |
|---|---|
| **R1** — never a random train/test split | Leave-one-station-out only. A random split leaks: the same station's neighbouring hours land on both sides. |
| **R2** — report honest metrics | `publish_model_card()` **refuses** a model that loses to its IDW baseline. It refused ours. |
| **R3** — every ingestion module accepts `as_of` | Makes replay exact and prevents accidental lookahead |
| **R4** — citizen photos raise confidence, never set values | Untrusted input must never dispatch a government response |
| **R5** — Gemini gets structured evidence | Enforced by `verify()`, §5 |
| **R6** — never wire alerts to real people | No real official's contact details exist anywhere, including tests and demo data |
| **R7** — do not overclaim | The demo is labelled **REPLAY** on screen |

**The demo is a replay, and says so.** The hero window is 10–13 November 2025, a real
Severe episode with 68 of ~70 stations reporting — the densest the network gets. The
same pipeline running live today sees 7 stations and ~50 µg/m³, because the upstream
feed is stalled. Both views exist; the live one is greyed when stale.

---

## 10. Running it

**Prerequisites:** Python 3.11+, Node 18+, a populated `.env`, and `gcloud auth
application-default login` for BigQuery, Earth Engine and Translation.

```bash
pip install -r requirements.txt
cd web && npm install && cd ..
```

**Terminal 1 — the API** (loads `.env` itself; real environment variables win, so
Cloud Run is unaffected):

```bash
python -m uvicorn api.main:app --port 8080 --reload
```

**Terminal 2 — the console:**

```bash
cd web && npm run dev
```

Open **http://localhost:3000**. `web/.env.local` points it at `http://localhost:8080` and
holds `VITE_GOOGLE_MAPS_API_KEY`. The API command runs from the repository root; the
website runs from `web/`.

**Standalone checks, no browser:**

```bash
python -m api.evidence         # assemble the hero episode; validates against the open schema
python -m api.gemini.brief     # generate a brief and verify it against R5
python -m ml.evaluate          # leave-one-station-out CV vs a real IDW baseline
python -m ml.evaluate_forecast # per-horizon vs persistence and climatology
```

---

## 11. File map

| Path | What lives there |
|---|---|
| `api/evidence.py` | **The core.** Evidence assembly, upwind geometry, event rendering |
| `api/gemini/brief.py` | Prompt, response schema, and the R5 verifier |
| `api/gemini/advisory.py` | Translation into ten languages |
| `api/routes_episode.py` | The product's endpoints, caching and generation lock |
| `api/main.py` | App composition, CORS, `.env` loading |
| `ingestion/` | OpenAQ, FIRMS, Open-Meteo, Earth Engine → BigQuery, all idempotent MERGE upserts |
| `ml/evaluate.py`, `ml/forecast_real.py` | The falsified models, kept reproducible |
| `ml/registry.py` | Model card publish/import with the R2 guard |
| `spec/` | The two open schemas |
| `api/residents.py` | The resident page's words: plain-language why, CPCB health meanings, batched translation |
| `api/gemini/vision.py` | Photo triage, with no fallback grade |
| `web/src/components/` | Officials and resident views, map, explanation panel, timeline |
| `web/src/theme.css` | Material 3 tokens for light and dark, and every layout rule |
| `TODO.md` | Every finding, with the numbers that killed each hypothesis |
| `docs/DATA_CONTRACTS.md` | Frozen interfaces; §7a records measured API reality |

---

## 12. Limitations

Stated plainly, because a system that briefs public authorities should be honest
about what it does not know.

- **Neither ML model is in the product.** Estimation loses to interpolation;
  forecasting loses to diurnal persistence.
- **Attribution is correlational.** r = +0.55 over 26 days of one stubble season is a
  real, correctly-signed relationship with a clear physical mechanism. It is not a
  source-apportionment study.
- **The upwind cone is not trajectory modelling.** ±30°, 100 km, straight-line.
- **Winter cloud and fog mask the satellite input.** 30–50% missing MAIAC AOD in Delhi
  winter is normal; the gap is disclosed, not forward-filled.
- **`dist_major_road_m` is always NULL.** Earth Engine has no free global roads layer.
- **Translations are machine output**, not reviewed by native speakers.
- **Photo triage is verified only on rejection.** Synthetic images are rejected by the real
  model; grading of genuine haze photographs has not been tested against a labelled set.
- **Transfer accuracy is unmeasured.** The Delhi→Lucknow import works, but the
  degradation figure is only real once Lucknow's own stations are ingested. Until then
  the API returns `transfer_measured: false` rather than an estimate.
- **The live view is thin** — 7 stations — because the upstream feed is stalled.
