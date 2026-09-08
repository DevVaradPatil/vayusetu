# Copilot instructions

**All project instructions live in [`AGENTS.md`](../AGENTS.md) at the repo root. Read it first.**

## Project

VayuSetu — federated air-quality intelligence for India. It detects pollution hotspots that the official CPCB monitoring network is blind to, forecasts AQI spikes 72 hours ahead, attributes likely sources from satellite fire data and wind, and lets any Indian city import another city's trained model.

The core output is the **residual**: model-estimated PM2.5 at a 1 km cell, minus what interpolation from existing stations would have said. A large positive residual is a blind spot.

## Where things are

| | |
|---|---|
| Entry point, stack, rules | [`AGENTS.md`](../AGENTS.md) |
| Design rationale | [`plan.md`](../plan.md) |
| Frozen interfaces | [`docs/DATA_CONTRACTS.md`](../docs/DATA_CONTRACTS.md) |
| Task list | [`BACKLOG.md`](../BACKLOG.md) |
| Role prompts | `.claude/agents/*.md` (body is portable, frontmatter is metadata) |
| Procedures | `.claude/skills/*/SKILL.md` |

## Stack

Python 3.11 + FastAPI on Cloud Run · BigQuery · Firestore · LightGBM on Vertex AI · Earth Engine · Gemini 2.5 Flash and Pro · React 18 + TypeScript + Vite · Google Maps JS + deck.gl · Firebase Auth.

Do not substitute these. Do not suggest a new dependency for what an existing one or a Google service already does.

## Rules most often broken

1. **Leave-one-station-out cross-validation on the grid model.** Never `train_test_split` — consecutive hours at one station are near-identical, so a random split leaks and reports a fake R² above 0.95.
2. **Citizen photos raise a cell's confidence score only.** They never set a PM2.5 value and never trigger an authority alert alone. This is a trust boundary: untrusted user input feeding a system that notifies government.
3. **Never wire alerts to real contact details** — not in code, tests, fixtures or demo data. Mock accounts only.
4. **Every ingestion function takes an `as_of` timestamp.** Nothing implicitly calls `now()`.
