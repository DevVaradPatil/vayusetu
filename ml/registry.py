"""
ml/registry.py — Federated Model Registry for VayuSetu.

W3.10 + W3.11: Publish and import model cards conforming to spec/model-card.schema.json.
               Implements the federation protocol described in plan.md §8.

Federation workflow:
  1. Source city (NCR) trains Model A → calls publish_model_card()
  2. Destination city (LKO) calls import_model_card() → downloads artifact + re-evaluates
  3. Honest accuracy drop is measured and logged per Rule R2

Rule R2: Always report honest LOSO metrics. Never quote in-sample numbers.
         Log and display the accuracy drop honestly — do not suppress it.
"""

import hashlib
import json
import logging
import os
import pickle
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vayusetu.ml.registry")

# Local registry store (substitutes GCS bucket in local dev / demo mode)
_LOCAL_REGISTRY_DIR = Path(__file__).parent / "artifacts" / "registry"


# ---------------------------------------------------------------------------
# Model Card validation — against spec/model-card.schema.json ITSELF
# ---------------------------------------------------------------------------
#
# An earlier revision kept a hand-maintained Python copy of the schema's required
# fields and enum values, commented "mirroring spec/model-card.schema.json". A
# mirror drifts. Since spec/ is published as the Digital Public Good and outside
# adopters validate against that file, a spec the implementation does not actually
# read is decoration — and the first divergence is silent in both directions.
#
# So: the schema file is the single source of truth. Structural rules come from
# jsonschema; only the rules a JSON Schema cannot express (R2: a published model
# must beat its baseline) are enforced here in code.

SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"
MODEL_CARD_SCHEMA_PATH = SPEC_DIR / "model-card.schema.json"


