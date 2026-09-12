<h1>VayuSetu</h1>

**Why the air is bad right now, which district to act on, and who should act.**

Submission for *Build with AI: Code for Communities — Track 02, Clean Air & Climate Resilience.*

---

## The idea

India has plenty of AQI dashboards. Every one of them tells you the same thing: a
number and a colour. None of them tells a district officer **what to do about it**.

VayuSetu answers the three questions that follow the number:

| Question | Answered from |
|---|---|
| *What is happening?* | 70 real CPCB stations via OpenAQ |
| *Where is it worst, far beyond the average?* | Each monitor against the robust median of the monitors around it |
| *Why?* | NASA FIRMS fire detections, sectored by ERA5 wind; boundary layer height |
| *Who should act, and how urgently?* | Gemini, reasoning over the measured evidence |

It then says it again, in the resident's own language.

The site has two views of the same hour. **For officials:** a map of monitors, fires and wind, the measured evidence, the localities running far above everywhere around them, an AI explanation checked against it, and who should act. **For residents:** how bad the air is, what it means for health, what to do and why, entirely in one of ten Indian languages, with the advice read aloud and a way to send a photo of the haze. Both are written for someone who has never seen an air quality map.

### A real episode, generated end to end

`GET /api/v1/ncr/episode?ts=2025-11-11T20:00:00Z` — 01:30 IST, the peak of the
November 2025 Delhi smog event:

> **Severe meteorological trapping combined with 35 upwind fires drives the elevated
> pollution level.**
>
> City PM2.5 reached 406.6 with a boundary layer height of 65.0 metres, creating a
> collapsed inversion that traps local and incoming emissions. Wind coming from
> 338.0 degrees carries smoke from 35 upwind fires within the sector. The current
> pollutant concentration is 2.3 times the 14-day baseline mean.
>
> **IMMEDIATE** — State Pollution Control Board: enforce strict bans on open burning
> and inspect industrial units
> **HIGH** — Municipal Corporation: deploy mechanical street sweepers and water
> sprinklers on arterial roads

Every number in that brief is measured. None is generated.

### The event the city average hid

The same pipeline, 16 November at 11:30 IST. Every dashboard for the region showed
**202 µg/m³** — bad, "Very Poor", an ordinary winter day. One monitor showed this:

> **Arya Nagar, Bahadurgarh — 918 µg/m³. 4.4× the area around it, +711 µg/m³ above the
> regional median, about 2,038 people in that square kilometre.**

That reading was public the whole time. It was hidden by the average, which is the
number GRAP decisions are taken on. Across the 26-day window the rule finds **251
station-hours across 48 localities on every single day**.

At the peak of the smog episode the same detector reports **nothing** — median 457,
every monitor severe together, no local outlier. That is the correct answer, and the
page says so instead of showing an empty table: a regional blanket needs a region-wide
response, a local plume needs an inspection team at one address.

---

## What we learned by testing our own idea

This project started as something else. The original thesis was the **residual** —
a model's PM2.5 estimate minus interpolation from official stations — with a large
positive residual read as a hotspot the government network is blind to.

We tested it properly, and it does not hold on this data:

| Claim tested | Result |
|---|---|
| Gridded model (LightGBM) beats IDW interpolation | **No.** Loses at every network density, 5 to 67 stations |
| Satellite AOD explains where interpolation is wrong | **No.** r = +0.04 |
| The model earns its place where stations are sparse | **No.** It loses *worse* as the network thins |
| 72-hour forecaster beats diurnal persistence | **No.** Loses at every horizon (-5.5% to -59.9%) |
| Day-ahead Severe-night warning beats the calendar | **No.** "Warn after 6 November" scores +0.71; the best weather rule, +0.61 |
| **Upwind fires + boundary layer explain the episodes** | **Yes.** r = **+0.55** and **-0.42** |

Full evidence, including the numbers that killed each hypothesis, is in
[`TODO.md`](TODO.md). Nothing was quietly deleted.

The measurement that mattered most was catching ourselves: the forecaster looked
like a **+42% win over persistence** until we asked whether persistence was a fair
baseline. It is not — PM2.5 has a strong diurnal cycle, so "the value six hours ago"
is a bad guess for structural reasons. Against *diurnal* persistence (same clock
hour, previous day) the model loses at every horizon. That flipped a headline result
from a win to a loss, so the win was dropped.

