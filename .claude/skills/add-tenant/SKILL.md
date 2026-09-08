---
name: add-tenant
description: Onboard a new city or state as a VayuSetu tenant — config, grid build, static layers, backfill, model import or training, and dashboard registration. Use when adding a city such as Lucknow, or when testing that the federation architecture actually generalises.
---

# Add a tenant

A tenant is a city or state deployment with its own BigQuery dataset, models and dashboard scope.

**If onboarding a tenant requires a code change, the architecture is wrong.** Config plus pipeline runs only. This procedure is also the test of that claim — run it end to end for Lucknow and any hardcoded `ncr` in the codebase will surface immediately.

## 1. Check the city is viable

| Requirement | Threshold | If below |
|---|---|---|
| CPCB stations in bbox | ≥ 8 | Satellite-only mode: import a model from a matching climate zone, do not train locally, widen confidence bands, and label the tenant `low_confidence` in the UI |
| Station history | ≥ 6 months | Import only, no local training |
| Earth Engine coverage | Always available | — |

Check it before committing:
```bash
python ingestion/stations.py --probe --bbox 26.70,80.80,26.99,81.10
```

Being able to onboard a city *below* the threshold, honestly labelled, is a feature — most Indian cities are below it. Do not treat it as a failure case.

## 2. Add the config entry

`infra/tenants.yaml`:
```yaml
lko:
  name: Lucknow
  state: Uttar Pradesh
  bbox: [26.70, 80.80, 26.99, 81.10]
  timezone: Asia/Kolkata
  climate_zone: indo_gangetic_plain_winter
  districts: [Lucknow]
  languages: [hi, en]
  fire_buffer_km: 200
```

`climate_zone` is what the registry filters on when suggesting importable models. Current values: `indo_gangetic_plain_winter`, `western_coastal`, `deccan_plateau`, `eastern_coastal`, `himalayan_foothill`.

## 3. Create the dataset and build the grid
```bash
python infra/create_tenant.py --tenant lko
python ingestion/static_layers.py --tenant lko
```

This creates `vayusetu_lko`, generates `grid_cells` on the shared 0.01° lattice (see `docs/DATA_CONTRACTS.md` §1), and loads GHSL population, WorldCover land use, elevation and road distance.

Sanity check: cell count should be roughly `(lat_span / 0.01) × (lon_span / 0.01)`. For Lucknow, about 870.

## 4. Backfill
```bash
python ingestion/stations.py     --tenant lko --from 2024-01-01 --to today
python ingestion/meteorology.py  --tenant lko --from 2024-01-01 --to today --source era5
python ingestion/satellite.py    --tenant lko --from 2024-01-01 --to today
python ingestion/fires.py        --bbox-buffer 200 --from 2024-01-01 --to today
```

Satellite backfill goes through GCS export, not `getInfo()`. It is the slow step — start it first and do the rest while it runs.

Then verify before going further:
```bash
python ml/verify_data.py --tenant lko --window 90d
```

## 5. Register schedulers
```bash
python infra/create_tenant.py --tenant lko --schedulers
```
Hourly: stations, fires, meteorology. Daily: satellite. All with `as_of` support.

## 6. Get a model — import or train

### Import (the federation path, and the demo)
```bash
python ml/registry.py --list --climate-zone indo_gangetic_plain_winter
python ml/registry.py --import ncr/grid-pm25/v3 --tenant lko
python ml/evaluate.py --tenant lko --model grid --cv loso --zero-shot
```

**Record the zero-shot number.** It will be worse than the source tenant's — Delhi ~31 MAE, Lucknow zero-shot ~45 is the expected shape. That degradation is the honest, interesting result, not something to hide. A transfer demo showing no drop is a transfer demo nobody believes.

### Fine-tune
```bash
python ml/train_grid.py --tenant lko --init-from ncr/grid-pm25/v3 --epochs-equivalent 100
python ml/evaluate.py --tenant lko --model grid --cv loso
python ml/registry.py --publish --tenant lko --model grid
```

### Train from scratch
Only if the city has ≥ 8 stations and ≥ 12 months of history. Otherwise import.

## 7. Register in the dashboard

Tenants come from `GET /api/v1/tenants` — no frontend change needed. Confirm:
- The tenant appears in the switcher.
- The map centres on its bbox.
- The federation view shows it on the India map.
- Language selector reflects `languages` from the config.

## 8. Verify the whole thing
```bash
python ml/verify_data.py --tenant lko --strict
curl "$API_BASE/api/v1/lko/hotspots?limit=5"
curl "$API_BASE/api/v1/lko/forecast?city=Lucknow&horizon=24"
```

## Checklist

- [ ] Station coverage probed, mode chosen (train vs import-only)
- [ ] Config entry added
- [ ] Dataset and grid created, cell count sane
- [ ] Static layers loaded
- [ ] Backfill complete, `verify_data.py` passing
- [ ] Schedulers registered and firing
- [ ] Model imported or trained, **LOSO number recorded honestly**
- [ ] Model card published to the registry
- [ ] Visible and correct in the dashboard
- [ ] **No code changes were needed** — if any were, fix the hardcoding and note it
