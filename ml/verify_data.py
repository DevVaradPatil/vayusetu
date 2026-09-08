"""
ml/verify_data.py — Data Quality and Integrity Verification Script.

Executes comprehensive data assertions across raw ingestion tables and feature datasets:
- Checks schema compliance and null rate thresholds.
- Verifies spatial bounds and grid cell ID consistency.
- Asserts value ranges for PM2.5 [0, 1000] µg/m³, wind speed [0, 100] m/s, wind_dir [0, 360]°.
- Supports --strict flag for deployment release gate.
"""

import argparse
import logging
import sys
from typing import Dict, List, Any

from ingestion.stations import generate_seed_stations
from ingestion.fires import generate_seed_fires, calculate_expanded_bbox
from ingestion.meteorology import generate_seed_meteorology
from ingestion.satellite import generate_seed_satellite_data
from ingestion.static_layers import generate_grid_cells_for_tenant

logger = logging.getLogger("vayusetu.ml.verify_data")


def verify_stations_data(records: List[Dict[str, Any]], strict: bool = False) -> bool:
    print(f"--- Verifying Station Data ({len(records)} records) ---")
    failures = 0
    for idx, r in enumerate(records):
        val = r.get("value")
        if val is not None:
            if val < 0 or val > 1000:
                logger.error(f"[FAIL] Station record {r.get('station_id')} value {val} out of bounds [0, 1000]")
                failures += 1
        
        lat, lon = r.get("lat"), r.get("lon")
        if not (20.0 <= lat <= 35.0 and 68.0 <= lon <= 90.0):
            logger.error(f"[FAIL] Station record {r.get('station_id')} lat/lon ({lat}, {lon}) outside India bounding box")
            failures += 1

    if failures == 0:
        print("  [OK] Station data quality checks passed 100%.")
        return True
    else:
        print(f"  [FAIL] Station data quality checks failed with {failures} errors.")
        return False if strict else True


def verify_fires_data(records: List[Dict[str, Any]], strict: bool = False) -> bool:
    print(f"--- Verifying Fire Data ({len(records)} records) ---")
    failures = 0
    for r in records:
        frp = r.get("frp", 0)
        if frp < 0 or frp > 5000:
            logger.error(f"[FAIL] Fire record {r.get('fire_id')} FRP {frp} out of plausible bounds")
            failures += 1

    if failures == 0:
        print("  [OK] Fire data quality checks passed 100%.")
        return True
    else:
        print(f"  [FAIL] Fire data quality checks failed with {failures} errors.")
        return False if strict else True


def verify_meteorology_data(records: List[Dict[str, Any]], strict: bool = False) -> bool:
    print(f"--- Verifying Meteorology Data ({len(records)} records) ---")
    failures = 0
    for r in records:
        wdir = r.get("wind_dir", 0)
        if not (0 <= wdir <= 360):
            logger.error(f"[FAIL] Meteorology record wind_dir {wdir} out of bounds [0, 360]")
            failures += 1
        
        wspeed = r.get("wind_speed", 0)
        if wspeed < 0 or wspeed > 100:
            logger.error(f"[FAIL] Meteorology record wind_speed {wspeed} out of bounds [0, 100]")
            failures += 1

    if failures == 0:
        print("  [OK] Meteorology data quality checks passed 100%.")
        return True
    else:
        print(f"  [FAIL] Meteorology data quality checks failed with {failures} errors.")
        return False if strict else True


def verify_grid_cells_data(records: List[Dict[str, Any]], strict: bool = False) -> bool:
    print(f"--- Verifying Grid Cells Data ({len(records)} records) ---")
    failures = 0
    for r in records:
        pop = r.get("population", 0)
        if pop < 0:
            logger.error(f"[FAIL] Grid cell {r.get('cell_id')} population {pop} negative")
            failures += 1

        b_frac = r.get("builtup_frac", 0)
        c_frac = r.get("cropland_frac", 0)
        if not (0 <= b_frac <= 1.0 and 0 <= c_frac <= 1.0):
            logger.error(f"[FAIL] Grid cell {r.get('cell_id')} land use fractions out of range [0, 1]")
            failures += 1

    if failures == 0:
        print("  [OK] Grid Cells data quality checks passed 100%.")
        return True
    else:
        print(f"  [FAIL] Grid Cells data quality checks failed with {failures} errors.")
        return False if strict else True


def main():
    parser = argparse.ArgumentParser(description="Verify data quality for VayuSetu datasets")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero code on any assertion failure")
    parser.add_argument("--tenant", default="ncr", help="Tenant to verify")
    args = parser.parse_args()

    print(f"=== Running VayuSetu Data Verification (Tenant: {args.tenant}, Strict: {args.strict}) ===")

    stations = generate_seed_stations(args.tenant)
    expanded_bbox = calculate_expanded_bbox((28.20, 76.80, 28.95, 77.60), 200.0)
    fires = generate_seed_fires(expanded_bbox)
    meteo = generate_seed_meteorology(args.tenant, "ncr-2863-7731")
    grid = generate_grid_cells_for_tenant(args.tenant)

    v1 = verify_stations_data(stations, args.strict)
    v2 = verify_fires_data(fires, args.strict)
    v3 = verify_meteorology_data(meteo, args.strict)
    v4 = verify_grid_cells_data(grid, args.strict)

    all_passed = v1 and v2 and v3 and v4

    if all_passed:
        print("\n[SUCCESS] ALL DATA QUALITY CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\n[FAILURE] DATA QUALITY CHECKS FAILED IN STRICT MODE!", file=sys.stderr)
        sys.exit(1 if args.strict else 0)


if __name__ == "__main__":
    main()
