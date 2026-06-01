# Research Journal — HouseAccount Pricing Model

Rigorous, looped model R&D: **research → architecture → build → test → pre/post-processing &
optimization → eval**, repeat. Every iteration logs hypothesis, change, multi-seed result, and an
adopt/reject decision with rationale.

## Protocol (overfitting discipline)
- **Primary metric:** repeated 5-fold out-of-fold MAPE, averaged over ≥8 seeds → report mean ± std.
  Separates real signal from fold-noise. Blended (all 411) + real-only (`base_ape>0.20`, n≈49).
- **Selection rule:** adopt a change only if (a) it beats the incumbent by **more than ~1 combined
  std**, AND (b) it is theoretically justified (not a seed-lucky CV artifact). Reject marginal/
  within-noise changes even if nominally lower.
- **Lockbox guard:** a fixed 20% stratified hold-out (seed 2024) never used during experimentation;
  the final chosen model is checked on it once. With ~82 rows (~10 real) it is noisy — used as a
  gross-overfit sanity check, not a precise estimate.
- **North star:** HouseAccount's hidden post-snapshot holdout. Favor robust, generalizable methods
  (proper losses, conformal calibration, ensembling) over fragile feature hacks.
- **Leakage:** every metric is OOF; conformal calibration nested; a shuffle test guards the pipeline.

## Baselines
- Old model (original_estimate midpoint): blended **11.56%**, real-only **36.75%**.
- Committed v1 (LightGBM quantile-q50 residual + CQR, 75%-data point, single seed): 11.31% / 34.54%.

## Iterations

### R1 — Loss-function sweep (residual = log(final/original), deterministic+scope features)
Hypothesis: the point-estimate loss matters; quantile-q50 may be suboptimal for MAPE.
Result (8-seed OOF):
| model | blended | real |
|---|---|---|
| lgbm_q50 (v1 loss) | 10.92 ±0.18 | 31.68 ±0.53 |
| lgbm_l1 (mae) | 10.94 ±0.18 | 31.74 ±0.53 |
| **lgbm_l2** | **10.73 ±0.15** | **27.91 ±0.43** |
| catboost_mae | 10.84 ±0.15 | 29.34 ±0.87 |
| xgb_mae | 10.80 ±0.16 | 29.55 ±0.62 |
| ensemble3 | 10.74 ±0.13 | 30.00 ±0.40 |

**Finding:** L2-on-log-residual dominates, esp. on real rows (27.9% vs 31.7%). Also: training the
point model on **all** data (not the 75% conformal split used in v1) is a free gain. **Adopt L2 as
the point loss; decouple point-model training from interval calibration.** (Both gains > noise.)

### R2 — Loss functions + MAPE-aligned sample weighting (8-seed OOF)
Hypothesis: weighting the loss by 1/final_price aligns training with MAPE (cheap jobs penalized
proportionally), and a custom |e^δ−1| objective could be MAPE-optimal.
| model | blended | real |
|---|---|---|
| **wl2_pow1** (L2, weight 1/fp) | 10.94 ±0.17 | **25.87 ±0.50** |
| **wl2_pow0.5** (L2, weight 1/√fp) | **10.74 ±0.12** | 26.99 ±0.42 |
| wl1_pow1 | 11.20 ±0.19 | 27.56 ±0.64 |
| lgbm_l2 | 10.73 ±0.15 | 27.91 ±0.43 |
| lgbm_huber | 10.72 ±0.15 | 27.94 ±0.39 |
| mape_obj (custom |e^δ−1|) | 14.36 ±0.40 | 28.18 — **unstable, reject** |
| lgbm_fair | 10.71 ±0.12 | 28.57 ±0.40 |

**Findings:** (1) **MAPE-aligned weighting (1/fp^p) is a strong lever for real-only** — pow=1 best
on real (25.9%) but costs blended; **pow=0.5 is the sweet spot** (blended unchanged 10.74, real
27.0%). (2) The custom |e^δ−1| objective is unstable (hessian surrogate) — reject. (3) huber/fair ≈
l2. **Adopt wl2 with a tuned power; sweep next.** Tweedie errored (needs positive target).

