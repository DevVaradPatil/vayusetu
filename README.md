<h1>VayuSetu</h1>

**Finding the air pollution that India's monitoring network cannot see.**

Submission for *Build with AI: Code for Communities — Track 02, Clean Air & Climate Resilience.*

---

> ### Project status — read before evaluating
>
> **This is a working harness, not yet a working system.** The full pipeline is
> implemented end to end, but it has **never run against real data** — the external
> API keys it depends on (OpenAQ, NASA FIRMS, Google Earth Engine, Maps) have not
> been obtained yet. See [`TODO.md`](TODO.md).
>
> Consequently **every metric currently in this repository comes from synthetic
> placeholder data** ([`ml/synthetic.py`](ml/synthetic.py)) and is tagged
> `data_source: SYNTHETIC` in the artifacts. None of it is a result, and none of it
> should be quoted. [`BACKLOG.md`](BACKLOG.md) marks such tasks `[~]`, not `[x]`.
>
> We would rather show you an honest half-finished system than a polished
> misleading one.

---

## The idea

Delhi has roughly 40 official air quality monitors for a metropolitan region of
over 30 million people. Between those stations are blind spots several kilometres
wide. A brick kiln cluster, a construction site, a landfill fire or a
waste-burning pocket can push local PM2.5 far above what the nearest official
monitor reports — and nothing in the current system notices.

**That gap is the product.** VayuSetu is not another AQI dashboard. Its core output
is the **residual**:

```
residual = model_estimated_PM2.5(cell)  −  interpolation_from_official_stations(cell)
```

A large positive residual is pollution the regulatory network is structurally
blind to. Everything else in this repository exists to compute that number, explain
it, or act on it.

The target output looks like this:

> *Grid cell 28.63N/77.31E is at an estimated PM2.5 of 310 µg/m³. The nearest
> official station reads 180. 84,000 people live in this cell. The likely cause is
> 47 active fire pixels 22 km upwind in Sonipat with a 310° wind at 11 km/h.
> Confidence 0.78. Three citizen photos in the last hour independently report
> heavy haze.*

## How it works

```
 CPCB/OpenAQ stations ─┐
 NASA FIRMS fires ─────┤
 Sentinel-5P + MAIAC ──┼──▶ BigQuery ──▶ LightGBM ──▶ residual ──▶ hotspot
 ERA5 / Open-Meteo ────┤                (Vertex AI)       │
 Citizen photos ───────┘                                  ▼
        │                                        Gemini 2.5 Pro
        └──▶ Gemini 2.5 Flash ──▶ confidence ──▶  source attribution
                (vision triage)                         │
                                                        ▼
                                          multilingual alert (10 languages,
                                          Translation API + Cloud TTS)
```

Two models do the work:

**Model A — gridded estimator.** Learns PM2.5 from satellite and meteorological
variables at locations where a station exists, then predicts at the ~6,000 1 km
cells where none does. Validated by **leave-one-station-out cross-validation**,
because that is the only protocol that measures the claim actually being made.

**Model B — 72-hour forecaster.** Direct multi-horizon (+6/+24/+48/+72 h), quantile
outputs for confidence bands, benchmarked against persistence and climatology.

## Where Google AI does real work

Nothing here is decorative — each of these is load-bearing:

| Service | Job |
|---|---|
| **Gemini 2.5 Flash** | Citizen photo triage — haze severity, visibility estimate, source classification, and the validity gate on untrusted uploads |
| **Gemini 2.5 Pro** | Source-attribution briefs grounded in an assembled evidence payload; the *Ask Vayu* function-calling agent |
| **Vertex AI** | Model training, registry, versioned serving endpoints |
| **Earth Engine** | Sentinel-5P NO₂ and aerosol index, MAIAC 1 km AOD, ERA5 meteorology, WorldCover land use, GHSL population |
| **BigQuery** | Every observation, feature, prediction and backtest |
| **Translation API + Cloud TTS** | Ten-language advisories with spoken output, for users who will not read a dashboard |
| **Cloud Run / Scheduler / Firestore / Maps** | Serverless ingestion, live state, mapping |

