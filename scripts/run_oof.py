#!/usr/bin/env python3
"""Leakage-free out-of-fold evaluation against the two baselines.

Reports: blended MAPE (all 411 vs 11.6%) and real-only MAPE (base_ape>0.20 proxy vs ~37-40%),
plus interval coverage. Optionally consumes cached scope/census features.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np
import pandas as pd
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, baseline_blended
from houseprice.model import oof_predict, LO_Q, HI_Q

REAL_THR = 0.20  # base_ape proxy for "genuinely-real" rows (A3)


def load_optional():
    scope = census = None
    sp = os.path.join("data", "processed", "scope.parquet")
    cp = os.path.join("data", "external", "zip_acs.csv")
    if os.path.exists(sp):
        scope = pd.read_parquet(sp)
    if os.path.exists(cp):
        census = pd.read_csv(cp, dtype={"zip_code": str})
    return scope, census


def main():
    df = load_dataset()
    lab = labeled(df)
    base = ape(lab["original_estimate"], lab["final_price"])
    real_mask = base > REAL_THR

    scope, census = load_optional()
    if scope is not None:
        scope = scope.reindex(range(len(df)))  # align to full df index then subset
    # build features needs scope/census aligned to lab index; rebuild on lab directly
    lo, mid, hi = oof_predict(lab, build_features, scope_df=None, census_df=census)

    blended = mape(mid, lab["final_price"])
    real = mape(mid[real_mask], lab["final_price"].values[real_mask])
    base_blended = baseline_blended(lab)
    base_real = 100 * base[real_mask].mean()
    cov = float(((lab["final_price"].values >= lo) & (lab["final_price"].values <= hi)).mean())
    width = float(np.mean((hi - lo) / np.clip(mid, 1, None)))

    print("=" * 64)
    print(f"{'metric':28s} {'model':>10s} {'baseline':>10s} {'pass?':>8s}")
    print("-" * 64)
    print(f"{'blended MAPE (all '+str(len(lab))+')':28s} {blended:9.2f}% {base_blended:9.2f}% "
          f"{'YES' if blended < base_blended else 'no':>8s}")
    print(f"{'real-only MAPE (n='+str(int(real_mask.sum()))+')':28s} {real:9.2f}% {base_real:9.2f}% "
          f"{'YES' if real < base_real else 'no':>8s}")
    print("-" * 64)
    print(f"interval coverage (target {int((HI_Q-LO_Q)*100)}%): {cov*100:.1f}%   mean rel width: {width:.2f}")
    print("=" * 64)


if __name__ == "__main__":
    main()
