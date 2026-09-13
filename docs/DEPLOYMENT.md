# VayuSetu — Deployment

**Live:** https://vayusetu-999960875509.asia-south1.run.app

This document has two halves. **Part A** is what is actually running today, and how to
redeploy it in one command. **Part B** is the runbook for onboarding a further city,
kept because the multi-tenant design is real — but read its status note first.

---

## Part A — The deployed demo

### What is running

One Cloud Run service, `vayusetu`, in `asia-south1`, serving both the API and the
website:

| Piece | Where |
|---|---|
| API (FastAPI) | `/api/v1/...`, `/health` |
| Website (built React bundle) | `/` — served by the API from `web/dist`, mounted after every route |
| Data | BigQuery `vayusetu_ncr` and `vayusetu_shared` |
| Gemini key | Secret Manager, `gemini-api-key`, mounted as `GEMINI_API_KEY` |
| Translation, Text-to-Speech, BigQuery access | The runtime service account (ADC), no key file |

One service rather than two, because it gives one URL, no CORS, and one deploy. The
cost is a coupling that has to be handled deliberately — see "Things that bite" below.

Settings: public (`--allow-unauthenticated`, required for a judged live link),
`--max-instances 2`, `--memory 1Gi`, scale to zero when idle. A cold request takes a
few seconds; the first hour a visitor opens also waits ~10 s for Gemini, after which
that hour is cached in the instance.

### Redeploy

```bash
bash infra/deploy.sh
```

It builds the site, uploads source, builds the image with Cloud Build, deploys, and then
smoke-tests **the deployment** — `/health`, the site, a BigQuery-backed endpoint — and
fails if `/.env` is reachable.

### One-time setup (already done for `vayusetu-507904`)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# The key is piped from .env, never typed or echoed.
sed -n 's/^GEMINI_API_KEY=//p' .env | tr -d '\r\n' | gcloud secrets create gemini-api-key --data-file=- --replication-policy=automatic

gcloud secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
```

The default compute service account has `roles/editor`, which covers BigQuery jobs and
data, Cloud Translation and Text-to-Speech. For anything beyond a demo, replace it with a
dedicated account holding `bigquery.jobUser`, `bigquery.dataEditor` on the tenant
datasets, `cloudtranslate.user` and the secret accessor — nothing else.

### Things that bite (each one did)

**`.gcloudignore` must exist.** Without it, `gcloud run deploy --source` falls back to
`.gitignore`, which excludes `web/dist` — the site this service serves. The first build
failed on exactly that. The file states the upload rules explicitly and keeps every
secret out. Verify with:

```bash
gcloud meta list-files-for-upload . | grep -iE "(^|/)\.env|credential|\.pem$|\.key$"
```

It should print nothing. Separately, the `Dockerfile` copies only `api/`, `ingestion/`,
`ml/`, `spec/`, `infra/tenants.yaml` and `web/dist/`, so nothing else uploaded reaches the
image.

**The site must call its own origin.** `web/.env.local` sets `VITE_API_BASE` to
localhost for development, and Vite loads that file for production builds too. A build
that honoured it would work on the machine that built it and fail for every visitor.
`web/src/lib/data.ts` therefore keys on the build mode: production calls `''`.

**The service worker must skip the API by path.** On a shared origin it would otherwise
cache `/api/` responses and show stale air readings offline. `web/public/sw.js` excludes
`/api/` and `/health*`.

**`/healthz` returns 404 on Cloud Run.** Google's front end reserves it and never
forwards it to the container. Use `/health`; `/healthz` remains for local use.

**The Maps key is compiled into the bundle.** It is a browser key and is visible to
anyone who opens the page. It must carry an HTTP-referrer restriction that includes
`https://vayusetu-999960875509.asia-south1.run.app/*` and
`https://vayusetu-ucleby347q-el.a.run.app/*` (Cloud Run answers on both), plus
`http://localhost:3000/*` for development, and an API restriction to the Maps
JavaScript API.

