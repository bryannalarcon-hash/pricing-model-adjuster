# Eval report — gauntlet-v1.0.0

Leakage-free 5-fold out-of-fold on the 411 labeled rows. Scope backend: **deterministic**.

| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (all 411) | **11.31%** | 11.56% | ✅ |
| Real-only MAPE (n=49, base_ape>20%) | **34.54%** | 36.75% | ✅ |
| Interval coverage (target 80%) | 81.5% | — | ✅ |

predictions.csv: 411 labeled rows are OOF (leakage-free); 1021 unlabeled use the full model.
