"""Rigorous multi-seed OOF harness for model-architecture experiments.

Scores the POINT estimate (what MAPE grades) via repeated 5-fold out-of-fold, averaged over many
seeds to separate signal from fold-noise. Each model is a factory exposing:
    fit(lab_train_df) -> self      # trains on raw labeled rows (build any features internally)
    predict(lab_test_df) -> np.ndarray of midpoint predictions
The raw labeled DataFrame (with scope columns attached) is passed so each approach can engineer its
own features (native categoricals for CatBoost, text for embeddings, etc.).
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from houseprice.data_load import load_dataset, labeled
from houseprice.eval import ape, mape, baseline_blended, stratify_key
from sklearn.model_selection import StratifiedKFold

REAL_THR = 0.20


def get_labeled(with_scope=True):
    df = load_dataset()
    lab = labeled(df).reset_index(drop=True)
    lab_idx = df.index[df["is_labeled"]].tolist()
    if with_scope and os.path.exists("data/processed/scope.parquet"):
        sc = pd.read_parquet("data/processed/scope.parquet").reindex(lab_idx).reset_index(drop=True)
        for c in ["scope_sqft", "scope_fixture_count", "scope_complexity", "scope_urgency"]:
            lab[c] = pd.to_numeric(sc[c], errors="coerce").fillna(-1) if c in sc else -1
    return lab


def _folds(lab, k, seed):
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
    return list(skf.split(lab, stratify_key(lab)))


def evaluate(factory, lab=None, seeds=range(10), k=5, verbose=False):
    """Return dict with multi-seed mean/std of blended & real-only MAPE + coverage if intervals."""
    if lab is None:
        lab = get_labeled()
    base = np.asarray(ape(lab["original_estimate"], lab["final_price"]))
    real = base > REAL_THR
    fp = lab["final_price"].values
    bl, rl = [], []
    for s in seeds:
        preds = np.full(len(lab), np.nan)
        for tr, te in _folds(lab, k, s):
            m = factory()
            m.fit(lab.iloc[tr].reset_index(drop=True))
            preds[te] = np.asarray(m.predict(lab.iloc[te].reset_index(drop=True)), float)
        bl.append(mape(preds, fp))
        rl.append(mape(preds[real], fp[real]))
    out = dict(blended=float(np.mean(bl)), blended_std=float(np.std(bl)),
               real=float(np.mean(rl)), real_std=float(np.std(rl)),
               base_blended=baseline_blended(lab), base_real=float(100 * base[real].mean()),
               n_real=int(real.sum()))
    if verbose:
        print(f"  blended {out['blended']:.2f}±{out['blended_std']:.2f}  "
              f"real {out['real']:.2f}±{out['real_std']:.2f}  "
              f"(base {out['base_blended']:.2f} / {out['base_real']:.1f})")
    return out


def split_lockbox(lab, frac=0.2, seed=2024):
    """Fixed stratified hold-out, never used during experimentation. Final sanity check only."""
    from sklearn.model_selection import train_test_split
    tr, lb = train_test_split(lab, test_size=frac, random_state=seed, stratify=stratify_key(lab))
    return tr.reset_index(drop=True), lb.reset_index(drop=True)


def eval_lockbox(factory, n_bag=5):
    """Train on the 80% experimentation split (bagged over n_bag fits), evaluate on the 20% lockbox.
    Returns blended & real-only MAPE on the lockbox (noisy: ~82 rows). Gross-overfit guard."""
    lab = get_labeled()
    exp, lb = split_lockbox(lab)
    base = np.asarray(ape(lb["original_estimate"], lb["final_price"]))
    real = base > REAL_THR
    oe = np.clip(lb["original_estimate"].values.astype(float), 1, None)
    logs = []
    for b in range(n_bag):
        m = factory()
        # vary the bag if the factory supports a seed via attribute; else identical (still fine)
        m.fit(exp.sample(frac=1.0, replace=True, random_state=b).reset_index(drop=True))
        logs.append(np.log(np.clip(np.asarray(m.predict(lb), float), 1, None) / oe))
    mid = oe * np.exp(np.mean(logs, axis=0))
    fp = lb["final_price"].values
    return dict(blended=mape(mid, fp), real=mape(mid[real], fp[real]),
                base_blended=mape(lb["original_estimate"], fp),
                base_real=float(100 * base[real].mean()), n=len(lb), n_real=int(real.sum()))


def compare(factories: dict, seeds=range(10)):
    lab = get_labeled()
    _b = ape(lab["original_estimate"], lab["final_price"])
    print(f"baseline: blended {baseline_blended(lab):.2f}%  real {100*_b[_b>REAL_THR].mean():.2f}%")
    print(f"{'model':22s} {'blended':>16s} {'real-only':>16s}")
    results = {}
    for name, fac in factories.items():
        r = evaluate(fac, lab, seeds=seeds)
        results[name] = r
        print(f"{name:22s} {r['blended']:6.2f} ±{r['blended_std']:.2f}    {r['real']:6.2f} ±{r['real_std']:.2f}")
    return results
