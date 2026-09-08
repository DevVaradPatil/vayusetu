# Runbook

Setup, run, deploy. If a step here is wrong or missing, fix it in the same PR that discovered it.

## Prerequisites

- Python 3.11, Node 20, `gcloud` CLI, `bq` CLI
- A GCP project with billing enabled
- An Earth Engine account registered to that project
- API keys: OpenAQ (`X-API-Key`), NASA FIRMS (`MAP_KEY`)

## Enable APIs

```bash
gcloud services enable \
  bigquery.googleapis.com \
  earthengine.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  translate.googleapis.com \
  texttospeech.googleapis.com \
  identitytoolkit.googleapis.com \
  secretmanager.googleapis.com
```

Maps JavaScript API is enabled from the Cloud Console and needs a browser key with an HTTP-referrer restriction — do not use an unrestricted key in the frontend.

## Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Used by | Notes |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | all | |
| `GOOGLE_APPLICATION_CREDENTIALS` | local only | Path to service-account JSON. Cloud Run uses its own identity |
| `VERTEX_REGION` | ml, api | `asia-south1` where available, else `us-central1` |
| `BQ_DATASET_SHARED` | all | `vayusetu_shared` |
| `GCS_BUCKET` | ingestion, api | Photos and EE exports |
| `REGISTRY_BUCKET` | federation | Public bucket for published models |
| `OPENAQ_API_KEY` | ingestion | |
| `FIRMS_MAP_KEY` | ingestion | |
| `GEMINI_MODEL_FLASH` | api | Confirm the current GA id in AI Studio — do not trust a hardcoded string |
| `GEMINI_MODEL_PRO` | api | Same |
| `REPLAY_AS_OF` | all | Unset for live. ISO8601 to drive the whole system from archived data |
| `VITE_API_BASE` | web | |
| `VITE_MAPS_API_KEY` | web | Referrer-restricted browser key |
| `VITE_FIREBASE_CONFIG` | web | JSON blob from the Firebase console |

## Python dependencies

`requirements.txt`:
```
google-cloud-bigquery
google-cloud-storage
google-cloud-firestore
google-cloud-aiplatform
google-cloud-translate
google-cloud-texttospeech
earthengine-api
lightgbm
pandas
numpy
scikit-learn
pyarrow
fastapi
uvicorn[standard]
pydantic
httpx
tenacity
structlog
pyyaml
python-multipart
pillow
```

Dev: `pytest`, `ruff`, `mypy`, `jupyter`.

Do not add to this list without a one-sentence justification in the PR.

## Frontend dependencies

`react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `deck.gl`, `@deck.gl/google-maps`, `@googlemaps/js-api-loader`, `firebase`, `recharts`, `date-fns`. Dev: `vite`, `typescript`, `@vitejs/plugin-react`, `eslint`.

## First-time setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
earthengine authenticate
python infra/create_tenant.py --tenant ncr
python ingestion/static_layers.py --tenant ncr
cd web && npm install
```

## Run locally

```bash
# API
uvicorn api.main:app --reload --port 8080

# Frontend
cd web && npm run dev

# One ingestion job
python ingestion/stations.py --tenant ncr --as-of 2024-11-05T09:00:00Z

# Backfill (satellite is the slow one — start it first)
python ingestion/satellite.py --tenant ncr --from 2024-01-01 --to 2025-09-01
```

## Replay mode

Drives the entire system from archived data. Same code path as live.

```bash
export REPLAY_AS_OF=2024-11-05T09:00:00Z
uvicorn api.main:app --port 8080
```

Or per request on any read endpoint: `?as_of=2024-11-05T09:00:00Z`.

Disclose replay openly in the demo. See `AGENTS.md` R7.

## Train

```bash
bq query --use_legacy_sql=false < ml/features.sql   # check the assertions
python ml/train_grid.py --tenant ncr
python ml/evaluate.py --tenant ncr --model grid --cv loso   # LOSO, not random
python ml/train_forecast.py --tenant ncr
python ml/evaluate.py --tenant ncr --model forecast --split temporal
python ml/registry.py --publish --tenant ncr --model grid
```

Run the `train-and-evaluate` skill before reporting any number.

## Verify data

```bash
python ml/verify_data.py --tenant ncr --window 30d
python ml/verify_data.py --tenant ncr --strict     # before the demo
```

## Deploy

```bash
# API
gcloud run deploy vayusetu-api --source . --region asia-south1 \
  --allow-unauthenticated --min-instances 0

# Frontend
cd web && npm run build
gcloud run deploy vayusetu-web --source . --region asia-south1 --allow-unauthenticated

# Ingestion jobs
gcloud run jobs deploy vayusetu-ingest-stations --source . --region asia-south1 \
  --command python --args ingestion/stations.py

# Schedulers
python infra/create_tenant.py --tenant ncr --schedulers
```

**Demo week:** set `--min-instances 1` on both services. A judge clicking around must not hit a cold start.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Attribution never lines up with fires | `wind_dir` convention inverted. It is the direction wind comes **from**. `DATA_CONTRACTS.md` §2 |
| Model R² above 0.90 | Leak. Random split, station id in features, or a lagged label. Do not celebrate it |
| Satellite job times out | Pulling through `getInfo()`. Export to GCS, then `bq load` |
| Many NULL AOD in winter | Normal — cloud and fog masking. Below 30% coverage suggests a real bug |
| Feature table row count halved | A join is dropping rows. The assertions in `features.sql` should have caught it |
| Gemini returns malformed JSON | Confirm `response_mime_type` is set and the schema is attached. One retry, then fail closed |
| Frontend map blank, no error | Maps key referrer restriction does not include your origin |
| Cold-start timeouts during judging | `--min-instances 1` was not set |