@lru_cache(maxsize=1)
def load_model_card_schema() -> Dict[str, Any]:
    """Load the published schema. Cached — it does not change at runtime."""
    if not MODEL_CARD_SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"Published schema missing: {MODEL_CARD_SCHEMA_PATH}. "
            "spec/ is the contract; the registry cannot validate without it."
        )
    return json.loads(MODEL_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_model_card(card: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate a model card against the published schema, plus the semantic rules
    the schema cannot express.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []
    schema = load_model_card_schema()

    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)
        for e in sorted(validator.iter_errors(card), key=lambda e: list(e.path)):
            location = ".".join(str(p) for p in e.path) or "(root)"
            errors.append(f"{location}: {e.message}")
    except ImportError:
        # Degraded, but still driven by the schema file rather than a copy of it.
        logger.warning("jsonschema not installed — structural validation is partial.")
        for field in schema.get("required", []):
            if field not in card:
                errors.append(f"(root): '{field}' is a required property")

    # --- Semantic rules JSON Schema cannot express ---------------------------

    # R2: a model that does not beat its own IDW baseline has no reason to exist,
    # and publishing it to a shared registry actively misleads other cities.
    perf = card.get("performance") or {}
    loso_mae = perf.get("loso_mae")
    idw_mae = perf.get("baseline_idw_mae")
    if isinstance(loso_mae, (int, float)) and isinstance(idw_mae, (int, float)):
        if loso_mae >= idw_mae:
            errors.append(
                f"R2 violation: loso_mae ({loso_mae}) must be < baseline_idw_mae ({idw_mae}). "
                f"A model that doesn't beat IDW should not be published."
            )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Publish (source city → registry)
# ---------------------------------------------------------------------------

def publish_model_card(card: Dict[str, Any], model_artifact_path: Optional[Path] = None) -> str:
    """
    Publishes a model card to the local registry (GCS bucket in production).
    Validates against spec/model-card.schema.json.

    Returns the registry path where the card is stored.
    R2: Validation blocks publication if model doesn't beat IDW baseline.
    """
    is_valid, errors = validate_model_card(card)
    if not is_valid:
        raise ValueError(f"Model card validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    model_id = card["model_id"]
    tenant = card["tenant"]
    task = card["task"]

    # Create local registry directory structure
    registry_dir = _LOCAL_REGISTRY_DIR / tenant / task
    registry_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize model_id for filename
    safe_id = model_id.replace("/", "_").replace(" ", "_")
    card_path = registry_dir / f"{safe_id}.json"

    # Add publication timestamp
    card["published_at"] = datetime.now(timezone.utc).isoformat()
    card["registry_schema"] = "vayusetu/model-card/1.0.0"

    with open(card_path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2)

    logger.info(
        f"Published model card: model_id={model_id}, tenant={tenant}, "
        f"LOSO MAE={card['performance']['loso_mae']}, "
        f"IDW baseline={card['performance']['baseline_idw_mae']}, "
        f"path={card_path}"
    )
    return str(card_path)


# ---------------------------------------------------------------------------
# Import (destination city ← registry)
# ---------------------------------------------------------------------------

def import_model_card(
    model_id: str,
    source_tenant: str,
    task: str,
    target_tenant: str,
) -> Dict[str, Any]:
    """
    Imports a published model card for a target city.
    Loads the card, verifies it, and returns the card + transfer metadata.

    W3.11: Honest transfer metrics are computed and logged (Rule R2).
    The accuracy drop from source to target city MUST be displayed honestly.
    """
    safe_id = model_id.replace("/", "_").replace(" ", "_")
    card_path = _LOCAL_REGISTRY_DIR / source_tenant / task / f"{safe_id}.json"

    if not card_path.exists():
        raise FileNotFoundError(
            f"Model card '{model_id}' not found in registry at {card_path}. "
            f"Check that '{source_tenant}/{task}/{safe_id}.json' has been published."
        )

    with open(card_path, "r", encoding="utf-8") as f:
        card = json.load(f)

    is_valid, errors = validate_model_card(card)
    if not is_valid:
        raise ValueError(f"Imported model card failed validation: {errors}")

    source_loso_mae = card["performance"]["loso_mae"]

    # The transfer penalty is NOT measured here and must never be presented as if
    # it were. Measuring it requires running LOSO on the target tenant's own
    # station data, which needs Lucknow ingestion (BACKLOG W3.11 / TODO.md).
    #
    # An earlier revision multiplied the source MAE by a hardcoded 1.18 and
    # reported the result as an honest transfer metric. That is a fabricated
    # measurement: the number carried no information about Lucknow at all. The
    # federation story's entire credibility rests on showing a REAL degradation
    # (see .claude/agents/federation.md), so this now returns None until one is
    # measured, and callers must render it as "not yet measured".
    transfer_result = {
        "model_card": card,
        "import_metadata": {
            "source_tenant": source_tenant,
            "target_tenant": target_tenant,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source_loso_mae": source_loso_mae,
            "target_loso_mae": None,
            "accuracy_drop_pct": None,
            "transfer_measured": False,
            "accuracy_drop_note": (
                f"Model imported from '{source_tenant}' into '{target_tenant}'. "
                f"Transfer accuracy has NOT been measured: that requires LOSO evaluation "
                f"on {target_tenant}'s own stations. Do not quote a degradation figure "
                f"until ml.evaluate has been run against {target_tenant} data."
                if target_tenant != source_tenant
                else "Same-tenant import — no transfer evaluation required."
            ),
        },
    }

    logger.info(
        "registry.import source=%s target=%s source_loso_mae=%s transfer_measured=False",
        source_tenant, target_tenant, source_loso_mae,
    )

    return transfer_result


def list_registry(tenant: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists all model cards in the local registry, optionally filtered by tenant."""
    if not _LOCAL_REGISTRY_DIR.exists():
        return []

    cards = []
    search_root = _LOCAL_REGISTRY_DIR / tenant if tenant else _LOCAL_REGISTRY_DIR

    for json_file in sorted(search_root.rglob("*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                card = json.load(f)
            cards.append({
                "model_id": card.get("model_id"),
                "tenant": card.get("tenant"),
                "task": card.get("task"),
                "published_at": card.get("published_at"),
                "loso_mae": card.get("performance", {}).get("loso_mae"),
                "registry_path": str(json_file),
            })
        except Exception as e:
            logger.warning(f"Could not read model card at {json_file}: {e}")

    return cards


# ---------------------------------------------------------------------------
# Demo / Self-Test
# ---------------------------------------------------------------------------

def demo():
    print("=== Federated Model Registry Demo (W3.10 + W3.11) ===")

    # Build the NCR card from the ACTUAL evaluation artifact. A model card whose
    # numbers were typed by hand rather than read from an evaluation run is a
    # fabricated provenance record, and the registry's whole value is provenance
    # (spec/README.md §2). Never hardcode performance figures here.
    metrics_path = Path(__file__).parent / "artifacts" / "evaluation_metrics.json"
    if not metrics_path.exists():
        raise SystemExit("Run `python -m ml.evaluate` first — no evaluation artifact to publish.")

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    from ml import synthetic

    ncr_card = {
        "model_id": "ncr/grid-pm25/v1",
        "tenant": "ncr",
        "task": "gridded_pm25_estimation",
        "trained_on": {
            # Mirrors what ml/synthetic.py actually generated, not an aspiration.
            "from": "2024-10-20",
            "to": "2024-10-30",
            "n_rows": metrics["n_rows"],
        },
        "features": list(synthetic.FEATURE_COLUMNS),
        "performance": {
            "loso_mae": metrics["model_a_loso"]["mae"],
            "loso_r2": metrics["model_a_loso"]["r2"],
            "baseline_idw_mae": metrics["baselines"]["idw_k4_p2_max50km"]["mae"],
        },
        "climate_zone": "indo_gangetic_plain_winter",
        "artifact_uri": "gs://vayusetu-registry/ncr/grid-pm25/v1/model.pkl",
        "license": "Apache-2.0",
        "schema_version": "1.0.0",
        "data_source": metrics["data_source"],
        "limitations": [
            "Trained on synthetic placeholder data; not validated on real observations.",
            "Synthetic targets are a smooth function of the features, so LOSO R2 here "
            "is optimistic relative to what real station data will produce.",
            "Covers a 10-day autumn window only; unvalidated for monsoon or summer.",
        ],
    }

    # Test validation
    is_valid, errors = validate_model_card(ncr_card)
    assert is_valid, f"NCR model card validation failed: {errors}"
    print(f"  [OK] NCR model card validates: LOSO MAE={ncr_card['performance']['loso_mae']} µg/m³, "
          f"vs IDW baseline {ncr_card['performance']['baseline_idw_mae']} µg/m³")

    # Test R2 violation detection: model worse than IDW baseline
    bad_card = ncr_card.copy()
    bad_card["performance"] = {"loso_mae": 35.0, "loso_r2": 0.42, "baseline_idw_mae": 28.52}
    is_valid_bad, errors_bad = validate_model_card(bad_card)
    assert not is_valid_bad, "Expected validation to fail for model worse than IDW baseline"
    assert any("R2 violation" in e for e in errors_bad)
    print(f"  [OK] R2 violation correctly detected: '{errors_bad[0][:60]}...'")

    # Publish NCR model card
    registry_path = publish_model_card(ncr_card)
    assert Path(registry_path).exists(), f"Card file not created at {registry_path}"
    print(f"  [OK] NCR model card published: {Path(registry_path).name}")

    # List registry
    all_cards = list_registry()
    assert len(all_cards) >= 1, "Registry should have at least 1 card after publish"
    print(f"  [OK] Registry listing: {len(all_cards)} model card(s) found")

    # Import to Lucknow — with honest transfer metrics
    transfer = import_model_card(
        model_id="ncr/grid-pm25/v1",
        source_tenant="ncr",
        task="gridded_pm25_estimation",
        target_tenant="lko",
    )

    meta = transfer["import_metadata"]
    assert meta["source_tenant"] == "ncr"
    assert meta["target_tenant"] == "lko"
    # A cross-tenant import must NOT invent a degradation figure. Guarding this in
    # the self-check because it is exactly the number a demo is tempted to fake.
    assert meta["transfer_measured"] is False, "transfer cannot be 'measured' without target data"
    assert meta["accuracy_drop_pct"] is None, "degradation must be None until measured on target stations"
    assert meta["target_loso_mae"] is None

    print(f"\n  --- Lucknow federation transfer ---")
    print(f"  Source (NCR) LOSO MAE  : {meta['source_loso_mae']} µg/m³  [synthetic]")
    print(f"  Target (LKO) LOSO MAE  : not yet measured")
    print(f"  Accuracy drop          : not yet measured — needs LKO ingestion (W3.11)")

    # Verify card can be re-imported and passes schema validation again
    reimported_card = transfer["model_card"]
    is_valid_reimport, errs = validate_model_card(reimported_card)
    assert is_valid_reimport, f"Re-imported card failed validation: {errs}"
    print(f"\n  [OK] Re-imported card validates: model_id={reimported_card['model_id']}")

    print("\nAll federated model registry checks passed successfully!")


if __name__ == "__main__":
    demo()
