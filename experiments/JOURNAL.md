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

### R6 — Generalization guards
- **No-scope decision:** scope vs no-scope OOF is within noise (10.74/26.99 vs 10.78/26.84) →
  **deploy scope-free** (zero train/serve skew, no LLM dependency). LLM scope = documented negative.
- **Lockbox** (fixed 20%, n=83, 7 real — noisy): real-only generalizes (27–28% vs ~40% base);
  blended ~flat on the small sample (the 411-row OOF 10.6% is the reliable blended estimate).
- **Bagged OOF** (6 seeds) for predictions.csv: blended **10.62%**, real **27.07%**, coverage 83%.
  Lower variance than any single split; this is the shipped submission.

### R7 — Data-density-aware confidence
Added a per-category support multiplier (≤1, floor 0.70) so sparse in-production categories read
as less certain than the global conformal pad implies. Verified live: Cleaning(66 labels) 0.82,
Plumbing(3) 0.60, Electrical(2) 0.60 — same job/interval. Out-of-production + OOD caps unchanged.

### R8 — Weighting-power sweep (bagged, production model)
Monotone tradeoff (cov 83% throughout): pow 0.3→0.8 gives blended 10.61→10.75, real 27.54→26.37.
**Chose power=0.5** — best blended (the reliable metric), and deliberately did NOT chase higher
power to minimize the target-defined real-only proxy (overfitting risk vs the hidden holdout).

### Feature importance (weighted-L2)
Top signals: **desc_len** (longest descriptions → off-estimate jobs), rel_range/range (estimate
uncertainty), estimate magnitude, season (month), ZIP geography, numerics/keywords. Confirms the
simple deterministic text features carry the signal — explaining why TF-IDF/scope were redundant.

### R9 — Bias check + per-category breakdown
Optimal global scalar c*=0.998 (model is unbiased — reject bias correction). Per-category: big wins
on hard real cats (Handyman 48.4→33.8, Plumbing 35.8→25.8, Flooring 29.4→19.7), neutral on synthetic
cats (HVAC slightly worse 9.7→10.1). Sparse cats are *under*-covered (Handyman 64%, Plumbing 33%).

### R10 — Normalized (adaptive) cross-conformal
Scale the conformity score by local predicted spread so the pad widens for uncertain rows. Improves
conditional coverage (Plumbing 39→44%, Flooring 62→71%, Cleaning over-coverage 86→83%) with marginal
coverage unchanged (~82%). **Adopted** (default normalized=True) — point MAPE unchanged.

### R11 — Robustness: leave-one-category-out + model family
- **LOCO** (train without a category, predict it — unseen-category generalization): the model still
  **beats baseline on the hard categories even unseen** (Plumbing 35.8→26.0, Flooring 29.4→19.9,
  Handyman 48.4→40.4) and only slightly trails on already-easy ones. Confirms it generalizes via the
  residual anchoring + features, not category memorization — supports the "estimate any category" req.
- **Model family** (6-seed OOF): lgbm_wl2 **10.71/27.06** (best balance); random_forest 10.67/28.77
  (better blended, worse real); extra_trees 10.78/27.72; hist_gb 10.97/26.85; ens_l2_huber_fair
  10.71/28.24 (ensemble ≠ better); MLP diverged (needs scaling, not worth it on 411 rows).
  **LightGBM weighted-L2 confirmed — no family beats it on the blended+real balance.**

## Final architecture (deployed, gauntlet-v2.0.0)
Residual target log(final/original) · LightGBM **L2 + MAPE-aligned weight 1/√final_price** point
model on ALL data · **cross-conformal** quantile intervals (coverage 83%) · bagged 6-seed OOF for
the submission · deterministic+ZIP-region features, **scope-free** · density-aware confidence + PRD
OOD gates. **Leakage-free OOF: blended 10.62% (base 11.56), real-only 27.07% (base 36.75).**
