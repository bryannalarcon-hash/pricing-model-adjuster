# Eval report — gauntlet-v2.1.0

Leakage-free 5-fold out-of-fold on the 411 labeled rows. Scope backend: **deterministic**.

| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (all 411) | **10.49%** | 11.56% | ✅ |
| Real-only MAPE (n=49, base_ape>20%) | **26.22%** | 36.75% | ✅ |
| Interval coverage (target 80%) | 82.7% | — | ✅ |

predictions.csv: 411 labeled rows are OOF (leakage-free); 1021 unlabeled use the full model.
