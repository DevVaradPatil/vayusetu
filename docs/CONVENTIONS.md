# Conventions

Short by design. If a convention is not written here, follow the surrounding code.

## Python

- Python 3.11. `ruff` for lint and format, line length 100. `mypy` on `ml/` and `api/` only.
- Type hints on every public function. Skip them on obvious locals.
- `pathlib`, not `os.path`. `datetime` with explicit `tz=timezone.utc`, never naive datetimes.
- Dataclasses or pydantic models for structured data. Never a bare dict passed between modules — a dict is where field-name typos go to hide.
- pydantic for anything crossing a trust boundary: API request bodies, LLM responses, config files.

### Errors

- Let it fail loudly in batch jobs. A scheduler job that silently succeeds with no data is worse than one that pages you.
- Catch narrowly — `except requests.HTTPError`, never bare `except Exception` outside a top-level handler.
- Retry only what is worth retrying: 429, 5xx, timeouts. Exponential backoff, max 5 attempts, then fail.
- Never swallow an exception to keep a loop running without counting and logging what you skipped.

### Logging

`structlog` to stdout as JSON — Cloud Run collects it. Every ingestion job logs, at completion:

```python
log.info("ingest.complete", source="openaq", as_of=as_of.isoformat(),
         rows_read=n_read, rows_written=n_written, rows_dropped=n_dropped,
         drop_reasons=drop_counts, duration_s=elapsed)
```

Silent data loss is this project's most dangerous failure mode. Count everything you discard.

### Testing

One runnable check per non-trivial function — a branch, a loop, a parser, anything touching money-equivalent correctness (here: anything feeding an alert).

Preferred, for a module:
```python
if __name__ == "__main__":
    demo()  # asserts against a small real fetch or a fixture
```

Or one `test_*.py` with pytest. **No** fixture factories, no mocking libraries, no per-function test suites unless asked. Trivial one-liners need no test.

The checks that matter most here are the data-quality assertions in `ml/verify_data.py` and the join assertions in `features.sql` — those catch real bugs. A test asserting that a getter returns what it was given catches nothing.

## SQL

- `features.sql` is deliberately SQL, not pandas. Readable equals auditable, and the joins are the risk.
- Uppercase keywords, snake_case identifiers, CTEs over nested subqueries.
- Every CTE gets a one-line comment saying what it produces and its expected row count.
- Assertions at the end of the file, not in a wrapper script — they belong next to the thing they check.
- Always partition and cluster. Always filter on the partition column.

## TypeScript / React

- Strict mode on. No `any` — use `unknown` and narrow.
- Function components, hooks. No class components.
- TanStack Query for all server state. No `useEffect` fetching.
- Component files under 200 lines. Past that, extract.
- Co-locate: `ComponentName.tsx` next to `ComponentName.module.css`.
- API types generated from or hand-mirrored to `docs/DATA_CONTRACTS.md` §5, in `web/src/shared/types.ts` — one definition, imported everywhere.

## Naming

- `cell_id`, `station_id`, `tenant` — exactly these names, everywhere, in every language. Not `cellId` in TypeScript and `cell_id` in Python for the same wire field. The wire format is snake_case; keep it snake_case in TS types too rather than transforming at the boundary.
- Times: variables holding UTC end in `_utc` when ambiguity is possible. Anything displayed is converted at the presentation layer only.
- Units in the name where a mistake is plausible: `distance_km`, `speed_ms`, `blh_m`, `pm25_ugm3` when not obvious from context.

## Config and secrets

- All config via environment variables, listed in `docs/RUNBOOK.md`. No config file with secrets in it, ever.
- Secrets in Secret Manager, injected as env vars at deploy.
- `.env.example` committed with every variable and a dummy value. `.env` gitignored.
- **No API key, service-account JSON, or credential is ever committed.** Check before every commit.

## Comments

Match the surrounding density. Comment *why*, not *what*.

One case where a comment is mandatory: a deliberate simplification with a known ceiling. Name the ceiling and the upgrade path.

```python
# Wind-sector cone rather than full HYSPLIT back-trajectory. Adequate for
# 100km attribution at hourly resolution; upgrade if we need multi-day transport.
```

## Commits

Imperative, scoped, one line:
```
ingestion: add FIRMS upwind sector aggregation
ml: fix leaked station id in grid feature set
web: throttle deck.gl layer rebuild on slider drag
```

## What not to build

From `AGENTS.md` §3, restated because it is the most common drift:

- No abstraction with one implementation. No factory for one product. No config for a value that never changes.
- No new dependency for what an existing one or a Google service already does.
- No scaffolding "for later." Later can scaffold for itself.
- Deletion over addition. Boring over clever.
