# AGENTS.md — VayuSetu

**Read this first. It is the single entry point for any AI coding agent or human working on this repo.**

This file is tool-agnostic and follows the `AGENTS.md` convention read by Cursor, Codex, Windsurf, Gemini CLI, Copilot, Zed, Aider and others. `CLAUDE.md`, `GEMINI.md`, `.cursorrules` and `.github/copilot-instructions.md` all point back here. **Do not duplicate content into them.**

---

## 1. What we are building

**VayuSetu** — a federated air-quality intelligence platform for India. Submission for *Build with AI: Code for Communities, Track 02 — Clean Air & Climate Resilience*.

The product is **not** an AQI dashboard. The product is the **residual**:

> Estimated PM2.5 at a 1 km grid cell, **minus** what interpolation from the existing official station network would have told you.

A large positive residual is a pollution hotspot the government's monitoring network is blind to. Everything else — the satellite ingestion, the citizen photos, the forecasting, the source attribution — exists to produce, explain, or act on that number.

If a proposed feature does not make the residual more accurate, better explained, or more actionable, it is out of scope.

**Full design rationale: [`plan.md`](plan.md). Read it before writing non-trivial code.**

---

## 2. Current status

| | |
|---|---|
| Phase | **Both ML models lose to simple baselines on real data.** Fire attribution holds (r=0.55). Product should pivot to attribution — see TODO.md 2026-09-08c |
| Code written | `infra/`, `ingestion/`, `api/`, `ml/`, `web/`, `spec/`, `docs/` |
| Code **run against real data** | Yes — `python run_ingest.py` writes live OpenAQ/FIRMS/Open-Meteo into BigQuery `vayusetu-507904`, idempotently |
| Contracts frozen | Yes — see [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) |
| Next work | Unblock [`TODO.md`](TODO.md) (OpenAQ, FIRMS, Earth Engine, Maps keys), then re-run Week 1 in [`BACKLOG.md`](BACKLOG.md) for real |
| Model A on real data | LOSO MAE 54.68 vs IDW 52.93 with the FULL feature set — **still loses**. Satellite features did not help. See TODO.md 2026-09-08 |
| Earth Engine | Working. Satellite + static layers backfilled 2026-09-08 |
| Gemini | Verified working; held back from the pipeline by request |
| Done without keys | `README.md`, `LICENSE`, `.gitignore`, `requirements.txt`, git repo, schema-driven registry validation, `ml/evaluate_forecast.py` |

Keep this table current. It is the first thing a new agent reads.

### Live-API note — 2026-09-07

First run against real APIs. Two bugs that only real data could expose:

- **`/v3/locations` carries no values.** `sensor["latest"]["value"]` was always
  `None`; the pipeline would have run clean and written nothing but nulls. Values
  need a second call to `/v3/locations/{id}/latest`, joined on `sensorsId`.
- **The bbox returns long-dead stations** — 24 of 118 last reported in 2018.

Measured facts now recorded in `docs/DATA_CONTRACTS.md` §7a, including that live
NCR coverage is **7 stations**, not the ~40-80 the plan assumed. Historical data is
intact, so training is unaffected; the live view and IDW baseline are.

`ingestion/common.py` gained `write_records()` — ingestion previously had no writer
at all, only a `generate_merge_query()` that produced SQL text nothing executed.

### Audit note — 2026-09-06

A prior revision marked 32 of 37 tasks complete and described the project as
"Week 3 Complete". That was not accurate, and the numbers it produced were not
usable. Corrected in this pass:

- **All model metrics came from `ml/synthetic.py` placeholder data**, never from real
  observations. Artifacts now carry a `data_source` field and are tagged SYNTHETIC.
- **LOSO was not actually spatial.** Station ids were assigned round-robin to random
  rows (`i % 10`), so every station was statistically identical and holding one out
  was equivalent to a random split — the exact leak R1 exists to prevent. Fixed:
  `ml/synthetic.py` now gives each station its own coordinates, static attributes,
  and a partly-unlearnable local emission offset.
