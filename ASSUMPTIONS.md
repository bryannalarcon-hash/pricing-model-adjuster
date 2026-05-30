# Assumptions & Decisions

Every ambiguity resolved autonomously during the build, with rationale. PRD-preferred values were
chosen wherever feasible (per explicit user direction). Grouped by area.

## Stack & deployment
- **A-Stack1** API layer = **Ruby on Rails** (API-only), the PRD's strongly-preferred choice;
  satisfies must-have #4 (Rails style guide). Model layer = Python behind a FastAPI sidecar — clean
  data/model/API separation, also a PRD requirement.
- **A-Stack2** Local deployment now (user directive); Railway deferred. Rails on **127.0.0.1:3007**
  (port 3000 was occupied by another local dev server), sidecar on **127.0.0.1:8011**.
- **A-Stack3** The endpoint path: serve a clean `POST /pricing-estimate` **and** the literal
  Appendix-A path `/.netlify/functions/pricing-estimate` as an alias — covers both readings of the
  spec. The "Netlify" path is HouseAccount's internal naming; what's graded is payload/response
  shape, which Rails reproduces.

## Eval & metrics
- **A1** MAPE is computed as we reproduced it: `|midpoint − final_price| / final_price`, mean over
  rows. Our harness reproduces the official blended baseline (11.56%) exactly — user confirmed they
  computed it the same way.
- **A3** "Real-only" subset (hidden from us) is approximated as labeled rows with baseline
  `APE > 20%` (n=49, baseline MAPE 36.7% ≈ the brief's "~40%"). This is a reporting partition only;
  the model never sees it during training, so no leakage. We also spot-checked `APE>25%` (53%) and
  `APE>30%` (62%) — the model beats baseline at every threshold.
- **A-Eval1** All reported metrics and the 411 labeled rows in `predictions.csv` are **out-of-fold**
  (leakage-free). Unlabeled rows in `predictions.csv` use the full model.
- **A-Eval2** The augmented/synthetic vs real split is inferred (the brief says sparse categories
  were "augmented" but doesn't label which rows). Evidence: well-covered categories have tight
  near-midpoint `final_price` (low APE, low position variance); sparse categories are messy/real.

## Predictions submission
- **A2** No submission format was specified, so `predictions/predictions.csv` has columns:
  `job_id, service_category, estimate_lo, estimate_hi, estimate_midpoint, confidence, is_labeled,
  model_version`. Covers all 1,432 rows (411 OOF, 1,021 full-model).

## Modeling
- **A-Model1** Target = `log(final_price / original_estimate)` — model the correction to the
  existing estimate, not the absolute price. Requests without `original_estimate` (optional per
  Appendix A) are anchored to the **category-median** `original_estimate` (global median fallback).
- **A-Model2** Point estimate = median residual quantile (minimizes relative error / MAPE).
- **A-Model3** Interval target coverage = **80%** (quantiles 0.1/0.9 + CQR). Chosen as a reasonable
  default; the PRD doesn't mandate a coverage level.

## Confidence / OOD (PRD values verbatim)
- **A-Conf1** OOD conditions exactly per PRD: midpoint > $5,000; interval > 3× median observed range;
  category outside the 10 production verticals → confidence forced < 0.5 (capped at 0.45). Estimates
  are never rejected or clamped — passed through with low confidence.
- **A-Conf2** "Median observed range" = median of `estimate_hi − estimate_lo` over the full dataset
  ($230). Literal reading of the PRD; means larger jobs with naturally wide intervals can be flagged
  — intended (route for review).
- **A-Conf3** Production verticals (the 10): electrical, exterior-cleaning, handyman, hvac,
  indoor-cleaning, irrigation, landscaping-lawn, pest-control, plumbing, tick-mosquito-treatment.
  Title-case dataset categories are mapped to these; categories with no production analogue
  (Moving, Painting, Roofing, Flooring, Appliance Repair, Auto, Chimney, Exterior, General
  Contractor, Pool, Remodeling) are treated as out-of-production → lower confidence.

## Scope extraction (LLM)
- **A-Scope1** Backends: `claude_cli` for offline enrichment now; `anthropic_api` switchable via
  `ANTHROPIC_API_KEY`; `deterministic` always-available floor. The **deployed endpoint defaults to
  deterministic** (claude -p can't run on a remote host) — a documented train/serve quality gap that
  closes when an API key is configured.
- **A-Scope2** Scope is extracted per row from `job_description` only (no `final_price`) — no leakage.

## External data
- **A6** Census ACS join is **key-gated**: the Census API now requires `CENSUS_API_KEY` (verified —
  keyless requests redirect to `missing_key.html`). Without it we use self-contained ZIP-region
  features. ZIP is treated as its ZCTA when the join is enabled.

## Integration (staging bookings)
- **A4** Demo bookings use **synthetic PII** (`name: "Gauntlet Test"`, dummy phone `5555550100`), a
  **real dataset ZIP** (staging validates "ZIP must exist"), `summary` prefixed `[GAUNTLET TEST]`,
  and `campaign.utm_source: "gauntlet-test"` — clearly disposable.
- **A-Int1** Staging exposes **no GET/DELETE/dry-run**. Policy: validate connectivity via
  zero-write 422/401 probes; create **exactly one** tagged booking for the demo; log its id to
  `staging_bookings.log`. Verified HMAC recipe: `App-Signature = HMAC-SHA256(timestamp + "." + body)`
  with the signing key as raw UTF-8 string bytes; headers `App-Name`, `App-Timestamp`.
- **A-Int2** App identity `App-Name: gauntlet` (user-provided). `HOUSEACCOUNT_SIGNING_KEY` is the
  HMAC key for *calling them*; `GAUNTLET_PRICING_SECRET` is the bearer for *them calling us* — two
  separate trust boundaries, two separate secrets.

## Versioning / misc
- **A-Misc1** `model_version = "gauntlet-v1.0.0"`.
- **A-Misc2** Secrets live in `.env` (gitignored); `.env.example` documents the structure.
- **A-Misc3** A demo video is out of scope per the goal directive ("all artifacts except the demo");
  a local deployment URL is provided instead.
