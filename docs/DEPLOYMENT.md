# Deployment Guide — HouseAccount AI Pricing Model

Local deployment for development and evaluation. The system runs as two processes: a Rails 7.1.6 API server and a Python FastAPI sidecar. They communicate over localhost only.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | Must be on PATH as `python3` |
| Ruby | 3.0.2 | See below if not installed |
| Bundler | any recent | Ships with Ruby 3; or `gem install bundler` |
| pip | any recent | For Python dependencies |

Port 3000 is assumed to be occupied by another local app. The Rails server runs on **3007**. If port 3007 is also taken, change the `-p` flag in the Rails start command.

## Environment variables

Copy `.env.example` to `.env` at the project root and fill in values before starting any process. The `.env` file is gitignored and must never be committed.

```bash
cp .env.example .env
```

Variables:

| Variable | Required for | Description |
|---|---|---|
| `GAUNTLET_PRICING_SECRET` | Rails API | Bearer token for `POST /pricing-estimate`. Choose any non-empty string for local use. |
| `HOUSEACCOUNT_APP_NAME` | Staging integration | Partner identity header. Default value `gauntlet` is already set in `.env.example`. |
| `HOUSEACCOUNT_SIGNING_KEY` | Staging integration | HMAC signing key issued by HouseAccount. Required only for `sign_and_post.py`. |
| `VAST_API_KEY` | Optional | Vast.ai GPU compute. Not needed for local training or inference. |
| `CENSUS_API_KEY` | Optional | Census ACS enrichment. The pipeline falls back gracefully when absent. |
| `ANTHROPIC_API_KEY` | Optional | Required only for `SCOPE_BACKEND=anthropic_api`. The default `deterministic` backend needs no key. |

`SIDECAR_URL` defaults to `http://127.0.0.1:8011/infer` and does not need to be set unless you run the sidecar on a different port.

## Full local bring-up

The system requires three terminals running concurrently. Steps 1-3 are one-time setup; steps 4-6 are the three long-running processes.

### One-time setup

**Step 1 — Install Python dependencies**

```bash
# From the repository root
pip install -r requirements.txt
```

**Step 2 — Train the model**

Training reads `data/raw/houseaccount_pricing_sample.csv` and writes three artifacts:

```bash
PYTHONPATH=src python3 -m houseprice.train
```

Expected output ends with lines like:
```
saved model/bundle.pkl, predictions/predictions.csv, reports/eval_report.md
```

Training takes ~30 seconds on a laptop. Do not skip this step; the sidecar will fail to start without `model/bundle.pkl`.

**Step 3 — Install Ruby gems**

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"
cd api && bundle install
```

### Three-terminal startup

Open three terminal windows in the project root.

**Terminal 1 — Python inference sidecar**

```bash
PYTHONPATH=src python3 -m uvicorn houseprice.infer_service:app --host 127.0.0.1 --port 8011
```

Wait for the line `Application startup complete.` before starting terminal 2.

**Terminal 2 — Rails API server**

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"
cd api && bin/rails server -p 3007 -b 127.0.0.1
```

Wait for `Listening on http://127.0.0.1:3007` before making requests.

**Terminal 3 — send a test request**

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
  }' | python3 -m json.tool