### R3 — Weighting power × target encoding × TF-IDF × ensembling (8-seed)
| model | blended | real |
|---|---|---|
| wl2_pow0.7 | 10.81 ±0.15 | **26.50 ±0.50** |
| wl2_pow0.5 | **10.74 ±0.12** | 26.99 ±0.42 |
| wl2_pow0.3 | 10.72 ±0.14 | 27.46 ±0.43 |
| ens_wl2_te | 10.79 | 27.28 |
| ens_wl2_cat_te | 10.72 | 27.88 |
| te_w0 (target-enc) | 10.97 | 28.58 |
| tfidf_w0.5 | 10.94 | 29.13 |

**Findings (mostly negative — important):** (1) **Target encoding HURTS** (28.6 vs 27.0) — overfits
on 411 rows. Reject. (2) **TF-IDF text features HURT** (29.1). Reject — the deterministic text
features already suffice. (3) **Ensembling adds nothing** over the best single model (and adds
complexity). Reject. (4) Weighting power: monotone blended↔real tradeoff; **pow 0.5–0.7 is the
sweet spot**. **Conclusion: simple weighted-L2 on deterministic+scope features is hard to beat;
complexity doesn't pay on this n. Adopt wl2, tune power + HPs next.**

### R4 — Hyperparameter sweep around weighted-L2 (10-seed)
Top configs (all within noise of each other): hp_mcs10 10.73/26.64, wl2_pow0.6 10.76/26.71,
wl2_pow0.5 10.74/26.94. Over-regularizing (mcs40, leaves31+mcs40) hurts (→10.94/28.0). reg_hi worse.
**Finding:** HP tuning is marginal (within ±noise); the gains came from the loss+weighting, not HPs.
**Adopt wl2 power=0.5, min_child_samples=20 (robust default).**

### R5 — model_v2 end-to-end (point=weighted-L2 on full data + cross-conformal intervals)
8-seed OOF: blended **10.74 ±0.12**, real **26.99 ±0.42**, **coverage 81.4%** (target 80%).
The cross-conformal intervals are well-calibrated and no data is wasted on the point model.
**vs committed v1 (11.31 / 34.54): blended −0.57pp, real-only −7.55pp (~22% relative).**

### R6 — Generalization guards
- **No-scope decision:** scope vs no-scope OOF is within noise (10.74/26.99 vs 10.78/26.84) →
  **deploy scope-free** (zero train/serve skew, no LLM dependency). LLM scope = documented negative.
- **Lockbox** (fixed 20%, n=83, 7 real — noisy): real-only generalizes (27–28% vs ~40% base);
  blended ~flat on the small sample (the 411-row OOF 10.6% is the reliable blended estimate).
- **Bagged OOF** (6 seeds) for predictions.csv: blended **10.62%**, real **27.07%**, coverage 83%.
  Lower variance than any single split; this is the shipped submission.

### R7 — Data-density-aware confidence
Added a per-category support multiplier (≤1, floor 0.70) so sparse in-production categories read
as less certain than the global conformal pad implies. Verified live: Cleaning(66 labels) 0.82,
Plumbing(3) 0.60, Electrical(2) 0.60 — same job/interval. Out-of-production + OOD caps unchanged.

### R8 — Weighting-power sweep (bagged, production model)
Monotone tradeoff (cov 83% throughout): pow 0.3→0.8 gives blended 10.61→10.75, real 27.54→26.37.
**Chose power=0.5** — best blended (the reliable metric), and deliberately did NOT chase higher
power to minimize the target-defined real-only proxy (overfitting risk vs the hidden holdout).

### Feature importance (weighted-L2)
Top signals: **desc_len** (longest descriptions → off-estimate jobs), rel_range/range (estimate
uncertainty), estimate magnitude, season (month), ZIP geography, numerics/keywords. Confirms the
simple deterministic text features carry the signal — explaining why TF-IDF/scope were redundant.

### R9 — Bias check + per-category breakdown
Optimal global scalar c*=0.998 (model is unbiased — reject bias correction). Per-category: big wins
on hard real cats (Handyman 48.4→33.8, Plumbing 35.8→25.8, Flooring 29.4→19.7), neutral on synthetic
cats (HVAC slightly worse 9.7→10.1). Sparse cats are *under*-covered (Handyman 64%, Plumbing 33%).