- **The IDW baseline was `y_val + noise`** — the held-out labels with noise added.
  That is not a baseline; beating it meant nothing. Fixed: `ml/evaluate.py` now calls
  the real `ml.common.compute_idw_baseline` against the other stations' concurrent
  readings.
- **The model card's numbers were typed by hand** and contradicted the evaluation
  artifact (R² 0.72 vs 0.8604; `n_rows` 87,600 vs 2,500 actually trained on). Fixed:
  `ml/registry.py` now builds the card from the evaluation artifact.
- **The federation transfer "honest metric" was a hardcoded 1.18× multiplier.** Fixed:
  it now returns `None` with `transfer_measured: False` until measured on real
  Lucknow stations.

The lesson worth keeping: code that runs and prints `[OK]` is not the same as code
that works. The Definition of Done in §7 says *real data* for this reason.

---

## 3. Tech stack — decided, do not substitute

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, deployed on Cloud Run |
| Batch jobs | Python on Cloud Run Jobs, triggered by Cloud Scheduler |
| Warehouse | BigQuery |
| Live state | Firestore |
| ML | LightGBM, trained and served via Vertex AI (Model Registry + Endpoints) |
| Geospatial | Google Earth Engine (Python API) |
| GenAI | Gemini 2.5 Flash (vision) and 2.5 Pro (reasoning), via Vertex AI |
| Frontend | React 18 + TypeScript + Vite |
| Map | Google Maps JavaScript API with deck.gl overlay |
| Auth | Firebase Auth — anonymous for citizens, email for officials |
| Storage | Cloud Storage |
| Language/voice | Cloud Translation API + Cloud Text-to-Speech |

**Do not introduce a new dependency for something the stdlib, an existing dependency, or a Google service already does.** If you believe a new dependency is genuinely required, note it in your PR description with one sentence of justification.

**Deliberately rejected, do not add:** PyTorch/TensorFlow (LightGBM is the right model for tabular data of this size), Vertex AI Vision (Gemini multimodal covers it), Dialogflow (Gemini function calling is better here), Redis (Firestore is the cache), Kubernetes (Cloud Run scales to zero), any state management library beyond React context and TanStack Query.

---

## 4. The seven rules

These encode the ways this specific project fails. Violating one is a bug even if the code runs.

**R1 — Spatial cross-validation, never random.** Model A (the grid estimator) must be validated with **leave-one-station-out** CV. A random split leaks catastrophically because consecutive hours at one station are near-identical, and it will report a fake R² above 0.95. Any evaluation code that uses `train_test_split` on this data is wrong. See the `train-and-evaluate` skill.

**R2 — Report honest metrics.** Never round a metric in your favour, never quote an in-sample number as if it were held-out, always show the baseline you beat (persistence and IDW interpolation). An honest R² of 0.68 beats a leaked 0.97, because a judge will ask how we split.

**R3 — Every ingestion module accepts `as_of`.** Replay mode is not a feature bolted on later; it is a parameter threaded through from the first commit. Any ingestion function that implicitly uses `now()` is broken. See `ingestion/common.py`.

**R4 — Citizen photos raise confidence, never set values.** Citizen submissions are untrusted input into a system that alerts government authorities. A photo may increase a cell's confidence score and flag it for review. A photo may **never** set a PM2.5 value, and may **never** be the sole trigger for an alert. Validity gating, geotag bounds checking and per-session rate limiting are mandatory, not optional.

**R5 — Gemini gets structured evidence, not raw speculation.** The source-attribution prompt receives an assembled evidence payload of real numbers and must cite fields from it. Gemini never invents a measurement. If a field is missing, the brief says so.

**R6 — Never wire alerts to real people.** Alert recipients in every environment are mock accounts inside the app. No real official's email, phone or webhook goes into this codebase, including in tests, fixtures and demo data.

**R7 — Don't overclaim in code comments, docs, UI copy or the deck.** We do federated *model sharing*, not federated *learning* with differential privacy. We do a wind-sector cone, not HYSPLIT back-trajectory modelling. The gridded product is daily, the forecast is hourly. Write it that way everywhere.

---

## 5. Repository map

