# FINAL STATUS — HouseAccount AI Pricing Model

Autonomous `/goal` build summary. All phases complete; all acceptance gates met.

## Acceptance gates

| # | Gate | Result |
|---|---|---|
| G1 | Beat blended MAPE 11.56% (leakage-free) | ✅ **10.62%** |
| G2 | Beat real-only baseline (~37%) | ✅ **27.07%** (n=49) |
| G3 | Response < 2s end-to-end | ✅ **0.02s** (Rails→sidecar) |
| G4 | Confidence ∈ [0,1]; <0.5 for OOD | ✅ ~35% <0.5 (OOD-driven), ~12% ≥0.8; density-aware |
| G5 | Real, non-invasive integration | ✅ 1 tagged booking (id 193, 201 draft); rest zero-write probes |
| G6 | Tests green + docs | ✅ 16 pytest + 21 rspec; full doc set |

The submitted `predictions/predictions.csv`, scored the way HouseAccount will (join on `job_id`,
MAPE of `estimate_midpoint` vs `final_price`), beats both baselines on the 411 labeled rows.

## What was built

- **Data/model (Python):** LightGBM L2 loss on log-residual `log(final/original)` with MAPE-aligned
  sample weights `1/final_price^0.5`, trained on all labeled data. Normalized (adaptive) cross-conformal
  quantile regression for calibrated intervals (~82% coverage). Bagged 6-seed OOF for predictions.csv.
  5-fold out-of-fold eval; a shuffle test guards against leakage. `src/houseprice/`.
- **Scope extraction:** `ScopeExtractor` with `claude_cli` / `anthropic_api` / `deterministic`
  backends; batch-extracted + cached. Deployed model is scope-free (deterministic + ZIP-region
  features only) — LLM scope did not beat deterministic on 411 rows.
- **Confidence/OOD:** PRD thresholds verbatim ($5k midpoint, 3× median range, non-production
  category → <0.5) plus data-density-aware support multiplier (sparse categories get lower
  confidence). Unknown categories correctly treated as out-of-production.
- **API (Rails):** API-only app, `POST /pricing-estimate` (+ Appendix A path alias), bearer auth
  (`secure_compare`), full error parity, proxy to a FastAPI inference sidecar.
- **Integration:** verified HMAC signing to staging; zero-write probes + exactly one tagged
  disposable booking.
- **Docs:** README, MODELING (model card), ASSUMPTIONS, AI_USAGE, DEPLOYMENT, eval report.

## Local deployment (live)

- **Endpoint:** `POST http://127.0.0.1:3007/pricing-estimate` (Bearer `GAUNTLET_PRICING_SECRET`)
- Alias: `POST http://127.0.0.1:3007/.netlify/functions/pricing-estimate`
- Sidecar health: `GET http://127.0.0.1:8011/health`
- Bring-up: see `docs/DEPLOYMENT.md` (sidecar on 8011, Rails on 3007).

## Scope-extraction finding (measured)
The LLM `ScopeExtractor` (`claude_cli`) was built and the dataset scope cached. A multi-round
research program (R1–R8, see `experiments/JOURNAL.md`) evaluated LLM scope features against
deterministic features on the 411 labeled rows. LLM scope did **not** beat deterministic: scope vs
no-scope OOF is within noise (10.78% vs 10.74% blended; 26.84% vs 26.99% real-only). With only 411
rows the extra features add overfitting risk, and the deterministic text features already capture the
signal. The **deployed/graded model is scope-free** — deterministic + ZIP-region features only, zero
train/serve skew, no LLM dependency. The `ScopeExtractor` remains a switchable, documented capability
but is not used by the final model. This is an honest documented negative result.

## Key decisions (full list in ASSUMPTIONS.md)
Rails (PRD-preferred) + Python model behind a sidecar · local deploy (Railway deferred) ·
real-only defined as `base_ape>20%` (≈ the brief's ~40%) · predictions.csv = bagged 6-seed OOF for
labeled rows (no leakage, lower variance) · Census key-gated, ZIP-region fallback ·
**scope-free deployment** (LLM scope within noise of deterministic; deterministic chosen for
zero skew and no LLM dependency) · **L2 loss + MAPE-aligned weights `1/√final_price`** on full
labeled data (beats quantile-q50 on real rows by ~7pp) · **normalized cross-conformal** intervals
(adaptive per-row widening for sparse categories) · **data-density-aware confidence** (per-category
support multiplier, floor 0.70).

## Known limitations
Thin blended margin (synthetic rows are near-irreducible); only ~49 genuinely-hard real rows (real-only
MAPE is ~27% but based on noisy, target-defined proxy rows); per-category coverage on sparse categories
like Handyman remains ~62% even with normalized conformal; real-only power kept at 0.5 (not pushed
higher) to avoid overfitting the proxy metric vs the hidden holdout. Census enrichment is key-gated
(ZIP-region fallback active). Detail in `docs/MODELING.md §8`.

## Out of scope (per goal directive)
Demo video (not produced; local deployment link provided instead).
