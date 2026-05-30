# HouseAccount Pricing API — Run Guide

Rails 7.1.6 API-only app. Exposes `POST /pricing-estimate` (and the Netlify alias
`POST /.netlify/functions/pricing-estimate`), authenticates via Bearer token, and
proxies validated bookings to the Python inference sidecar.

---

## Prerequisites

- Ruby 3.0.2
- Bundler (ships with Ruby; or `gem install bundler`)
- Python sidecar running on `http://127.0.0.1:8011` (see `src/houseprice/infer_service.py`)
- A `.env` file at the **project root** (`../` relative to this directory) with:

```
GAUNTLET_PRICING_SECRET=<your-secret>
SIDECAR_URL=http://127.0.0.1:8011/infer   # optional, this is the default
```

---

## Install dependencies

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"

cd api/
bundle install
```

---

## Run the server (port 3000)

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"

cd api/
bin/rails server -p 3000
```

The server reads `GAUNTLET_PRICING_SECRET` and `SIDECAR_URL` from the project-root
`.env` file via `dotenv-rails` (loaded automatically in development mode).

The app will raise at boot if `GAUNTLET_PRICING_SECRET` is unset (outside test mode).

---

## Run tests

```bash
export GEM_HOME="$HOME/.gem"
export PATH="$HOME/.gem/bin:$PATH"

cd api/
bundle exec rspec
```

Tests stub the sidecar HTTP call via WebMock — no running sidecar required.

---

## Example request

```bash
curl -s -X POST http://127.0.0.1:3000/pricing-estimate \
  -H "Authorization: Bearer $GAUNTLET_PRICING_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "abc123",
    "service_category": "Plumbing",
    "zip_code": "78704",
    "job_description": "Replace kitchen faucet"
  }' | jq .
```

Expected response shape:

```json
{
  "ok": true,
  "job_id": "abc123",
  "estimate_lo": 120.0,
  "estimate_hi": 200.0,
  "estimate_midpoint": 160.0,
  "confidence": 0.82,
  "model_version": "gauntlet-v1.0.0"
}
```

---

## Netlify alias

The same endpoint is also available at:

```
POST /.netlify/functions/pricing-estimate
```

---

## Error reference

| Status | Body | Trigger |
|--------|------|---------|
| 401 | `{"error":"Unauthorized"}` | Missing or wrong Bearer token |
| 400 | `{"error":"Malformed JSON"}` | Unparseable request body |
| 400 | `{"error":"<field> required"}` | Missing/blank required field |
| 405 | `{"error":"Method not allowed"}` | Non-POST request |
| 500 | `{"error":"inference unavailable"}` | Sidecar unreachable or timed out |
| 500 | `{"error":"<short reason>"}` | Other internal failure |