## Interoperability — the Digital Public Good half

Air pollution crosses administrative boundaries; smoke from Punjab reaches Delhi.
Two open, versioned, Apache-2.0 schemas in [`spec/`](spec/) let independent systems
compose:

- [`hotspot-event.schema.json`](spec/hotspot-event.schema.json) — how you say *"there
  is a hotspot here"* in a form another city, a state dashboard, or a third-party
  app can consume.
- [`model-card.schema.json`](spec/model-card.schema.json) — how a city publishes a
  trained model so a city with fewer monitors and no data science team can evaluate
  and import it.

The registry implementation validates against these published files directly
([`ml/registry.py`](ml/registry.py)), rather than against a copy — a spec the
implementation does not actually read is decoration.

This is federated **model sharing**: publishing weights and metadata to a shared
registry. It is *not* federated learning — there is no secure aggregation and no
differential privacy. See "Limitations" below.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run the model harness on synthetic data — no API keys or cloud access needed:

```bash
python -m ml.evaluate            # Model A, leave-one-station-out CV + baselines
python -m ml.evaluate_forecast   # Model B, per-horizon vs persistence & climatology
python -m ml.registry            # publish/import a model card against the open spec
```

Every self-check in one go:

```bash
python -m ml.synthetic && python -m ml.evaluate && python -m ml.evaluate_forecast && python -m ml.registry
```

For real data, cloud deployment and replay mode, see [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Repository

| Path | Contents |
|---|---|
| [`plan.md`](plan.md) | Full design rationale — the *why* behind every decision |
| [`AGENTS.md`](AGENTS.md) | Entry point for contributors and AI agents; the seven project rules |
| [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) | Frozen interfaces between workstreams |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | How a new city onboards, with cost estimate |
| [`spec/`](spec/) | The open schemas |
| `ingestion/` `ml/` `api/` `web/` | Pipeline, models, service, frontend |

## Limitations

Stated plainly, because a system that issues alerts to public authorities should
be honest about what it does not know.

**Not yet validated on real data.** The single largest limitation. Every number
this repository currently produces comes from synthetic placeholder data. Expect
real leave-one-station-out R² in the 0.60–0.75 range — meaningfully lower than the
synthetic harness reports, because the synthetic target is a smooth function of its
own features.

**The gridded product is daily, not hourly.** Satellites pass overhead roughly once
a day (Sentinel-5P ~13:30 local). The 1 km grid is anchored to that overpass with
hourly refinement from stations and meteorology. The forecast is hourly. We do not
have hourly 1 km satellite truth and do not claim it.

**Winter cloud and fog mask the satellite input.** 30–50% missing MAIAC AOD in
Delhi winter is normal. Stale satellite data widens confidence bands rather than
being silently forward-filled.

**"Approximately 1 km", not exactly.** The grid is a 0.01° lattice — about 1.11 km
north–south and 0.98 km east–west at 28.5°N. A deliberate simplification that avoids
reprojection in every module.

**Source attribution is a wind-sector cone, not trajectory modelling.** We trace a
±30° cone 100 km upwind. That is not HYSPLIT, and multi-day or vertically complex
transport is out of its reach.

**Federated model sharing, not federated learning.** No secure aggregation, no
differential privacy, no training across parties without sharing data. The
differentially-private version is future work, not a current capability.

**Citizen photos are corroborating evidence only.** They raise a cell's confidence
score. They never set a PM2.5 value and never trigger an alert on their own —
untrusted input must not be able to dispatch a government response.

**Alerts go to mock accounts.** No real official's contact details exist anywhere in
this codebase, including in tests and demo data.

**Transfer accuracy is unmeasured.** The Delhi→Lucknow import works, but the
degradation figure will only be real once Lucknow's own stations have been ingested
and evaluated. Until then the API returns `transfer_measured: false` rather than an
estimate.

## Licence

Apache-2.0 — see [`LICENSE`](LICENSE). The schemas in [`spec/`](spec/) are published
under the same licence and are intended for reuse by anyone.
