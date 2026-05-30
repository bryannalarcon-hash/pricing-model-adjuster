# Research Journal — HouseAccount Pricing Model

Rigorous, looped model R&D: **research → architecture → build → test → pre/post-processing &
optimization → eval**, repeat. Every iteration logs hypothesis, change, multi-seed result, and an
adopt/reject decision with rationale.

## Protocol (overfitting discipline)
- **Primary metric:** repeated 5-fold out-of-fold MAPE, averaged over ≥8 seeds → report mean ± std.
  Separates real signal from fold-noise. Blended (all 411) + real-only (`base_ape>0.20`, n≈49).
- **Selection rule:** adopt a change only if (a) it beats the incumbent by **more than ~1 combined
  std**, AND (b) it is theoretically justified (not a seed-lucky CV artifact). Reject marginal/
  within-noise changes even if nominally lower.
- **Lockbox guard:** a fixed 20% stratified hold-out (seed 2024) never used during experimentation;
  the final chosen model is checked on it once. With ~82 rows (~10 real) it is noisy — used as a
  gross-overfit sanity check, not a precise estimate.
- **North star:** HouseAccount's hidden post-snapshot holdout. Favor robust, generalizable methods
  (proper losses, conformal calibration, ensembling) over fragile feature hacks.
- **Leakage:** every metric is OOF; conformal calibration nested; a shuffle test guards the pipeline.

## Baselines
- Old model (original_estimate midpoint): blended **11.56%**, real-only **36.75%**.
- Committed v1 (LightGBM quantile-q50 residual + CQR, 75%-data point, single seed): 11.31% / 34.54%.

## Iterations

### R1 — Loss-function sweep (residual = log(final/original), deterministic+scope features)
Hypothesis: the point-estimate loss matters; quantile-q50 may be suboptimal for MAPE.
Result (8-seed OOF):
| model | blended | real |
|---|---|---|
| lgbm_q50 (v1 loss) | 10.92 ±0.18 | 31.68 ±0.53 |
| lgbm_l1 (mae) | 10.94 ±0.18 | 31.74 ±0.53 |
| **lgbm_l2** | **10.73 ±0.15** | **27.91 ±0.43** |
| catboost_mae | 10.84 ±0.15 | 29.34 ±0.87 |
| xgb_mae | 10.80 ±0.16 | 29.55 ±0.62 |
| ensemble3 | 10.74 ±0.13 | 30.00 ±0.40 |

**Finding:** L2-on-log-residual dominates, esp. on real rows (27.9% vs 31.7%). Also: training the
point model on **all** data (not the 75% conformal split used in v1) is a free gain. **Adopt L2 as
the point loss; decouple point-model training from interval calibration.** (Both gains > noise.)

### R2 — Loss functions + MAPE-aligned sample weighting (8-seed OOF)
Hypothesis: weighting the loss by 1/final_price aligns training with MAPE (cheap jobs penalized
proportionally), and a custom |e^δ−1| objective could be MAPE-optimal.
| model | blended | real |
|---|---|---|
| **wl2_pow1** (L2, weight 1/fp) | 10.94 ±0.17 | **25.87 ±0.50** |
| **wl2_pow0.5** (L2, weight 1/√fp) | **10.74 ±0.12** | 26.99 ±0.42 |
| wl1_pow1 | 11.20 ±0.19 | 27.56 ±0.64 |
| lgbm_l2 | 10.73 ±0.15 | 27.91 ±0.43 |
| lgbm_huber | 10.72 ±0.15 | 27.94 ±0.39 |
| mape_obj (custom |e^δ−1|) | 14.36 ±0.40 | 28.18 — **unstable, reject** |
| lgbm_fair | 10.71 ±0.12 | 28.57 ±0.40 |

**Findings:** (1) **MAPE-aligned weighting (1/fp^p) is a strong lever for real-only** — pow=1 best
on real (25.9%) but costs blended; **pow=0.5 is the sweet spot** (blended unchanged 10.74, real
27.0%). (2) The custom |e^δ−1| objective is unstable (hessian surrogate) — reject. (3) huber/fair ≈
l2. **Adopt wl2 with a tuned power; sweep next.** Tweedie errored (needs positive target).

### R3 — Weighting power × target encoding × TF-IDF × ensembling (8-seed)
| model | blended | real |
|---|---|---|
| wl2_pow0.7 | 10.81 ±0.15 | **26.50 ±0.50** |
| wl2_pow0.5 | **10.74 ±0.12** | 26.99 ±0.42 |
| wl2_pow0.3 | 10.72 ±0.14 | 27.46 ±0.43 |
| ens_wl2_te | 10.79 | 27.28 |
| ens_wl2_cat_te | 10.72 | 27.88 |
| te_w0 (target-enc) | 10.97 | 28.58 |
| tfidf_w0.5 | 10.94 | 29.13 |

**Findings (mostly negative — important):** (1) **Target encoding HURTS** (28.6 vs 27.0) — overfits
on 411 rows. Reject. (2) **TF-IDF text features HURT** (29.1). Reject — the deterministic text
features already suffice. (3) **Ensembling adds nothing** over the best single model (and adds
complexity). Reject. (4) Weighting power: monotone blended↔real tradeoff; **pow 0.5–0.7 is the
sweet spot**. **Conclusion: simple weighted-L2 on deterministic+scope features is hard to beat;
complexity doesn't pay on this n. Adopt wl2, tune power + HPs next.**

### R4 — Hyperparameter sweep around weighted-L2 (10-seed)
Top configs (all within noise of each other): hp_mcs10 10.73/26.64, wl2_pow0.6 10.76/26.71,
wl2_pow0.5 10.74/26.94. Over-regularizing (mcs40, leaves31+mcs40) hurts (→10.94/28.0). reg_hi worse.
**Finding:** HP tuning is marginal (within ±noise); the gains came from the loss+weighting, not HPs.
**Adopt wl2 power=0.5, min_child_samples=20 (robust default).**

### R5 — model_v2 end-to-end (point=weighted-L2 on full data + cross-conformal intervals)
8-seed OOF: blended **10.74 ±0.12**, real **26.99 ±0.42**, **coverage 81.4%** (target 80%).
The cross-conformal intervals are well-calibrated and no data is wasted on the point model.
**vs committed v1 (11.31 / 34.54): blended −0.57pp, real-only −7.55pp (~22% relative).**

### R6 — Generalization guard: lockbox + per-category (running)
