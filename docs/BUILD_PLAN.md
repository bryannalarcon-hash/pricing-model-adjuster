# BUILD_PLAN — HouseAccount AI Pricing Model (autonomous /goal)

Master contract + resume anchor. All modules build against the seams defined here so parallel
agents don't collide. Source of truth for decisions, assumptions, and phase gates.
**Do not modify `assignment_description.md`.**

Deadline: 2026-05-30 ~06:24 CDT (7.5h window). Vast.ai budget: ≤ $20 (only if needed).

---

## 0. Locked decisions (from planning session)

| Area | Decision | Rationale (PRD-paramount) |
|---|---|---|
| API layer | **Ruby on Rails** (API-only) | PRD strongly prefers Rails; satisfies must-have #4 (style guide) |
| Model layer | **Python** (LightGBM) served behind Rails | PRD: modeling any framework; clean data/model/API separation |
| Rails↔Python seam | Python inference as a local sidecar service (uvicorn) on 127.0.0.1; Rails proxies | Robust, <2s, language-clean |
| LLM scope extraction | `ScopeExtractor` interface: `claude_cli` (now) → `anthropic_api` (when key) → `deterministic` (always, deploy fallback) | User directive; claude -p won't run on a remote host |
| Deploy | **Local** now (Rails + Python sidecar); Railway later | User directive |
| Confidence/OOD | PRD values verbatim: thresholds 0.8/0.5; OOD = midpoint>$5k OR interval>3×median OR category∉10 production verticals → confidence<0.5 | PRD §Confidence calibration |
| Predictions file | `predictions/predictions.csv`: job_id,estimate_lo,estimate_hi,estimate_midpoint,confidence | default (eval computed as we reproduced) |
| model_version | `gauntlet-v1.0.0` | free-form per Appendix A |
| Endpoint path | `/pricing-estimate` + alias `/.netlify/functions/pricing-estimate` | cover both readings of Appendix A |
| Error parity | `{"error": "..."}`; 400 malformed/missing, 401 unauth, 405 method, 200 ok | Appendix A |

## 1. Data facts (verified)
- 1,432 rows, 18 categories. **411 labeled** (`final_price`).
- Baseline reproduced EXACTLY: blended MAPE **11.6%**, median APE **8.3%** (original_estimate vs final_price).
- Label concentration: signal in Cleaning/PestControl/HVAC/Landscaping/Moving (~60–66 each); high-volume cats nearly unlabeled (Plumbing 3, Electrical 2, Painting 2, Handyman 14, Roofing 24).
- 1,033 ZIPs. Title-case categories (dataset) vs kebab (production seed) — normalize on read.
- 10 production verticals: electrical, exterior-cleaning, handyman, hvac, indoor-cleaning, irrigation, landscaping-lawn, pest-control, plumbing, tick-mosquito-treatment.

## 2. Targets (acceptance gates)
- **G1 Blended MAPE < 11.6%** on all 411 priced rows, leakage-free (out-of-fold).
- **G2 Real-only MAPE < ~40%** baseline, estimated on genuinely-real rows via OOF (we don't see their hidden holdout).
- **G3** Response time < 2s end-to-end (local).
- **G4** OOD confidence < 0.5 for the three OOD conditions; calibrated confidence in [0,1].
- **G5** Real, non-invasive integration: exactly ONE tagged staging booking, logged; rest via no-write 401/422 probes.
- **G6** Tests green (model logic + API boundary + integration). README<15min, modeling doc, deployment guide, AI_USAGE.md, ASSUMPTIONS.md.

## 3. Leakage-free eval protocol (CRITICAL)
- **K-fold (k=5), grouped by nothing but stratified by category-bucket**, on the 411 labeled rows.
- Every reported prediction is **out-of-fold**: the model scoring row i was trained without row i.
- **Conformal calibration is nested**: residual quantiles computed only on the training portion of each fold (never the held-out fold).
- Feature selection / hyperparams fixed a priori or tuned via inner CV only — no peeking at OOF metrics to choose.
- `original_estimate` (and lo/hi) are legitimate inputs — present in the API request (Appendix A optional fields) — so blending against them is NOT leakage.
- LLM scope features derive from `job_description` only (never `final_price`).
- "Real-only" subset = labeled rows excluding the augmented/near-synthetic ones; report OOF MAPE on it. State the definition used.

## 4. Architecture / module contracts (build seams)
```
data/raw/houseaccount_pricing_sample.csv        # input (immutable)
src/houseprice/
  data_load.py     load_dataset() -> DataFrame (normalized categories, typed)
  census.py        zip_features(zips) -> DataFrame[zip, median_income, home_value, ...]  (ACS, cached data/external/)
  scope.py         ScopeExtractor (claude_cli|anthropic_api|deterministic).extract(desc, category) -> dict
  features.py      build_features(df, scope_df, census_df) -> X, feature_meta
  model.py         train_quantile_models(X,y) ; ConformalPriceModel.predict(X) -> lo,mid,hi
  confidence.py    confidence_and_ood(row, interval, median_range, production_set) -> (confidence, flags)
  eval.py          oof_eval() -> {blended_mape, real_only_mape, coverage, ...}; writes reports
  predict_cli.py   batch predict -> predictions/predictions.csv ; single predict (stdin JSON) for sidecar
  infer_service.py FastAPI sidecar: POST /infer {booking} -> {lo,hi,mid,confidence,coverage,uncertainties}
api/ (Rails app)   /pricing-estimate -> validate -> bearer auth -> call sidecar -> Appendix A response
integration/sign_and_post.py  HMAC sign + POST one tagged booking to staging; log to staging_bookings.log
tests/             pytest (model/eval/confidence) + rails request specs + integration probe tests
```
Artifacts: `model/*.pkl` (trained), `data/processed/features.parquet`, `data/external/zip_acs.csv`,
`predictions/predictions.csv`, `docs/` (model_card, README pointers), `reports/eval_report.md`.

## 5. Phase plan (each phase = a workflow, gated)
- **P0 Setup**: ruby/rails install (bg), python pkg env, repo skeleton, data_load + eval harness reproducing 11.6%.
- **P1 Features**: census ACS join; scope extraction (claude_cli, cached); feature matrix.
- **P2 Model**: LightGBM quantile (lo/p50/hi), log target, monotonic constraints, blend w/ original_estimate; nested conformal; OOF eval → **must pass G1+G2**. Iterate (loop) until gates pass or budget. Vast.ai only if a heavier model is needed.
- **P3 Confidence/OOD**: calibrate; enforce thresholds; coverage check.
- **P4 API**: Rails endpoint + sidecar + auth + error parity; <2s; request specs.
- **P5 Integration**: signed probes (no write) + ONE tagged booking; log.
- **P6 Deliverables**: predictions.csv; README, modeling doc/model card, deployment guide, AI_USAGE.md, ASSUMPTIONS.md, FINAL_STATUS.md; local deploy link; full test pass.

## 6. Assumptions (running list — finalize in ASSUMPTIONS.md)
- A1: Eval computed as reproduced (MAPE of midpoint vs final_price). User confirmed.
- A2: predictions.csv schema as in §0 (no destination given).
- A3: "Real-only" = labeled rows with baseline APE above a synthetic-detection threshold; exact def in ASSUMPTIONS.md.
- A4: Demo booking uses synthetic PII + real dataset ZIP, tagged `[GAUNTLET TEST]`, utm_source=gauntlet-test.
- A5: Local deploy link = http://127.0.0.1:PORT (Rails), sidecar on 127.0.0.1:PORT2.
- A6: Census ACS keyless light use; ZCTA≈ZIP crosswalk noted.
