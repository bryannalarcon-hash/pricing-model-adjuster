#!/usr/bin/env python3
"""Lockbox overfit-guard: fixed 20% hold-out never used in model selection. Also compares
scope vs no-scope (deployment-skew decision). Features built once on full data then sliced
(consistent columns)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from sklearn.model_selection import train_test_split
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, stratify_key
from houseprice.model_v2 import ConformalPriceModelV2

POWER = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5


def run(use_scope):
    df = load_dataset(); lab = labeled(df).reset_index(drop=True)
    lab_idx = df.index[df["is_labeled"]].tolist()
    scope = None
    if use_scope and os.path.exists("data/processed/scope.parquet"):
        scope = pd.read_parquet("data/processed/scope.parquet").reindex(lab_idx).reset_index(drop=True)
    X, _ = build_features(lab, scope_df=scope)          # built once -> consistent columns
    tr_i, lb_i = train_test_split(np.arange(len(lab)), test_size=0.2, random_state=2024,
                                  stratify=stratify_key(lab))
    fp = lab["final_price"].values; oe = lab["original_estimate"].values
    base_l = np.asarray(ape(oe[lb_i], fp[lb_i])); real_l = base_l > 0.20
    mids = []
    for b in range(7):
        m = ConformalPriceModelV2(weight_power=POWER, seed=b).fit(X.iloc[tr_i], fp[tr_i], oe[tr_i])
        mids.append(m.predict(X.iloc[lb_i], oe[lb_i])[:, 1])
    mid = np.mean(mids, axis=0)
    tag = "with-scope" if use_scope else "no-scope  "
    print(f"  [{tag}] lockbox(n={len(lb_i)},real={int(real_l.sum())}): "
          f"blended {mape(mid, fp[lb_i]):.2f} (base {mape(oe[lb_i], fp[lb_i]):.2f}) | "
          f"real {mape(mid[real_l], fp[lb_i][real_l]):.2f} (base {100*base_l[real_l].mean():.2f})")


if __name__ == "__main__":
    print(f"=== LOCKBOX (power={POWER}, fixed 20% holdout, bagged x7) ===")
    run(True)
    run(False)