[`ml/registry.py`](ml/registry.py) enforces this in code: `publish_model_card()`
refuses any model whose leave-one-station-out MAE is not better than the IDW
baseline. It refused ours.

**So we built the half that survived contact with the data.** Attribution never
needed to beat a statistical baseline to be useful — and it is the half no AQI app
offers.

---

## How it works

```
 CPCB / OpenAQ stations ─┐
 NASA FIRMS fires ───────┤
 ERA5 wind + boundary  ──┼──▶ BigQuery ──▶ api/evidence.py ──▶ measured evidence
 layer (Open-Meteo)      │                                            │
 MAIAC AOD, GHSL pop ────┘                                            ▼
 (Earth Engine)                                          Gemini (attribution brief)
                                                                      │
                                            ┌─────────────────────────┤
                                            ▼                         ▼
                                   R5 verifier (code)        Translation API
                                   every citation checked    ten Indian languages
```

**[`api/evidence.py`](api/evidence.py)** assembles one hour of measured evidence: city
and worst-station PM2.5, CPCB AQI band, wind bearing, boundary layer height, and the
fires inside a 30-degree half-angle cone up to 100 km upwind over the previous 48
hours. Anything unavailable is named in `missing_fields` rather than defaulted.

**[`api/gemini/brief.py`](api/gemini/brief.py)** hands that payload to Gemini and gets
back a cause, a confidence, a narrative, role-addressed actions, caveats, and a public
advisory.

**`verify()` enforces the trust boundary in code, not in the prompt.** Every path in
`evidence_cited` must exist in the payload; every entry in `missing_fields` must
appear in the caveats; a brief citing nothing is rejected; actors must name an office,
never a contact detail. A brief that fails twice raises rather than degrading — a
silently-degraded brief is indistinguishable from a real one, which is worse than none.

### It is reasoning, not templating

Same prompt, a different day. **10 November** has 9 upwind fires instead of 35, and
Gemini reclassifies the dominant cause from crop residue burning to *meteorological
trapping* on its own. The conclusion follows the evidence.

## Where Google AI does real work

| Service | Job |
|---|---|
| **Gemini 3.5 Flash Lite** | Reasons over fused multi-source evidence into an attribution brief with role-addressed actions — the reasoning step, not a wrapper |
| **BigQuery (robust statistics)** | Per-hour median and MAD across every reporting monitor, the hyper-local event detector |
| **BigQuery** | Every observation, join and aggregation; the evidence assembly is SQL |
| **Earth Engine** | MAIAC 1 km AOD, Sentinel-5P, WorldCover land use, GHSL population, SRTM elevation |
| **Gemini 3.1 Flash Lite** | Triage of residents' haze photos: rejects screenshots, graphics and indoor shots, grades haze only in genuine outdoor photos, and never produces a pollution reading |
| **Cloud Translation** | The whole resident page in ten Indian languages, in one batched request, not only the advice sentence |
| **Cloud Text-to-Speech** | The advice read aloud in all ten languages, for people who will not or cannot read a screen |
| **Google Maps JavaScript API** | The interactive map: real borders and place names, with the wind fan drawn as geodesic geometry |
| **Cloud Run / Firestore** | Serverless service and live state |

Vertex AI training and serving are wired but currently carry no published model — see
the falsification table above. We would rather ship an empty registry than a model the
registry's own guard rejects.

## Interoperability — the Digital Public Good half

Air pollution crosses administrative boundaries; smoke from Punjab reaches Delhi.
Two open, versioned, Apache-2.0 schemas in [`spec/`](spec/) let independent systems
compose:

- [`hotspot-event.schema.json`](spec/hotspot-event.schema.json) — how you say *"there
  is an episode here, and this is why"* in a form another city, a state dashboard or a
  third-party app can consume.
- [`model-card.schema.json`](spec/model-card.schema.json) — how a city publishes a
  trained model so a city with fewer monitors and no data science team can evaluate
  and import it.

[`ml/registry.py`](ml/registry.py) validates against those published files directly
rather than against a copy — a spec the implementation does not read is decoration.

This is federated **model sharing**: publishing weights and metadata to a shared
registry. It is *not* federated learning — no secure aggregation, no differential
privacy.

## Quickstart

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

With `.env` populated (see [`docs/RUNBOOK.md`](docs/RUNBOOK.md)):

```bash
python -m api.evidence         # assemble measured evidence for the hero episode
python -m api.hotspots         # find hyper-local events; check both the local and regional hours
python -m api.gemini.brief     # generate a brief and verify it against R5
python -m uvicorn api.main:app --port 8080 --reload   # the API, from the repository root
```

