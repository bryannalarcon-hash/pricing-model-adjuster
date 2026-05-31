# Design Brief — HouseAccount Pricing Dashboard (Demo)

**For:** a designer drafting visual mockups.
**What this is:** a single-page web dashboard that demos the HouseAccount AI pricing model — a homeowner/operator pastes or uploads a booking, the app returns a price estimate with a confidence interval, and a results panel shows the model beating the old pricing baseline. Every prediction is produced by the real pricing API.
**Goal of the mocks:** show what each view and each on-screen state looks like, polished enough to record a short demo walkthrough against.

> Note for rendered UI: use the human-readable labels in this doc. Never surface internal flag keys (e.g. show "Outside production category", not a raw code) in anything a viewer reads.

---

## Image seed (art direction)

Paste-ready seed prompt for an image/mock generator (v0, Nano Banana, Midjourney, Figma AI, etc.). **Fixed seed: `74532`** (reuse it across page generations for a consistent look).

> **Seed prompt:** "Clean, trustworthy SaaS pricing dashboard for a home-services marketplace. Light theme, generous white space, one calm accent color (deep teal or trust-blue) with a warm secondary (amber) reserved for confidence/warning. Modern geometric sans-serif (Inter/Geist vibe). Data-forward but friendly — rounded 8–12px cards with soft shadows, not flat. A single page with a sticky top header (product name + live API status dot) and three clearly separated work areas. Financial-grade clarity: large legible numbers, a horizontal confidence interval bar, a circular/segmented confidence meter. Feels like Stripe or Linear dashboards meet a home-services brand. Desktop-first, 1440px. Calm, confident, no clutter."

**Mood:** confident, calm, legible. The emotional job is *trust* — homeowners and providers believe the price.
**Avoid:** dark dramatic themes, dense enterprise tables with no breathing room, playful/cartoonish styling, loud gradients.

---

## Global shell (present on every view)

- **Top header (sticky):** product name/logo lockup ("HouseAccount Pricing"), a **live API status indicator** (green dot "API connected" / red "API offline"), and the active **model version** badge (e.g. `gauntlet-v2.1.0`).
- **Primary navigation:** three tabs/segments — **Predict**, **Batch**, **Results** (the three views below). Single-page; switching tabs swaps the work area, header persists.
- **Footer (quiet):** model version, a one-line "leakage-free out-of-fold metrics" disclaimer link.
- **Responsive:** desktop-first (1440px primary). Tablet (768px) acceptable; mobile is out of scope for the demo.

---

## Views (the "pages")

### View 1 — Predict (single booking)
**Purpose:** paste or compose one booking, get one prediction. The hero "it works" moment.

**Features:**
- A **JSON input editor** (multiline, monospace) accepting the booking payload (job category, ZIP, description, optional original estimate, etc.).
- A **"Load sample" control** that prefills a realistic booking (for one-click demoing).
- A **Predict button** (primary action).
- A **result card** showing: the **estimate interval** (low → midpoint → high) as a horizontal bar with the midpoint marked; a **confidence meter** (0–100%, color-shifts: green high, amber mid, red low); and an **"uncertainties / why it might vary"** list (plain-language flags — e.g. "Large job outside typical range", "Scope ambiguous from description", "Outside production category", "Unlike anything in training data").
- A **low-confidence banner** inside the card when confidence < 0.5 (amber), making the out-of-distribution signal unmistakable.

**States:** Default (empty editor + sample hint) · Sample-loaded · Loading ("Predicting…", button spinner) · Success (result card) · Validation error (inline, e.g. "zip_code required") · Auth/Server error (toast) · **Rate-limited** (toast: "Rate limit exceeded — retry in 60s").

### View 2 — Batch (CSV → predictions)
**Purpose:** upload a CSV of bookings, watch them convert to the API's JSON shape, and score them in bulk.

**Features:**
- A **file dropzone / upload** for CSV.
- A **"converted JSON" preview** — shows the CSV transformed into the request payload array, so the conversion is visible.
- A **"Run batch" button** with a **progress indicator** (e.g. "12 / 40 scored").
- A **results table:** one row per booking — inputs (category, ZIP, short description) → estimate low/mid/high → confidence (mini meter or %). Rows that fail validation are **flagged inline** (a warning chip) without stopping the batch.
- **Row interaction:** clicking a row opens a detail overlay (see Overlays).
- An **export/download** affordance for the scored table (nice-to-have).

