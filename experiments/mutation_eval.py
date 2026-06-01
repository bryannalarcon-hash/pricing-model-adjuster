"""Mutation-engine experiment (user-requested).

Hypothesis under test: does 10x-ing the labeled rows — keeping the category distribution,
just replicating each row with small numeric jitter — improve OOF MAPE and/or raise
confidence on sparse categories?

LEAKAGE DISCIPLINE (load-bearing): the mutation engine only ever expands a fold's TRAIN
split. The held-out test rows are the ORIGINAL 411 real rows, never mutated, and no mutated
copy of a test row ever enters training. Anything else fakes the result.

Two parts:
  A. OOF eval  — baseline (no aug) vs +mutation(10x), blended + real-only MAPE, multi-seed.
  B. Samples   — build the full deployed-style bundle WITH and WITHOUT mutation, then price the
                 dashboard's Predict samples to show the effect on confidence/midpoint.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features, align_to
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import make_folds, ape, mape, baseline_blended
from houseprice.confidence import ConfidenceCalibrator
from houseprice.predict import _novelty, predict_one

FACTOR = 10
N_SEEDS = 5
NOVELTY_K = 10
JITTER = 0.05  # ~5% lognormal multiplicative noise on price fields

lab = labeled(load_dataset()).reset_index(drop=True)
FP = lab["final_price"].values.astype(float)
OE = lab["original_estimate"].values.astype(float)
REAL = ape(OE, FP) > 0.20


# --------------------------------------------------------------------------- #
# THE MUTATION ENGINE
# --------------------------------------------------------------------------- #
def mutate(df: pd.DataFrame, factor: int, rng) -> pd.DataFrame:
    """Expand df to `factor`x rows, preserving the category distribution exactly (each row is
    replicated `factor` times). The original rows are kept; the (factor-1) extra copies get
    independent ~JITTER lognormal multiplicative noise on the price fields (original_estimate,
    estimate_lo/hi, final_price). Category / zip / description / subtype are untouched, so the
    distribution and text features are identical — this is jittered oversampling, not new signal.
    """
    parts = [df.copy()]
    n = len(df)
    for _ in range(factor - 1):
        m = df.copy()
        oj = np.exp(rng.normal(0.0, JITTER, n))   # estimate jitter
        fj = np.exp(rng.normal(0.0, JITTER, n))   # final jitter (independent -> residual spreads)
        m["original_estimate"] = df["original_estimate"].values * oj
        m["estimate_lo"] = df["estimate_lo"].values * oj
        m["estimate_hi"] = df["estimate_hi"].values * oj
        m["final_price"] = df["final_price"].values * fj
        parts.append(m)
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------- #
# PART A — leakage-safe OOF eval
# --------------------------------------------------------------------------- #
def oof(augment: bool, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pred = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        train_df = lab.iloc[tr].reset_index(drop=True)
        if augment:
            train_df = mutate(train_df, FACTOR, rng)            # TRAIN split only
        Xtr_base, base_names = build_features(train_df)
        ftr = train_df["final_price"].values.astype(float)
        otr = train_df["original_estimate"].values.astype(float)
        sc = StandardScaler().fit(Xtr_base.values)
        nn = NearestNeighbors(n_neighbors=NOVELTY_K + 1).fit(sc.transform(Xtr_base.values))
        Xtr = Xtr_base.copy()
        Xtr["novelty"] = _novelty(sc.transform(Xtr_base.values), nn, NOVELTY_K)
        te_df = lab.iloc[te]                                     # ORIGINAL held-out rows
        Xte_base = align_to(build_features(te_df)[0], base_names)
        Xte = Xte_base.copy()
        Xte["novelty"] = _novelty(sc.transform(Xte_base.values), nn, NOVELTY_K)
        m = ConformalPriceModelV2(weight_power=0.5, seed=seed).fit(Xtr, ftr, otr)
        pred[te] = m.predict(Xte, OE[te])[:, 1]
    return pred


def run_eval():
    base = np.array([(lambda p: (mape(p, FP), mape(p[REAL], FP[REAL])))(oof(False, s))
                     for s in range(N_SEEDS)])
    aug = np.array([(lambda p: (mape(p, FP), mape(p[REAL], FP[REAL])))(oof(True, s))
                    for s in range(N_SEEDS)])
    print("PART A — leakage-safe OOF (train mutated 10x; test = original 411 real rows)\n")
    print(f"{'condition':26s} {'blended':>9s} {'real-only':>11s}")
    print(f"{'baseline (no aug)':26s} {base[:,0].mean():>8.2f}% {base[:,1].mean():>10.2f}%")
    dbl = base[:, 0].mean() - aug[:, 0].mean()
    drl = base[:, 1].mean() - aug[:, 1].mean()
    print(f"{'+ mutation 10x':26s} {aug[:,0].mean():>8.2f}% {aug[:,1].mean():>10.2f}%   "
          f"(Δbl {dbl:+.2f}, Δreal {drl:+.2f}; + = better)")
    print(f"\nbaseline blended (orig estimate): {baseline_blended(lab):.2f}%   "
          f"(seed std: bl {base[:,0].std():.2f} / aug {aug[:,0].std():.2f})")


# --------------------------------------------------------------------------- #
# PART B — full bundle with/without mutation, scored on the dashboard samples
# --------------------------------------------------------------------------- #
def build_bundle(augment: bool, seed: int = 42) -> dict:
    df = load_dataset()
    train_df = lab.copy()
    if augment:
        train_df = mutate(train_df, FACTOR, np.random.default_rng(seed))
    X_base, base_names = build_features(train_df)
    fp = train_df["final_price"].values.astype(float)
    oe = train_df["original_estimate"].values.astype(float)
    sc = StandardScaler().fit(X_base.values)
    nn = NearestNeighbors(n_neighbors=NOVELTY_K + 1).fit(sc.transform(X_base.values))
    train_nov = _novelty(sc.transform(X_base.values), nn, NOVELTY_K)
    X_lab = X_base.copy(); X_lab["novelty"] = train_nov
    model = ConformalPriceModelV2(weight_power=0.5).fit(X_lab, fp, oe)
    # OOF-ish calibrator inputs: reuse the full-model preds for width refs (parity w/ train.py shape)
    lo, mid, hi = model.predict(X_lab, oe).T
    observed = (df["estimate_hi"] - df["estimate_lo"]).dropna().values
    cat_counts = train_df["category"].value_counts().to_dict()
    cal = ConfidenceCalibrator.fit(lo, hi, mid, observed, cat_counts=cat_counts)
    cal.novelty_ref = float(np.median(train_nov))
    cal.novelty_p95 = float(np.quantile(train_nov, 0.95))
    cat_anchor = df.groupby("category")["original_estimate"].median().dropna().to_dict()
    return {
        "model": model, "calibrator": cal, "feature_names": list(X_lab.columns),
        "census": None, "model_version": "mut10x" if augment else "baseline",
        "cat_anchor": {k: float(v) for k, v in cat_anchor.items()},
        "global_anchor": float(df["original_estimate"].median()),
        "scaler": sc, "novelty_nn": nn, "novelty_k": NOVELTY_K,
    }


SAMPLES = {
    "Cleaning · standard": {"job_id": "s1", "service_category": "Cleaning", "zip_code": "75062",
        "job_description": "Standard 2 bedroom apartment cleaning", "original_estimate": 160},
    "HVAC · tune-up": {"job_id": "s2", "service_category": "HVAC", "zip_code": "33324",
        "job_description": "AC tune-up and filter replacement", "original_estimate": 200},
    "Plumbing · water heater": {"job_id": "s3", "service_category": "Plumbing", "zip_code": "78704",
        "job_description": "50-gal gas water heater won't stay lit, needs replacement", "original_estimate": 1850},
    "Plumbing · small fix": {"job_id": "s4", "service_category": "Plumbing", "zip_code": "33484",
        "job_description": "Replace kitchen sink shutoff valve", "original_estimate": 150},
    "Remodel · large (OOD)": {"job_id": "s5", "service_category": "Remodeling", "zip_code": "75062",
        "job_description": "Full kitchen remodel, cabinets counters flooring", "original_estimate": 7200},
    "Auto · out-of-category": {"job_id": "s6", "service_category": "Auto", "zip_code": "33324",
        "job_description": "Full interior and exterior detail, midsize SUV", "original_estimate": 280},
}


def run_samples():
    os.environ.setdefault("SCOPE_BACKEND", "deterministic")
    base_b = build_bundle(False)
    aug_b = build_bundle(True)
    print("\nPART B — dashboard samples: confidence (midpoint) baseline vs +mutation 10x\n")
    print(f"{'sample':26s} {'baseline':>20s} {'+mutation 10x':>20s}")
    for name, payload in SAMPLES.items():
        b = predict_one(base_b, payload)
        a = predict_one(aug_b, payload)
        print(f"{name:26s} "
              f"{b['confidence']:>7.3f} (${b['estimate_midpoint']:>7.0f})   "
              f"{a['confidence']:>7.3f} (${a['estimate_midpoint']:>7.0f})")
    print("\nConfidence bands: >=0.80 green / 0.50-0.79 amber / <0.50 red.")


if __name__ == "__main__":
    print(f"rows: {len(lab)} -> {len(lab) * FACTOR} at {FACTOR}x "
          f"(category distribution preserved, ~{int(JITTER*100)}% price jitter)\n")
    run_eval()
    run_samples()
