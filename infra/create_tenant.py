#!/usr/bin/env python3
"""
infra/create_tenant.py — Tenant dataset & table setup script for VayuSetu.

Creates BigQuery datasets and tables matching frozen schemas in docs/DATA_CONTRACTS.md.
Supports --dry-run mode for local validation.
"""

import argparse
import os
import sys
import yaml
from pathlib import Path

# Table creation DDL schemas strictly adhering to docs/DATA_CONTRACTS.md

TABLE_SCHEMAS = {
    "raw_stations": """
        CREATE TABLE IF NOT EXISTS `{dataset}.raw_stations` (
            station_id STRING NOT NULL,
            station_name STRING,
            city STRING,
            state STRING,
            lat FLOAT64 NOT NULL,
            lon FLOAT64 NOT NULL,
            cell_id STRING NOT NULL,
            ts TIMESTAMP NOT NULL,
            pollutant STRING NOT NULL,
            value FLOAT64,
            unit STRING NOT NULL,
            source STRING NOT NULL,
            ingested_at TIMESTAMP NOT NULL
        )
        PARTITION BY DATE(ts)
        CLUSTER BY station_id;
    """,
    "raw_fires": """
        CREATE TABLE IF NOT EXISTS `{dataset}.raw_fires` (
            fire_id STRING NOT NULL,
            lat FLOAT64 NOT NULL,
            lon FLOAT64 NOT NULL,
            acq_ts TIMESTAMP NOT NULL,
            confidence STRING,
            frp FLOAT64,
            satellite STRING,
            ingested_at TIMESTAMP NOT NULL
        )
        PARTITION BY DATE(acq_ts);
    """,
    "raw_satellite": """
        CREATE TABLE IF NOT EXISTS `{dataset}.raw_satellite` (
            cell_id STRING NOT NULL,
            date DATE NOT NULL,
            aod_maiac FLOAT64,
            s5p_no2 FLOAT64,
            s5p_aer_ai FLOAT64,
            cloud_fraction FLOAT64,
            ingested_at TIMESTAMP NOT NULL
        )
        PARTITION BY date
        CLUSTER BY cell_id;
    """,
    "raw_meteorology": """
        CREATE TABLE IF NOT EXISTS `{dataset}.raw_meteorology` (
            cell_id STRING NOT NULL,
            ts TIMESTAMP NOT NULL,
            is_forecast BOOL NOT NULL,
            issued_at TIMESTAMP,
            wind_u FLOAT64,
            wind_v FLOAT64,
            wind_speed FLOAT64,
            wind_dir FLOAT64,
            blh FLOAT64,
            temp_c FLOAT64,
            rh FLOAT64,
            precip_mm FLOAT64,
            ingested_at TIMESTAMP NOT NULL
        )
        PARTITION BY DATE(ts)
        CLUSTER BY cell_id;
    """,
    "grid_cells": """
        CREATE TABLE IF NOT EXISTS `{dataset}.grid_cells` (
            cell_id STRING NOT NULL,
            tenant STRING NOT NULL,
            lat FLOAT64 NOT NULL,
            lon FLOAT64 NOT NULL,
            geom GEOGRAPHY NOT NULL,
            district STRING,
            population INT64,
            builtup_frac FLOAT64,
            cropland_frac FLOAT64,
            elevation_m FLOAT64,
            dist_major_road_m FLOAT64,
            has_station BOOL NOT NULL
        );
    """,
    "predictions_grid": """
        CREATE TABLE IF NOT EXISTS `{dataset}.predictions_grid` (
            cell_id STRING NOT NULL,
            tenant STRING NOT NULL,
            ts TIMESTAMP NOT NULL,
            model_version STRING NOT NULL,
            pm25_pred FLOAT64 NOT NULL,
            pm25_p10 FLOAT64,
            pm25_p90 FLOAT64,
            idw_baseline FLOAT64 NOT NULL,
            residual FLOAT64 NOT NULL,
            confidence FLOAT64 NOT NULL,
            is_hotspot BOOL NOT NULL,
            citizen_support INT64 NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        PARTITION BY DATE(ts)
        CLUSTER BY cell_id;
    """,
    "predictions_forecast": """
        CREATE TABLE IF NOT EXISTS `{dataset}.predictions_forecast` (
            station_id STRING NOT NULL,
            tenant STRING NOT NULL,
            issued_at TIMESTAMP NOT NULL,
            target_ts TIMESTAMP NOT NULL,
            horizon_h INT64 NOT NULL,
            model_version STRING NOT NULL,
            pm25_p10 FLOAT64 NOT NULL,
            pm25_p50 FLOAT64 NOT NULL,
            pm25_p90 FLOAT64 NOT NULL,
            created_at TIMESTAMP NOT NULL
        );
    """,
    "citizen_reports": """
        CREATE TABLE IF NOT EXISTS `{dataset}.citizen_reports` (
            report_id STRING NOT NULL,
            tenant STRING NOT NULL,
            session_id STRING NOT NULL,
            cell_id STRING NOT NULL,
            ts TIMESTAMP NOT NULL,
            lat FLOAT64 NOT NULL,
            lon FLOAT64 NOT NULL,
            photo_uri STRING NOT NULL,
            gemini_analysis JSON NOT NULL,
            is_valid BOOL NOT NULL,
            haze_severity INT64,
            visible_sources ARRAY<STRING>,
            created_at TIMESTAMP NOT NULL
        );
    """,
    "alerts": """
        CREATE TABLE IF NOT EXISTS `{dataset}.alerts` (
            alert_id STRING NOT NULL,
            tenant STRING NOT NULL,
            cell_id STRING,
            city STRING,
            alert_type STRING NOT NULL,
            issued_at TIMESTAMP NOT NULL,
            severity STRING NOT NULL,
            population_exposed INT64,
            attribution JSON,
            recipients ARRAY<STRING>,
            acknowledged_at TIMESTAMP,
            acknowledged_by STRING
        );
    """
}

