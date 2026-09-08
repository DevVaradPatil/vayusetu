# Backlog

Pick the topmost unchecked task whose dependencies are all checked. Tick the box when the Definition of Done in [`AGENTS.md`](AGENTS.md) §7 is met.

Owner tags map to `.claude/agents/`. `[blocked: X]` means task X must be done first.

**Status markers:**

| Marker | Meaning |
|---|---|
| `[x]` | Done, and verified against the Definition of Done |
| `[~]` | **Code written, but never run against real data or a real deployment.** Not done |
| `[ ]` | Not started |

`[~]` exists because the Definition of Done requires running against real data. As of the last audit no API keys have been obtained (see [`TODO.md`](TODO.md)), so nothing in the ingestion or deployment path has ever executed for real. Code that has only ever seen `ml/synthetic.py` output is `[~]`, not `[x]`.

---

## Week 1 — Data foundation

- [x] **W1.1** Create GCP project, enable APIs, service accounts, secrets `@data-ingestion`
  - APIs: BigQuery, Earth Engine, Vertex AI, Cloud Run, Cloud Scheduler, Firestore, Storage, Maps JS, Translation, Text-to-Speech, Firebase Auth
- [x] **W1.2** `infra/tenants.yaml` + `infra/create_tenant.py`, create `vayusetu_ncr` and `vayusetu_shared` `@federation` [blocked: W1.1] — 3 datasets, 16 tables created in `vayusetu-507904`
- [x] **W1.3** `ingestion/common.py` — `as_of` resolution, retry/backoff, idempotent upsert, sink `@data-ingestion` — added `write_records()`; idempotency verified on real data
- [x] **W1.4** `ingestion/stations.py` — OpenAQ v3 → `raw_stations`, hourly `@data-ingestion` [blocked: W1.3] — **verified live 2026-09-07**: rewritten as a two-step locations+latest join; real NCR PM2.5 ingested
- [x] **W1.5** `ingestion/static_layers.py` — GHSL population, WorldCover, SRTM elevation `@data-ingestion` — `backfill_static.py`, 66 cells. road distance NULL (no EE roads layer)
- [x] **W1.6** `ingestion/fires.py` — FIRMS → `raw_fires`, 200 km buffer, shared dataset `@data-ingestion` [blocked: W1.3] — **verified live**: buffer was dead code, and the API date is a forward window start; both fixed
- [x] **W1.7** `ingestion/meteorology.py` — Open-Meteo forecast + ERA5 reanalysis `@data-ingestion` [blocked: W1.3]
- [x] **W1.8** `ingestion/satellite.py` — MAIAC AOD + S5P via Earth Engine, GCS export path `@data-ingestion` [blocked: W1.5]
- [x] **W1.9** Backfill satellite for the training window `@data-ingestion` [blocked: W1.8] — **done 2026-09-08** via `backfill_satellite.py`: 1,755 cell-days, 80% AOD coverage. Scoped to the hero window rather than 18 months
- [ ] **W1.10** `infra/schedulers.yaml` + register Cloud Scheduler jobs `@data-ingestion` [blocked: W1.4, W1.6, W1.7, W1.8]
- [~] **W1.11** `ml/verify_data.py` — the checks from the `verify-data-quality` skill `@ml-modeling` [blocked: W1.4]
- [~] **W1.12** FastAPI skeleton + `/healthz` + `/tenants` + `/{tenant}/stations/current`, deployed to Cloud Run `@frontend-dashboard` [blocked: W1.4]
- [~] **W1.13** React + Vite skeleton, Maps base map, live station points `@frontend-dashboard` [blocked: W1.12]
- [x] **W1.14** Write `spec/hotspot-event.schema.json` and `spec/model-card.schema.json` `@federation`
- [x] **W1.15** Replay hero episode frozen: **2025-11-10..13**, 68 stations, city mean 299 ug/m3 peak. Chosen from real data `@demo-producer` — MAIAC still pending (EE), stations + meteorology confirmed

**Week 1 gate:** schedulers firing, 18 months of satellite in BigQuery, map shows live station AQI, `verify_data.py` green.

---

## Week 2 — Models

- [x] **W2.1** `ml/common.py` — IDW baseline, confidence, hotspot test, AQI bands, upwind sector. Implemented **once** `@ml-modeling`
- [x] **W2.2** `ml/features.sql` — the joined training table, with row-count and null-rate assertions after every join `@ml-modeling` — **built on real data**: 35,198 rows, 67 stations, assertions passing
- [~] **W2.3** `ml/train_grid.py` — Model A, LightGBM + quantiles at α 0.1/0.5/0.9 `@ml-modeling` [blocked: W2.2]
- [x] **W2.4** `ml/evaluate.py` — LOSO CV, IDW + station-mean baselines, per-station table `@ml-modeling` [blocked: W2.3] — **run the `train-and-evaluate` skill.** **Run on real data 2026-09-07**: MAE 53.81 vs IDW 52.93 — model does NOT beat baseline. See TODO.md finding
- [~] **W2.5** `ml/train_forecast.py` — Model B, direct multi-horizon, quantiles `@ml-modeling` [blocked: W2.2]
- [~] **W2.6** Forecast evaluation vs persistence and climatology, per horizon, band calibration `@ml-modeling` [blocked: W2.5] — `ml/evaluate_forecast.py` added; runs on synthetic data only
- [ ] **W2.7** Register both models in Vertex AI Model Registry, deploy endpoints `@ml-modeling` [blocked: W2.4, W2.6] — only a local `.pkl` exists; nothing is in Vertex AI
- [~] **W2.8** Inference job → `predictions_grid` + `predictions_forecast`, on a scheduler `@ml-modeling` [blocked: W2.7]
- [~] **W2.9** `api/gemini/vision.py` — photo triage, frozen JSON schema, pydantic validation `@gemini-integration` [blocked: W1.12]
- [~] **W2.10** `api/validation.py` — all five server-side gates on citizen uploads `@gemini-integration` [blocked: W2.9]
- [~] **W2.11** API: `/grid`, `/hotspots`, `/cells/{id}` `@frontend-dashboard` [blocked: W2.8]
- [~] **W2.12** Map: predicted grid layer + **residual layer** `@frontend-dashboard` [blocked: W2.11]