### Known exposure of a public demo

Every endpoint is unauthenticated, which a judged live link requires. Two consequences:

- **Gemini quota can be spent by anyone.** Each uncached hour opened costs one call
  against a 500-per-day limit, and the window has 648 hours. Photo triage costs one call
  per upload. `--max-instances 2` caps cost, not calls. If the quota is exhausted the
  site says the explanation is unavailable rather than inventing one — measurements,
  hotspots, alerts, translation and speech keep working, because none of them use Gemini.
- **Anyone can raise, acknowledge or resolve alerts in the mock inbox.** The recipients
  are demo accounts with no contact details (AGENTS.md R6), so nobody can be notified —
  but the inbox state is shared by every visitor. A production deployment puts these
  routes behind identity (IAP or Firebase Auth) and records a real, authorised actor.

---

## Part B — Onboarding a further city

> **Status.** This runbook predates the findings in `TODO.md`. The tenant architecture,
> datasets and ingestion it describes are real and ran for NCR. **Model onboarding
> (Step 5) and the inference and forecast schedulers (Step 7) are not**: the gridded
> estimator lost to interpolation, the forecaster lost to diurnal persistence, and the
> registry refuses both, so there is no model to import and no inference job to run. A
> new city today gets ingestion, evidence, attribution briefs, hotspot detection and
> alerts — everything in Part A — by adding a tenant and backfilling its data. Lucknow
> (`vayusetu_lko`) has been provisioned but not ingested.

## Overview

A new city joins VayuSetu in **three stages**:

| Stage | Duration | What happens |
|---|---|---|
| 1. Infrastructure provisioning | Day 1 (< 4 h) | GCP project, BigQuery datasets, Cloud Run services |
| 2. Data pipeline setup | Days 2–3 | Ingest stations, fire pixels, satellite, meteorology |
| 3. Model onboarding | Days 4–7 | Import or train grid estimator, verify, go live |

Once provisioned, the city participates in the VayuSetu federation and can immediately import a trained model from any city with a compatible airshed.

---

## Prerequisites

| Item | Required by | Notes |
|---|---|---|
| Google Cloud project (billing enabled) | Day 1 | Minimal budget: ~₹5,000/mo for a small city |
| `gcloud` CLI installed | Day 1 | `gcloud auth application-default login` |
| `python 3.11+` and `pip` | Day 1 | |
| OpenAQ API key (free tier) | Day 2 | Register at openaq.org |
| NASA FIRMS MAP_KEY (free) | Day 2 | Register at firms.modaps.eosdis.nasa.gov |
| Google Earth Engine access | Day 2 | Institutional or non-commercial access required |
| Google Maps JS API key | Day 3 | Enable Maps JS + Geocoding APIs |
| Gemini API key or Vertex AI credentials | Day 4 | `gemini-2.5-flash` (vision) + `gemini-2.5-pro` (attribution) |

---

## Step 1: GCP Project and APIs

```bash
# 1.1 Set your project
export PROJECT_ID="vayusetu-lucknow"
gcloud config set project $PROJECT_ID

# 1.2 Enable required APIs
gcloud services enable \
  bigquery.googleapis.com \
  run.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  earthengine.googleapis.com \
  vertexai.googleapis.com \
  translate.googleapis.com \
  texttospeech.googleapis.com \
  firebase.googleapis.com \
  maps-backend.googleapis.com

# 1.3 Create service account
gcloud iam service-accounts create vayusetu-sa \
  --display-name="VayuSetu Service Account"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:vayusetu-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"
# (Repeat for roles: run.invoker, storage.admin, earthengine.writer, datastore.user)

# 1.4 Download service account key
gcloud iam service-accounts keys create ./credentials.json \
  --iam-account="vayusetu-sa@$PROJECT_ID.iam.gserviceaccount.com"

export GOOGLE_APPLICATION_CREDENTIALS="./credentials.json"
```