TENANT_TABLES = ["raw_stations", "raw_satellite", "raw_meteorology", "predictions_grid", "predictions_forecast", "citizen_reports", "alerts"]
SHARED_TABLES = ["raw_fires", "grid_cells"]


def load_config() -> dict:
    config_path = Path(__file__).parent / "tenants.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_tenant(tenant_name: str, project_id: str, dry_run: bool = False):
    config = load_config()
    tenants = config.get("tenants", {})
    shared_config = config.get("shared", {})
    
    if tenant_name != "shared" and tenant_name not in tenants:
        raise ValueError(f"Unknown tenant '{tenant_name}'. Valid tenants in tenants.yaml: {list(tenants.keys())}")

    if tenant_name == "shared":
        dataset_id = shared_config.get("dataset", "vayusetu_shared")
        tables_to_create = SHARED_TABLES
    else:
        dataset_id = tenants[tenant_name].get("dataset", f"vayusetu_{tenant_name}")
        tables_to_create = TENANT_TABLES

    full_dataset = f"{project_id}.{dataset_id}"

    print(f"\n--- Provisioning dataset: {full_dataset} ---")
    if dry_run:
        print(f"[DRY-RUN] Would create BigQuery dataset: {full_dataset}")
        for table_name in tables_to_create:
            ddl = TABLE_SCHEMAS[table_name].format(dataset=full_dataset)
            print(f"[DRY-RUN] DDL for {full_dataset}.{table_name}:\n{ddl.strip()}\n")
    else:
        try:
            from google.cloud import bigquery
            client = bigquery.Client(project=project_id)
            
            # Create Dataset
            dataset_ref = client.dataset(dataset_id)
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = "asia-south1"
            dataset = client.create_dataset(dataset, exists_ok=True)
            print(f"Created/Verified dataset: {full_dataset}")

            # Create Tables
            for table_name in tables_to_create:
                ddl = TABLE_SCHEMAS[table_name].format(dataset=full_dataset)
                query_job = client.query(ddl)
                query_job.result()
                print(f"  [OK] Table created/verified: {full_dataset}.{table_name}")

        except Exception as e:
            print(f"Error creating dataset/tables via BigQuery API: {e}", file=sys.stderr)
            print("Fallback: Check your GCP credentials or run with --dry-run", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Create BigQuery tenant datasets and tables for VayuSetu")
    parser.add_argument("--tenant", action="append", help="Tenant key (e.g. ncr, lko, shared). Can specify multiple.")
    parser.add_argument("--project-id", default=os.getenv("GCP_PROJECT_ID", "civicpulse-v2s-01"), help="GCP Project ID")
    parser.add_argument("--dry-run", action="store_true", help="Print DDL queries without executing against BigQuery")

    args = parser.parse_args()

    tenants = args.tenant if args.tenant else ["ncr", "lko", "shared"]
    for t in tenants:
        create_tenant(t, args.project_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