### R10 — Normalized (adaptive) cross-conformal
Scale the conformity score by local predicted spread so the pad widens for uncertain rows. Improves
conditional coverage (Plumbing 39→44%, Flooring 62→71%, Cleaning over-coverage 86→83%) with marginal
coverage unchanged (~82%). **Adopted** (default normalized=True) — point MAPE unchanged.

### R11 — Robustness: leave-one-category-out + model family
- **LOCO** (train without a category, predict it — unseen-category generalization): the model still
  **beats baseline on the hard categories even unseen** (Plumbing 35.8→26.0, Flooring 29.4→19.9,
  Handyman 48.4→40.4) and only slightly trails on already-easy ones. Confirms it generalizes via the
  residual anchoring + features, not category memorization — supports the "estimate any category" req.
- **Model family** (6-seed OOF): lgbm_wl2 **10.71/27.06** (best balance); random_forest 10.67/28.77
  (better blended, worse real); extra_trees 10.78/27.72; hist_gb 10.97/26.85; ens_l2_huber_fair
  10.71/28.24 (ensemble ≠ better); MLP diverged (needs scaling, not worth it on 411 rows).
  **LightGBM weighted-L2 confirmed — no family beats it on the blended+real balance.**

### R12 — Feature ablation, confidence reliability, error analysis, shrinkage
- **Ablation** (drop a feature group, 5-seed OOF; FULL = 10.72/27.00): drop text +0.26/+0.69 (keep),
  drop subtype +0.17/+1.04 (keep), drop time +0.02/+0.44 (keep), drop category-onehot +0.03/+0.07
  (≈neutral), **drop ZIP-geography −0.16/−0.51 (BETTER without!)**. ZIP features overfit on 411 rows
  / ~1033 ZIPs → confirmed at 10 seeds (below) and **removed**.
- **Confidence reliability:** mean OOF APE decreases monotonically by confidence bin
  (<0.5 → 12.4%, 0.7–0.85 → 9.2%, ≥0.85 → 8.9%) — the confidence score is genuinely informative.
- **Error analysis:** worst misses are "we-supply-materials" Handyman jobs (price drops far below
  estimate; only a few training examples). 72/411 rows the model does worse than baseline are the
  already-good synthetic categories (cost of helping the real rows).
- **Residual shrinkage** (adaptive/uniform/soft-threshold to dampen small corrections): **negative
  result** — trades the real-only win for a noise-level blended gain (a=0.02: 10.58 but real 28.0).
  Rejected — the model is already at a sound operating point.

### R13 — Final tuning on the no-ZIP model (8-seed)
Power re-sweep: 0.4→0.7 gives blended 10.59→10.66, real 26.58→25.92 (same monotone tradeoff within
noise) → **keep power=0.5**. Dropping category one-hot is neutral (10.62/26.32 vs 10.60/26.38) → keep
for interpretability. No further robust gains — model is at the data's ceiling (411 rows / 49 real).

### R14 — External Census ACS geography (income + home value by ZCTA) — REJECTED
Sourced keyless ACS 2019–2023 by ZCTA (michaelminn.net repackaging of public-domain Census; **98.7%**
of our 955 ZIPs matched, 12 fall back to national median). Joined `median_household_income` +
`median_home_value` as 2 features. **8-seed paired OOF: blended 10.60→10.73 (−0.13pp, ~5σ WORSE),
real-only 26.38→26.98 (−0.60pp, ~7σ WORSE).** Robust degradation across every seed, not noise. Same
failure family as raw ZIP (R12): geography **overfits on 411 rows AND is redundant with
`original_estimate`**, which already encodes the local price level (confirmed empirically: varying the
category label barely moves the point estimate; the estimate anchor sets the scale). **Rejected.** CSV
retained as `data/external/zip_acs.rejected.csv` (auto-load disabled by the `.rejected` rename). Reinforces
that the remaining lever is more ROWS (taller), not more features (wider) — see the learning curve in
`experiments/learning_curve.py`. **Replicated with the OFFICIAL Census API (key obtained; 2022 ACS5,
99.1% ZIP coverage): blended 10.60→10.80 (−0.20pp/6.6σ), real 26.38→26.89 (−0.51pp/5.8σ) — same verdict
across two independent ACS vintages and three geography attempts total (raw ZIP R12 + both ACS pulls).**
The `census.py` live-API path is validated and retained as a switchable capability (like the LLM scope
extractor) — built, measured, rejected, kept switchable + documented.