**Week 2 gate:** a real hotspot on the map from real data, with an honest LOSO metric written down. This is the midpoint — if it slips, cut federation before cutting model quality.

---

## Week 3 — Intelligence and reach

- [~] **W3.1** Upwind sector logic + evidence payload assembly `@ml-modeling` [blocked: W2.1]
- [~] **W3.2** `api/gemini/attribution.py` — briefs with enforced citation checking `@gemini-integration` [blocked: W3.1]
- [~] **W3.3** `api/alerts.py` — rules, dispatch to **mock accounts only**, ack flow `@gemini-integration` [blocked: W3.2]
- [~] **W3.4** `api/gemini/agent.py` — Ask Vayu, six tools, citation required `@gemini-integration` [blocked: W2.11]
- [~] **W3.5** `api/gemini/advisory.py` — Translation API + Cloud TTS, cached by `(text_hash, lang)` `@gemini-integration`
- [~] **W3.6** Citizen PWA — camera capture, upload, instant Gemini result card `@frontend-dashboard` [blocked: W2.10]
- [~] **W3.7** Language selector, 10 languages, voice play button `@frontend-dashboard` [blocked: W3.5]
- [~] **W3.8** Console: hotspot table, forecast view with baseline comparison, alert inbox `@frontend-dashboard` [blocked: W2.11, W3.3]
- [~] **W3.9** Time slider, −72h to +72h, observed/forecast boundary visible `@frontend-dashboard` [blocked: W2.11]
- [~] **W3.10** `ml/registry.py` — publish + import model cards `@federation` [blocked: W2.7]
- [ ] **W3.11** Onboard Lucknow via the `add-tenant` skill — **no code changes allowed** `@federation` [blocked: W3.10] — no LKO data ingested, so transfer accuracy is unmeasured
- [ ] **W3.12** Federation view + import flow + honest transfer metrics on screen `@federation` [blocked: W3.11] — import flow works; the degradation figure was hardcoded and has been removed
- [ ] **W3.13** Team photographs 30–50 real NCR skies with genuine geotags as the citizen seed set `@demo-producer`
- [x] **W3.14** `docs/DEPLOYMENT.md` with a **real** monthly cost estimate `@federation`

**Week 3 gate:** full story runs without touching a terminal — citizen photo → hotspot → attribution → alert → multilingual advisory, plus the Lucknow import.

---

## Week 4 — Prove, ship, tell

- [x] **W4.0** Repo hygiene: `git init`, `.gitignore`, `LICENSE` (Apache-2.0), `requirements.txt` — prerequisites for the source-code deliverable

- [ ] **W4.1** `notebooks/backtest_*.ipynb` — forecast vs actual vs persistence for the hero episode `@ml-modeling` [blocked: W2.6]
- [ ] **W4.2** Deploy everything to production URLs, `min-instances=1` for demo week `@frontend-dashboard`
- [ ] **W4.3** Test the deployed link on a real phone on mobile data, from outside our network `@demo-producer` [blocked: W4.2]
- [ ] **W4.4** `ml/verify_data.py --strict` passing on both tenants `@ml-modeling` [blocked: W4.2]
- [x] **W4.5** `README.md` — architecture, setup, honest limitations, licence `@demo-producer` — done; quickstart verified to run offline
- [ ] **W4.6** Verify every claim against the code; cut anything unsupported `@demo-producer` [blocked: W4.1]
- [ ] **W4.7** Record demo video, 3–5 min, per `plan.md` §10 `@demo-producer` [blocked: W4.6]
- [ ] **W4.8** Pitch deck, 10–12 slides, per `plan.md` §11 `@demo-producer` [blocked: W4.6]
- [ ] **W4.9** Brief description, 2–3 lines `@demo-producer`
- [ ] **W4.10** Walk `docs/SUBMISSION_CHECKLIST.md` end to end `@demo-producer`

**Code freezes 48 hours before the deadline.** W4.5 onward get that window.

---

## Cut list — in this order, without debate

1. Animated wind particles (static arrows are fine)
2. Offline PWA support (W3.6 partial)
3. SHAP feature contributions in the cell inspector
4. Languages beyond Hindi + English (keep the selector)
5. Fine-tune step in federation (import alone proves the point)
6. Ask Vayu agent (W3.4)

**Never cut:** residual layer, source attribution, honest metrics, Lucknow import, deployed link.
