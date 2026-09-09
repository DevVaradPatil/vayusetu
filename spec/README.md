# VayuSetu Open Specifications — Digital Public Good

This directory contains open, versioned JSON Schemas published under the Apache-2.0 Licence. These schemas define the interoperability contracts for VayuSetu:

1. **[`hotspot-event.schema.json`](hotspot-event.schema.json)**
   - Defines the interchange format for a pollution episode: what was observed, the measured drivers behind it (upwind fires, boundary layer height, wind), the reasoning that connects them, and who should act. A consumer can re-derive the conclusion without trusting — or even knowing about — the publisher's models.
   - **v2.0.0** makes `predicted_pm25`, `station_idw_baseline` and `residual_pm25` optional. They were required in 1.0.0, when the residual was the product. A residual is only meaningful alongside evidence that the estimator beats its IDW baseline under leave-one-station-out validation; ours does not, so VayuSetu no longer publishes one.

2. **[`model-card.schema.json`](model-card.schema.json)**
   - Defines the model card structure used by the VayuSetu Federated Registry to publish, import, and cross-evaluate machine learning models across Indian cities and state pollution control boards.

## License
Apache-2.0