### R15 — Hand-crafted price-CHANGE features (hedge / scope-discrepancy / round-estimate) — REJECTED
Motivated by the residual framing (model the *change*, not the *level* — the same lens that explained
R14's Census failure: setting-features are redundant with `original_estimate`). 8-seed paired OOF scan
(singles, pairs, triple). **hedge +0.00/0.0σ — DEAD** (only 2/411 descriptions contain any hedge cue;
signal absent in this terse/templated text). **scope-discrepancy (Σnumbers/estimate) +0.04pp blended/2.9σ
but real-only −0.03 (noise)** — trivial and redundant with existing `max_number`+`orig`+`rel_range`.
**round-estimate −0.13pp real/1.7σ WORSE** (only 7.5% of estimates are round — premise false + noise).
**Reject all.** The existing change features (`desc_len` #1, `rel_range`/`range` ~21%) already capture the
available change signal. **Sixth feature attempt to fail** (3 setting: ZIP R12 + 2× ACS R14; 3 change here)
— confirms the point estimate is at the data's feature ceiling on 411 rows; the lever is ROWS (taller),
not FEATURES (wider). Scan: `experiments/change_features.py`.

### R16 — Feature-space novelty → CONFIDENCE layer (option 2) — ADOPTED
The first change-signal with positive evidence (after R15 killed hand-crafted change features): a
k-NN distance-to-training **novelty** score correlates with upstream error (Spearman ρ=0.18, p=2e-4;
real rows novelty 4.75 vs easy 2.92). Wired into `ConfidenceCalibrator`: a **soft penalty** (down-weight
as novelty exceeds the training median, floor 0.5) + a **4th OOD gate** firing beyond the 95th pct of
training novelty (**5.1%** of rows — principled; an earlier 2.5×median over-fired at 8.5%). **Fixes the
known gap**: a gibberish description in a known category at a normal price drops from ~0.72 to **0.26**
(flagged); a normal description stays 0.72; sparse/atypical real jobs (e.g. $1850 Plumbing, 3 labels)
read ~0.30. **MAPE UNCHANGED (10.47/26.58)** — novelty touches only confidence. Confidence stays
informative (low-conf bin 12.6% OOF APE vs high-conf 8.2%). Stored `scaler`+`NearestNeighbors` in the
bundle; leakage-safe (feature geometry, no `final_price`). 20/20 tests green (+4 regression tests).
**NOTE:** novelty as a POINT-ESTIMATE feature (option 1) was a separate tradeoff — **ADOPTED, see R17.**

### R17 — Feature-space novelty as a POINT-ESTIMATE feature (option 1) — ADOPTED (gauntlet-v2.1.0)
Scan (`experiments/novelty_knn.py`, 6-seed paired OOF): **novelty** improves real-only **26.58→26.12
(+0.46pp, 5.2σ)** at a small blended cost (−0.07pp, 2.1σ); `knn_ref` (sparse neighbors' mean residual)
and `cat_unc` (category-relative rel_range z-score) both REJECTED (hurt or neutral). Adopted novelty
because it is a genuine atypicality mechanism (not proxy-fitting — leakage-safe feature geometry), and
real-only is the upstream-error subset / hidden-holdout proxy that matters most; both metrics still beat
baseline. Integrated leakage-safely: a **per-fold** novelty index for the OOF metrics (refit on each
train split — `train._oof_bagged_with_novelty`) and a full-data index for serving (`predict._novelty`,
appended before `align_to`). Deployed bagged OOF: **blended 10.49% (was 10.47), real-only 26.22% (was
26.58, −0.36pp), coverage 82.7%** — bagging shrank the blended cost to noise (+0.02pp) while keeping the
real-only gain. No leakage (OOF matches the scan; a leak would have collapsed real-only). 20/20 tests
green. The novelty feature is shared with the confidence layer (R16).

### R18 — External scraped FINALS (Reddit "what I paid", browser-control) — REJECTED
Built a browser-control scraping pipeline (Playwright + headless Chromium; WebFetch's blocks were
*tool-level* — a real browser reaches old.reddit + trade forums, only Yelp-class sites stay 403).
Six parallel sharded waves across ~60 home-service subreddits with payment-oriented queries
("i paid" / "total was" / "out the door" / "they charged" / …) → **331 unique REAL finals** matched to
our job descriptions (TF-IDF), all in our $46–7266 range, including **64 real estimate→final pairs**.
Median $600 (vs our $302 — Reddit self-selects bigger/notable jobs). **Augmentation OOF eval
(leakage-safe: scraped rows train-only, scored on the 411): both arms WORSE** — +PAIRS blended
10.59→11.88 (−1.28pp), real 26.58→28.57 (−1.99pp); +ALL-finals (synthesized estimate) blended →13.44
(−2.85pp), real →33.60 (−7.02pp). **Rejected.** Even real "what I paid" data hurts: distribution shift
(2× our median) + extraction noise + (for ALL) the circular synthesized-estimate problem. Confirms the
data ceiling — HouseAccount's marketplace-distribution labels are irreplaceable; *every* external
final source (cost guides, permits, AHS, now scraped community finals) fails the gate. Pipeline:
`experiments/scrape_finals.py` + `augment_eval.py`; data `data/external/scraped_pilot.csv` (gitignored).
**Deployed model unchanged (v2.1.0, 10.49/26.22).**

### R19 — Well-reviewed marketplace prices (Thumbtack) + combined augmentation eval — REJECTED
Per the "mimic HouseAccount / well-reviewed contractors" hypothesis, scraped Thumbtack (browser control,
15 cities × 18 categories, well-reviewed pros, avg rating 4.87) → 76 marketplace prices. Distribution-
*closer* than Reddit but **low-skewed (median $100 — advertised "starting prices", not job finals)** and
**narrow** (Cleaning/Handyman only; other trades show "contact for quote", not a price). Final combined
scraped dataset: **407 real prices** (331 Reddit finals incl. 64 estimate→final pairs + 76 Thumbtack).
**Full augmentation OOF eval (leakage-safe, scored on the 411):** every arm WORSE — +Thumbtack
10.59→10.85 / 26.58→28.65 (−0.26/−2.07); +Reddit →13.44/33.60 (−2.85/−7.02); +both →13.43/34.21. The
marketplace arm was *least* harmful on blended (the distribution instinct was directionally right) but
still hurts. **Definitive close: no scrapeable external source helps.** What mimics HouseAccount IS
proprietary marketplace transaction data; public sources are estimates (cost guides, advertised minimums)
or distribution-skewed discussion (Reddit high). Data ceiling confirmed from every angle tried (cost
guides, Census, permits/AHS, Reddit finals, marketplace pros). Deployed model unchanged (**v2.1.0,
10.49/26.22**). Pipeline: `experiments/scrape_thumbtack.py`, `augment_eval2.py`; data
`data/external/scraped_pilot.csv` (407 rows, gitignored).

### R20 — HomeStars (CA) "approximate cost" field — REJECTED (premise disproven, no crawl run)
The last open augmentation lead (HANDOFF_2): HomeStars was believed to expose a structured *"Approximate
cost of services: $X"* field on customer reviews — real paid finals with a HouseAccount-like marketplace
distribution, robots-permissive (robots.txt for `*` only disallows /login, /_next, /*.json$). Built a
compliant crawler (`experiments/scrape_homestars.py`, normal browser, FX CAD→USD) and **verified the
premise on the live site before crawling.** It is **false today**: HomeStars migrated to a Next.js layout
where reviews render as *job-type tag + star rating + date + prose* with **no price**. Measured across
**30 fully-rendered reviews / 5 profiles / 3 categories (plumbing, heating, roofing) / 2 cities**:
**0 "approximate cost" fields and 0 dollar amounts of any kind.** The PoC's earlier "$700" was a fluke
(portfolio/About text, not a review price field). **No crawl was launched** — there is nothing to extract,
and running parallel crawls would only hammer the site for ~0 priced rows (ToS politeness). This closes
the last external lead: HomeStars joins cost guides, Census, permits/AHS, Reddit, and Thumbtack as a
documented negative. **Data ceiling fully confirmed; deployed model unchanged (v2.1.0, 10.49/26.22).**

### R21 — TabPFN (small-data tabular foundation model) vs LightGBM — REJECTED
The only untried *architecture* lever (not new data). Ran TabPFN v2 (ungated, downloaded from the public
GCS bucket — **fully local inference, no data egress**; the v8 cloud client requiring `TABPFN_TOKEN` was
**not** used, as it would ship the proprietary 411 rows off-machine) under the project's exact OOF gate:
same 411 rows, same 41 deterministic features, same residual target log(final/original), same 5-fold
stratified folds, midpoint MAPE, 5 seeds. Three arms to separate architecture from the MAPE-weighting trick:
| Arm | Blended | Real-only |
|---|---|---|
| A. LightGBM v2 weighted (deployed) | 10.56% | 26.50% |
| B. LightGBM v2 unweighted (control) | 10.58% | 27.59% |
| **C. TabPFN residual** | **10.82%** | **29.42%** |
TabPFN loses to BOTH LightGBM arms — vs deployed −0.26 bl / −2.92 real; **vs the unweighted control −0.23
bl / −1.82 real**, so the loss is *architectural*, not just the missing weighting (TabPFN takes no sample
weights). Also ~34× slower (432s vs 12s, CPU). 411×41 is squarely in GBDT's wheelhouse; TabPFN's
general-purpose in-context prior can't exploit the residual-on-estimate structure or MAPE weighting that
LightGBM is tuned for. **LightGBM v2 stays.** Pipeline: `experiments/tabpfn_eval.py`.
**This closes the last open lever (data AND architecture). v2.1.0 is final.**

### R22 — Mutation engine: 10x jittered oversampling (distribution-preserving) — REJECTED
Tested the "even out by 10x-ing every row, keeping the category distribution" idea via a
mutation engine (`experiments/mutation_eval.py`): each labeled row replicated 10x, the 9 extra
copies given ~5% independent lognormal jitter on the price fields (original_estimate, lo/hi,
final_price); category/zip/description untouched. **Leakage-safe**: only each fold's TRAIN split
is mutated; the held-out test rows are the original 411, never mutated.
| condition | blended | real-only |
|---|---|---|
| baseline (no aug) | 10.65% | 26.19% |
| + mutation 10x | **14.36%** | **35.60%** |
**Worse by −3.72pp blended / −9.40pp real-only**, and seed-std jumped 0.16→1.84 (less stable).
On the dashboard samples, confidence did NOT even up — it **crashed on the well-supported
categories** (Cleaning 0.79→0.29, HVAC 0.61→0.29) and only nudged the sparse Plumbing ones
(0.19→0.36). Root cause: jittered duplicates add **no new information** but do introduce a
train/serve mismatch — the conformal intervals widen (jittered residuals = noise) and the
novelty index/calibration is built on dense near-duplicate clusters, so the real (un-mutated)
bookings look more atypical and get wider intervals → lower confidence. Confirms R14–R20's
lesson at the data-shape level: you cannot manufacture signal for sparse categories by
replicating/jittering — only real marketplace labels help. **Deployed model unchanged
(v2.1.0).** The sparse-category low confidence is correct/honest (the brief requires it).

## Final architecture (deployed, gauntlet-v2.1.0)
Residual target log(final/original) · LightGBM **L2 + MAPE-aligned weight 1/√final_price** point
model on ALL data · **normalized cross-conformal** quantile intervals (coverage ~83%) · bagged 6-seed
OOF for the submission · **deterministic features only** (scope-free AND ZIP-free) **+ a leakage-safe
feature-space novelty feature** (R17) · density-aware confidence + PRD OOD gates **+ a novelty OOD
gate/penalty** (R16).
**Leakage-free bagged OOF: blended 10.49% (base 11.56), real-only 26.22% (base 36.75), coverage 82.7%.**

## Journey
| Stage | Blended | Real-only |
|---|---|---|
| Baseline (old estimate) | 11.56% | 36.75% |
| v1 (quantile-q50 + CQR) | 11.31% | 34.54% |
| v2 (L2 + weight + cross-conformal + bagging) | 10.62% | 27.07% |
| v2 + no-ZIP | 10.47% | 26.58% |
| **v2.1 + novelty feature + novelty-aware confidence (final)** | **10.49%** | **26.22%** |

Real-only: **−29% relative** vs baseline. Blended: **−9.3% relative** vs baseline.
