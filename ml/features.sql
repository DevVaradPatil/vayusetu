-- ml/features.sql — Model A training table.
--
-- Joins station observations (the label) against meteorology, active fires, and —
-- when available — satellite and static grid layers.
--
-- DEGRADES DELIBERATELY. Earth Engine registration is still pending (TODO.md), so
-- `raw_satellite` and `grid_cells` are empty. Every optional source is LEFT JOINed
-- and every derived column is NULL-safe, so this query produces real training rows
-- today from stations + meteorology + fires, and picks up the satellite and static
-- features automatically once they land. An earlier revision INNER JOINed
-- grid_cells, which silently returns zero rows when that table is empty.
--
-- Station lat/lon come from raw_stations rather than grid_cells for the same
-- reason: the label rows always carry coordinates, so the query never depends on a
-- table that may not be populated yet.
--
-- Assertions at the bottom, not in a wrapper script: they belong next to the joins
-- they check (docs/CONVENTIONS.md). A join that silently drops most rows looks
-- exactly like a join that works.

CREATE OR REPLACE TABLE `{project_id}.{dataset}.features_training` AS
WITH station_obs AS (
    -- The label. One row per station-hour.
    SELECT
        station_id,
        cell_id,
        ANY_VALUE(lat) AS lat,
        ANY_VALUE(lon) AS lon,
        ts,
        DATE(ts) AS date,
        EXTRACT(HOUR FROM ts) AS hour_of_day,
        EXTRACT(DAYOFWEEK FROM ts) AS day_of_week,
        EXTRACT(DAYOFYEAR FROM ts) AS day_of_year,
        AVG(value) AS target_pm25
    FROM `{project_id}.{dataset}.raw_stations`
    WHERE pollutant = 'pm25'
      AND value IS NOT NULL
      AND value BETWEEN 0 AND 1000
    GROUP BY station_id, cell_id, ts
),
grid_static AS (
    -- Empty until Earth Engine static layers land. LEFT JOINed below.
    SELECT
        cell_id, population, builtup_frac, cropland_frac,
        elevation_m, dist_major_road_m
    FROM `{project_id}.vayusetu_shared.grid_cells`
),
sat_features AS (
    -- Empty until the MAIAC/S5P backfill runs. Daily cadence, joined on DATE.
    SELECT cell_id, date, aod_maiac, s5p_no2, s5p_aer_ai, cloud_fraction
    FROM `{project_id}.{dataset}.raw_satellite`
),
met_features AS (
    -- Historical reanalysis only. is_forecast = TRUE rows are the live/serving
    -- path; training on them would leak forecast skill into the estimator.
    SELECT cell_id, ts, wind_u, wind_v, wind_speed, wind_dir, blh, temp_c, rh, precip_mm
    FROM `{project_id}.{dataset}.raw_meteorology`
    WHERE is_forecast = FALSE
),
obs_met AS (
    SELECT
        s.*,
        met.wind_u, met.wind_v, met.wind_speed, met.wind_dir,
        met.blh, met.temp_c, met.rh, met.precip_mm
    FROM station_obs s
    LEFT JOIN met_features met
      ON s.cell_id = met.cell_id AND s.ts = met.ts
),
obs_fire_pairs AS (
    -- Every (station-hour, fire) pair within 100 km and the preceding 48 h.
    -- ST_DWITHIN bounds the join so this stays small even in stubble season, when
    -- the fire table runs to thousands of rows a day.
    --
    -- wind_dir is the direction the wind comes FROM (docs/DATA_CONTRACTS.md §2), so
    -- a fire is upwind when the bearing from station TO fire is within +/-30 deg of
    -- wind_dir. The angular difference is wrapped through 360 explicitly — a naive
    -- comparison breaks across north and would silently mis-sector every fire near
    -- a 0/360 wind.
    SELECT
        o.station_id,
        o.ts,
        ST_DISTANCE(ST_GEOGPOINT(o.lon, o.lat), ST_GEOGPOINT(fr.lon, fr.lat)) / 1000.0 AS dist_km,
        fr.frp,
        -- Angular difference between the station->fire bearing and wind_dir,
        -- wrapped into [-180, 180]. BigQuery's MOD is integer-only, so the wrap is
        -- done with FLOOR arithmetic rather than a modulo operator.
        ABS(
            (ST_AZIMUTH(ST_GEOGPOINT(o.lon, o.lat), ST_GEOGPOINT(fr.lon, fr.lat)) * 180.0 / ACOS(-1) - o.wind_dir + 180.0)
            - 360.0 * FLOOR(
                (ST_AZIMUTH(ST_GEOGPOINT(o.lon, o.lat), ST_GEOGPOINT(fr.lon, fr.lat)) * 180.0 / ACOS(-1) - o.wind_dir + 180.0) / 360.0
              )
            - 180.0
        ) <= 30.0 AS is_upwind
    FROM obs_met o
    JOIN `{project_id}.vayusetu_shared.raw_fires` fr
      ON fr.acq_ts > TIMESTAMP_SUB(o.ts, INTERVAL 48 HOUR)
     AND fr.acq_ts <= o.ts
     AND ST_DWITHIN(ST_GEOGPOINT(o.lon, o.lat), ST_GEOGPOINT(fr.lon, fr.lat), 100000)
    WHERE o.wind_dir IS NOT NULL
),
fire_features AS (
    SELECT
        station_id,
        ts,
        COUNTIF(dist_km <= 25)  AS fire_count_25km_48h,
        COUNTIF(dist_km <= 50)  AS fire_count_50km_48h,
        COUNTIF(dist_km <= 100) AS fire_count_100km_48h,
        COUNTIF(is_upwind)      AS fire_count_upwind_100km_48h,
        COALESCE(SUM(IF(is_upwind, frp, 0)), 0) AS fire_frp_upwind_100km_48h
    FROM obs_fire_pairs
    GROUP BY station_id, ts
)
SELECT
    o.station_id,
    o.cell_id,
    o.ts,
    o.target_pm25,
    o.lat,
    o.lon,
    -- Static layers: NULL until Earth Engine lands.
    g.population,
    g.builtup_frac,
    g.cropland_frac,
    g.elevation_m,
    g.dist_major_road_m,
    -- Satellite: NULL until Earth Engine lands.
    sat.aod_maiac,
    sat.s5p_no2,
    sat.s5p_aer_ai,
    sat.cloud_fraction,
    -- Meteorology: available now.
    o.wind_u,
    o.wind_v,
    o.wind_speed,
    o.wind_dir,
    o.blh,
    o.temp_c,
    o.rh,
    o.precip_mm,
    -- Fires: available now. Absence of a matching row means no fires were
    -- detected nearby, which is genuinely zero — unlike a missing satellite
    -- reading, which means "not observed" and stays NULL.
    COALESCE(f.fire_count_25km_48h, 0)          AS fire_count_25km_48h,
    COALESCE(f.fire_count_50km_48h, 0)          AS fire_count_50km_48h,
    COALESCE(f.fire_count_100km_48h, 0)         AS fire_count_100km_48h,
    COALESCE(f.fire_count_upwind_100km_48h, 0)  AS fire_count_upwind_100km_48h,
    COALESCE(f.fire_frp_upwind_100km_48h, 0.0)  AS fire_frp_upwind_100km_48h,
    -- Temporal.
    o.hour_of_day,
    o.day_of_week,
    SIN(2 * ACOS(-1) * o.day_of_year / 365.0) AS day_of_year_sin,
    COS(2 * ACOS(-1) * o.day_of_year / 365.0) AS day_of_year_cos,
    IF(o.day_of_year BETWEEN 288 AND 335, 1, 0) AS is_stubble_season
