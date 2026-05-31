---
date: 2026-05-31
topic: pricing-model-robustness-avenues
---

# Pricing Model — Robustness-First Avenues of Change

## Summary

Push the HouseAccount pricing model further with three compatible, robustness-first levers — each adopted only if it should generalize to the hidden post-snapshot holdout, not merely squeeze the noisy OOF proxy: **(B)** a variance-reduction ensemble with monotonic domain priors, **(A)** one OOF-safe semantic-kNN feature from job-description embeddings, and **(C)** an additive selective-prediction layer that flags/abstains and widens intervals on likely-wrong rows. This doc also locks in the full record of what has been tried and rejected (R1–R21), so the data/architecture ceiling is auditable.

## Problem Frame

The deployed model `gauntlet-v2.1.0` (blended MAPE 10.49%, real-only 26.22%, coverage 82.7%) sits at a documented data ceiling. Every external data source has been OOF-tested and rejected — cost guides, Census ACS (6σ worse), permits/AHS, Reddit finals, Thumbtack marketplace, and most recently HomeStars (premise disproven: no prices in current reviews). The only untried *architecture* lever, TabPFN, also lost head-to-head and was ~34× slower.

So the remaining surface is narrow and the failure mode is specific: gains here will be tenths of a point and the OOF gate carries ~±0.3pp seed noise on a noisy n=49 real-only proxy (`base_ape>0.20`). A lever that "wins" by overfitting that proxy can *lose* on the hidden holdout (the R8 conservatism lesson). The work must therefore optimize for generalization and stability, with point-MAPE held flat-or-better, rather than chasing the headline number.

## Key Decisions

- **Robustness over squeeze.** A lever is worth adopting only if it is expected to hold on the hidden holdout #3 and reduces (or holds) variance — even if the OOF proxy barely moves. Do not tune to the n=49 cohort.
- **Sequencing and primacy.** B (variance reduction) is the primary base; A (text kNN feature) is the one signal-adding lever that fits the robustness bar; C (selective prediction) is an additive value layer.
- **Text signal as one feature, computed locally.** Tap the description via a single OOF-safe semantic-kNN ratio feature — not raw high-dimensional embeddings dumped into a 411-row fit (overfit). Embeddings are computed locally; no proprietary rows leave the machine (the same line held when rejecting the TabPFN cloud client).
- **C is additive, not a reframe.** The selective-prediction layer sits on top of the existing confidence machinery and the unchanged point estimate; it does not replace the midpoint model.
- **Honest success definition.** Because the point estimate is near its floor, a real win is no-blended-regression + seed stability + better real-world flagging — not a guaranteed lower real-only MAPE.

## Requirements

**Shared evaluation gate (all avenues)**

- R1. Every lever is evaluated under the existing 5-fold stratified OOF gate, scored on `estimate_midpoint` MAPE — both blended (411 rows) and the real-only proxy (`base_ape > 0.20`) — averaged over ≥5 seeds.
- R2. Every lever passes the shuffle-label leakage test; no in-sample metrics are reported as results.
- R3. A lever is adopted only when it does **not** regress blended MAPE beyond seed noise **and** does not increase seed-to-seed OOF variance. Expected-to-generalize beats proxy-squeezing in every tie.
- R4. Any new computation (embeddings, meta-model training, inference) runs locally; no proprietary rows are sent to an external service.

**Avenue B — variance reduction (primary)**

- R5. Add monotonic constraints encoding domain priors to the point model: predicted final is non-decreasing in `original_estimate` and in the estimate range/`estimate_hi`.
- R6. Build a simple averaging ensemble of the LightGBM point model with at least one decorrelated GBDT (CatBoost and/or XGBoost — already installed), on the same residual target `log(final/original)`.
- R7. Evaluate wider bagging breadth purely for variance reduction; keep only if it improves stability without a blended regression.
- R8. Report the **stability delta** (seed std of OOF MAPE), not just the mean — stability is the primary success signal for this avenue.

**Avenue A — conservative text signal**

- R9. Compute sentence embeddings of `job_description` with a locally-run encoder.
- R10. Derive a single OOF-safe "semantic-kNN final/estimate-ratio" feature (the typical correction of the k nearest descriptions), mirroring the existing novelty feature; nested per-fold so no test row sees its own neighbors' labels.
- R11. Optionally add a small number of PCA-reduced embedding dimensions **only if** R10 alone underperforms. Never inject raw high-dimensional embeddings into the 411-row fit.
- R12. Adopt only if the feature adds signal beyond the existing keyword/length/number features under the shared gate (R1–R3).

**Avenue C — selective prediction (additive)**

- R13. Train a leakage-safe (OOF) meta-model predicting per-row error magnitude (or P(real-only blowout)) from the existing features plus novelty.
- R14. Use the meta-score to widen intervals and/or raise a flag/abstain signal on high-predicted-error rows, integrated with the existing confidence layer rather than replacing it.
- R15. The midpoint point estimate is unchanged by C. C is evaluated on flagging quality (e.g., recall of the `base_ape > 0.20` cohort at a fixed flag budget; interval sharpness), not on midpoint MAPE.
- R16. C must not degrade existing interval coverage (≥80%) or the confidence calibration.

## Acceptance Examples