```
plan.md                      Full design document. The why behind everything
AGENTS.md                    This file. Entry point for all agents
BACKLOG.md                   Checkbox work breakdown. Pick tasks from here
CLAUDE.md / GEMINI.md        Thin pointers to this file
.cursorrules                 Thin pointer to this file
.github/copilot-instructions.md   Thin pointer to this file

docs/
  DATA_CONTRACTS.md          FROZEN interfaces. Read before touching any boundary
  CONVENTIONS.md             Code style, errors, logging, testing
  RUNBOOK.md                 Setup, env vars, run locally, deploy
  GLOSSARY.md                Domain terms (AOD, BLH, LOSO, GRAP, MAIAC...)
  SUBMISSION_CHECKLIST.md    What must be true before we submit
  DEPLOYMENT.md              How a new city onboards (scored artifact — write it well)

spec/                        The Digital Public Good. Open schemas, versioned
  hotspot-event.schema.json
  model-card.schema.json
  README.md

.claude/
  agents/                    Six role definitions. Bodies are plain prompts —
                             usable by any tool, not just Claude Code
  skills/                    Three procedures with gotchas. Plain runbooks

README.md                    Public face of the submission. Honest status banner
LICENSE                      Apache-2.0
requirements.txt             Core deps run the harness offline; cloud deps separate

ingestion/                   Source → BigQuery. See data-ingestion agent
ml/                          Features, training, evaluation, registry
  synthetic.py               Station-structured PLACEHOLDER data. Never a result
  evaluate.py                LOSO CV + real IDW baseline
  evaluate_forecast.py       Per-horizon vs persistence + climatology
api/                         FastAPI service, Gemini integrations, alerts
web/                         React console + citizen PWA
notebooks/                   Backtest evidence
infra/                       Project setup, schedulers
```

---

## 6. How to pick up work

1. Read this file, then [`plan.md`](plan.md) §0–§5 for the design, then [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md).
2. Open [`BACKLOG.md`](BACKLOG.md). Take the topmost unchecked task whose dependencies are all checked.
3. Check which role in `.claude/agents/` owns that workstream and read that file — it carries the domain gotchas for that area.
4. If the task touches a frozen contract, **stop and ask a human.** Contracts are frozen so that parallel work does not collide.
5. Build the smallest thing that satisfies the task's Definition of Done.
6. Tick the box in `BACKLOG.md` and update §2 of this file if the phase changed.

### If you are not Claude Code

The `.claude/agents/*.md` and `.claude/skills/*/SKILL.md` files have YAML frontmatter that Claude Code uses for routing. **The frontmatter is metadata only.** The body of each file is a plain-English role prompt or procedure. Paste the body into any assistant — Gemini, Copilot, Cursor, Codex, Aider — and it works unchanged. Nothing in this project depends on Claude Code.

---

## 7. Definition of done

A task is done when all of these hold:

- It runs against **real data**, not fixtures, unless the task is explicitly about fixtures.
- It handles the documented failure mode for its data source (see [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) §7). Stations drop out. Satellites are cloud-masked. APIs rate-limit.
- Non-trivial logic has one runnable check — an `assert`-based `demo()` under `if __name__ == "__main__":`, or one small `test_*.py`. No test frameworks beyond pytest, no fixtures factories, no mocking libraries.
- It respects the seven rules in §4.
- The `BACKLOG.md` box is ticked.

---

## 8. Things that are 20% of the score and easy to forget

The rubric weights deployability at 20% and reach at 20%, and both are won with documents rather than code:

- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — a real onboarding runbook for a new city, with a real monthly cost estimate. This is the direct answer to *"could this be piloted within a ministry in weeks?"*
- [`spec/`](spec/) — the open JSON schemas under Apache-2.0. This is what makes the claim "digital public good" true rather than decorative.
- The Lucknow federation transfer, with its **honest** accuracy drop shown.

Do not leave these to the last week.

---

## 9. Communication

- Commit messages: imperative, one line, scoped — `ingestion: add FIRMS upwind sector aggregation`.
- If you discover the plan is wrong, say so in the PR and update `plan.md` in the same change. A stale plan is worse than no plan.
- Flag anything that would require overclaiming to demo. We would rather cut a feature than misrepresent one.
