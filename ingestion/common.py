"""
ingestion/common.py — Common utilities for ingestion modules.

Provides:
- resolve_as_of(): Replay mode support, threads as_of parameter or REPLAY_AS_OF env var.
- get_cell_id(): Converts (lat, lon) to standard 0.01° grid cell ID.
- retry_with_backoff(): Decorator for resilient HTTP/API requests.
- generate_merge_query(): SQL helper for idempotent BigQuery MERGE upserts.
"""

import functools
import json
import logging
from pathlib import Path
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("vayusetu.ingestion")


def resolve_as_of(as_of: Optional[datetime] = None) -> datetime:
    """
    Resolves the execution timestamp `as_of`.
    Order of precedence:
    1. REPLAY_AS_OF environment variable (ISO 8601 string)
    2. Passed `as_of` argument
    3. Current UTC time (`now(timezone.utc)`)
    
    Guarantees returning a timezone-aware UTC datetime.
    """
    env_replay = os.getenv("REPLAY_AS_OF")
    if env_replay and env_replay.strip():
        try:
            dt = datetime.fromisoformat(env_replay.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError as e:
            logger.warning(f"Failed to parse REPLAY_AS_OF='{env_replay}': {e}. Falling back to argument or current time.")

    if as_of is not None:
        if as_of.tzinfo is None:
            return as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def get_cell_id(tenant: str, lat: float, lon: float) -> str:
    """
    Calculates cell ID per docs/DATA_CONTRACTS.md §1:
    lat_idx = floor(lat / 0.01)
    lon_idx = floor(lon / 0.01)
    cell_id = f"{tenant}-{lat_idx}-{lon_idx}"
    """
    lat_idx = math.floor(lat / 0.01)
    lon_idx = math.floor(lon / 0.01)
    return f"{tenant}-{lat_idx}-{lon_idx}"


def get_cell_center(cell_id: str) -> tuple[float, float]:
    """
    Extracts (lat, lon) center coordinates from cell_id formatted as '{tenant}-{lat_idx}-{lon_idx}'
    """
    parts = cell_id.split("-")
    if len(parts) < 3:
        raise ValueError(f"Invalid cell_id format: {cell_id}")
    lat_idx = int(parts[-2])
    lon_idx = int(parts[-1])
    lat_center = (lat_idx + 0.5) * 0.01
    lon_center = (lon_idx + 0.5) * 0.01
    return (round(lat_center, 4), round(lon_center, 4))


def retry_with_backoff(max_retries: int = 5, initial_delay: float = 1.0, backoff_factor: float = 2.0):
    """
    Decorator to retry function calls on failure with exponential backoff.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"Attempt {attempt}/{max_retries} for {func.__name__} failed permanently: {e}")
                        raise
                    logger.warning(f"Attempt {attempt}/{max_retries} for {func.__name__} failed: {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= backoff_factor
        return wrapper
    return decorator


def generate_merge_query(
    target_table: str,
    staging_table: str,
    primary_keys: List[str],
    columns: List[str]
) -> str:
    """
    Generates BigQuery MERGE DDL query for idempotent upserts.
    """
    join_clause = " AND ".join([f"T.{pk} = S.{pk}" for pk in primary_keys])
    update_clause = ", ".join([f"T.{col} = S.{col}" for col in columns if col not in primary_keys])
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join([f"S.{col}" for col in columns])

    return f"""
    MERGE INTO `{target_table}` T
    USING `{staging_table}` S
    ON {join_clause}
    WHEN MATCHED THEN
        UPDATE SET {update_clause}
    WHEN NOT MATCHED THEN
        INSERT ({insert_cols})
        VALUES ({insert_vals});
    """


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------
#
# Until a BigQuery project is reachable, records land in local newline-delimited
# JSON under data/raw/. This is not a second architecture: the record shape is
# exactly the raw_* schema in docs/DATA_CONTRACTS.md §2, and the same primary keys
# are enforced here, so the BigQuery loader becomes a swap of this one function
# rather than a rewrite. It exists because ingestion had no writer at all —
# generate_merge_query() produces SQL text but never executed anything.

LOCAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _write_bigquery(
    table: str,
    records: List[Dict[str, Any]],
    primary_keys: List[str],
    dataset: str,
) -> Dict[str, int]:
    """
    Load into a staging table, then MERGE into the target.

    The MERGE is what makes a retried Cloud Run Job safe: a plain insert would
    duplicate every row on the second attempt. generate_merge_query() has existed
    since the first commit but was never executed by anything — this is its caller.
    """
    from google.cloud import bigquery  # imported lazily; the harness runs without it

    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise RuntimeError("GCP_PROJECT_ID is not set")
    if not records:
        return {"received": 0, "inserted": 0, "updated": 0, "total_in_partition": 0}

    client = bigquery.Client(project=project)
    target = f"{project}.{dataset}.{table}"
    staging = f"{project}.{dataset}._staging_{table}_{uuid.uuid4().hex[:8]}"

    columns = list(records[0].keys())

    job = client.load_table_from_json(
        records,
        staging,
        job_config=bigquery.LoadJobConfig(
            schema=client.get_table(target).schema,
            write_disposition="WRITE_TRUNCATE",
        ),
    )
    job.result()

    try:
        before = list(client.query(f"SELECT COUNT(*) AS n FROM `{target}`").result())[0].n
        client.query(generate_merge_query(target, staging, primary_keys, columns)).result()
        after = list(client.query(f"SELECT COUNT(*) AS n FROM `{target}`").result())[0].n
    finally:
        client.delete_table(staging, not_found_ok=True)

    counts = {
        "received": len(records),
        "inserted": after - before,
        "updated": len(records) - (after - before),
        "total_in_partition": after,
    }
    logger.info(
        "sink.bigquery table=%s received=%d inserted=%d updated=%d total=%d",
        target, counts["received"], counts["inserted"],
        counts["updated"], counts["total_in_partition"],
    )
    return counts


def write_records(
    table: str,
    records: List[Dict[str, Any]],
    primary_keys: List[str],
    as_of: Optional[datetime] = None,
    dataset: Optional[str] = None,
) -> Dict[str, int]:
    """
    Idempotent upsert, keyed on `primary_keys`.

    Writes to BigQuery when a project and the client library are available, and to
    the local JSONL sink otherwise. Both paths enforce the same primary key, so a
    retried job never duplicates rows either way.

    Pass `dataset` to route explicitly (e.g. "vayusetu_shared" for raw_fires and
    grid_cells, which are not tenant-scoped per docs/DATA_CONTRACTS.md §2).
    """
    if dataset:
        try:
            return _write_bigquery(table, records, primary_keys, dataset)
        except Exception as e:
            logger.warning(
                "BigQuery write to %s.%s failed (%s); falling back to local sink.",
                dataset, table, e,
            )

    as_of_dt = resolve_as_of(as_of)
    out_dir = LOCAL_DATA_DIR / table
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{as_of_dt.strftime('%Y-%m-%d')}.jsonl"

    def key_of(rec: Dict[str, Any]) -> tuple:
        return tuple(str(rec.get(k)) for k in primary_keys)

    existing: Dict[tuple, Dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                existing[key_of(rec)] = rec

    n_before = len(existing)
    n_updated = 0
    for rec in records:
        k = key_of(rec)
        if k in existing:
            n_updated += 1
        existing[k] = rec

    with path.open("w", encoding="utf-8") as f:
        for rec in existing.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    counts = {
        "received": len(records),
        "inserted": len(existing) - n_before,
        "updated": n_updated,
        "total_in_partition": len(existing),
    }
    logger.info(
        "sink.write table=%s path=%s received=%d inserted=%d updated=%d total=%d",
        table, path.name, counts["received"], counts["inserted"],
        counts["updated"], counts["total_in_partition"],
    )
    return counts


def read_records(table: str, as_of: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Read back one partition written by write_records."""
    as_of_dt = resolve_as_of(as_of)
    path = LOCAL_DATA_DIR / table / f"{as_of_dt.strftime('%Y-%m-%d')}.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    # Self-test checks
    print("Testing resolve_as_of()...")
    dt = resolve_as_of()
    assert dt.tzinfo == timezone.utc, "resolve_as_of() must return UTC"
    print(f"  [OK] Current UTC: {dt.isoformat()}")

    # Test cell_id derivation
    cid = get_cell_id("ncr", 28.6315, 77.3102)
    assert cid == "ncr-2863-7731", f"Expected ncr-2863-7731, got {cid}"
    print(f"  [OK] get_cell_id('ncr', 28.6315, 77.3102) -> {cid}")

    center = get_cell_center("ncr-2863-7731")
    assert abs(center[0] - 28.635) < 1e-4 and abs(center[1] - 77.315) < 1e-4
    print(f"  [OK] get_cell_center('ncr-2863-7731') -> {center}")

    print("\nAll ingestion/common.py self-checks passed successfully!")
