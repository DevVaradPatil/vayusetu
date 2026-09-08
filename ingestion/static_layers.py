"""
ingestion/static_layers.py — Static Grid Lattice and Spatial Feature Generator.

Generates the 0.01° × 0.01° (~1 km) fixed global lattice grid cells for each tenant,
calculating spatial bounding polygons (WKT GEOGRAPHY), population estimates, land use fractions,
elevation, road distance proxies, and marking cells that house official stations.

Fulfills Task W1.5 per docs/DATA_CONTRACTS.md §1 & §2.
"""

import json
import logging
import math
import yaml
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from ingestion.common import get_cell_id, get_cell_center

logger = logging.getLogger("vayusetu.ingestion.static_layers")


def load_tenant_config() -> dict:
    config_path = Path(__file__).parent.parent / "infra" / "tenants.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_grid_cells_for_tenant(
    tenant: str,
    station_cell_ids: Optional[set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Generates 0.01° grid cells covering tenant bounding box.
    """
    config = load_tenant_config()
    tenants = config.get("tenants", {})

    if tenant not in tenants:
        raise ValueError(f"Tenant '{tenant}' not found in tenants.yaml")

    bounds = tenants[tenant]["bounds"]
    lat_min, lon_min = bounds["lat_min"], bounds["lon_min"]
    lat_max, lon_max = bounds["lat_max"], bounds["lon_max"]

    lat_min_idx = math.floor(lat_min / 0.01)
    lat_max_idx = math.floor(lat_max / 0.01)
    lon_min_idx = math.floor(lon_min / 0.01)
    lon_max_idx = math.floor(lon_max / 0.01)

    station_set = station_cell_ids or set()

    cells = []
    logger.info(f"Building grid for tenant '{tenant}' across lat_idx [{lat_min_idx}..{lat_max_idx-1}], lon_idx [{lon_min_idx}..{lon_max_idx-1}]")

    for lat_idx in range(lat_min_idx, lat_max_idx):
        for lon_idx in range(lon_min_idx, lon_max_idx):
            cell_id = f"{tenant}-{lat_idx}-{lon_idx}"
            
            # Box corners
            lat0 = round(lat_idx * 0.01, 4)
            lat1 = round((lat_idx + 1) * 0.01, 4)
            lon0 = round(lon_idx * 0.01, 4)
            lon1 = round((lon_idx + 1) * 0.01, 4)

            # Center
            lat_center = round((lat_idx + 0.5) * 0.01, 4)
            lon_center = round((lon_idx + 0.5) * 0.01, 4)

            # WKT Polygon for BigQuery GEOGRAPHY
            wkt_polygon = f"POLYGON(({lon0} {lat0}, {lon1} {lat0}, {lon1} {lat1}, {lon0} {lat1}, {lon0} {lat0}))"

            # Synthetic baseline estimates for urban vs rural
            # Central Delhi / Urban centers have high builtup_frac and population
            dist_from_center = math.sqrt((lat_center - 28.6139)**2 + (lon_center - 77.2090)**2) if tenant == "ncr" else math.sqrt((lat_center - 26.8467)**2 + (lon_center - 80.9462)**2)
            
            is_urban = dist_from_center < 0.2
            population = int(max(500, (1.0 - min(1.0, dist_from_center / 0.5)) * 45000 + 1200))
            builtup_frac = round(max(0.05, min(0.95, 1.0 - dist_from_center * 2.0)), 2)
            cropland_frac = round(max(0.02, min(0.85, 1.0 - builtup_frac - 0.10)), 2)
            elevation_m = round(210.0 + (lat_center - 28.0) * 15.0, 1)
            dist_road_m = round(max(100.0, dist_from_center * 15000.0), 1)

            cell_record = {
                "cell_id": cell_id,
                "tenant": tenant,
                "lat": lat_center,
                "lon": lon_center,
                "geom": wkt_polygon,
                "district": "Delhi Urban" if is_urban else "NCR Outskirts",
                "population": population,
                "builtup_frac": builtup_frac,
                "cropland_frac": cropland_frac,
                "elevation_m": elevation_m,
                "dist_major_road_m": dist_road_m,
                "has_station": cell_id in station_set
            }
            cells.append(cell_record)

    logger.info(f"Generated {len(cells)} grid cells for tenant '{tenant}'")
    return cells


def demo():
    print("=== Ingestion Demo: Static Grid Layer Generation ===")
    
    # Sample station cell IDs in NCR
    sample_station_cells = {"ncr-2864-7731", "ncr-2856-7718", "ncr-2867-7713"}

    # Generate NCR grid
    ncr_cells = generate_grid_cells_for_tenant("ncr", sample_station_cells)
    print(f"  [OK] NCR Grid Cells Generated: {len(ncr_cells)} (Expected ~6,000)")
    assert 5000 <= len(ncr_cells) <= 7000, f"Unexpected NCR cell count: {len(ncr_cells)}"

    # Generate Lucknow grid
    lko_cells = generate_grid_cells_for_tenant("lko")
    print(f"  [OK] Lucknow Grid Cells Generated: {len(lko_cells)} (Expected ~870)")
    assert 800 <= len(lko_cells) <= 1000, f"Unexpected Lucknow cell count: {len(lko_cells)}"

    # Validate Schema against docs/DATA_CONTRACTS.md §2 grid_cells
    required_keys = {
        "cell_id", "tenant", "lat", "lon", "geom", "district", "population",
        "builtup_frac", "cropland_frac", "elevation_m", "dist_major_road_m", "has_station"
    }

    sample_cell = ncr_cells[0]
    missing = required_keys - sample_cell.keys()
    assert not missing, f"Missing keys in grid_cells record: {missing}"
    assert sample_cell["geom"].startswith("POLYGON(("), "Geometry must be WKT Polygon"

    # Verify station cell marking
    station_matches = [c for c in ncr_cells if c["has_station"]]
    assert len(station_matches) == len(sample_station_cells), "has_station flag mismatch"
    print(f"  [OK] Station cell marking verified ({len(station_matches)} station cells tagged).")

    print(f"  [OK] Sample Grid Cell Record:\n{json.dumps(sample_cell, indent=4)}")
    print("\nAll Static Grid Layer checks passed successfully!")


if __name__ == "__main__":
    demo()
