# AI Usage Log

How AI tooling was used to build the HouseAccount AI Pricing Model. Per the project template.

## Tools used

- **Claude Code (Opus 4.8, "ultracode" mode)** — primary coding agent and orchestrator. Did the
  data analysis, modeling, Rails + Python implementation, tests, integration, and docs. Ran as a
  long-horizon autonomous `/goal` session with a hard 7.5h deadline (cron-enforced).
- **Background subagents** (Sonnet) — spawned by the orchestrator for well-bounded parallel work:
  one built the Rails API app + RSpec specs; one drafted the README + deployment guide. The
  orchestrator defined exact contracts so the parallel outputs integrated without collision.
- **`claude -p` (headless CLI)** — used as a *separate model instance* inside the data pipeline to
  extract structured scope (sqft, fixture count, complexity, urgency) from free-text
  `job_description` in batches. Wrapped behind a `ScopeExtractor` interface so it can be swapped for
  the Anthropic API (`anthropic_api` backend) in deployment.
- **Conversation logging hooks** — a `UserPromptSubmit`/`Stop` hook system records every prompt and
  final reply to `claude-planner-conversation.md`, giving a durable audit trail of the AI session.

## Significant prompts (the ones that shaped the architecture)

1. *"Read the assignment description. We're basically making a prediction model?"* — set the framing:
   established that the task is half modeling, half shipping a real integrated API, and surfaced the
   tiny-label / no-scope-fields challenges early.
2. *"choices should be the PRD's preferred value whenever possible"* / *"follow the PRD is
   paramount"* — the decisive tiebreaker. Flipped the stack from FastAPI to **Rails** (PRD-preferred)
   and pinned confidence/OOD thresholds to PRD values verbatim.
3. *"use the headless claude command for now but have it switchable to an api key once we get it"* —
   produced the three-backend `ScopeExtractor` (claude_cli → anthropic_api → deterministic) and the
   decision that the deployed endpoint runs pure-ML with a deterministic floor.
4. *"are we able to delete these bookings or view them? … it seems unwise to allow writes like this"*
   — drove the write-safety policy: staging has no GET/DELETE, so connectivity is verified with
   zero-write 422/401 probes and exactly **one** tagged booking is created.
5. **The `/goal` directive** — *"Accomplish assignment_description.md … reach the correct metrics
   without training leakage … api integration real but not invasive … all ambiguities decided by
   you, all assumptions stated."* This defined the acceptance gates and the leakage discipline that
   shaped the OOF evaluation harness.
6. Internal architecture prompt (orchestrator → self, in `docs/BUILD_PLAN.md`): *model the residual
   `log(final_price/original_estimate)` so synthetic rows stay near the strong baseline while real
   rows get a learned correction* — the single most important modeling decision.
7. Rails subagent contract prompt — specified the exact Appendix A request/response, error parity
   (400/401/405), bearer `secure_compare`, and the Rails↔sidecar HTTP contract, so the generated app
   matched the spec on the first integration.

## Validation steps for AI-generated code

- **Baseline reproduction as ground truth.** Before trusting any model number, the eval harness was
  required to reproduce the official 11.56% blended baseline — it does, exactly. This caught that
  naive "real-only = APE>2%" was wrong and led to the correct `APE>20%` ≈ 37% subset.
- **Leakage tests, not just accuracy tests.** A unit test shuffles `final_price` and asserts MAPE
  blows up (>25%), proving the pipeline can't be memorizing labels. All metrics are out-of-fold.
- **Full test suites run and green:** 15 Python tests (`pytest`) including the model-beats-both-
  baselines regression gate; 21 Rails request specs (`rspec`) covering auth/validation/errors.
- **Live end-to-end verification:** started the sidecar + Rails and exercised the real HTTP path —
  200 happy/alias, 401, 400-per-field, 405, and 0.02s latency (≪2s target).
- **Integration verified without side effects:** the HMAC signing was confirmed against the live
  staging endpoint with zero-write probes (422 = auth OK, 401 = bad sig) before any booking was
  created.

### Hallucinations / bad output caught
- The agent initially mis-renamed the staging signing key as the endpoint bearer secret; the live
  HMAC scheme contradicted that, so it was corrected into two separate secrets.
- A confidence-calibration bug used the *model's* interval median instead of the PRD's *observed*
  range for the OOD threshold — caught by an obviously-wrong low confidence on a normal water heater
  and fixed.
- The endpoint 500'd on requests without `original_estimate` (NaN propagation); caught by an alias
  test and fixed with category-median anchors.
- The Census API was assumed keyless; a live probe proved it now requires a key, so the join was
  made optional with a self-contained ZIP-region fallback.

## Reflection

**Where AI helped most.** Speed from data-understanding to a *correct, leakage-free* model: the
agent reproduced the baseline, diagnosed the augmented-vs-real structure, and found the residual
formulation in one focused pass. Parallel subagents building the Rails app and docs while the
orchestrator built the numeric core compressed wall-clock meaningfully. Treating `claude -p` as a
data-pipeline component (scope extraction) was a force-multiplier the schema otherwise lacked.

**Where it produced bad output.** Anything depending on external, unverifiable facts (the Census
keyless assumption; the secret's purpose) was wrong until checked against reality. The lesson held
throughout: *probe the real system before trusting a plausible assumption.* The agent also needed
guardrails against optimistic evaluation — left alone, accuracy code tends to leak; the explicit
OOF discipline and shuffle test were essential.

**What I'd do differently.** Stand up the live end-to-end path *first* (it surfaced the port
conflict and the missing-estimate 500 that unit tests alone missed). Acquire a Census key up front
for the demographic join (likely the biggest untapped lever on real-only MAPE). And add a
category-data-density term to confidence so sparse in-production categories read as appropriately
uncertain.