- AE1. **Covers R3.** A new feature lowers real-only OOF MAPE by 0.4pp but raises seed std from 0.30 to 0.55 → **rejected** (gain is inside noise and stability worsened), even though the mean "improved."
- AE2. **Covers R10.** For a held-out test fold, the kNN-ratio feature for each test row is computed only from training-fold descriptions/labels → a shuffle-label run shows no signal leakage → **valid**.
- AE3. **Covers R15.** Avenue C leaves blended/real-only midpoint MAPE numerically identical to v2.1.0, but flags 70% of the `base_ape>0.20` cohort within a 15% flag budget and keeps coverage at 82% → **success** (value is in flagging, not the headline number).

## Success Criteria

- No blended-MAPE regression beyond seed noise vs `v2.1.0` (10.49%).
- Seed-to-seed OOF variance reduced or unchanged (stability is the headline for B).
- All levers leakage-safe (shuffle-label test passes; no in-sample reporting).
- C improves flagging of the high-error cohort at a fixed flag budget while interval coverage stays ≥80%.
- The "Prior Work — Tried & Locked" ledger below is present and accurate, so the ceiling is auditable by a future reader.

## Scope Boundaries

**Deferred for later**
- Railway deployment, demo video, and assignment packaging — outside this metrics-focused pass.
- PCA embedding dimensions (R11) — only revisited if the single kNN feature underperforms.

**Outside this effort's identity**
- New external data sources — closed (R14–R20); the marketplace labels are irreplaceable.
- New model architectures beyond simple ensembling — TabPFN closed (R21); other GBDTs are only for variance reduction, not as replacements.
- Re-tuning to the n=49 real-only proxy as a headline objective — that is the squeeze trap this effort explicitly rejects.

## Prior Work — Tried & Locked

The adopted lineage (each stage leakage-safe bagged OOF; blended / real-only):

| Stage | Blended | Real-only |
|---|---|---|
| Baseline (old estimate) | 11.56% | 36.75% |
| v1 (quantile-q50 + CQR) | 11.31% | 34.54% |
| v2 (L2 + MAPE weight + cross-conformal + bagging) | 10.62% | 27.07% |
| v2 + no-ZIP (ablation) | 10.47% | 26.58% |
| **v2.1 + novelty feature + novelty-aware confidence (deployed)** | **10.49%** | **26.22%** |

Foundational experiments R1–R13 (detail in `experiments/JOURNAL.md`): established the **residual/multiplier target** (`log(final/original)`: multiplier 10.60% vs log-price 13.63% vs direct-price 19.06%), **MAPE-aligned sample weighting** (`1/√final`, power 0.5), **5-fold stratified OOF** leakage discipline, **normalized cross-conformal** intervals, data-density-aware confidence, and the ZIP-feature ablation.

Rejected / adopted ledger R14–R21 (all OOF-gated, scored on the 411 real rows):

| ID | Lever | Verdict |
|---|---|---|
| R14 | Census ACS geography (income/home value) | Rejected — 6σ worse (key obtained, 2 vintages) |
| R15 | Hand-crafted change features (hedge/scope/round) | Rejected — absent/redundant/noise |
| R16 | Novelty → confidence penalty + OOD gate | **Adopted** — fixed gibberish-confidence gap |
| R17 | Novelty as a point feature | **Adopted** — real-only 26.58 → 26.22 (v2.1.0) |
| R18 | Reddit "what I paid" finals (331, browser-control) | Rejected — −2 to −7pp |
| R19 | Thumbtack well-reviewed marketplace prices (76) | Rejected — least-bad but still worse |
| R20 | HomeStars (CA) "approximate cost" field | Rejected — premise false on live site (0 prices / 30 reviews); no crawl run |
| R21 | TabPFN small-data foundation model | Rejected — lost vs deployed (−2.92 real) and vs unweighted control (−1.82 real); ~34× slower |

Root cause of the data ceiling: HouseAccount's marketplace-distribution labels are irreplaceable; public sources are estimates or distribution-skewed, and a general-purpose tabular prior cannot beat a GBDT tuned to the residual target on 411×41.

## Dependencies / Assumptions

- A local sentence-transformer encoder is installable and runs offline; embeddings add no data egress.
- CatBoost / XGBoost are already installed (used for experiments) and available for the ensemble.
- The hidden post-snapshot holdout (#3) is the true generalization target; the OOF blended/real-only metrics are noisy stand-ins.
- **Assumption (load-bearing):** GBDT ensemble diversity is low (the TabPFN result hints other learners correlate with LightGBM), so B's gain is likely *stability*, not a lower mean MAPE. If diversity proves higher, mean gains are possible.

## Outstanding Questions

**Resolve before planning** — none blocking; avenues are chosen and the adoption bar is set.

**Deferred to planning**
- Which local encoder model and `k` for the kNN-ratio feature (A).
- Ensemble weighting scheme and which second GBDT(s) to include (B).
- Meta-model family and the flag-budget threshold for C.
- Whether monotonic constraints apply to the point model only or also the quantile models.

## Sources / Research

- `experiments/JOURNAL.md` — research log R1–R21 (read R14–R21 for the augmentation + architecture closes).
- `docs/MODELING.md` — model card / deployed architecture; `reports/eval_report.md` — current metrics.
- Experiment harnesses: `experiments/tabpfn_eval.py` (R21), `experiments/scrape_homestars.py` (R20), `experiments/augment_eval.py` / `augment_eval2.py` (R18–R19 OOF gate), `experiments/novelty_knn.py` (the proven kNN pattern A mirrors).
- Model code: `src/houseprice/model_v2.py`, `confidence.py`, `predict.py`, `train.py`, `eval.py`.
