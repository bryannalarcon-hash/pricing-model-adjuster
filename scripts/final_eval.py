#!/usr/bin/env python3
"""Rigorous final-candidate validation for ConformalPriceModelV2:
  - high-seed OOF (blended/real/coverage) on all 411
  - lockbox check (fixed 20% hold-out never used in selection)
  - per-category MAPE breakdown (model vs baseline)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, baseline_blended, stratify_key
from houseprice.model_v2 import ConformalPriceModelV2

POWER = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
SEEDS = int(sys.argv[2]) if len(sys.argv) > 2 else 15


def feats(lab):
    df = load_dataset(); lab_idx = df.index[df["is_labeled"]].tolist()
    scope = pd.read_parquet("data/processed/scope.parquet").reindex(lab_idx).reset_index(drop=True) \
        if os.path.exists("data/processed/scope.parquet") else None
    # rebuild scope aligned to the given lab subset by job_id
    if scope is not None:
        scope.index = labeled(df).reset_index(drop=True).index
    X, _ = build_features(lab.reset_index(drop=True),
                          scope_df=scope.loc[lab.index] if scope is not None else None)
    return X.reset_index(drop=True)


def oof(lab, seeds):
    X = feats(lab); fp = lab["final_price"].values; oe = lab["original_estimate"].values
    base = np.asarray(ape(oe, fp)); real = base > 0.20
    bl, rl, cov = [], [], []
    allmid = np.zeros(len(lab))
    for s in range(seeds):
        lo = np.full(len(lab), np.nan); mid = lo.copy(); hi = lo.copy()
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=s).split(lab, stratify_key(lab)):
            m = ConformalPriceModelV2(weight_power=POWER, seed=s).fit(X.iloc[tr], fp[tr], oe[tr])
            p = m.predict(X.iloc[te], oe[te]); lo[te], mid[te], hi[te] = p[:,0], p[:,1], p[:,2]
        bl.append(mape(mid, fp)); rl.append(mape(mid[real], fp[real]))
        cov.append(float(((fp>=lo)&(fp<=hi)).mean())); allmid += mid
    return bl, rl, cov, allmid/seeds, real, base


def main():
    df = load_dataset(); lab = labeled(df).reset_index(drop=True)
    bl, rl, cov, meanmid, real, base = oof(lab, SEEDS)
    print(f"=== model_v2 power={POWER}  ({SEEDS}-seed OOF) ===")
    print(f"  blended : {np.mean(bl):.2f} ± {np.std(bl):.2f}  (baseline {baseline_blended(lab):.2f})")
    print(f"  real    : {np.mean(rl):.2f} ± {np.std(rl):.2f}  (baseline {100*base[real].mean():.2f})")
    print(f"  coverage: {100*np.mean(cov):.1f}%")

    # Lockbox: train on 80%, eval on fixed 20% hold-out
    exp, lb = train_test_split(lab, test_size=0.2, random_state=2024, stratify=stratify_key(lab))
    exp, lb = exp.reset_index(drop=True), lb.reset_index(drop=True)
    Xall = feats(lab)
    Xe = Xall.loc[exp.index] if False else feats(exp); Xl = feats(lb)
    fp_l = lb["final_price"].values; oe_l = lb["original_estimate"].values
    base_l = np.asarray(ape(oe_l, fp_l)); real_l = base_l > 0.20
    mids = []
    for b in range(5):
        m = ConformalPriceModelV2(weight_power=POWER, seed=b).fit(
            feats(exp), exp["final_price"].values, exp["original_estimate"].values)
        mids.append(m.predict(Xl, oe_l)[:, 1])
    mid_l = np.mean(mids, axis=0)
    print(f"=== LOCKBOX (n={len(lb)}, real={int(real_l.sum())}) — overfit guard ===")
    print(f"  blended : {mape(mid_l, fp_l):.2f}  (baseline {mape(oe_l, fp_l):.2f})")
    if real_l.sum() > 0:
        print(f"  real    : {mape(mid_l[real_l], fp_l[real_l]):.2f}  (baseline {100*base_l[real_l].mean():.2f})")

    # per-category breakdown (OOF mean predictions)
    print("=== per-category MAPE (OOF) ===")
    lab2 = lab.assign(m_ape=np.asarray(ape(meanmid, lab["final_price"])), b_ape=base)
    g = lab2.groupby("category").agg(n=("final_price","size"),
                                     model=("m_ape", lambda x:100*x.mean()),
                                     base=("b_ape", lambda x:100*x.mean())).sort_values("base")
    print(g.round(1).to_string())


if __name__ == "__main__":
    main()
