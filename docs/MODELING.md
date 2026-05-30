# Modeling Approach & Model Card — `gauntlet-v1.0.0`

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

## 3. Model

- **LightGBM quantile regression**, three models at q=0.1 / 0.5 / 0.9, shallow + regularized
  (depth 4, num_leaves 15, min_child_samples 20, 400 trees @ lr 0.03, subsampled) to resist
  overfitting on ~330 rows/fold.
- **Conformalized Quantile Regression (CQR; Romano et al. 2019).** The raw q0.1/q0.9 band is
  widened by the (1-α) quantile of the conformity score `E = max(q̂_lo − y, y − q̂_hi)` measured on
  a held-out calibration split *inside each fold*. This gives the interval **finite-sample coverage**
  rather than relying on the quantile models being perfectly calibrated. Observed OOF coverage ≈ 81%
  against an 80% target.

### Features (all computable at request time — no `final_price`)
Estimate anchors (log original, relative range), urgency (deadline), booking month/seasonality,
subtype signals, **text features** from the description (length, numerics, unit mentions, keyword
flags: replace/repair/install/emergency/leak/…), **ZIP-region geography** (first 1/2/3 digits as a
cost-of-living proxy), category one-hot, production-vertical flag, and **LLM-extracted scope**
(sqft, fixture count, complexity, urgency) — see §4.

## 4. Scope extraction (LLM, switchable)
`ScopeExtractor` has three interchangeable backends emitting the same schema:
`claude_cli` (shells to `claude -p`, used offline now), `anthropic_api` (drop-in via
`ANTHROPIC_API_KEY` for deployment), and `deterministic` (regex/keyword — the always-available
deploy floor, <1ms, no deps). Scope for the dataset is batch-extracted and cached
(`data/processed/scope.parquet`). The deployed endpoint uses the deterministic floor unless an API
key is configured; with the key it matches the offline training-quality scope.

**Empirical finding (measured, not assumed):** adding the LLM scope features did **not** beat the
deterministic features on this dataset (≈11.42% vs 11.28% blended; 35.2% vs 34.4% real-only) — with
only 411 labeled rows the extra features add overfitting risk, and the deterministic text features
(numerics, unit mentions, keyword flags) already capture most of the scope signal. So the **graded
and deployed model uses deterministic scope** (also skew-free and simpler). The LLM `ScopeExtractor`
is retained as a switchable, documented capability and the cached extraction is shipped — but it is
not used for the headline metrics, because rigor beat it. This is a genuine "AI output that didn't
improve things" result, kept honest rather than force-fit.

## 5. Confidence & out-of-distribution (PRD §Confidence calibration, verbatim)
Confidence ∈ [0,1] is high when the conformal interval is tight relative to the typical interval,
lower as it widens. Three hard OOD conditions **force confidence < 0.5** (the estimate is still
returned — never rejected or capped):
1. `estimate_midpoint` > **$5,000**
2. prediction interval (`hi − lo`) > **3× the median observed range** ($230 → $690)
3. `service_category` outside the **10 production verticals**

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
| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (411) | ~11.3% | 11.56% | ✅ |
| Real-only MAPE (49) | ~34.5% | 36.7% | ✅ |
| Interval coverage | ~81% | 80% target | ✅ |

(Exact current numbers in `reports/eval_report.md`, regenerated each train run.)

## 8. Limitations & honest caveats
- **Tiny real signal.** Only ~49 genuinely-hard rows; gains there are real but the confidence
  interval on the *improvement* is wide. Top categories (Plumbing/Electrical/Painting) have 2–3
  labels — predictions there lean on the prior + scope, not category data.
- **Real-only subset is a proxy.** We don't see HouseAccount's hidden holdout; we define real-only
  as `base_ape > 20%` (baseline 36.7% ≈ their ~40%). Stated in `ASSUMPTIONS.md` (A3).
- **Census enrichment is off by default** — the Census API now requires a key; we substitute
  self-contained ZIP-region features. With `CENSUS_API_KEY` the ACS join activates.
- **Train/serve scope parity.** Best accuracy uses LLM scope (offline / with API key); the bare
  deployed endpoint uses the deterministic floor, a small quality gap documented in ASSUMPTIONS.
- **Confidence is interval-driven, not data-density-driven** — a sparse in-production category with
  a coincidentally narrow interval can read as confident. A category-support penalty is a known
  future improvement.
