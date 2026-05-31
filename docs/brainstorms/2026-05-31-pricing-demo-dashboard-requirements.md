---
date: 2026-05-31
topic: pricing-demo-dashboard
---

# Pricing Demo Dashboard — Requirements

## Summary

A presentable, single-page demo dashboard that wraps the deployed pricing model and proves it works end-to-end. Built as a **static SPA served same-origin by the Rails app**, it offers three panels: paste a booking as JSON and get a live prediction; upload a CSV, see it converted to the API's JSON, and batch-predict it; and a results panel showing the model correcting the `original_estimate` and beating baseline. Every prediction routes through the real Appendix A endpoint (`POST /pricing-estimate`) — the dashboard demonstrates the actual serving path, not a side-loaded model.

## Problem Frame

The model (`gauntlet-v2.1.0`) works and passes its gates, but the only ways to exercise it today are `curl`, pytest, and the raw `predictions.csv`. There is nothing **presentable** — no way to show, in a demo, that a booking goes in and a calibrated estimate + confidence comes out, that a CSV of bookings can be scored in bulk, or that the aggregate result beats the existing estimate. This dashboard is the "proof it works" deliverable: a surface a presenter can drive in front of an evaluator to see single predictions, batch conversion/scoring, and the headline metrics, all against the live API.

## Key Decisions

- **Static SPA served by Rails, not a separate app (see origin dialogue).** Same-origin serving avoids CORS and keeps it production-like; the tradeoff is hand-built charts/CSS vs. a batteries-included tool like Streamlit.
- **Predictions go through the live Rails endpoint, not the model bundle.** "All this works" means the real Appendix A contract — request in, `estimate_lo/midpoint/hi` + `confidence` + uncertainties out.
- **Browser auth never exposes the prod secret.** A dev-only proxy route (or a server-injected token) performs the Bearer auth server-side; `GAUNTLET_PRICING_SECRET` is never present in client JS.
- **Metrics panel displays committed OOF artifacts, not a live recompute.** It reads `reports/eval_report.md` + `predictions/predictions.csv` and labels them as leakage-free OOF — honest and simple.
- **CSV batch loops the single endpoint client-side (concurrency-capped); no new batch API.** Fine for demo volumes; avoids expanding the API surface.

## Requirements

**Serving & auth**

- R1. The dashboard is a static SPA served same-origin by the Rails app (no separate server, no CORS).
- R2. Every prediction is produced by POSTing to the live `POST /pricing-estimate` (Appendix A), not by importing the model bundle.
- R3. The browser authenticates without exposing the production bearer secret: a dev-only proxy route (or server-injected token) handles auth server-side; `GAUNTLET_PRICING_SECRET` never appears in client-delivered JS/HTML.

**Single prediction (paste JSON)**