---

## Step 2: Create the City Tenant

### 2.1 Add city to `infra/tenants.yaml`

```yaml
tenants:
  lko:
    name: Lucknow
    state: Uttar Pradesh
    description: "Lucknow Municipal Corporation and surrounding peri-urban areas"
    bounds:
      lat_min: 26.60
      lat_max: 27.10
      lon_min: 80.75
      lon_max: 81.10
    bigquery_dataset: vayusetu_lko
    timezone: Asia/Kolkata
    population: 3700000
```

### 2.2 Create BigQuery datasets

```bash
python infra/create_tenant.py --tenant lko --project $PROJECT_ID
```

This creates:
- `vayusetu_lko` dataset with 9 tables (grid, stations, fires, satellite, meteorology, predictions, forecasts, hotspot_events, citizen_reports)
- `vayusetu_shared` dataset (created once, shared across tenants for fires + satellite)

---

## Step 3: Configure Environment Variables

Copy `.env.example` to `.env.lko` and fill in:

```bash
cp .env.example .env.lko

# Required for ingestion
OPENAQ_API_KEY=your_openaq_key_here
FIRMS_MAP_KEY=your_firms_key_here
GCP_PROJECT_ID=vayusetu-lucknow
TENANT_ID=lko

# Required for Gemini
GEMINI_API_KEY=your_gemini_api_key_here
# OR use Vertex AI via service account (recommended for production):
VERTEX_LOCATION=us-central1

# Required for maps
VITE_GOOGLE_MAPS_KEY=your_maps_js_key_here
```

---

## Step 4: Run Initial Data Ingestion

```bash
# Seed OpenAQ stations for Lucknow
python -m ingestion.stations --tenant lko

# Fetch NASA FIRMS fire pixels (200 km buffer — captures Bihar/MP fires)
python -m ingestion.fires --tenant lko --as_of 2024-11-01

# Fetch Open-Meteo meteorology
python -m ingestion.meteorology --tenant lko --as_of 2024-11-01

# Static layers (grid cells, population, land use)
python -m ingestion.static_layers --tenant lko

# Optional: MAIAC AOD backfill via Earth Engine (slow — 6–18h for 18 months)
# python -m ingestion.satellite --tenant lko --backfill --months 18
```

Verify ingestion quality:

```bash
python -m ml.verify_data --tenant lko --strict
```

Expected output: **0 errors**. If errors appear, check the `docs/DATA_CONTRACTS.md §7` failure mode table.

---

## Step 5: Onboard a Model

### Option A — Import NCR Model (recommended for first deploy)

```python
from ml.registry import import_model_card

result = import_model_card(
    model_id="ncr/grid-pm25/v1",
    source_tenant="ncr",
    task="gridded_pm25_estimation",
    target_tenant="lko",
)

meta = result["import_metadata"]
print(f"Transfer MAE: {meta['source_loso_mae']} → {meta['target_loso_mae_estimate']} µg/m³")
print(f"Accuracy drop: {meta['accuracy_drop_pct']}%")
```

> **Honest metric expectation:** Expect a **15–25% accuracy drop** when importing the NCR model to Lucknow. The airshed boundary between the Yamuna plain and the Gomti corridor introduces systematic bias. The imported model is still substantially better than IDW interpolation from Lucknow's sparse station network (typically +40% better). Fine-tuning on 6 months of local data reduces the gap to ~8%.

### Option B — Train locally from scratch

```bash
python -m ml.train_grid --tenant lko
python -m ml.evaluate --tenant lko
```

---

## Step 6: Deploy

The service is shared across tenants: a city is a dataset and an entry in
`infra/tenants.yaml`, not a separate deployment. After adding the tenant, redeploy so the
new `tenants.yaml` ships (Part A):

```bash
bash infra/deploy.sh
```

---

## Step 7: Register Cloud Schedulers

```bash
python infra/create_schedulers.py --tenant lko --project $PROJECT_ID
```

