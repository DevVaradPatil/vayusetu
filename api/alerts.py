"""
api/alerts.py — Rule-Based Alert Engine for VayuSetu.

W3.3: Generates alerts when hotspot + attribution triggers thresholds.
      Dispatches ONLY to mock accounts (Rule R6 — never real official contacts).
      Supports acknowledgement flow via mock Firestore state.
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ml.common import get_cpcb_aqi_band
from api.gemini.attribution import AttributionBrief, AttributionEvidence

logger = logging.getLogger("vayusetu.alerts")


# ---------------------------------------------------------------------------
# Mock-only alert recipient registry (R6 — no real contacts)
# ---------------------------------------------------------------------------

# Rule R6: ALL recipients are mock accounts. No real official's email/phone goes in this file.
MOCK_RECIPIENTS: Dict[str, Dict[str, str]] = {
    "mock_district_officer": {
        "name": "Demo: District Environment Officer",
        "role": "district_official",
        "channel": "in_app",       # Only in-app mock notification
        "email": "demo.officer@vayusetu-mock.example",  # Non-deliverable mock domain
    },
    "mock_pollution_board": {
        "name": "Demo: State Pollution Control Board",
        "role": "state_board",
        "channel": "in_app",
        "email": "demo.spcb@vayusetu-mock.example",
    },
    "mock_city_commissioner": {
        "name": "Demo: Municipal Commissioner",
        "role": "municipal",
        "channel": "in_app",
        "email": "demo.mc@vayusetu-mock.example",
    },
}


class AlertSeverity(str, Enum):
    WATCH = "watch"       # Residual > 40, not yet hotspot-threshold
    WARNING = "warning"   # Hotspot confirmed (R > 60, PM2.5 > 150, conf > 0.6)
    EMERGENCY = "emergency"  # PM2.5 > 300 and confidence > 0.7


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(BaseModel):
    alert_id: str
    tenant: str
    cell_id: str
    created_at: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN

    # Core pollution data
    pm25_pred: float
    residual: float
    aqi_band: str
    confidence: float
    population_exposed: int

    # Attribution
    cause_category: str
    cause: str
    narrative: str
    evidence_cited: List[str]

    # Dispatch log (in-app only, mock accounts)
    dispatched_to: List[str]
    dispatch_channel: str = "in_app"

    # Acknowledgement
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    ack_note: Optional[str] = None


def _make_alert_id(tenant: str, cell_id: str, severity: AlertSeverity, as_of: datetime) -> str:
    """Generates deterministic alert ID to prevent duplicate alerts for same event."""
    raw = f"{tenant}:{cell_id}:{severity.value}:{as_of.strftime('%Y%m%dT%H')}"
    return "alert_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _select_recipients(severity: AlertSeverity, cause_category: str) -> List[str]:
    """
    Selects appropriate mock recipients based on alert severity and cause.
    Returns list of mock recipient keys.
    """
    if severity == AlertSeverity.EMERGENCY:
        return ["mock_district_officer", "mock_pollution_board", "mock_city_commissioner"]
    elif severity == AlertSeverity.WARNING:
        if cause_category in ("industrial", "vehicular"):
            return ["mock_pollution_board", "mock_district_officer"]
        return ["mock_district_officer"]
    else:  # WATCH
        return ["mock_district_officer"]


def _determine_severity(pm25_pred: float, residual: float, confidence: float) -> Optional[AlertSeverity]:
    """
    Returns alert severity level or None if below watch threshold.

    Thresholds (matched to CPCB GRAP activation levels):
    - EMERGENCY: PM2.5 > 300 and confidence > 0.7
    - WARNING  : residual > 60 and PM2.5 > 150 and confidence > 0.6
    - WATCH    : residual > 40 and PM2.5 > 120
    """
    if pm25_pred > 300.0 and confidence > 0.7:
        return AlertSeverity.EMERGENCY
    elif residual > 60.0 and pm25_pred > 150.0 and confidence > 0.6:
        return AlertSeverity.WARNING
    elif residual > 40.0 and pm25_pred > 120.0:
        return AlertSeverity.WATCH
    return None


def generate_alert(
    tenant: str,
    evidence: AttributionEvidence,
    brief: AttributionBrief,
    population_exposed: int = 0,
    as_of: Optional[datetime] = None,
) -> Optional[Alert]:
    """
    Evaluates alert thresholds against evidence and brief.
    Returns an Alert if thresholds are met, None otherwise.

    R6: All dispatches go to mock accounts only.
    R4: Alert is never triggered by citizen photos alone (confidence gate enforces this).
    """
    as_of_dt = as_of or datetime.now(timezone.utc)

    severity = _determine_severity(
        evidence.pm25_pred, evidence.residual, evidence.confidence_score
    )
    if severity is None:
        logger.debug(f"Cell {evidence.cell_id}: below alert thresholds, no alert generated.")
        return None

    aqi_band, _ = get_cpcb_aqi_band(evidence.pm25_pred)
    alert_id = _make_alert_id(tenant, evidence.cell_id, severity, as_of_dt)
    recipients = _select_recipients(severity, brief.cause_category)

    # Log dispatch to mock accounts — R6 compliance
    for r_key in recipients:
        rec = MOCK_RECIPIENTS.get(r_key, {})
        logger.info(
            f"[MOCK DISPATCH] Alert {alert_id} -> {rec.get('name')} "
            f"via {rec.get('channel')} ({rec.get('email')}) [SEVERITY={severity.value}]"
        )

    alert = Alert(
        alert_id=alert_id,
        tenant=tenant,
        cell_id=evidence.cell_id,
        created_at=as_of_dt.isoformat(),
        severity=severity,
        status=AlertStatus.OPEN,
        pm25_pred=evidence.pm25_pred,
        residual=evidence.residual,
        aqi_band=aqi_band,
        confidence=evidence.confidence_score,
        population_exposed=population_exposed,
        cause_category=brief.cause_category,
        cause=brief.cause,
        narrative=brief.narrative,
        evidence_cited=brief.evidence_cited,
        dispatched_to=recipients,
        dispatch_channel="in_app",
    )

    return alert


def acknowledge_alert(alert: Alert, officer_id: str, note: str = "") -> Alert:
    """
    Updates alert status to ACKNOWLEDGED.
    In production this would update Firestore; here we return updated Pydantic model.
    """
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by = officer_id
    alert.acknowledged_at = datetime.now(timezone.utc).isoformat()
    alert.ack_note = note
    logger.info(f"Alert {alert.alert_id} acknowledged by '{officer_id}'.")
    return alert


def resolve_alert(alert: Alert, officer_id: str, resolution_note: str = "") -> Alert:
    """Marks alert as resolved."""
    alert.status = AlertStatus.RESOLVED
    alert.acknowledged_by = officer_id
    alert.acknowledged_at = datetime.now(timezone.utc).isoformat()
    alert.ack_note = resolution_note
    logger.info(f"Alert {alert.alert_id} resolved by '{officer_id}'.")
    return alert


# ---------------------------------------------------------------------------
# Demo / Self-Test
# ---------------------------------------------------------------------------

def demo():
    print("=== VayuSetu Alert Engine Demo (W3.3) ===")

    # Import attribution module to build evidence + brief
    from api.gemini.attribution import assemble_evidence, generate_attribution_brief
    from ingestion.fires import generate_seed_fires

    ncr_bbox = (28.20, 76.80, 28.95, 77.60)
    fires = generate_seed_fires(ncr_bbox)

    evidence = assemble_evidence(
        cell_id="ncr:2863:7731",
        cell_lat=28.63,
        cell_lon=77.31,
        pm25_pred=310.4,
        idw_baseline=181.2,
        confidence_score=0.78,
        wind_dir_deg=310.0,
        wind_speed_ms=3.0,
        fires=fires,
        no2_col_ratio=2.1,
        citizen_reports_count=3,
        citizen_source_votes={"crop_residue_burning": 3},
    )

    brief = generate_attribution_brief(evidence)
    print(f"  [OK] Evidence assembled — PM2.5: {evidence.pm25_pred}, "
          f"residual: {evidence.residual}, confidence: {evidence.confidence_score}")

    # Test WATCH threshold (threshold: residual > 40, PM > 120)
    from api.gemini.attribution import assemble_evidence as ae2
    evidence_watch = ae2(
        cell_id="ncr:2855:7730",
        cell_lat=28.55, cell_lon=77.30,
        pm25_pred=135.0, idw_baseline=90.0,
        confidence_score=0.5, wind_dir_deg=310.0,
        wind_speed_ms=2.0, fires=fires,
    )
    sev_watch = _determine_severity(135.0, 45.0, 0.5)
    assert sev_watch == AlertSeverity.WATCH, f"Expected WATCH, got {sev_watch}"
    print(f"  [OK] Severity WATCH threshold test passed (residual=45, PM=135)")

    # Test WARNING threshold
    sev_warn = _determine_severity(220.0, 70.0, 0.65)
    assert sev_warn == AlertSeverity.WARNING, f"Expected WARNING, got {sev_warn}"
    print(f"  [OK] Severity WARNING threshold test passed (residual=70, PM=220, conf=0.65)")

    # Test EMERGENCY threshold
    sev_emerg = _determine_severity(310.0, 130.0, 0.78)
    assert sev_emerg == AlertSeverity.EMERGENCY, f"Expected EMERGENCY, got {sev_emerg}"
    print(f"  [OK] Severity EMERGENCY threshold test passed (PM=310, conf=0.78)")

    # Below threshold — no alert
    sev_none = _determine_severity(100.0, 20.0, 0.4)
    assert sev_none is None, f"Expected None, got {sev_none}"
    print(f"  [OK] Below threshold — no alert generated")

    # Full alert generation
    alert = generate_alert("ncr", evidence, brief, population_exposed=84000)
    assert alert is not None, "Expected alert for PM=310, residual=129.2, conf=0.78"
    assert alert.severity == AlertSeverity.EMERGENCY
    assert alert.status == AlertStatus.OPEN
    assert len(alert.dispatched_to) == 3   # EMERGENCY dispatches to all 3 mock recipients
    assert all(r in MOCK_RECIPIENTS for r in alert.dispatched_to), "Non-mock recipients detected! R6 violation!"
    print(f"  [OK] Alert generated: {alert.alert_id}")
    print(f"       Severity : {alert.severity.value}")
    print(f"       Cause    : {alert.cause}")
    print(f"       Recipients: {alert.dispatched_to}")
    print(f"       Status   : {alert.status.value}")

    # Acknowledgement flow
    alert = acknowledge_alert(alert, officer_id="mock_district_officer", note="Dispatching field team to Sonipat")
    assert alert.status == AlertStatus.ACKNOWLEDGED
    assert alert.acknowledged_by == "mock_district_officer"
    print(f"  [OK] Acknowledgement flow: {alert.status.value} by {alert.acknowledged_by}")

    # Resolution flow
    alert = resolve_alert(alert, officer_id="mock_district_officer", resolution_note="Field team confirmed 4 fire sites")
    assert alert.status == AlertStatus.RESOLVED
    print(f"  [OK] Resolution flow: {alert.status.value}")

    print("\nAll alert engine checks passed successfully!")


if __name__ == "__main__":
    demo()
