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
| *Why?* | NASA FIRMS fire detections, sectored by ERA5 wind; boundary layer height |
| *Who should act, and how urgently?* | Gemini, reasoning over the measured evidence |

It then says it again, in the resident's own language.

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
| **BigQuery** | Every observation, join and aggregation; the evidence assembly is SQL |
| **Earth Engine** | MAIAC 1 km AOD, Sentinel-5P, WorldCover land use, GHSL population, SRTM elevation |
| **Cloud Translation** | Ten-language advisories, so the finding reaches people who will never open a dashboard |
| **Cloud Run / Firestore / Maps** | Serverless service, live state, mapping |

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
python -m api.gemini.brief     # generate a brief and verify it against R5
uvicorn api.main:app --reload  # the service
```

No API keys? The model harness runs standalone on placeholder data:

```bash
python -m ml.evaluate            # leave-one-station-out CV against a real IDW baseline
python -m ml.evaluate_forecast   # per-horizon vs persistence and climatology
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

**Neither ML model is in the product.** Gridded estimation loses to interpolation;
forecasting loses to diurnal persistence. Both harnesses remain in the repository so
the result is reproducible, but no residual map and no forecast is served.

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

**Ten languages via machine translation.** The API supports ten; the console exposes
eight. Translations are Cloud Translation output, not reviewed by native speakers, and
the endpoint reports `translated: false` rather than labelling English as Hindi when
the service is unavailable.

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
