# Eval report — gauntlet-v2.0.0

Leakage-free 5-fold out-of-fold on the 411 labeled rows. Scope backend: **deterministic**.

| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (all 411) | **10.47%** | 11.56% | ✅ |
| Real-only MAPE (n=49, base_ape>20%) | **26.58%** | 36.75% | ✅ |
| Interval coverage (target 80%) | 82.2% | — | ✅ |

predictions.csv: 411 labeled rows are OOF (leakage-free); 1021 unlabeled use the full model.
