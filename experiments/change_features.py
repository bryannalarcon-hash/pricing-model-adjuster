"""Ablation scan of candidate PRICE-CHANGE features (predict the residual, not the level).

Three leakage-safe features (from job_description + original_estimate only, never final_price):
  hedge  : count of homeowner uncertainty/hedging cues ("not sure", "approx", "?", ...)
  scope  : scope-vs-dollar discrepancy = sum_of_numbers_in_desc / original_estimate
  round  : roundness of original_estimate (round numbers => rough guess => more error-prone)

Scan: baseline (none), each alone, all pairs, all three. Paired multi-seed OOF.
Adopt only if it beats baseline by >1 combined std AND is justified (JOURNAL rule).
"""
from __future__ import annotations
import sys, os, re, itertools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features, NUM_RE
from houseprice.model_v2 import oof_predict
from houseprice.eval import ape, mape

N_SEEDS = 8

HEDGE = [r"not sure", r"approx", r"around", r"about", r"roughly", r"maybe", r"might",
         r"depend", r"if needed", r"if necessary", r"\btbd\b", r"to be determined",
         r"unsure", r"possibly", r"or so", r"\bguess", r"not certain", r"unclear", r"\bish\b"]

def hedge_count(d):
    d = (d or "").lower()
    return float(sum(len(re.findall(p, d)) for p in HEDGE) + d.count("?"))

def roundness(x):
    x = float(x)
    if x <= 0:
        return 0.0
    xi = int(round(x))
    for m, s in [(1000, 4), (500, 3), (100, 2), (50, 1), (25, 0.5)]:
        if xi % m == 0:
            return float(s)
    return 0.0

def sum_numbers(d):
    return float(sum(float(x) for x in NUM_RE.findall((d or "").lower())))


def run():
    df = load_dataset(); lab = labeled(df).reset_index(drop=True)
    oe = lab["original_estimate"].values.astype(float)
    fp = lab["final_price"].values.astype(float)
    real = ape(oe, fp) > 0.20
    baseX, _ = build_features(lab)

    cands = {
        "hedge": lab["job_description"].map(hedge_count).values.astype(float),
        "scope": lab["job_description"].map(sum_numbers).values / np.clip(oe, 1, None),
        "round": lab["original_estimate"].map(roundness).values.astype(float),
    }

    def make_X(cols):
        X = baseX.copy()
        for c in cols:
            X[c] = cands[c]
        return X

    def oof_metrics(X, s):
        _, mid, _ = oof_predict(lab, build_features, X_all=X, seed=s)
        return mape(mid, fp), mape(mid[real], fp[real])

    seeds = list(range(N_SEEDS))
    base = np.array([oof_metrics(baseX, s) for s in seeds])  # (seeds, [bl, rl])
    bl0, rl0 = base[:, 0], base[:, 1]

    conds = ([["hedge"], ["scope"], ["round"]] +
             [list(c) for c in itertools.combinations(cands, 2)] +
             [list(cands)])

    print(f"PRICE-CHANGE FEATURE SCAN  ({N_SEEDS}-seed paired OOF)\n")
    print(f"{'condition':22s} {'blended':>8s} {'Δbl(σ)':>13s} {'real':>8s} {'Δreal(σ)':>14s}")
    print(f"{'baseline (none)':22s} {bl0.mean():>7.2f}% {'—':>13s} {rl0.mean():>7.2f}% {'—':>14s}")
    for cols in conds:
        m = np.array([oof_metrics(make_X(cols), s) for s in seeds])
        bl, rl = m[:, 0], m[:, 1]
        dbl, drl = bl0 - bl, rl0 - rl          # positive = improvement
        sb = dbl.std() / np.sqrt(len(dbl)) + 1e-9
        sr = drl.std() / np.sqrt(len(drl)) + 1e-9
        print(f"{'+'.join(cols):22s} {bl.mean():>7.2f}% "
              f"{dbl.mean():>+6.2f} ({abs(dbl.mean())/sb:>3.1f}) {rl.mean():>7.2f}% "
              f"{drl.mean():>+6.2f} ({abs(drl.mean())/sr:>3.1f})")
    print("\n(Δ positive = better than baseline; σ = std-errors of the paired delta. "
          "Adopt only if Δ>0 by >~1σ AND robust.)")


if __name__ == "__main__":
    run()
