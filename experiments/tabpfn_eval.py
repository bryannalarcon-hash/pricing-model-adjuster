"""TabPFN vs LightGBM head-to-head, under the project's EXACT OOF gate.
Same 411 real rows, same deterministic features, same residual target log(final/original),
same 5-fold stratified folds, scored on estimate_midpoint MAPE (blended + real-only n=49 proxy),
averaged over N seeds. Three arms to separate ARCHITECTURE from the MAPE-weighting trick:

  A. LightGBM v2 (DEPLOYED)   — residual, MAPE-aligned weight 1/sqrt(final)   [incumbent]
  B. LightGBM v2 unweighted   — residual, uniform weight                      [control: arch w/o weighting]
  C. TabPFN regressor         — residual, uniform (TabPFN takes no weights)   [the test]

If C beats A it's a genuine win; if C only rivals B, LightGBM+weighting still wins. Honest read either way.
TabPFN downloads its pretrained weights from HuggingFace on first fit (~tens of MB)."""
from __future__ import annotations
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import make_folds, ape, mape

N_SEEDS = 5

lab = labeled(load_dataset()).reset_index(drop=True)
fp = lab["final_price"].values.astype(float)
oe = lab["original_estimate"].values.astype(float)
real_mask = ape(oe, fp) > 0.20
X, names = build_features(lab)
Xf = X.astype(float)                      # bool/int -> float for TabPFN
y_resid = np.log(fp / oe)                 # the multiplier target everything uses

def score(pred):
    return mape(pred, fp), mape(pred[real_mask], fp[real_mask])

# ---- Arm A/B: LightGBM v2 point (weighted / unweighted) -------------------------------
def oof_lgbm(weight_power, seed):
    pred = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        m = ConformalPriceModelV2(weight_power=weight_power, seed=seed).fit(X.iloc[tr], fp[tr], oe[tr])
        pred[te] = m.predict(X.iloc[te], oe[te])[:, 1]      # midpoint
    return score(pred)

# ---- Arm C: TabPFN residual regressor (ungated v2, LOCAL inference — no data egress) ----
def oof_tabpfn(seed):
    from tabpfn import TabPFNRegressor
    from tabpfn.constants import ModelVersion
    reg = TabPFNRegressor.create_default_for_version(   # build once/seed; refit per fold is cheap
        ModelVersion.V2, device="cpu", random_state=seed, ignore_pretraining_limits=True)
    pred = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        reg.fit(Xf.iloc[tr].values, y_resid[tr])
        corr = reg.predict(Xf.iloc[te].values)
        pred[te] = oe[te] * np.exp(corr)                    # final = original * exp(correction)
    return score(pred)

def run(label, fn):
    t0 = time.time()
    arr = np.array([fn(s) for s in range(N_SEEDS)])
    bl, rl = arr[:, 0].mean(), arr[:, 1].mean()
    print(f"{label:34s} {bl:>7.2f}% {rl:>10.2f}%   ({time.time()-t0:5.1f}s)", flush=True)
    return bl, rl

if __name__ == "__main__":
    print(f"TabPFN vs LightGBM — OOF on {len(lab)} real rows, residual target, {N_SEEDS} seeds\n")
    print(f"{'arm':34s} {'blended':>7s} {'real-only':>10s}")
    a = run("A. LightGBM v2 weighted (DEPLOYED)", lambda s: oof_lgbm(0.5, s))
    b = run("B. LightGBM v2 unweighted (control)", lambda s: oof_lgbm(0.0, s))
    c = run("C. TabPFN residual", oof_tabpfn)
    print()
    print(f"C vs A (deployed):  Δblended {a[0]-c[0]:+.2f}  Δreal {a[1]-c[1]:+.2f}   (+ = TabPFN better)")
    print(f"C vs B (arch only): Δblended {b[0]-c[0]:+.2f}  Δreal {b[1]-c[1]:+.2f}   (+ = TabPFN better)")
    print("\nLeakage-safe: each row scored by a model trained without its fold. Same features/target/folds across arms.")