```

A successful response looks like:

```json
{
  "ok": true,
  "job_id": "x",
  "estimate_lo": 1423.50,
  "estimate_hi": 2187.30,
  "estimate_midpoint": 1780.40,
  "confidence": 0.78,
  "model_version": "gauntlet-v1.0.0"
}
```

## Health checks

Sidecar health (does not require Rails):

```bash
curl -s http://127.0.0.1:8011/health | python3 -m json.tool
```

Expected response:

```json
{
  "ok": true,
  "model_version": "gauntlet-v1.0.0",
  "scope_backend": "deterministic",
  "trained_rows": 411
}
```

Rails liveness: any request to the endpoint with a valid Bearer token returns a 200 (or 400 for missing fields). A 500 with `"inference unavailable"` means the sidecar is not running.

## Running against the staging endpoint

The `integration/sign_and_post.py` script handles HMAC-signed requests to the HouseAccount staging API. Requires `HOUSEACCOUNT_APP_NAME` and `HOUSEACCOUNT_SIGNING_KEY` to be set in `.env`.

**Probe (zero-write auth check) — run this first**

Sends a correctly-signed but intentionally invalid body. Expects HTTP 422 (auth accepted, validation failed) and confirms that a bad signature is rejected with 401. Nothing is created.

```bash
python3 integration/sign_and_post.py --probe
```

Healthy output:
```
[probe] HTTP 422 (auth OK): ...
[probe] bad-sig HTTP 401 (expect 401): ...
[probe] healthy
```

**Post one tagged staging booking**

Creates exactly one booking tagged `[GAUNTLET TEST]` with synthetic PII and a real dataset ZIP. The booking ID is appended to `staging_bookings.log`. Run this at most once per evaluation cycle.

```bash
python3 integration/sign_and_post.py --post
```

The staging API has no GET or DELETE endpoints. Writes are minimal by design.

## Optional scope enrichment before retraining

Run LLM-powered scope extraction to enrich `job_description` features, then retrain:

```bash
SCOPE_BACKEND=claude_cli python3 scripts/extract_scope.py
PYTHONPATH=src python3 -m houseprice.train
```

The `deterministic` backend (default) requires no API key and is the production-safe fallback. The `anthropic_api` backend requires `ANTHROPIC_API_KEY`.

## Troubleshooting

**Port conflict on 3007**

Rails will refuse to start if port 3007 is occupied. Find the process and kill it, or change the port:

```bash
lsof -ti:3007 | xargs kill -9          # kill whatever holds 3007
# or start Rails on a different port:
bin/rails server -p 3008 -b 127.0.0.1
```

**Port conflict on 3000**

The project deliberately avoids port 3000 (assumed occupied). If you see another Rails process defaulting to 3000, always start this app explicitly with `-p 3007`.

**Sidecar not running — 500 from Rails**

If the Rails endpoint returns `{"error":"inference unavailable"}`, the sidecar in terminal 1 is not running or crashed. Check terminal 1 for errors, then restart it. The most common cause is a missing `model/bundle.pkl` — run the training step first.

**`model/bundle.pkl` not found**

The sidecar raises `FileNotFoundError` at startup if training has not been run. Run:

```bash
PYTHONPATH=src python3 -m houseprice.train
```

**Rails raises at boot: `GAUNTLET_PRICING_SECRET` unset**

The app requires this variable outside test mode. Ensure `.env` exists at the project root (one level above `api/`) and contains a non-empty value.

**`bundle install` fails — wrong Ruby version**

Ruby 3.0.2 is required. Check your version with `ruby --version`. If it is wrong, use `rbenv` or `rvm` to install 3.0.2, or run `scripts/install_ruby.sh` if present.

**`pip install` errors on LightGBM or XGBoost**

Both packages require a C compiler. On Ubuntu/Debian: `sudo apt-get install build-essential`. On macOS: `xcode-select --install`.

## Railway deployment (deferred)

Cloud deployment is deferred beyond the current evaluation window. When ready, the two-process architecture maps naturally to two Railway services:

- **sidecar service** — Python container running `uvicorn houseprice.infer_service:app --host 0.0.0.0 --port 8011`. `model/bundle.pkl` must be included in the image or fetched from Railway volume storage.
- **rails service** — Ruby container running `bin/rails server`. Set `SIDECAR_URL` to the internal Railway URL of the sidecar service.

Both services need the env vars from the `.env` template injected as Railway environment variables. The `GAUNTLET_PRICING_SECRET` and `HOUSEACCOUNT_SIGNING_KEY` values should be set as secrets, not plaintext config.
