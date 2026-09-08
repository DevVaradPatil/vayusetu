# GEMINI.md

**All project instructions live in [`AGENTS.md`](AGENTS.md). Read it first.**

This file exists only so Gemini CLI / Code Assist picks up context automatically. Do not duplicate guidance here.

## Quick orientation

- **What we're building:** VayuSetu — detects air pollution hotspots that India's official monitoring network is blind to, forecasts AQI spikes 72h ahead, names the likely source, and lets any Indian city import another city's trained model. Track 02 of *Build with AI: Code for Communities*.
- **Design rationale:** [`plan.md`](plan.md)
- **Frozen interfaces:** [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) — read before touching any boundary
- **Task list:** [`BACKLOG.md`](BACKLOG.md)
- **Role prompts:** `.claude/agents/*.md` — the YAML frontmatter is Claude Code metadata, the body is a plain role prompt that works here unchanged
- **Procedures:** `.claude/skills/*/SKILL.md` — same, plain runbooks

## Non-negotiable

The seven rules in [`AGENTS.md`](AGENTS.md) §4. Most commonly violated:

- **Leave-one-station-out cross-validation, never `train_test_split`,** on the grid model. A random split leaks and reports a fake R² above 0.95.
- **Citizen photos raise confidence, never set values,** and never trigger an alert alone.

## Note on Google AI

This project is *required* to use Google AI in the product — Gemini, Vertex AI, Earth Engine, Translation, TTS. That requirement is about the shipped system, not about which assistant writes the code. Both are satisfied here.