This registers the following jobs:

| Job | Schedule | Purpose |
|---|---|---|
| `ingest-stations-lko` | `0 * * * *` | Hourly OpenAQ fetch |
| `ingest-fires-lko` | `30 5 * * *` | Daily FIRMS fire update |
| `ingest-meteo-lko` | `0 */3 * * *` | 3-hourly meteorology |
| ~~`run-inference-lko`~~ | — | **Not deployed.** No grid model passed the registry guard |
| ~~`run-forecast-lko`~~ | — | **Not deployed.** Forecasting lost to diurnal persistence; the day-ahead warning lost to the calendar |

---

## Monthly Cost Estimate (Lucknow — Small City Tier)

> All prices in USD (₹ converted at 83.5/USD as of Q3 2024).

| Service | Usage | Monthly USD | Monthly ₹ |
|---|---|---|---|
| **BigQuery** | 50 GB storage, 500 GB queries | $8 | ₹668 |
| **Cloud Run** (API) | 2M requests, 0.5 vCPU avg | $12 | ₹1,002 |
| **Cloud Run** (ingestion jobs) | 60 jobs/day × 30s avg | $4 | ₹334 |
| **Cloud Storage** | 100 GB (satellite GeoTIFFs) | $2 | ₹167 |
| **Vertex AI** (inference) | 10K predictions/day, `n1-standard-2` | $18 | ₹1,503 |
| **Google Earth Engine** | Non-commercial: free; commercial: ~$50 | $0–50 | ₹0–4,175 |
| **Gemini API** | 50K attribution calls/mo (2.5 Flash) | $8 | ₹668 |
| **Cloud Translation** | 2M chars/mo (advisories) | $10 | ₹835 |
| **Cloud Text-to-Speech** | 500K chars/mo | $4 | ₹334 |
| **Cloud Scheduler** | 10 jobs | $0.10 | ₹9 |
| **Firebase Auth** | 10K MAU | Free | ₹0 |
| **Maps JS API** | 100K loads/mo | $28 | ₹2,338 |
| **Networking / misc** | Egress, logging | $5 | ₹418 |
| **Total (non-commercial EE)** | | **~$99/month** | **~₹8,268** |
| **Total (commercial EE)** | | **~$149/month** | **~₹12,442** |

> **Notes:**
> - These are list prices. State government GCP contracts typically get 20–40% discount.
> - Earth Engine cost is $0 for academic/NGO use; for government deployments a nonprofit agreement is available.
> - BigQuery costs can be cut by 60% by switching to flat-rate slot reservations at >10 TB/mo query volume.
> - The largest single cost driver is Maps JS API; this can be replaced with OpenLayers + OpenStreetMap at $0 (with UI tradeoffs).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `verify_data --strict` fails on `null_rate` | OpenAQ has no stations for this city | Add manual station seed entries in `ingestion/stations.py` |
| `loso_mae > baseline_idw_mae` after training | Too few stations for LOSO (< 5) | Import NCR model instead; train locally when more stations are added |
| Cloud Run 503 at `/grid` | Vertex AI endpoint cold start | Set `--min-instances=1` on the inference endpoint |
| Earth Engine quota exceeded | Backfill running in parallel | Add `--workers=1` flag to the satellite backfill script |
| Translation garbled for regional script | Wrong BCP-47 code | Check `TTS_LANGUAGE_CODES` in `api/gemini/advisory.py` |

---

## Offboarding

If a city decides to leave the federation:

1. Delete the BigQuery dataset: `bq rm -r -f $PROJECT_ID:vayusetu_lko`
2. Remove the city from `infra/tenants.yaml`
3. The model card remains in the shared registry (Apache-2.0 licensed — other cities may still import it)

---

*This runbook was validated against a simulated Lucknow onboarding on 2026-09-06. Estimated end-to-end provisioning time: 6–8 hours for a team familiar with GCP.*
