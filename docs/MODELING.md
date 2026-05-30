# Modeling Approach & Model Card — `gauntlet-v2.0.0`

How the HouseAccount AI pricing model works: data, assumptions, training strategy, confidence,
and honest limitations. Companion to `reports/eval_report.md` (the metrics) and `ASSUMPTIONS.md`.

## 1. Problem & data

Predict a price range + point estimate + confidence for a home-service booking. Training data:
1,432 jobs across 18 categories; **only 411 have `final_price`** (the supervised signal). No
scope fields (sqft, fixture count) exist — they must be mined from `job_description`.

**The decisive finding (drives the whole design).** The 411 labels are *not* distributed like the
dataset. The signal concentrates in five well-covered categories (Cleaning, Pest Control, HVAC,
Landscaping, Moving — ~60–66 labels each) where the old estimate is already good (baseline APE
~9–12%); these rows look **augmented/synthetic** (`final_price` sits tightly near the estimate
midpoint, position-in-range ≈ 0.48 ± 0.15). The genuinely-**real** rows are the sparsely-labeled
categories (Handyman 48%, Plumbing 36%, Flooring 29%, Painting 25% baseline APE) where the old
estimate is badly off and `final_price` often falls *outside* the quoted range. The two graded
numbers map onto this split:

| Subset | Rows | Baseline (old estimate) MAPE |
|---|---|---|
| Blended (all priced) | 411 | **11.56%** (reproduced exactly) |
| Real-only (`base_ape` > 20% proxy) | 49 | **36.7%** (≈ the brief's "~40%") |

Per-category modeling is impossible for most of the catalog (Plumbing has 3 labels, Electrical 2).
**The game is generalization** — text scope + geography + the existing estimate prior — not
category-specific fitting. Winning on the ~49 hard real rows is what drives *both* metrics down.

## 2. Core idea — model the residual, not the price

Target = **`log(final_price / original_estimate)`** — the multiplicative *correction* the old
estimate got wrong. This is the crux:

- **Synthetic rows** (`final_price ≈ estimate`) → target ≈ 0 → the model predicts a near-zero
  correction and **stays close to the already-strong baseline** (safe; preserves the 11.6%).
- **Real rows** (estimate badly off) → large target → the model **learns the correction** from
  scope/text/geography signals.
- When the model has no signal it predicts ≈ 0 and falls back to the trusted estimate — a built-in
  safety net. `original_estimate` is a legitimate input (Appendix A optional field), so using it is
  **not leakage**. Requests without it are anchored to a category-median price.

Prediction: `lo, mid, hi = original_estimate × exp(residual_quantile)`.

## 3. Model (v2 — selected by the research program in `experiments/JOURNAL.md`)

**Point estimate (what MAPE grades):** a single **LightGBM regressor with L2 loss on the log-residual
and MAPE-aligned sample weights `1/final_price^0.5`**, trained on **all** labeled data. Three findings
drove this (multi-seed OOF, 8–15 seeds):
- L2-on-log-residual beats quantile-q50 and MAE, especially on the hard real rows (real-only
  31.7%→27.9%). Reasoning: for large residuals the relative error `|e^δ−1|` is convex/asymmetric, and
  L2 handles the big real-row corrections better than the median.
- Weighting by `1/final_price^p` aligns the loss with MAPE (cheap jobs penalised proportionally).
  `p=0.5` is the sweet spot (best blended; higher p chases the target-defined real subset → overfit
  risk). A *custom* `|e^δ−1|` objective was MAPE-optimal in theory but numerically unstable — rejected.
- The v1 model wasted 25% of data on the conformal split *for the point model*. v2 trains the point
  model on 100% and calibrates intervals separately.
- Shallow + regularized (depth 4, num_leaves 15, min_child_samples 20, 400 trees @ lr 0.03) — tuning
  was marginal; the loss+weighting was the lever.

**Intervals:** **cross-conformal quantile regression** — q0.1/q0.9 LightGBM models on all data, with
the CQR pad calibrated by K-fold cross-fitting (no data wasted). **Normalized (adaptive)** conformity
scales the pad by the local predicted spread, widening intervals for high-uncertainty rows → better
conditional coverage on the sparse real categories. Marginal OOF coverage ≈ 83% (target 80%).

**Submission:** the 411 labeled rows in `predictions.csv` use **bagged 6-seed OOF** (each row's
out-of-fold prediction averaged over repeated CV splits) — leakage-free and lower-variance than any
single split.

### Features (all computable at request time — no `final_price`)
Estimate anchors (log original/lo/hi, relative range), urgency (deadline), booking month/seasonality,
subtype signals, **text features** from the description (length, numerics, unit mentions, keyword
flags: replace/repair/install/emergency/leak/…), category one-hot, production-vertical flag. Feature
importance ranks **description length** #1 (long descriptions ⇒ off-estimate jobs), then estimate-range
shape and magnitude. **The model is scope-free AND geography-free** at request time: ablation showed
raw ZIP-region features overfit on 411 rows / ~1033 ZIPs and were removed (JOURNAL R12; blended
10.78→10.61 at 10 seeds). A *keyed* Census ACS join (income/home-value by ZCTA) remains the principled
way to add geography and is wired but off by default (the Census API now requires a key).

## 4. Scope extraction (LLM, switchable)
`ScopeExtractor` has three interchangeable backends emitting the same schema:
`claude_cli` (shells to `claude -p`, used offline now), `anthropic_api` (drop-in via
`ANTHROPIC_API_KEY` for deployment), and `deterministic` (regex/keyword — the always-available
deploy floor, <1ms, no deps). Scope for the dataset is batch-extracted and cached
(`data/processed/scope.parquet`). The deployed endpoint uses the deterministic floor unless an API
key is configured; with the key it matches the offline training-quality scope.

**Empirical finding (measured, not assumed):** with the full scope extraction over all 411 labeled
rows, adding LLM scope features did **not** beat the deterministic features (with-scope 10.74% vs
no-scope **10.78%** blended; 26.99% vs 26.84% real-only — statistically identical, 8-seed OOF). On
only 411 rows the extra features add overfitting risk, and the deterministic text features
(description length, numerics, unit mentions, keyword flags) already capture the scope signal. So the
**deployed and graded model is scope-free** — deterministic features only (ZIP-region features removed per ablation), with **zero
train/serve skew** (the live endpoint isn't quietly worse than the offline model) and **no LLM
dependency**. The LLM `ScopeExtractor` (and its anthropic_api backend) is retained as a documented,
switchable capability and the cached extraction is shipped, but the final model does not use it. A
genuine "the LLM didn't help — kept honest rather than force-fit" result.

## 5. Confidence & out-of-distribution (PRD §Confidence calibration, verbatim)
Confidence ∈ [0,1] is high when the conformal interval is tight relative to the typical interval,
lower as it widens. Three hard OOD conditions **force confidence < 0.5** (the estimate is still
returned — never rejected or capped):
1. `estimate_midpoint` > **$5,000**
2. prediction interval (`hi − lo`) > **3× the median observed range** ($230 → $690)
3. `service_category` outside the **10 production verticals** — unknown categories are correctly
   treated as out-of-production (a bug present in v1 that read unknown categories as in-production
   was fixed in v2)

**Data-density-aware confidence (v2 addition):** a per-category support multiplier (≤1, floor 0.70)
is applied so that sparse in-production categories read as less certain than the global conformal pad
implies. The multiplier is proportional to the category's label count relative to the best-covered
category. Example at equal interval width: Cleaning (66 labels) → confidence ~0.82; Plumbing
(3 labels) → ~0.60; Electrical (2 labels) → ~0.60. This means a sparse category with a coincidentally
narrow interval no longer reads as highly confident.

Distribution over all 1,432 rows: ~35% below 0.5 (mostly out-of-production categories, as intended),
~12% ≥ 0.8. The booking-integration layer also surfaces human-readable `coverage` ("what's included")
and `uncertainties` ("why it might vary") strings derived from scope + the OOD flags.

## 6. Leakage discipline (how the metrics stay honest)
- **5-fold stratified out-of-fold**: every reported prediction — and every labeled row in
  `predictions.csv` — is scored by a model that never saw it.
- **CQR calibration is nested** inside each fold (calibration split ≠ test fold).
- The deployed `bundle.pkl` is the full model on all 411 (used for the live API + unlabeled rows).
- A unit test shuffles `final_price` and asserts MAPE blows up (>25%) — proving the pipeline isn't
  memorizing labels.

## 7. Results (leakage-free OOF)
All metrics are from the bagged 6-seed out-of-fold run on all 411 labeled rows (gauntlet-v2.0.0).

| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (411) | **10.47%** | 11.56% | ✅ |
| Real-only MAPE (49) | **26.58%** | 36.75% | ✅ |
| Interval coverage (target 80%) | **82%** | — | ✅ |

The real-only improvement (36.75% → 26.58%, ~26% relative) was the primary driver of the v2 research
program and is robust across seeds and the lockbox hold-out. Exact current numbers in
`reports/eval_report.md`, regenerated each train run.

## 8. Limitations & honest caveats
- **Tiny real signal.** Only ~49 genuinely-hard rows; the real-only MAPE (~27%) is based on noisy,
  target-defined proxy rows. Gains there are real and robust across seeds and the lockbox, but the
  confidence interval on the improvement remains wide given n=49.
- **Real-only subset is a proxy.** We don't see HouseAccount's hidden holdout; we define real-only
  as `base_ape > 20%` (baseline 36.7% ≈ their ~40%). Stated in `ASSUMPTIONS.md` (A3). The real-only
  weighting power was kept at 0.5 (not pushed higher) to avoid overfitting the proxy metric vs the
  hidden holdout — a deliberate conservatism (R8 in JOURNAL.md).
- **Per-category coverage on sparse categories remains imperfect.** Handyman (sparse, erratic real
  prices) shows ~62% interval coverage in OOF even with normalized conformal widening. The global
  82% target is met; conditional per-category calibration on 2–3 labels is not achievable.
- **Scope-free deployment.** The deployed model uses deterministic features only (ZIP-region features removed per ablation) (no LLM).
  This was a research finding, not a compromise: LLM scope did not beat deterministic on 411 rows.
  Train/serve skew is zero. The `ScopeExtractor` is retained as a switchable capability.
- **Census enrichment is off by default** — the Census API now requires a key; we substitute
  self-contained ZIP-region features. With `CENSUS_API_KEY` the ACS join activates.
- **Thin blended margin on synthetic rows.** The five well-covered augmented categories are near-
  irreducible (old estimate already good); the blended 10.47% win comes mostly from the ~49 real rows.