**States:** Empty (dropzone prompt) · File parsed (JSON preview shown) · Scoring (progress) · Complete (full table) · Partial-with-errors (table + flagged rows + a summary "38 scored, 2 skipped") · Upload error ("Couldn't parse CSV").

### View 3 — Results / Metrics ("see changes")
**Purpose:** prove the model beats the old baseline, at a glance.

**Features:**
- **Headline metric stat-cards:** Blended MAPE (model vs baseline), Real-only MAPE (model vs baseline), Interval coverage — each with a **pass/fail check** and the delta vs baseline.
- A **comparison chart** (grouped bars: model vs baseline for each MAPE; or a simple before/after).
- A **predictions table/scatter** showing the model's estimates across the dataset (the "changes" the model makes), with confidence encoded (color/size).
- A clear **"leakage-free out-of-fold"** caption so the numbers read as honest.

**States:** Loading (skeleton cards) · Loaded (cards + chart + table) · Data-unavailable (graceful "metrics not generated yet — run training" message).

---

## Overlays / windows that spawn over the page

Yes — the app spawns overlays. Inventory:

- **Result detail drawer (Batch):** clicking a results row slides in a right-hand drawer with that booking's full prediction — interval bar, confidence meter, and the uncertainties/flags list. Dismiss by clicking out or an X.
- **Toast notifications (transient, top-right):** API errors (401 Unauthorized, 500 inference unavailable), **rate-limit (429)** with the 60-second retry note, and success confirmations (e.g. "Batch complete"). Auto-dismiss + manual close.
- **CSV conversion preview:** rendered inline in the Batch view by default; if space is tight, may be a modal showing the converted JSON. Designer's call — provide both an inline and a modal variant.
- **Confidence/flag tooltip:** hovering the confidence meter or a flag chip shows a short explanation popover.
- **Chart tooltips (Results):** hovering a bar/point shows the exact metric value.
- **(Optional) "About this estimate" modal:** explains how the interval + confidence are produced, for the demo narrative.

No full-screen blocking modals are required for the core flow — prefer inline cards + a side drawer + toasts. Provide the overlay set so the demo can show the app responding to errors and detail-drilling.

---

## Page-state matrix (mock every cell)

| View | Default / Empty | Loading | Success | Error |
|---|---|---|---|---|
| Predict | empty editor + "Load sample" | "Predicting…" spinner | result card (interval + confidence + flags) | inline validation; toast for auth/500/429 |
| Batch | dropzone prompt | progress "n / N" | results table (+ row drawer) | flagged rows; "couldn't parse" |
| Results | skeleton | skeleton cards | stat-cards + chart + table | "metrics unavailable" |

Also mock these cross-cutting states: **API offline** (header red dot + a banner), **low-confidence / out-of-distribution** result (amber emphasis), and **rate-limited** (429 toast).

---

## Reusable components (build a small kit)

- **Estimate interval bar** — low → midpoint → high, midpoint emphasized, USD labels.
- **Confidence meter** — 0–100%, color by band (≥80 green "obvious", 50–79 amber "ambiguous", <50 red "guess").
- **Uncertainty/flag chip** — short plain-language label + tooltip.
- **Metric stat-card** — big number, baseline comparison, pass/fail check.
- **Results table row** — compact, with mini confidence indicator + warning chip for failed rows.
- **File dropzone** + **JSON code block** (monospace, syntax-tinted).
- **Toast** + **side drawer** + **tooltip/popover** primitives.

---

## The data the UI displays (so numbers in mocks are realistic)

- Per prediction: `estimate_lo`, `estimate_midpoint`, `estimate_hi` (USD), `confidence` (0–1 → show as %), `model_version`, and a list of plain-language uncertainty reasons.
- Realistic sample: Plumbing, ~$120–$200 range, midpoint ~$160, confidence ~0.82. A low-confidence example: a $7,000 remodel, wide interval, confidence ~0.19, flagged "Large job outside typical range".
- Results metrics (real): Blended MAPE **10.5%** vs baseline 11.6%; Real-only MAPE **26.2%** vs baseline 36.8%; coverage **83%**. All passing.

---

## Out of scope for the mocks
- User accounts / login screens (single shared API auth, handled server-side).
- Mobile-first layouts (desktop demo).
- Editing the model or data from the UI; settings/admin screens.
- Multi-page routing — this is one page with three tabbed views + overlays.
