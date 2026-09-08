# Glossary

For anyone — human or agent — arriving without atmospheric science or Indian public-administration context.

## The core concept

**Residual** — In this project, `pm25_pred − idw_baseline`: what our model estimates at a grid cell, minus what interpolating from the existing official stations would have said. **A large positive residual is a pollution hotspot the government's monitoring network cannot see.** This is the product. Not a statistics term here; a product term.

## Air quality

**PM2.5** — Particulate matter under 2.5 micrometres. The pollutant that matters most for health because it reaches deep into lungs and enters the bloodstream. Measured in µg/m³. Our primary target variable.

**PM10** — Particulate matter under 10 µm. Coarser: dust, construction. Always ≥ PM2.5 at the same place and time.

**AQI** — Air Quality Index. A 0–500+ scale derived from pollutant concentrations. **India uses CPCB National AQI breakpoints, which differ from the US EPA scale** — do not use EPA numbers. Bands: Good 0–30, Satisfactory 31–60, Moderate 61–90, Poor 91–120, Very Poor 121–250, Severe 250+. We store PM2.5 and derive AQI at read time.

**NO₂** — Nitrogen dioxide. A combustion marker — traffic, industry, burning. Useful for distinguishing combustion sources from dust.

## Indian institutions and policy

**CPCB** — Central Pollution Control Board. India's national pollution regulator. Operates the official monitoring network and defines the National AQI.

**CAAQMS** — Continuous Ambient Air Quality Monitoring Station. The official reference-grade monitors. Roughly 40 in Delhi, ~80 across NCR. **Their sparseness is the problem this project addresses.**

**SPCB** — State Pollution Control Board. The state-level counterpart, and a realistic pilot customer.

**GRAP** — Graded Response Action Plan. Delhi-NCR's staged emergency response — construction bans, traffic restrictions, school closures — triggered at AQI thresholds. Our alerts are designed to feed this existing decision process, which is a large part of why the solution is deployable rather than hypothetical.

**NCR** — National Capital Region. Delhi plus surrounding districts in Haryana, Uttar Pradesh and Rajasthan. ~30M+ people, and jurisdictionally fragmented, which is exactly why a federated design fits.

**Stubble burning** — Post-harvest burning of crop residue in Punjab and Haryana, Oct–Nov. A dominant driver of Delhi's winter smog, and the reason our fire data must cover a 200 km buffer well outside the NCR boundary.

**data.gov.in** — India's open government data portal.

## Satellite and remote sensing

**AOD** — Aerosol Optical Depth. How much light aerosols block through the atmospheric column. Dimensionless, roughly 0–5. Correlates with surface PM2.5 but is not the same thing — it is a whole-column measure, so converting to surface concentration needs meteorological correction, which is exactly what Model A learns.

**MAIAC** — Multi-Angle Implementation of Atmospheric Correction. The MODIS algorithm giving 1 km AOD. Earth Engine: `MODIS/061/MCD19A2_GRANULES`. Our finest-resolution satellite input, and why our grid is ~1 km.

**Sentinel-5P / TROPOMI** — ESA satellite measuring atmospheric composition. Gives NO₂ column and UV aerosol index at ~7 km, one overpass daily around 13:30 local. Good for regional plumes, not street level.

**FIRMS** — Fire Information for Resource Management System (NASA). Near-real-time active fire detections. VIIRS at 375 m. Our stubble-burning signal and the single highest-value feed for source attribution.

**FRP** — Fire Radiative Power, in megawatts. How intense a detected fire is. Bigger FRP, more smoke.

**ERA5** — ECMWF's atmospheric reanalysis. Historical hourly meteorology, ~5 day lag. Training features only, never live.

**GHSL** — Global Human Settlement Layer. Gridded population. Powers our exposure metric — the number that turns a hotspot into an impact claim.

**Cloud masking** — Satellites cannot see the surface through cloud, so those pixels return NULL. Delhi winters have heavy fog and cloud, so **30–50% NULL AOD in winter is normal**, not a bug.

**Overpass** — When a satellite passes over a location. Roughly daily per satellite, which is why our gridded product is daily while the forecast is hourly.

## Meteorology

**BLH** — Boundary Layer Height, in metres. The depth of the atmospheric layer pollutants mix into. **Low BLH means the same emissions produce far higher concentrations** — Delhi winter inversions can drop it below 100 m. One of the most important features in both models.

**Inversion** — When a warm layer sits above cooler surface air, trapping pollution. The mechanism behind Delhi's winter smog episodes.

**Wind direction convention** — In meteorology, wind direction is the direction wind comes **FROM**. A 310° wind blows from the northwest toward the southeast. **The upwind bearing is `wind_dir` itself, not `wind_dir + 180`.** Getting this backwards inverts every source attribution, and it is the first thing to check when fires never line up with plumes.

**Back-trajectory** — Tracing an air parcel backwards to find where it came from. Proper implementations (HYSPLIT) model 3D transport over days. **We use a ±30° wind-sector cone over 100 km** — a deliberate, documented approximation. Never call ours back-trajectory modelling.

## Machine learning

**LOSO** — Leave-One-Station-Out cross-validation. Hold out every row from one station, train on the rest, predict that station, repeat. **The only valid protocol for Model A**, because it mirrors the actual claim: estimating PM2.5 where no monitor exists. A random split leaks badly and reports a meaningless R² above 0.95.

**IDW** — Inverse Distance Weighting. Spatial interpolation weighting nearby points by `1/d²`. Our baseline: what the existing station network alone would tell you. The residual is defined against it.

**Persistence baseline** — "Tomorrow equals today." Deceptively strong for air quality, and the baseline every forecaster must beat to be worth anything.

**Climatology baseline** — The historical mean for that time of year. The second mandatory baseline.

**Quantile regression** — Training models to predict the 10th, 50th and 90th percentiles rather than just the mean, which gives a confidence band nearly free. Source of `pm25_p10` / `pm25_p90`.

**LightGBM** — Gradient-boosted decision trees. The right tool for tabular data at this scale; a neural network here would be both worse and slower to build.

## This project

**Tenant** — A city or state deployment. Own BigQuery dataset, own models, own dashboard scope. `ncr` and `lko` in the demo.

**Federated model sharing** — What we actually do: publish trained weights and schemas to a registry, other tenants import them. **Not federated learning** — no secure aggregation, no differential privacy. Describing it as federated learning is overclaiming, and `AGENTS.md` R7 forbids it.

**Climate zone** — A tag on a model card (`indo_gangetic_plain_winter`, `western_coastal`, ...) used to filter which models are sensible to import into a given city.

**Replay mode** — Driving the whole system from archived data for a chosen historical window, via `REPLAY_AS_OF`. Same code path as live. Makes the demo deterministic and enables backtesting. Always disclosed.

**Citizen support** — The count of valid corroborating citizen photo reports for a cell. **Raises confidence; never sets a PM2.5 value; never triggers an alert alone.**

**DPG** — Digital Public Good. Open-licensed, openly specified, reusable public infrastructure. Ours is the `spec/` schemas plus the Apache-2.0 code and the public read API.
