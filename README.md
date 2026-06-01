# HouseAccount AI Pricing Model

An AI-powered pricing engine for home-service bookings. Given a booking request (service category, ZIP code, job description, and an optional existing estimate), the model returns a calibrated price interval (`estimate_lo` / `estimate_hi`), a midpoint, and a confidence score in [0, 1]. The model beats both MAPE baselines using leakage-free out-of-fold evaluation on 411 labeled rows from the HouseAccount dataset.

**▶ 5-minute demo video:** <https://youtu.be/2FHjLjmG8Q4>

## Model performance

Model version: `gauntlet-v2.1.0`.

| Metric | Model | Baseline | Status |
|---|---|---|---|
| Blended MAPE (all 411 labeled rows) | 10.49% | 11.56% | Pass |
| Real-only MAPE (n=49, rows where base APE > 20%) | 26.22% | 36.75% | Pass |
| Interval coverage (target 80%) | 82.7% | — | Pass |

Evaluation is leakage-free: every labeled row is scored by a model trained without it (5-fold OOF). Conformal calibration is nested inside each fold.

## Architecture

```
Booking request (JSON)
        |
        v
Rails API (port 3007)          -- bearer auth, input validation, Appendix A response shape
        |
        v
FastAPI sidecar (port 8011)    -- loads model/bundle.pkl, runs inference
        |
        v
LightGBM L2 loss on log-residual + normalized cross-conformal intervals
  target: log(final_price / original_estimate)
  point model: L2 loss, MAPE-aligned weights 1/final_price^0.5, trained on all labeled data
  interval: normalized (adaptive) cross-conformal quantile regression (~82% coverage)
  confidence: data-density-aware + OOD-gated score in [0,1]
  scope: deterministic features only (ZIP removed per ablation) (scope-free deployment)
```

Three clean layers with no cross-layer coupling:

- **Data layer** — `src/houseprice/data_load.py`: loads and normalizes `data/raw/houseaccount_pricing_sample.csv`
- **Model layer** — `src/houseprice/{features,scope,model,confidence,predict,train}.py` + `infer_service.py` (FastAPI sidecar on `127.0.0.1:8011`)
- **API layer** — `api/` (Rails 7.1.6, API-only) on `127.0.0.1:3007`: authenticates, validates, proxies to sidecar

## Quickstart

### Fastest: one command

```bash
./scripts/up.sh
```

Brings up the entire local stack with a single command. **It will:**

- install Python deps + Rails gems if they're missing, and create `.env` from `.env.example` if absent
- start the Python model **sidecar** on `http://127.0.0.1:8011`
- start the **Rails API + dashboard** on `http://127.0.0.1:3007` (dashboard at `/`)

**Safety:** `BOOKING_LIVE` is force-unset, so bookings are **simulated** — nothing is posted to the real staging endpoint. **Press Ctrl-C to stop both services.** The first run installs dependencies (~a minute); later runs start in seconds.

