"""
api/validation.py — Server-Side Citizen Upload Validation & Trust Boundary Gates.

Enforces mandatory security and data integrity gates per docs/DATA_CONTRACTS.md §3:
1. Geotag bound check against tenant bbox.
2. Timestamp sanity (within 2h window).
3. Session rate limits (10/session/h, 3/cell/session/h).
4. Content-type and file size (< 10 MB).
5. Fusion rule: Citizen reports increment cell confidence score, NEVER set PM2.5 values (AGENTS.md Rule R4).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ingestion.common import get_cell_id

logger = logging.getLogger("vayusetu.api.validation")

# InMemory Rate Limiter state: session_id -> list of timestamps
SESSION_REPORTS_CACHE: Dict[str, List[datetime]] = {}
CELL_SESSION_REPORTS_CACHE: Dict[str, List[datetime]] = {}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_citizen_upload(
    tenant: str,
    bbox: Tuple[float, float, float, float],
    lat: float,
    lon: float,
    photo_ts: datetime,
    file_size_bytes: int,
    content_type: str,
    session_id: str
) -> Tuple[bool, Optional[str]]:
    """
    Executes all 5 server-side trust boundary validation gates.
    Returns (is_valid, rejection_reason).
    """
    # Gate 1: File size & MIME type
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        return False, "file_too_large"
    if content_type.lower() not in ALLOWED_MIME_TYPES:
        return False, "invalid_content_type"

    # Gate 2: Geotag bounding box check
    lat_min, lon_min, lat_max, lon_max = bbox
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        logger.warning(f"Rejected report from session '{session_id}': ({lat}, {lon}) outside tenant '{tenant}' bbox")
        return False, "geotag_outside_bbox"

    # Gate 3: Timestamp freshness check (must be within last 2 hours and not in future)
    now_utc = datetime.now(timezone.utc)
    if photo_ts.tzinfo is None:
        photo_ts = photo_ts.replace(tzinfo=timezone.utc)

    if photo_ts > now_utc + timedelta(minutes=5):
        return False, "timestamp_in_future"
    if now_utc - photo_ts > timedelta(hours=2):
        return False, "photo_too_old"

    # Gate 4: Session Rate Limiting
    cutoff_1h = now_utc - timedelta(hours=1)
    
    session_history = [t for t in SESSION_REPORTS_CACHE.get(session_id, []) if t > cutoff_1h]
    if len(session_history) >= 10:
        logger.warning(f"Rate limit exceeded for session '{session_id}' (10 reports/hour)")
        return False, "session_rate_limit_exceeded"

    cell_id = get_cell_id(tenant, lat, lon)
    cell_key = f"{session_id}:{cell_id}"
    cell_history = [t for t in CELL_SESSION_REPORTS_CACHE.get(cell_key, []) if t > cutoff_1h]
    if len(cell_history) >= 3:
        logger.warning(f"Rate limit exceeded for session '{session_id}' in cell '{cell_id}' (3 reports/cell/hour)")
        return False, "cell_rate_limit_exceeded"

    # Record successful upload timestamp
    session_history.append(now_utc)
    SESSION_REPORTS_CACHE[session_id] = session_history
    
    cell_history.append(now_utc)
    CELL_SESSION_REPORTS_CACHE[cell_key] = cell_history

    return True, None


def apply_fusion_rule(
    current_confidence: float,
    valid_reports_last_hour: int,
    haze_severity_ge_4_count: int
) -> float:
    """
    Enforces Rule R4: Citizen photos raise confidence scores, NEVER set PM2.5 values.
    
    Fusion rule per docs/DATA_CONTRACTS.md §3:
    - 0 reports -> confidence unchanged
    - 1-2 reports with severity >= 4 -> +0.05 each
    - 3+ reports with severity >= 4 -> +0.15 total
    Clamped to [0, 1].
    """
    if haze_severity_ge_4_count == 0:
        increment = 0.0
    elif haze_severity_ge_4_count in [1, 2]:
        increment = 0.05 * haze_severity_ge_4_count
    else:
        increment = 0.15

    new_conf = round(min(1.0, current_confidence + increment), 2)
    return new_conf


def demo():
    print("=== Server-Side Validation & Fusion Gate Demo ===")
    ncr_bbox = (28.20, 76.80, 28.95, 77.60)
    now = datetime.now(timezone.utc)

    # Valid check
    ok, err = validate_citizen_upload(
        tenant="ncr", bbox=ncr_bbox, lat=28.6315, lon=77.3102,
        photo_ts=now, file_size_bytes=2*1024*1024, content_type="image/jpeg",
        session_id="anon_user_101"
    )
    assert ok is True and err is None, f"Expected valid upload, got {err}"
    print("  [OK] Gate 1-4 Valid Upload Passed.")

    # Geotag outside bbox check
    ok_bad, err_bad = validate_citizen_upload(
        tenant="ncr", bbox=ncr_bbox, lat=19.0760, lon=72.8777, # Mumbai coords
        photo_ts=now, file_size_bytes=2*1024*1024, content_type="image/jpeg",
        session_id="anon_user_102"
    )
    assert ok_bad is False and err_bad == "geotag_outside_bbox", f"Expected geotag error, got {err_bad}"
    print(f"  [OK] Geotag Rejection Gate Verified ({err_bad}).")

    # Fusion Rule Check (Rule R4)
    conf_before = 0.65
    conf_after = apply_fusion_rule(conf_before, valid_reports_last_hour=3, haze_severity_ge_4_count=3)
    assert conf_after == 0.80, f"Expected 0.80 confidence after fusion, got {conf_after}"
    print(f"  [OK] Rule R4 Fusion Rule Verified: Confidence {conf_before} -> {conf_after}")

    print("\nAll validation gate checks passed successfully!")


if __name__ == "__main__":
    demo()