FROM obs_met o
LEFT JOIN grid_static g    ON o.cell_id = g.cell_id
LEFT JOIN sat_features sat ON o.cell_id = sat.cell_id AND o.date = sat.date
LEFT JOIN fire_features f  ON o.station_id = f.station_id AND o.ts = f.ts;


-- ---------------------------------------------------------------------------
-- Assertions. Run these after the table builds; a failure here means the joins
-- corrupted the data, which on a map looks exactly like a working pipeline.
-- ---------------------------------------------------------------------------
SELECT
    COUNT(*)                                                       AS n_rows,
    COUNT(DISTINCT station_id)                                     AS n_stations,
    ROUND(100 * COUNTIF(target_pm25 IS NULL) / COUNT(*), 2)        AS pct_null_label,
    ROUND(100 * COUNTIF(wind_dir IS NULL)    / COUNT(*), 2)        AS pct_null_wind,
    ROUND(100 * COUNTIF(blh IS NULL)         / COUNT(*), 2)        AS pct_null_blh,
    ROUND(100 * COUNTIF(aod_maiac IS NULL)   / COUNT(*), 2)        AS pct_null_aod,
    ROUND(100 * COUNTIF(population IS NULL)  / COUNT(*), 2)        AS pct_null_static,
    ROUND(MIN(target_pm25), 1)                                     AS pm25_min,
    ROUND(MAX(target_pm25), 1)                                     AS pm25_max,
    ROUND(AVG(target_pm25), 1)                                     AS pm25_mean,
    SUM(fire_count_upwind_100km_48h)                               AS total_upwind_fires
FROM `{project_id}.{dataset}.features_training`;

-- Expected while Earth Engine is pending:
--   pct_null_label   = 0     (the label must never be null)
--   pct_null_wind    < 5     (meteorology backfill should cover every station cell)
--   pct_null_aod     = 100   (satellite not yet ingested)
--   pct_null_static  = 100   (grid_cells not yet populated)
--   pm25_min >= 0, pm25_max <= 1000
-- A jump in pct_null_wind, or pm25 outside those bounds, means a join or a unit
-- broke. Investigate before training: do not train through it.
