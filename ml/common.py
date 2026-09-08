"""
ml/common.py — Shared Derived Quantities and Domain Logic.

Implements all core mathematical primitives ONCE per docs/DATA_CONTRACTS.md §6:
- compute_idw_baseline(): Inverse Distance Weighting (k=4, power=2, max_radius=50km)
- compute_confidence(): Tri-factor confidence score [0, 1]
- is_hotspot(): Hotspot test rule (residual > 60, pm25 > 150, confidence > 0.6)
- get_cpcb_aqi_band(): National CPCB AQI breakpoints
- is_point_in_upwind_sector(): Upwind sector cone calculation (wind_dir convention)
"""

import math
from typing import Dict, List, Optional, Tuple, Any

# CPCB Breakpoints for PM2.5 (24h mean)
CPCB_AQI_BANDS = [
    (30.0, "Good", "#10b981"),
    (60.0, "Satisfactory", "#84cc16"),
    (90.0, "Moderate", "#eab308"),
    (120.0, "Poor", "#f97316"),
    (250.0, "Very Poor", "#ef4444"),
    (float("inf"), "Severe", "#991b1b")
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates great-circle distance in km between two (lat, lon) coordinates using Haversine formula.
    """
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def compute_idw_baseline(
    cell_lat: float,
    cell_lon: float,
    stations_reporting: List[Dict[str, Any]],
    power: float = 2.0,
    max_radius_km: float = 50.0,
    min_stations: int = 2
) -> Optional[float]:
    """
    Inverse Distance Weighting (IDW) baseline from station readings.
    Returns None if fewer than min_stations are within max_radius_km.
    """
    weighted_sum = 0.0
    sum_of_weights = 0.0
    valid_count = 0

    # Calculate distances
    station_distances = []
    for st in stations_reporting:
        val = st.get("value")
        slat = st.get("lat")
        slon = st.get("lon")

        if val is None or slat is None or slon is None:
            continue

        dist = haversine_distance_km(cell_lat, cell_lon, slat, slon)
        if dist <= max_radius_km:
            station_distances.append((dist, val))

    if len(station_distances) < min_stations:
        return None

    # Take up to 4 nearest stations
    station_distances.sort(key=lambda x: x[0])
    nearest = station_distances[:4]

    for dist, val in nearest:
        if dist < 0.001:  # Co-located station
            return val
        w = 1.0 / (dist ** power)
        weighted_sum += w * val
        sum_of_weights += w
        valid_count += 1

    return round(weighted_sum / sum_of_weights, 1) if sum_of_weights > 0 else None


def compute_confidence(
    pm25_pred: float,
    pm25_p10: Optional[float] = None,
    pm25_p90: Optional[float] = None,
    satellite_age_h: float = 0.0,
    citizen_reports_count: int = 0
) -> float:
    """
    Confidence score calculation per docs/DATA_CONTRACTS.md §6:
    confidence = 0.5 * model_agreement + 0.3 * data_freshness + 0.2 * citizen_support_factor
    """
    # 1. Model agreement from quantile spread
    if pm25_p10 is not None and pm25_p90 is not None and pm25_pred > 0:
        spread = pm25_p90 - pm25_p10
        model_agreement = max(0.0, min(1.0, 1.0 - (spread / (2.0 * pm25_pred))))
    else:
        model_agreement = 0.75  # Default baseline agreement when quantiles omitted

    # 2. Satellite data freshness (decays from 1.0 at 0h to 0.0 at 48h)
    data_freshness = max(0.0, min(1.0, 1.0 - (satellite_age_h / 48.0)))

    # 3. Citizen support factor (0.2 per report up to 1.0 max)
    citizen_support_factor = min(1.0, citizen_reports_count * 0.2)

    confidence = 0.5 * model_agreement + 0.3 * data_freshness + 0.2 * citizen_support_factor
    return round(max(0.0, min(1.0, confidence)), 2)


def is_hotspot(pm25_pred: float, idw_baseline: float, confidence: float) -> bool:
    """
    Hotspot test per docs/DATA_CONTRACTS.md §6:
    residual > 60 µg/m³ AND pm25_pred > 150 µg/m³ AND confidence > 0.6
    """
    residual = pm25_pred - idw_baseline
    return residual > 60.0 and pm25_pred > 150.0 and confidence > 0.6


def get_cpcb_aqi_band(pm25_value: float) -> Tuple[str, str]:
    """
    Returns (band_name, color_hex) for a PM2.5 value based on CPCB National AQI breakpoints.
    """
    for upper_bound, band, color in CPCB_AQI_BANDS:
        if pm25_value <= upper_bound:
            return band, color
    return "Severe", "#991b1b"


def calculate_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates initial compass bearing (0° to 360°) from point 1 to point 2.
    """
    dlon = math.radians(lon2 - lon1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return round(bearing, 1)


def is_point_in_upwind_sector(
    cell_lat: float,
    cell_lon: float,
    target_lat: float,
    target_lon: float,
    wind_dir_deg: float,
    cone_angle_deg: float = 30.0,
    max_radius_km: float = 100.0
) -> Tuple[bool, float, float]:
    """
    Checks if target_lat/lon lies within upwind sector cone of cell_lat/lon.
    Note: wind_dir is direction wind comes FROM. Upwind bearing is wind_dir itself.
    
    Returns (is_inside, distance_km, bearing_deg).
    """
    dist_km = haversine_distance_km(cell_lat, cell_lon, target_lat, target_lon)
    if dist_km > max_radius_km or dist_km < 0.1:
        return False, dist_km, 0.0

    bearing = calculate_bearing_deg(cell_lat, cell_lon, target_lat, target_lon)
    
    # Angular difference between target bearing and upwind direction (wind_dir)
    diff = abs((bearing - wind_dir_deg + 180) % 360 - 180)
    is_inside = diff <= cone_angle_deg

    return is_inside, round(dist_km, 1), bearing


def demo():
    print("=== ML Shared Utilities Demo (ml/common.py) ===")

    # Test IDW baseline
    sample_stations = [
        {"station_id": "openaq:1001", "lat": 28.6469, "lon": 77.3160, "value": 245.0},
        {"station_id": "openaq:1002", "lat": 28.5632, "lon": 77.1869, "value": 190.0},
        {"station_id": "openaq:1003", "lat": 28.6721, "lon": 77.1310, "value": 210.0},
    ]

    idw_val = compute_idw_baseline(28.6315, 77.3102, sample_stations)
    assert idw_val is not None, "IDW baseline returned None for valid stations"
    print(f"  [OK] IDW Baseline for cell (28.6315, 77.3102): {idw_val} µg/m³")

    # Test Confidence calculation
    conf = compute_confidence(pm25_pred=310.0, pm25_p10=280.0, pm25_p90=340.0, satellite_age_h=6.0, citizen_reports_count=2)
    assert 0.0 <= conf <= 1.0, f"Confidence {conf} out of bounds"
    print(f"  [OK] Confidence Score: {conf}")

    # Test Hotspot Test Rule
    hotspot_flag = is_hotspot(pm25_pred=310.4, idw_baseline=181.2, confidence=0.78)
    assert hotspot_flag is True, "Expected hotspot_flag True for high residual"
    print(f"  [OK] Hotspot Test Rule: {hotspot_flag} (Residual: 129.2 µg/m³)")

    # Test CPCB AQI Band
    band, color = get_cpcb_aqi_band(310.4)
    assert band == "Severe", f"Expected Severe, got {band}"
    print(f"  [OK] CPCB AQI Band for 310.4 µg/m³: {band} ({color})")

    # Test Upwind Sector Cone (Fire at 29.0°N, 77.0°E, wind FROM 310°)
    in_sector, dist, bearing = is_point_in_upwind_sector(28.6315, 77.3102, 29.05, 76.95, wind_dir_deg=310.0)
    assert in_sector is True, f"Fire should be in 310° upwind cone (dist: {dist}km, bearing: {bearing}°)"
    print(f"  [OK] Upwind Sector Cone Check: Fire in cone = {in_sector} ({dist} km away, bearing {bearing}°)")

    print("\nAll ml/common.py self-checks passed successfully!")


if __name__ == "__main__":
    demo()
