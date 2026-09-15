# VayuSetu — How It Works

A complete technical walkthrough: what the system does, what data it uses, what
every component computes, and what we measured. Written to be read start to finish
by someone who has not seen the code.

**Last updated:** 2026-09-13

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
| 6 | A day-ahead "will tonight be Severe?" warning beats the calendar | Real archived 24 h model runs, leave-one-out thresholds, 26 nights | **No** — "warn after 6 Nov" scores Peirce **+0.71** against the best weather rule's **+0.61** |
| 7 | **Upwind fires + boundary layer explain the episodes** | 26 days of the real stubble season | **Yes** — r = **+0.55**, **−0.42** |

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
useful.** Nobody has a baseline that says "33 fires are burning 8 km upwind of your
worst station under a 110 m inversion." It is also the half no AQI app offers.

So the product became attribution-first. The ML harnesses stay in the repository so
the result is reproducible, but **no residual map, no forecast and no predictive warning
is served.**

The warning was the last thing tested, in September 2026, and it failed the same way
Model B did. Scored against genuine 24-hour-lead forecasts (Open-Meteo's archived model
runs, not the window's own observed weather) with leave-one-out thresholds, a
"tonight will be Severe" rule reaches Peirce **+0.61** — but **"warn after 6 November"
reaches +0.71.** Over 26 consecutive nights of one seasonal ramp the calendar is the
better predictor, so the apparent skill is the season, not the weather. Its edge over
persistence is +0.20 with a bootstrap 90% CI of **−0.16 to +0.56**. And
`boundary_layer_height_previous_day1` is NULL for every hour of the archive, so the one
driver with a clean mechanism is the one that cannot be forecast at all. Harness:
`ml/evaluate_warning.py`. Full numbers: TODO.md 2026-09-12b.

**Cases are therefore raised from observed conditions, not predicted ones** (§6a). An official
who evacuates a school district on a warning we cannot demonstrate, or who stops
trusting the system after two false alarms, is worse off than with no warning at all.

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
  change in emissions.* In the hero episode it is **110 m**.

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
                    ↑ wind FROM 325°
              ╲     │     ╱
               ╲  fires  ╱     ← ±30° cone, out to 100 km
                ╲   ·   ╱
                 ╲ · · ╱
                  ╲ · ╱
                   ╲ ╱
                    ●  worst trusted station (710 µg/m³)
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
  "city_pm25": 407.3,
  "aqi_band": "Severe",
  "n_stations_reporting": 63,
  "monitors_excluded_as_faulty": ["Arya Nagar, Bahadurgarh - HSPCB", "Sirifort, Delhi - CPCB"],
  "worst_station": { "name": "Rohini, Delhi - DPCC",
                     "pm25": 710.0, "lat": 28.7325, "lon": 77.1199 },
  "wind": { "from_bearing_deg": 325.0, "speed_ms": 2.25 },
  "boundary_layer_m": 110.0,
  "upwind_fires": { "count": 33, "total_fires_within_radius": 68,
                    "nearest_km": 7.9, "transport_time_h": 9.4, "sector_deg": 30.0,
                    "radius_km": 100.0, "window_h": 48 },
  "comparison": { "baseline_14d_mean_pm25": 176.7, "ratio_to_baseline": 2.31 },
  "population_exposed": 24013,
  "missing_fields": []
}
```

Every one of those numbers came out of a query, and only trusted readings reach it.
Until September 2026 this example read `"worst_station": "Arya Nagar ... 768.9"`,
`"boundary_layer_m": 65.0` and 35 upwind fires: the whole analysis was anchored on a
faulty monitor whose surrounding hours ran 642, 161, 587, 769, 0, 741 (§4b).

---

## 4a. Hyper-local events: the hotspot detector

**File: `api/hotspots.py`.**

The track asks for hidden pollution hotspots. §2 killed the way we originally meant to
find them — model estimate minus station interpolation — so this detector uses no model
at all. It asks one question per hour: **is any monitor reading far above the monitors
around it?**

Median and median absolute deviation over every monitor reporting that hour, then

```
robust z = (this monitor − regional median) / (MAD × 1.4826)
```

MAD rather than standard deviation, because one extreme locality would inflate a
standard deviation and hide itself inside the baseline it is compared against. A monitor
is flagged at `z ≥ 3.5` **and** at least 50 µg/m³ above the median **and** reading at
least 90 µg/m³ — the two absolute floors stop a clean day producing "hotspots" that are
20 µg/m³ above a very low median.

Two further conditions, both added after the first version ranked broken instruments
as its worst events: the reading must pass the integrity gate (§4b), and an event is
**confirmed** only when the same monitor was a trusted outlier for at least **two
consecutive hours** with distinct values. Single-hour outliers are listed as unconfirmed
and never raise an alert.

| | Station-hours |
|---|---|
| Statistical outliers (the rule alone) | 248 |
| Refused as sensor faults | **51** |
| Trusted | 197 |
| **Confirmed (≥ 2 h)** | **111**, in 26 localities on 21 days |

The sharpest confirmed events:

| Hour (IST) | Locality | Reading | Regional median | Ratio | Hours |
|---|---|---|---|---|---|
| 4 Nov 18:30 | Sector-51, Gurugram | 370 | 70 | 5.3× | 4 |
| 30 Oct 13:30 | NSIT Dwarka, Delhi | **507** (629 the hour before) | 123 | 4.1× | 3 |
| 28 Oct 05:30 | Arya Nagar, Bahadurgarh | 462 | 146 | 3.2× | 2 |
| 8 Nov 12:30 | Sector 62, Noida | 594 | 191 | 3.1× | 2 |

Arya Nagar appears here on 28 October, before its instrument started failing: the gate
judges readings, not monitors, so a monitor is not blacklisted for faults on other days.

> **What this table used to say.** The first version's top rows were *Arya Nagar 918 vs
> 207* and *CRRI Mathura Road 589 vs 93*. Both are gone: Arya Nagar's hours that morning
> ran 717, 31, 559, 33, 500, 0, 886, 4, 918, 19, 557, 0, 0, 0, and CRRI had zeros within
> three hours. The detector was ranking faults as the worst pollution in the region.

### Reporting nothing is a result

At the hero hour — the peak of the November episode — the detector flags **zero**:
median 457, MAD 110, nothing near 3.5 σ. Every monitor was severe at once. That is the
correct answer, not a miss, and the distinction is operational: a regional blanket needs
a region-wide response, while a local plume needs an inspection team at one address.
Conflating them sends people to the wrong place. So the UI never shows a bare empty
table; it states that the whole region is affected together, and offers the hours where
local events did occur.

### The second detector we deleted

A satellite NO₂ anomaly detector was written first, because Sentinel-5P is the only
signal in this stack that could flag a place with **no monitor at all** — which is what
"hidden" ought to mean. Two measurements killed it:

- `cloud_fraction` is NULL in all **1755** satellite rows we ingest, so cloudy
  retrievals cannot be screened out. A cloud artefact and a plume are indistinguishable.
- No NO₂ anomaly in the window is spatially isolated. On 19 November, 48 cells cleared
  z ≥ 2 while the mean z across **every other cell that day** was 2.51 — the whole grid
  rose together. The remaining candidate days have 1–4 cells each, unscreenable.

A detector that cannot separate a plume from a region-wide day, and cannot rule out a
retrieval artefact, has no business telling an officer where to go. It was deleted
rather than tuned into looking like it worked. The honest consequence is stated in §12:
**this finds hotspots hidden by the average, not hotspots hidden from the network.**

---

## 4b. Can the monitor be trusted? The integrity gate

**File: `api/integrity.py`.**

Every hotspot, alert and brief starts from one number on one monitor, so this runs
before all of them. It is also useful on its own: a monitor that is broken, dark, or
reading implausibly is something a pollution control board has to act on.

**Why it exists.** Measured in our data, and reported nationally:

- Our first hotspot headline, and the anchor of our hero AI brief, was a faulty monitor
  (§4a). 22 of the top 40 first-ranked events had faults nearby.
- In 2025 only **270 of India's 562** real-time monitors gave stable data (Airvoice);
  **40%** of districts have no government monitor at all.
- **13 of Haryana's 31** stations went dark as October 2025's smog built, including
  Gurugram Teri Gram, "non-functional since January" (Newslaundry). Our checks
  independently mark Teri Gram offline with 61 dead-zero hours.
- Panipat's monitor read a flat **183-187 for ten days** while neighbouring districts
  were Severe (The Tribune); water tankers were filmed spraying around the Anand Vihar
  monitor (Newslaundry). The CAG found monitors sited near trees and roads.

**The checks.** Each is a pattern real hourly PM2.5 does not produce. Thresholds come
from the distribution of 35,602 station-hours, not from intuition:

| Flag | Rule | Measured basis |
|---|---|---|
| `stuck` | Same value (±0.05) for 3+ consecutive hours | Runs: 34,875 of 1 h, 302 of 2 h, then 8 of 3 h — a clean break |
| `dead_zero` | Below 5 µg/m³ while the regional median ≥ 60 | 310 readings below 2, only 36 more up to 10 — bimodal |
| `spike` | Up ≥ 200 from the previous hour **and** down ≥ 200 to the next | 39 cases; 99% of hourly changes are under 161 |
| `low_in_episode` | Robust z ≤ −3.5 while the regional median ≥ 250 | The sprinkler / bad-siting signature — a suspicion, not proof |

A reading is **trusted** when no fault flag (the first three) appears at that monitor
within ±3 hours. `low_in_episode` never distrusts a reading; it marks the monitor for
inspection, because a monitor in a genuinely cleaner pocket can read low.

**Monitor status**, over a chosen window (`GET /api/v1/{tenant}/monitors/health`):

| Status | Rule | Action it implies |
|---|---|---|
| `faulty` | Fault flags on ≥ 5% of reported hours | Send the maintenance contractor |
| `offline` | Reported < 50% of expected hours | The monitor is dark |
| `suspect` | 2+ hours far below neighbours during Severe | Inspect siting and surroundings |
| `healthy` | Otherwise | — |

Over the full window: 4 faulty (Arya Nagar 25% of hours; Manesar stuck at 240.2; Alipur
stuck at 161.0 for 29 h; Chandni Chowk runs of zeros), 5 offline, 61 healthy. Each
status carries one stretch of raw readings as evidence, so a claim that a government
monitor is broken can be checked by eye before anyone acts on it.

**Does the core finding survive?** Yes. Recomputed on trusted readings only, daily PM2.5
correlates **+0.572** with upwind fires and **−0.483** with boundary layer height,
against +0.579 and −0.481 on all readings.

**Limits.** These checks catch faults, not bias. Smooth calibration drift, or a monitor
reading somewhat low because of trees or a water tanker, passes; `low_in_episode` only
catches the extreme case. The whole window is flagged in memory once per process, which
suits a replay; live ingestion would flag each hour as it lands.

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
("smoke from 33 fires spotted by satellites is blowing in from the north-west") with coarse
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
| `GET /api/v1/{tenant}/hotspots?ts=` | Hyper-local events for one hour, plus the whole field they stand out from |
| `GET /api/v1/{tenant}/hotspots/top?limit=` | The sharpest local events in the window, ranked, each with its hour |
| `GET /api/v1/{tenant}/monitors/health?ts=&days=` | Every monitor: faulty, offline, suspect or healthy, with evidence |
| `GET /api/v1/{tenant}/cases` | The queue: owner, deadline, overdue, closure verdict, audit trail |
| `GET /api/v1/{tenant}/cases/preview?ts=` | What this hour's measurements justify — **writes nothing** |
| `POST /api/v1/{tenant}/cases/raise?ts=` | Open them, never duplicating open work |
| `POST /api/v1/{tenant}/cases/{id}/acknowledge?actor=` | Take ownership, as a named demo account |
| `POST /api/v1/{tenant}/cases/{id}/close` (multipart) | Photo + note + location; closes only if the evidence and the measurements agree |

Two design decisions:

**Briefs are cached by `(tenant, hour)`.** The inputs for a past hour never change, a
demo hits the same episode repeatedly, and Gemini is capped at 500 requests/day.
Regenerating would burn quota to produce the same paragraph. Generation is also
serialised behind a lock, so a page load firing three requests — or two judges
refreshing at once — produces **one** Gemini call, not three.

**There is deliberately no endpoint serving a predicted hotspot map or a forecast.**
Those were falsified (§2). The absence is the honest design. `/hotspots` is not that
endpoint: it serves measurement only — one monitor against the robust median of the
monitors reporting in the same hour — and returns an empty list when the episode is
regional rather than local.

**Ten endpoints were deleted, not kept.** `/grid` and `/hotspots` used to rank cells by
a Gaussian plume added in Python around a hardcoded coordinate, with
`population_exposed` written literally as `84000 if rank == 1 else 32000`; `/forecast`
returned a "+24h spike" that was the constant 90; `/cells/{id}` returned 310.4 for any
cell id containing "2863". A demo that fabricates the thing the project claims to detect
cannot be told apart from a working one, which makes it worse than no demo. The old-SDK
modules behind them (`api/gemini/attribution.py`, `api/gemini/agent.py`, `api/alerts.py`)
went with them.

Cold call ≈ 10.7 s (BigQuery + Gemini); cached ≈ instant.

**Inputs that reach SQL are validated at the boundary.** The `{tenant}` path value is
interpolated into BigQuery dataset names and the timeline's dates into its query, so one
router-level dependency restricts the tenant to a dataset-safe key and the dates are
pattern-checked. A backtick tenant or SQL in `date_from` returns 422.

---

## 6a. Cases: from a trusted measurement to verified closure

**Files: `api/cases.py`, `api/gemini/closure.py`; triggers in `api/alerts.py`.**

The track asks us to alert authorities for rapid intervention. Research into how India's
response actually works found that it rarely fails at detection. It fails at closure:

- The Green Delhi app took **84,765** pollution complaints in 2024; **10,656** went
  overdue, and no department met its stipulated deadlines.
- Closures are unreliable: one department had **99 of the 183** complaints it "resolved"
  reopened; another 76 of 226.
- CAQM's flying squads report "unsatisfactory levels of compliance" at inspected sites.

So an alert on its own is not the product. A **case** is: work for a named agency, with
a deadline, that can only be closed when the evidence and the measurements agree.

### What opens a case

Only trusted measurements (§4b), and never a forecast — the day-ahead warning was
falsified (§2.4). Triggers live in `api/alerts.py`:

| Kind | Raised when | Owner | Copied | Deadline |
|---|---|---|---|---|
| `local_event` | A **confirmed** hyper-local event (§4a) | The town's municipal body | The state board | 24 h |
| `monitor_fault` | A government monitor is `faulty` or `offline` (§4b) | The monitor's operator | The state board | 72 h |
| `regional_episode` | Regional median ≥ 250 (CPCB Severe) | The state board | CAQM | 12 h |

**Routing needs no lookup service.** Every monitor's name carries its operator and town —
`NSIT Dwarka, Delhi - CPCB`, `Arya Nagar, Bahadurgarh - HSPCB` — so a fault goes to the
operator and a local event to that town's municipal body. Community sensors on OpenAQ
("Air Check", "GK1 (Oberoi Terrace)") get no maintenance case: a state board cannot
repair a private device, and a case nobody can act on is noise. Their readings are still
excluded when untrusted.

Open work is never duplicated: one open case per faulty monitor, one per local event
within 6 hours at the same monitor, one open regional episode. Overdue and escalation to
CAQM are computed when a case is read, from its deadline, so there is no scheduler that
can fail silently.

On 30 October 2025 at 08:00 UTC this opens 9 cases: NSIT Dwarka to the Municipal
Corporation of Delhi, and eight monitor faults — including Faridabad Sector 11, Faridabad
New Industrial Town and Gurugram Sector 51 as dark, the same stations Newslaundry reported
offline in those days.

### How a case closes

Two independent checks, **decided in code** (`decide_closure`, a pure function), never by
the model:

1. **The photo.** Gemini describes it (`api/gemini/closure.py`): is it a genuine camera
   photo of a real place, is an active source still visible (smoke, flames, a dust cloud,
   uncovered material, a garbage heap), is monitoring equipment in frame. It describes;
   it does not decide. A local event also needs the upload within **1 km** of the site.
2. **The measurement.** What the monitor recorded afterwards
   (`outcome_local_event`, `outcome_monitor_fault`, `outcome_regional`), judged on the
   last three trusted hours of a 24-hour window.

| Photo | Measurement | Result |
|---|---|---|
| Passes | Resolved | `closed_verified` |
| Passes | **Persisting** | **Refused** — however good the photo |
| Fails (screenshot, source still visible, too far, missing) | any | **Refused** |
| Passes | No trusted data to judge | `closed_unverified` — never counted as verified |

A refused closure keeps the case open and writes the reasons into the audit trail. The
desk's headline numbers are accountability numbers: open, overdue, closed and verified,
closed without proof, and closures refused.

**Measured on the replay data:**

- NSIT Dwarka (30 Oct): the local excess **subsided 2 h after** the event and stayed
  down, so a valid photo closes it verified.
- Arya Nagar's monitor (16 Nov): **still faulty**, 4 faulty hours in the last 12, so a
  technician's photo cannot close it.
- The region (12 Nov 01:30 IST): **still Severe**, median 304 a day later, so a note that
  GRAP measures were applied cannot close it.

Against BigQuery, closures were refused without a photo, for the region with a note, and
for a synthetic gradient that Gemini classified as a graphic. Email-address "actors" are
rejected.

### Honest limits

- **In the replay, "afterwards" is the 24 recorded hours after the event**, not the hours
  after someone presses Close. In live operation the window starts at the closure.
- **Location is what the uploader's device reports.** Browsers usually strip EXIF GPS,
  so it cannot be cross-checked against the photo itself. For demo reviewers who are not
  in Delhi, the form offers the case's own coordinates; that is recorded as
  `location_source: demo_case_location` and shown in the audit trail as "not a field
  visit".
- **Gemini's closure descriptions are verified only on rejection** (a synthetic image),
  not against a labelled set of real site photos.
- **Photos are not stored**, only their SHA-256 and Gemini's description. That protects
  privacy and keeps the demo free of personal images, and means a disputed closure cannot
  be re-examined from the original photo.

### Guards that are about the shape of the code

**Opening is a POST; previewing is a GET that writes nothing.** Every agency is a demo
account, so no page load could notify anyone — but a page load that assigns work is one
wiring change away from paging a real official, and that change should have to show up in
a diff.

**R6 by construction.** Agencies and actors are a key and a display name beginning
`Demo:`, with no address field of any kind. The self-check asserts it.

**R4.** No case is ever raised from a photo; a photo is only closure evidence.

Writes use `MERGE`/`UPDATE` DML, not the streaming API: streamed rows cannot be updated
for up to 30 minutes, and acting on a case seconds after it opens is the normal case.

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

### Deployed

**https://vayusetu-999960875509.asia-south1.run.app** — one Cloud Run service in `asia-south1` serving the API and the built
site from `web/dist`. Redeploy with `bash infra/deploy.sh`, which builds, deploys and
then smoke-tests the deployment itself. The Gemini key is in Secret Manager; BigQuery,
Translation and Text-to-Speech use the runtime service account. Full setup and the four
things that broke on the way (a missing `.gcloudignore`, a localhost API base baked into
the bundle, a service worker that would have cached API responses on a shared origin,
and Cloud Run swallowing `/healthz`) are in `docs/DEPLOYMENT.md`.

---

## 11. File map

| Path | What lives there |
|---|---|
| `api/evidence.py` | **The core.** Evidence assembly, upwind geometry, event rendering |
| `api/hotspots.py` | Hyper-local event detection, measurement only (§4a) |
| `api/integrity.py` | Per-reading integrity checks and monitor status (§4b) |
| `api/alerts.py` | What an hour's trusted measurements justify (§6a) |
| `api/cases.py` | Case routing, deadlines, closure policy and outcome checks (§6a) |
| `api/gemini/closure.py` | Gemini's description of a closure photo — describes, never decides (§6a) |
| `api/gemini/brief.py` | Prompt, response schema, and the R5 verifier |
| `api/gemini/advisory.py` | Translation into ten languages |
| `api/routes_episode.py` | The product's endpoints, caching and generation lock |
| `api/main.py` | App composition, CORS, `.env` loading, serving the built site |
| `Dockerfile`, `.gcloudignore`, `requirements-api.txt`, `infra/deploy.sh` | The Cloud Run deployment |
| `ingestion/` | OpenAQ, FIRMS, Open-Meteo, Earth Engine → BigQuery, all idempotent MERGE upserts |
| `ml/evaluate.py`, `ml/forecast_real.py`, `ml/evaluate_warning.py` | The falsified models and the falsified warning, kept reproducible |
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
- **Hotspots are hidden by the average, not hidden from the network.** The detector
  compares monitors against monitors, so it can only flag a place that already has one.
  Finding an unmonitored hotspot needs the satellite detector we deleted (§4a), and that
  needs a cloud-screened NO₂ retrieval we do not currently ingest.
- **A hotspot is an anomaly, not an apportioned source.** It says this locality is far
  worse than its surroundings and how many people live there. It does not say what is
  burning; the attribution brief reasons about that separately, from the fire and
  meteorology evidence.
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
- **The public demo's quotas are public.** Anyone can spend Gemini calls (500/day) by
  opening uncached hours or submitting closure photos, and anyone can act on the shared
  demo case queue. Without Gemini the site still shows measurements, hotspots, monitor
  health, cases, translation and speech, and says the explanation is unavailable;
  closures that need a photo are refused rather than accepted. Production would put case actions behind
  identity.
