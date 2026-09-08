# CLAUDE.md

**All project instructions live in [`AGENTS.md`](AGENTS.md). Read it first.**

This file exists only so Claude Code picks up the context automatically. Do not duplicate guidance here — if something needs saying, it belongs in `AGENTS.md` so every tool sees it.

## Claude Code specifics

- Six subagent roles are defined in `.claude/agents/`. Use them for workstream-scoped work: `data-ingestion`, `ml-modeling`, `gemini-integration`, `frontend-dashboard`, `federation`, `demo-producer`.
- Three skills are defined in `.claude/skills/`. Invoke `train-and-evaluate` before reporting **any** model metric — it encodes the leave-one-station-out protocol that this project's correctness depends on.
- Design rationale: [`plan.md`](plan.md). Frozen interfaces: [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md). Task list: [`BACKLOG.md`](BACKLOG.md).

## Non-negotiable

The seven rules in [`AGENTS.md`](AGENTS.md) §4 apply to every change. The two most commonly violated:

- **Never use a random train/test split on the grid model.** Leave-one-station-out only.
- **Never let a citizen photo set a PM2.5 value or trigger an alert on its own.**