- R4. A JSON text area accepts a booking payload in the Appendix A request shape; a predict action POSTs it and renders `estimate_lo` / `estimate_midpoint` / `estimate_hi`, `confidence`, and the uncertainties / OOD flags.
- R5. Malformed JSON or a non-2xx response surfaces a clear inline error (echoing the API's 400/401 message), not a silent failure or crash.
- R6. A prefilled sample booking is available so a presenter can demo a prediction in one click.

**CSV → JSON batch**

- R7. A CSV uploader parses client-side and shows the converted JSON array, so the CSV→JSON transform is visible to the viewer.
- R8. A batch-predict action loops the single endpoint with a small concurrency cap and renders a per-row results table (inputs → `lo`/`midpoint`/`hi`/`confidence`).
- R9. Rows that fail validation (bad/missing fields) are flagged in the table without aborting the rest of the batch.

**Results / "see changes" panel**

- R10. A metrics panel shows the model vs baseline at a glance — blended MAPE, real-only MAPE, and interval coverage — with pass/fail against the baselines (sourced from `reports/eval_report.md`).
- R11. A predictions view (table and/or chart) shows the model's correction of `original_estimate` per booking (sourced from `predictions/predictions.csv`), so "see changes" = how each estimate was adjusted.
- R12. The panel reads the committed OOF artifacts (no live recompute) and labels the numbers as leakage-free out-of-fold.

**Presentation**

- R13. The page is presentable and demo-grade: the three panels are legible together on one screen with clean, intentional styling.

## Key Flows

- F1. **Single prediction.** **Trigger:** presenter pastes (or loads the sample) booking JSON and clicks predict. **Steps:** SPA POSTs to the live endpoint via the dev proxy → renders lo/mid/hi, confidence, uncertainties. **Covered by:** R2, R4, R5, R6.
- F2. **CSV batch.** **Trigger:** presenter uploads a CSV of bookings. **Steps:** parse client-side → show converted JSON array → batch POST (concurrency-capped) → per-row results table, bad rows flagged. **Covered by:** R7, R8, R9.
- F3. **Results / metrics.** **Trigger:** dashboard loads or presenter opens the results panel. **Steps:** read `eval_report.md` + `predictions.csv` → render metrics vs baseline + the estimate-correction view. **Covered by:** R10, R11, R12.

## Acceptance Examples

- AE1. **Covers R5.** Pasting malformed JSON shows an inline parse error and the predict button does not fire a request; pasting a valid payload that the API rejects (e.g. 401) shows the API's error message.
- AE2. **Covers R3.** Viewing page source / network calls reveals no `GAUNTLET_PRICING_SECRET` value in any client-delivered asset.
- AE3. **Covers R8, R9.** A 20-row CSV with one malformed row yields 19 predictions in the table and 1 flagged row; requests run with the concurrency cap, not 20 at once.
- AE4. **Covers R2.** A prediction shown in the UI matches the response from `curl`-ing `POST /pricing-estimate` directly with the same payload — proving the UI uses the live path.

## Success Criteria

- All three capabilities (single predict, CSV batch convert+score, metrics view) demonstrably work against the running stack (Rails `:3007` + FastAPI sidecar `:8011`).
- No secret is present in client-delivered code; every prediction goes through the real API.
- The metrics panel reproduces the numbers in `reports/eval_report.md` (blended/real-only MAPE, coverage) against baseline.
- The dashboard is presentable on a single screen without further styling work to demo it.

## Scope Boundaries

**Deferred for later**
- Railway (or any remote) deployment of the dashboard — local demo first.
- A real server-side batch prediction endpoint.
- Persistence/history of past predictions; export of results.

**Outside this effort's identity**
- User accounts, multi-tenant auth, or a production ops console.
- Editing the model, data, or config from the UI; live retraining.
- The model-improvement avenues (separate paused brainstorm/plan).

## Dependencies / Assumptions

- The Rails API (`:3007`) and FastAPI sidecar (`:8011`) are running, and `predictions/predictions.csv` + `reports/eval_report.md` exist (regenerated by `src/houseprice/train.py`).
- The Rails app is currently API-only; a small serving shim is needed to deliver the static SPA (static files under `api/public/` or a minimal view/controller route) plus the dev-only auth-proxy route.
- CSV column mapping: the uploaded CSV's columns map to the Appendix A booking fields (`job_description`, `service_category`, `zip_code`, optional `original_estimate`, etc.); the converter maps columns → request JSON and handles missing/optional fields.
- Demo runs on a trusted local machine, so a dev-only auth proxy / injected token is acceptable; it is explicitly not a production auth design.

## Outstanding Questions

**Resolve before planning** — none blocking; scope and the two auth/batch call-outs are settled.

**Deferred to planning**
- Charting approach (a CDN charting lib vs. hand-drawn) and CSV parsing approach (a small lib vs. hand-rolled).
- Where the dev auth-proxy / token injection lives in the Rails app, and whether the SPA is served from `api/public/` or a controller view.
- CSV column-mapping UX: auto-map by header name vs. a manual mapping step.

## Sources / Research

- `assignment_description.md` — Appendix A request/response contract and auth semantics (the API the SPA calls).
- `api/app/controllers/pricing_estimate_controller.rb` — the live endpoint + Bearer auth (constant-time compare).
- `src/houseprice/infer_service.py` — the FastAPI sidecar the Rails controller proxies to.
- `predictions/predictions.csv`, `reports/eval_report.md` — data sources for the metrics / correction panel.
