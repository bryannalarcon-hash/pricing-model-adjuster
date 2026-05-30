#!/usr/bin/env python3
"""Validate ConformalPriceModelV2 end-to-end via multi-seed OOF: point MAPE + interval coverage."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, baseline_blended, stratify_key
from houseprice.model_v2 import ConformalPriceModelV2

POWER = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
SEEDS = int(sys.argv[2]) if len(sys.argv) > 2 else 8


def main():
    df = load_dataset(); lab = labeled(df).reset_index(drop=True)
    lab_idx = df.index[df["is_labeled"]].tolist()
    scope = None
    if os.path.exists("data/processed/scope.parquet"):
        scope = pd.read_parquet("data/processed/scope.parquet").reindex(lab_idx).reset_index(drop=True)
    X, _ = build_features(lab, scope_df=scope)
    fp = lab["final_price"].values; oe = lab["original_estimate"].values
    base = np.asarray(ape(oe, fp)); real = base > 0.20
    bl, rl, cov = [], [], []
    for s in range(SEEDS):
        lo = np.full(len(lab), np.nan); mid = lo.copy(); hi = lo.copy()
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=s).split(lab, stratify_key(lab)):
            m = ConformalPriceModelV2(weight_power=POWER, seed=s).fit(X.iloc[tr], fp[tr], oe[tr])
            p = m.predict(X.iloc[te], oe[te])
            lo[te], mid[te], hi[te] = p[:, 0], p[:, 1], p[:, 2]
        bl.append(mape(mid, fp)); rl.append(mape(mid[real], fp[real]))
        cov.append(float(((fp >= lo) & (fp <= hi)).mean()))
    print(f"model_v2 (weight_power={POWER}, {SEEDS} seeds)")
    print(f"  blended MAPE : {np.mean(bl):.2f} ± {np.std(bl):.2f}   (baseline {baseline_blended(lab):.2f})")
    print(f"  real-only    : {np.mean(rl):.2f} ± {np.std(rl):.2f}   (baseline {100*base[real].mean():.2f})")
    print(f"  coverage     : {100*np.mean(cov):.1f}%  (target 80%)")


if __name__ == "__main__":
    main()