> Prerequisites: Python 3.10+, and Ruby 3.0.2 with **Bundler 2.5.23** (`gem install bundler -v 2.5.23` — it matches `Gemfile.lock`; the older Bundler that ships with Ruby 3.0's default RubyGems mis-resolves the `tsort` gem and breaks `bundle exec`). If `bundle` isn't on your `PATH`, the script falls back to the `~/.gem` convention used in the manual steps below.

### Manual / step-by-step

The same bring-up by hand — useful for understanding the moving parts or debugging. These five steps take a freshly cloned repository to a working local endpoint.

**1. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**2. Train the model — _optional_**

The trained artifact `model/bundle.pkl` **is committed to this repo**, so you can skip straight to step 3 and run inference immediately — no dataset required. Retrain only if you have the dataset and want to reproduce the result:

```bash
# requires data/raw/houseaccount_pricing_sample.csv (the proprietary dataset, not committed)
PYTHONPATH=src python3 -m houseprice.train deterministic
```

Retraining rewrites `model/bundle.pkl`, `predictions/predictions.csv`, `reports/eval_report.md`, and `reports/eval_metrics.json`. Takes under a minute on a laptop CPU.

**3. Start the Python inference sidecar (terminal 1)**

```bash
PYTHONPATH=src python3 -m uvicorn houseprice.infer_service:app --host 127.0.0.1 --port 8011
```

**4. Copy `.env.example` to `.env` and fill in the secrets** (see [Environment variables](#environment-variables))

```bash
cp .env.example .env
# edit .env: set GAUNTLET_PRICING_SECRET to any non-empty string for local use.
# For the staging booking integration you also need HOUSEACCOUNT_SIGNING_KEY (below).
```

**5. Start the Rails API (terminal 2)**

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"
cd api && bundle install && bin/rails server -p 3007 -b 127.0.0.1
```

The endpoint is now live at `http://127.0.0.1:3007/pricing-estimate`, and the **demo dashboard** at **`http://127.0.0.1:3007/`** (see [Dashboard](#dashboard)).

## Environment variables

Copy `.env.example` → `.env`. Two of these are **issued by HouseAccount** and must be supplied to exercise the live staging integration:

| Variable | Who sets it | Purpose |
|---|---|---|
| `GAUNTLET_PRICING_SECRET` | You (any non-empty string locally) | Bearer token for `POST /pricing-estimate` (Appendix A auth). The same value is also injected server-side by the dashboard proxy. |
| `HOUSEACCOUNT_SIGNING_KEY` | **HouseAccount-issued** | HMAC key for signing requests to the staging booking API (`App-Signature = HMAC-SHA256(timestamp + "." + body)`). Required by `integration/sign_and_post.py`. **Not committed — request it from HouseAccount.** |
| `HOUSEACCOUNT_APP_NAME` | Pre-set to `gauntlet` | Partner identity sent as the `App-Name` header to staging. Change only if HouseAccount issues a different name. |
| `BOOKING_LIVE` | You (demo only) | Gates the dashboard's "send to booking flow". When `1`, sends are **real** HMAC-signed tagged bookings POSTed to HouseAccount staging. **Default off → every send is simulated and recorded locally only** (no staging writes), so tests and casual runs never create bookings. Set `1` only for a live demo. |
| `VAST_API_KEY` | Optional | Unused at runtime; present for optional GPU experiments. |

The pricing model + dashboard run with only `GAUNTLET_PRICING_SECRET`. `HOUSEACCOUNT_SIGNING_KEY` + `HOUSEACCOUNT_APP_NAME` are needed **only** to post bookings to the HouseAccount staging endpoint via `integration/sign_and_post.py`.

## Dashboard

A single-page demo dashboard is served same-origin by the Rails app at **`http://127.0.0.1:3007/`**:

- **Predict** — paste a booking as JSON (or load the sample) and see the estimate interval, confidence, and out-of-distribution flags. Sample payloads: `examples/sample_payloads.md`.
- **Batch** — upload a CSV of bookings; it converts to the API's JSON shape and scores each row. Sample: `examples/sample_bookings.csv`.
- **Results** — the model-vs-baseline MAPE/coverage metrics and the per-row predictions.

Every prediction is forwarded server-side to the real `POST /pricing-estimate` (with the bearer injected by the proxy, so no secret reaches the browser). The Results panel reads the committed `reports/eval_metrics.json` and `predictions/predictions.csv`, so it works even without the dataset.

## Example request and response

```bash
curl -s -X POST http://127.0.0.1:3007/pricing-estimate \
  -H "Authorization: Bearer $GAUNTLET_PRICING_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "x",
    "service_category": "Plumbing",
    "zip_code": "78704",
    "job_description": "50-gallon gas water heater replacement",
    "original_estimate": 1850,
    "original_estimate_lo": 1400,
    "original_estimate_hi": 2300
  }'
```

Response:

```json
{
  "ok": true,
  "job_id": "x",
  "estimate_lo": 1423.50,
  "estimate_hi": 2187.30,
  "estimate_midpoint": 1780.40,
  "confidence": 0.78,
  "model_version": "gauntlet-v2.1.0"
}
```

The same endpoint is aliased at `POST /.netlify/functions/pricing-estimate`.

### Error responses

| Status | Body | Trigger |
|---|---|---|
| 401 | `{"error":"Unauthorized"}` | Missing or wrong Bearer token |
| 400 | `{"error":"Malformed JSON"}` | Unparseable body |
| 400 | `{"error":"<field> required"}` | Missing required field |
| 405 | `{"error":"Method not allowed"}` | Non-POST request |
| 500 | `{"error":"inference unavailable"}` | Sidecar unreachable or timed out |

## Deliverables

| Deliverable | Where it lives in this repo |
|---|---|
| **Source code** | **Model** — `src/houseprice/` (`train.py`, `model_v2.py`, `confidence.py`, `predict.py`, `infer_service.py`, `data_load.py`, `features.py`, `scope.py`, …) + `model/bundle.pkl`. **Rails API + dashboard** — `api/app/**` (controllers, services, concerns), `api/config/**`, `api/public/dashboard/{index.html,app.js,styles.css}`. **Integration** — `integration/sign_and_post.py`. **Build** — `Dockerfile`, `api/Dockerfile`, `requirements.txt`. **Research/experiments** — `experiments/*.py` |
| **Technical documentation** | `MODELING.md` (model card: data, training, confidence) · `JOURNAL.md` (research journal) · `ASSUMPTIONS.md` · `docs/BUILD_PLAN.md` · `docs/design/` (brief + screenshots) · this `README.md` |
| **Demo video** | [youtu.be/2FHjLjmG8Q4](https://youtu.be/2FHjLjmG8Q4) — 5-minute walkthrough |
| **Deployment guide** | `docs/DEPLOYMENT.md` · `scripts/up.sh` (one-command bring-up) · the [Quickstart](#quickstart) above · `Dockerfile` / `api/Dockerfile` · `.env.example` |
| **Test results** | **Tests** — `tests/` (21 pytest + 14 Playwright e2e), `api/spec/requests/` (42 RSpec). **Outputs** — `reports/eval_report.md`, `reports/eval_metrics.json`, `predictions/predictions.csv` (leakage-free OOF) |
| **AI usage log** | `AI_USAGE.md` (logging tooling: `scripts/prompt_logger.py`) |

## Project layout

```
.
├── api/                          Rails 7.1.6 API-only app
│   ├── app/controllers/          PricingEstimateController
│   └── spec/requests/            42 RSpec request specs
├── data/
│   └── raw/houseaccount_pricing_sample.csv   source data (1,432 rows, 411 labeled)
├── docs/
│   ├── BUILD_PLAN.md             architecture decisions and phase plan
│   ├── DEPLOYMENT.md             full local bring-up and troubleshooting
│   └── MODELING.md               feature engineering, eval protocol, model card
├── integration/
│   └── sign_and_post.py          HMAC-signed staging probes and booking creation
├── model/
│   └── bundle.pkl                trained model artifact (generated by train)
├── predictions/
│   └── predictions.csv           OOF predictions for all 1,432 rows
├── reports/
│   └── eval_report.md            leakage-free MAPE + coverage metrics
├── scripts/
│   └── extract_scope.py          optional LLM scope enrichment before retraining
├── src/houseprice/
│   ├── data_load.py              load + normalize dataset
│   ├── features.py               build model feature matrix
│   ├── scope.py                  ScopeExtractor (deterministic / claude_cli / anthropic_api)
│   ├── model.py                  LightGBM quantile + CQR (ConformalPriceModel)
│   ├── confidence.py             OOD detection + confidence calibration
│   ├── predict.py                single-booking inference (used by sidecar and CLI)
│   ├── predict_cli.py            batch predict CLI
│   ├── train.py                  full training pipeline
│   └── infer_service.py          FastAPI sidecar (POST /infer, GET /health)
├── tests/                        21 pytest tests + 14 Playwright e2e (model logic, eval, confidence)
├── .env.example                  env var template
├── requirements.txt              Python dependencies
└── ASSUMPTIONS.md                modeling assumptions and data notes
```

## Confidence and OOD detection

The confidence score reflects how tightly the model's conformal interval constrains the price relative to the typical interval width seen during training, adjusted for how densely the booking's category is represented in training data. A score near 1.0 indicates a well-constrained, in-distribution booking from a well-covered category; near 0.0 indicates high uncertainty.

Confidence is **data-density-aware**: sparse in-production categories receive a lower confidence multiplier (floor 0.70) proportional to their label count. For example, a Plumbing booking (3 training labels) scores approximately 0.60 at the same interval width where a Cleaning booking (66 labels) scores approximately 0.82.

Three hard out-of-distribution (OOD) conditions force `confidence` below 0.5 regardless of interval width or density:

1. `estimate_midpoint` exceeds $5,000 (large job outside typical training range)
2. Prediction interval (`estimate_hi - estimate_lo`) exceeds 3x the median observed range in training data
3. `service_category` does not map to one of the 10 production verticals (electrical, exterior-cleaning, handyman, hvac, indoor-cleaning, irrigation, landscaping-lawn, pest-control, plumbing, tick-mosquito-treatment); unknown categories are correctly treated as out-of-production

The estimate itself is always returned; only the confidence score changes.

## Testing

Python tests (model logic, OOF eval, confidence/OOD, metrics emit):

```bash
python3 -m pytest tests/ -q
```

Rails request specs (API contract, auth, errors, rate limiting, dashboard proxy/metrics/predictions; the sidecar is stubbed via WebMock — no running sidecar needed):

```bash
cd api && bundle exec rspec      # 42 examples
```

End-to-end browser tests (Playwright; cover every dashboard path — predict, batch, results, error handling). Requires the stack running locally:

```bash
python3 -m pytest tests/e2e/ -q  # 14 examples
```

## Further reading

- `MODELING.md` — model card: feature engineering, leakage protocol, confidence design (root copy of `docs/MODELING.md`)
- `JOURNAL.md` — the research journal: every experiment run and why it was kept or rejected (root copy of `experiments/JOURNAL.md`)
- `docs/DEPLOYMENT.md` — full three-terminal bring-up, env vars, staging integration, troubleshooting
- `ASSUMPTIONS.md` — data assumptions, real-only subset definition, design choices
- `AI_USAGE.md` — how AI tools were used in this project
