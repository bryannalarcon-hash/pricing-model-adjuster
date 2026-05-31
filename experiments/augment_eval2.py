"""Augmentation eval across all scraped sources: baseline vs +Thumbtack-marketplace vs +Reddit-finals
vs +both. Leakage-safe (scraped rows train-only; OOF scored on the 411 real rows). Estimate for
scraped rows = real quote if present else OUR category-median (synthesized)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from houseprice.data_load import load_dataset, labeled, normalize_category, is_production_category
from houseprice.features import build_features, align_to
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import make_folds, ape, mape

N = 6
lab = labeled(load_dataset()).reset_index(drop=True)
fp_real = lab["final_price"].values.astype(float); oe_real = lab["original_estimate"].values.astype(float)
real_mask = ape(oe_real, fp_real) > 0.20
X_real, names = build_features(lab)
catmed = lab.groupby("category")["original_estimate"].median().to_dict(); gmed = float(lab["original_estimate"].median())

def to_rows(df):
    df = df.copy(); df["final_price"] = pd.to_numeric(df["final_price"], errors="coerce")
    df["q"] = pd.to_numeric(df.get("quoted_price"), errors="coerce")
    df = df.dropna(subset=["final_price"]); df = df[(df.final_price >= 46) & (df.final_price <= 7300)]
    est = df["service_category"].map(lambda c: catmed.get(str(c), gmed)).fillna(gmed).astype(float)
    est = np.where(df["q"].fillna(0) > 0, df["q"].fillna(0), est)
    r = pd.DataFrame({"category": df["service_category"].astype(str).replace("nan", "Handyman"),
        "service_subtype": "", "zip_code": "", "booking_month": "2024-01", "deadline": "",
        "job_description": df["job_description"].astype(str),
        "original_estimate": est, "estimate_lo": est * 0.9, "estimate_hi": est * 1.1,
        "final_price": df["final_price"].astype(float)})
    r["in_production"] = r["category"].map(lambda c: is_production_category(normalize_category(c)))
    return r.reset_index(drop=True)

def oof(extra, seed):
    Xe = fe = oee = None
    if extra is not None and len(extra):
        Xe = align_to(build_features(extra)[0], names)
        fe = extra["final_price"].values.astype(float); oee = extra["original_estimate"].values.astype(float)
    pred = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        Xtr, ftr, otr = X_real.iloc[tr], fp_real[tr], oe_real[tr]
        if Xe is not None:
            Xtr = pd.concat([Xtr, Xe], ignore_index=True); ftr = np.concatenate([ftr, fe]); otr = np.concatenate([otr, oee])
        m = ConformalPriceModelV2(weight_power=0.5, seed=seed).fit(Xtr, ftr, otr)
        pred[te] = m.predict(X_real.iloc[te], oe_real[te])[:, 1]
    return mape(pred, fp_real), mape(pred[real_mask], fp_real[real_mask])

def avg(extra):
    a = np.array([oof(extra, s) for s in range(N)]); return a[:, 0].mean(), a[:, 1].mean()

tt = to_rows(pd.read_csv("data/external/scraped_marketplace.csv"))
rd = to_rows(pd.read_csv("data/external/scraped_pilot.csv"))
both = pd.concat([tt, rd], ignore_index=True)
print(f"Thumbtack marketplace rows: {len(tt)} | Reddit finals rows: {len(rd)}\n")
b_bl, b_rl = avg(None)
print(f"{'condition':28s} {'blended':>9s} {'real-only':>11s}")
print(f"{'baseline (411 only)':28s} {b_bl:>8.2f}% {b_rl:>10.2f}%")
for label, ex in [("+ Thumbtack marketplace", tt), ("+ Reddit finals", rd), ("+ both", both)]:
    bl, rl = avg(ex)
    print(f"{label:28s} {bl:>8.2f}% {rl:>10.2f}%   (Δbl {b_bl-bl:+.2f}, Δreal {b_rl-rl:+.2f})")