Then the website, from `web/` (it needs `VITE_GOOGLE_MAPS_API_KEY` in `web/.env.local`):

```bash
npm install
npm run dev                    # http://localhost:3000
```

No API keys? The model harness runs standalone on placeholder data:

```bash
python -m ml.evaluate            # leave-one-station-out CV against a real IDW baseline
python -m ml.evaluate_forecast   # per-horizon vs persistence and climatology
python -m ml.evaluate_warning    # day-ahead Severe-night warning vs calendar and persistence
```

## Repository

| Path | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Entry point for contributors and AI agents; the seven project rules |
| [`TODO.md`](TODO.md) | The findings, including every falsified hypothesis and its evidence |
| [`plan.md`](plan.md) | Original design rationale, with the superseded sections marked |
| [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) | Frozen interfaces; §7a records measured API reality |
| [`spec/`](spec/) | The open schemas |
| `ingestion/` `ml/` `api/` `web/` | Pipeline, model harness, service, console |

## Limitations

Stated plainly, because a system that briefs public authorities should be honest
about what it does not know.

**Neither ML model is in the product, and neither is a forecast.** Gridded estimation
loses to interpolation; 72-hour forecasting loses to diurnal persistence; and a
day-ahead "will tonight be Severe?" warning loses to the calendar — over 26 consecutive
nights of one seasonal ramp, "warn after 6 November" beats every weather rule we can
build from genuine 24-hour-lead forecasts, and the edge over persistence has a bootstrap
90% CI of −0.16 to +0.56. All three harnesses remain in the repository so the results
are reproducible, but no residual map, no forecast and no predictive warning is served.
Alerts fire on observed conditions instead.

**Hotspots are hidden by the average, not hidden from the monitoring network.** The
detector compares monitors against monitors, so it can only flag a locality that already
has one. A satellite NO₂ detector was written to cover the unmonitored case and then
deleted: `cloud_fraction` is NULL in all 1755 rows we ingest, so cloud artefacts cannot
be screened out, and no NO₂ anomaly in the window is spatially isolated — on 19 November
48 cells cleared z ≥ 2 while the mean z of every other cell that day was 2.51. A detector
that cannot tell a plume from a region-wide day should not be telling an officer where to
go.

**Attribution is correlational.** r = +0.55 between upwind fire count and city PM2.5
over 26 days of one stubble season is a real, correctly-signed relationship with a
clear physical mechanism. It is not a source-apportionment study, and Gemini is
instructed to return `unknown` with low confidence when the evidence does not support
a call.

**Source attribution is a wind-sector cone, not trajectory modelling.** A 30-degree
half-angle cone, 100 km upwind. That is not HYSPLIT; multi-day and vertically complex
transport are out of its reach, and the prompt forbids describing it otherwise.

**The demo is a replay, and says so.** The hero window is 10–13 November 2025, a real
Severe episode with 68 of ~70 stations reporting. The same pipeline running live today
sees 7 stations, because the CPCB-to-OpenAQ feed is largely stalled. Both views are in
the console; the live one is greyed when stale.

**Winter cloud and fog mask the satellite input.** 30–50% missing MAIAC AOD in Delhi
winter is normal; the gap is disclosed in `missing_fields`, not forward-filled.

**Ten languages via machine translation.** Every resident-facing word is Cloud
Translation output, not reviewed by native speakers. When the service is unavailable
the page falls back to English and says so, rather than labelling English as Hindi.

**Photo triage is verified only on rejection.** Against the real model, synthetic
gradients and fake screenshots are rejected with no haze grade. Grading of genuine haze
photographs has not yet been tested against a labelled set.

**Citizen photos are corroborating evidence only.** They raise a cell's confidence
score. They never set a PM2.5 value and never trigger an alert on their own —
untrusted input must not be able to dispatch a government response.

**Alerts go to mock accounts.** No real official's contact details exist anywhere in
this codebase, including in tests and demo data.

**Transfer accuracy is unmeasured.** The Delhi-to-Lucknow import works, but the
degradation figure will only be real once Lucknow's own stations have been ingested
and evaluated. Until then the API returns `transfer_measured: false` rather than an
estimate.

## Licence

Apache-2.0 — see [`LICENSE`](LICENSE). The schemas in [`spec/`](spec/) are published
under the same licence and are intended for reuse by anyone.
