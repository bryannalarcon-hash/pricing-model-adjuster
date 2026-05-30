"""Eval layer: MAPE metrics, leakage-free out-of-fold runner, real/synthetic split.

The two graded numbers:
  - blended MAPE on all 411 priced rows (baseline 11.6%)
  - real-only MAPE on the genuinely-real (non-augmented) subset (baseline ~40%)

All model metrics are OUT-OF-FOLD: a row is always scored by a model trained without it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from .data_load import load_dataset, labeled


def ape(pred, actual) -> np.ndarray:
    pred = np.asarray(pred, float)
    actual = np.asarray(actual, float)
    return np.abs(pred - actual) / np.abs(actual)


def mape(pred, actual) -> float:
    return float(np.mean(ape(pred, actual)) * 100.0)


def baseline_blended(df_lab: pd.DataFrame) -> float:
    """Reproduce the official baseline: original_estimate midpoint vs final_price."""
    return mape(df_lab["original_estimate"], df_lab["final_price"])


def stratify_key(df_lab: pd.DataFrame) -> pd.Series:
    """Stratify folds by category (collapse tiny categories) so each fold is representative."""
    vc = df_lab["category"].value_counts()
    small = set(vc[vc < 5].index)
    return df_lab["category"].where(~df_lab["category"].isin(small), other="__small__")


def make_folds(df_lab: pd.DataFrame, k: int = 5, seed: int = 42):
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
    return list(skf.split(df_lab, stratify_key(df_lab)))


def detect_synthetic(df_lab: pd.DataFrame) -> pd.Series:
    """Heuristic flag for augmented/synthetic rows.

    The dataset note says sparse categories were 'augmented'. Augmented rows tend to have
    final_price generated to sit at a near-fixed fraction of the estimate range (low, stable
    baseline APE), whereas genuinely-real rows show wide, messy deviation from the old estimate.
    We flag a row as synthetic if final_price lands very close to the estimate midpoint's
    implied position consistently. The concrete definition is calibrated in the diagnostic and
    finalized in ASSUMPTIONS.md; this function is the single switch used by real_only_mask().
    """
    pos = (df_lab["final_price"] - df_lab["estimate_lo"]) / (
        df_lab["estimate_hi"] - df_lab["estimate_lo"]
    ).replace(0, np.nan)
    # placeholder; real definition set after diagnostic (see __main__).
    return pos.notna() & False


def diagnostic():
    df = load_dataset()
    lab = labeled(df)
    print("=== blended baseline ===")
    print("blended MAPE all %d : %.2f%%" % (len(lab), baseline_blended(lab)))
    a = ape(lab["original_estimate"], lab["final_price"])
    lab = lab.assign(base_ape=a)
    print("\n=== per-category baseline APE (labeled) ===")
    g = lab.groupby("category").agg(
        n=("final_price", "size"),
        base_mape=("base_ape", lambda x: 100 * x.mean()),
        med_ape=("base_ape", lambda x: 100 * x.median()),
    ).sort_values("base_mape")
    print(g.to_string(float_format=lambda v: f"{v:6.1f}"))

    print("\n=== position-in-range stats (synthetic tell) ===")
    pos = (lab["final_price"] - lab["estimate_lo"]) / (lab["estimate_hi"] - lab["estimate_lo"])
    lab = lab.assign(pos=pos)
    for cat, sub in lab.groupby("category"):
        print(f"  {cat:20s} n={len(sub):3d}  pos mean={sub.pos.mean():.3f} std={sub.pos.std():.3f}"
              f"  base_mape={100*sub.base_ape.mean():5.1f}%")

    # Hypothesis test: split by whether final_price == a clean function of the range.
    print("\n=== APE if we call high-APE-categories 'real' ===")
    for thr in (0.20, 0.25, 0.30):
        real = lab[lab.base_ape > thr]
        print(f"  rows with base_ape>{thr:.0%}: n={len(real):3d}  their baseline MAPE={100*real.base_ape.mean():.1f}%")


if __name__ == "__main__":
    diagnostic()
