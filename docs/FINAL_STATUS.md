# FINAL STATUS — HouseAccount AI Pricing Model

Autonomous `/goal` build summary. All phases complete; all acceptance gates met.

## Acceptance gates

| # | Gate | Result |
|---|---|---|
| G1 | Beat blended MAPE 11.56% (leakage-free) | ✅ **11.31%** |
| G2 | Beat real-only baseline (~37%) | ✅ **34.54%** (n=49) |
| G3 | Response < 2s end-to-end | ✅ **0.02s** (Rails→sidecar) |
| G4 | Confidence ∈ [0,1]; <0.5 for OOD | ✅ ~35% <0.5 (OOD-driven), ~12% ≥0.8 |
| G5 | Real, non-invasive integration | ✅ 1 tagged booking (id 193, 201 draft); rest zero-write probes |
| G6 | Tests green + docs | ✅ 15 pytest + 21 rspec; full doc set |

The submitted `predictions/predictions.csv`, scored the way HouseAccount will (join on `job_id`,
MAPE of `estimate_midpoint` vs `final_price`), beats both baselines on the 411 labeled rows.

## What was built

- **Data/model (Python):** residual-quantile LightGBM (`target = log(final/original)`) +
  Conformalized Quantile Regression for calibrated 80% intervals. 5-fold out-of-fold eval; a
  shuffle test guards against leakage. `src/houseprice/`.
- **Scope extraction:** `ScopeExtractor` with `claude_cli` / `anthropic_api` / `deterministic`
  backends; batch-extracted + cached.
- **Confidence/OOD:** PRD thresholds verbatim ($5k midpoint, 3× median range, non-production
  category → <0.5).
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
The LLM `ScopeExtractor` (`claude_cli`) was built and the dataset scope cached, but adding LLM
scope features **did not beat** deterministic features on the 411 labeled rows (11.37% vs 11.28%
blended; 35.2% vs 34.4% real — consistent across 310/1050/1155 extracted rows). On so few rows the
extra features overfit and the deterministic text features already capture the signal. The graded
and deployed model therefore uses **deterministic** scope (skew-free, simpler); the LLM backend
remains switchable per the original requirement. Honest negative result, kept rather than force-fit.

## Key decisions (full list in ASSUMPTIONS.md)
Rails (PRD-preferred) + Python model behind a sidecar · local deploy (Railway deferred) ·
real-only defined as `base_ape>20%` (≈ the brief's ~40%) · predictions.csv = OOF for labeled rows
(no leakage) · Census key-gated, ZIP-region fallback · scope `claude_cli` now / API-key switchable /
deterministic deploy floor.

## Known limitations
Thin blended margin (synthetic rows are near-irreducible); only ~49 genuinely-hard real rows;
real-only subset is a proxy for the hidden holdout; deployed endpoint uses deterministic scope
(LLM scope offline/with key); confidence is interval-driven, not data-density-driven. Detail in
`docs/MODELING.md §8`.

## Out of scope (per goal directive)
Demo video (not produced; local deployment link provided instead).
