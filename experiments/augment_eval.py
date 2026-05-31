"""Full augmentation eval: do the scraped FINALS help? Train on the 411 real rows + scraped rows,
evaluate leakage-safely OOF on the 411 real HouseAccount rows ONLY (scraped rows never enter the
eval fold). Compare baseline vs +scraped. Two arms:
  PAIRS : scraped rows that have a real quote (original_estimate=quoted_price, final=final_price)
  ALL   : every scraped final, original_estimate synthesized as the OUR-category-median estimate
          (so the residual = how the scraped final differs from a typical estimate for that category)
Reports blended + real-only MAPE (vs baseline 411-only), multi-seed, adopt/reject.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from houseprice.data_load import load_dataset, labeled, normalize_category, is_production_category
from houseprice.features import build_features, align_to
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import make_folds, ape, mape

N_SEEDS = 6
SCRAPED = "data/external/scraped_pilot.csv"

lab = labeled(load_dataset()).reset_index(drop=True)
fp_real = lab["final_price"].values.astype(float)
oe_real = lab["original_estimate"].values.astype(float)
real_mask = ape(oe_real, fp_real) > 0.20
X_real, names = build_features(lab)
cat_med_est = lab.groupby("category")["original_estimate"].median().to_dict()
glob_med_est = float(lab["original_estimate"].median())

def scraped_rows(arm):
    df = pd.read_csv(SCRAPED)
    df["final_price"] = pd.to_numeric(df["final_price"], errors="coerce")
    df["quoted_price"] = pd.to_numeric(df.get("quoted_price"), errors="coerce")
    df = df.dropna(subset=["final_price"])
    if arm == "PAIRS":
        df = df[df["quoted_price"] > 0].copy()
        df["orig_est"] = df["quoted_price"]
    else:  # ALL: synthesize estimate = our category-median estimate
        df = df.copy()
        df["cat_norm"] = df["service_category"].map(lambda c: normalize_category(str(c)))
        df["orig_est"] = df["service_category"].map(lambda c: cat_med_est.get(str(c), glob_med_est)).fillna(glob_med_est)
        df.loc[df["quoted_price"] > 0, "orig_est"] = df["quoted_price"]  # use real quote when present
    rows = pd.DataFrame({
        "category": df["service_category"].map(lambda c: str(c) if str(c) != "nan" else "Handyman"),
        "service_subtype": "", "zip_code": df.get("zip_code", "").astype(str),
        "booking_month": df["year"].map(lambda y: f"{int(y)}-01" if pd.notna(y) else "2024-01"),
        "job_description": df["job_description"].astype(str), "deadline": "",
        "original_estimate": df["orig_est"].astype(float),
        "estimate_lo": df["orig_est"].astype(float) * 0.9, "estimate_hi": df["orig_est"].astype(float) * 1.1,
        "final_price": df["final_price"].astype(float),
    })
    rows["in_production"] = rows["category"].map(lambda c: is_production_category(normalize_category(c)))
    rows = rows[(rows["final_price"] >= 46) & (rows["final_price"] <= 7300) & (rows["original_estimate"] > 0)]
    return rows.reset_index(drop=True)

def oof_blended_real(extra=None, seed=42):
    Xe = fe = oee = None
    if extra is not None and len(extra):
        Xe = align_to(build_features(extra)[0], names)
        fe = extra["final_price"].values.astype(float); oee = extra["original_estimate"].values.astype(float)
    pred = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        Xtr, ftr, otr = X_real.iloc[tr], fp_real[tr], oe_real[tr]
        if Xe is not None:
            Xtr = pd.concat([Xtr, Xe], ignore_index=True)
            ftr = np.concatenate([ftr, fe]); otr = np.concatenate([otr, oee])
        m = ConformalPriceModelV2(weight_power=0.5, seed=seed).fit(Xtr, ftr, otr)
        pred[te] = m.predict(X_real.iloc[te], oe_real[te])[:, 1]
    return mape(pred, fp_real), mape(pred[real_mask], fp_real[real_mask])

def run(label, extra):
    bl = np.array([oof_blended_real(extra, s) for s in range(N_SEEDS)])
    return bl[:, 0].mean(), bl[:, 1].mean()

if __name__ == "__main__":
    pairs = scraped_rows("PAIRS"); allf = scraped_rows("ALL")
    print(f"scraped usable -> PAIRS: {len(pairs)} rows | ALL: {len(allf)} rows\n")
    b_bl, b_rl = run("baseline", None)
    print(f"{'condition':22s} {'blended':>9s} {'real-only':>11s}")
    print(f"{'baseline (411 only)':22s} {b_bl:>8.2f}% {b_rl:>10.2f}%")
    for label, extra in [("+ scraped PAIRS", pairs), ("+ scraped ALL (synth est)", allf)]:
        bl, rl = run(label, extra)
        print(f"{label:22s} {bl:>8.2f}% {rl:>10.2f}%   "
              f"(Δbl {b_bl-bl:+.2f}, Δreal {b_rl-rl:+.2f}; + = better)")
    print("\nLeakage-safe: scraped rows only ever in TRAIN folds; OOF scored on the 411 real rows.")
