"""Train the production bundle, generate predictions.csv, write the eval report.

Leakage discipline:
  - Reported metrics + the predictions.csv rows for the 411 LABELED rows are OUT-OF-FOLD
    (each scored by a model that never saw it) — so the graded MAPE == the honest OOF MAPE.
  - The deployed bundle is the full model fit on all 411 (used for unlabeled rows + the live API).
"""
from __future__ import annotations

import os
import pickle
import numpy as np
import pandas as pd

from . import MODEL_VERSION
from .data_load import load_dataset, labeled
from .features import build_features
from .model_v2 import ConformalPriceModelV2, oof_predict_bagged, LO_Q, HI_Q
from .confidence import ConfidenceCalibrator
from .eval import ape, mape, baseline_blended

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(ROOT, "model")
PRED_PATH = os.path.join(ROOT, "predictions", "predictions.csv")
REPORT_PATH = os.path.join(ROOT, "reports", "eval_report.md")
SCOPE_CACHE = os.path.join(ROOT, "data", "processed", "scope.parquet")
REAL_THR = 0.20


def _scope():
    if os.path.exists(SCOPE_CACHE):
        return pd.read_parquet(SCOPE_CACHE)
    return None


def _census():
    p = os.path.join(ROOT, "data", "external", "zip_acs.csv")
    return pd.read_csv(p, dtype={"zip_code": str}) if os.path.exists(p) else None


def _oof_bagged_with_novelty(lab, X_base, fp, oe, seeds=range(6), k=10, weight_power=0.5):
    """Leakage-safe bagged OOF with a per-fold novelty feature: the novelty index is refit on each
    train split only, so a held-out row's novelty never sees other held-out rows (JOURNAL R17)."""
    from .eval import make_folds
    from sklearn.preprocessing import StandardScaler
    from sklearn.neighbors import NearestNeighbors
    from .predict import _novelty
    acc = np.zeros((len(lab), 3))
    seeds = list(seeds)
    for s in seeds:
        out = np.full((len(lab), 3), np.nan)
        for tr, te in make_folds(lab, k=5, seed=s):
            sc = StandardScaler().fit(X_base.iloc[tr].values)
            nn = NearestNeighbors(n_neighbors=k + 1).fit(sc.transform(X_base.iloc[tr].values))
            Xtr, Xte = X_base.iloc[tr].copy(), X_base.iloc[te].copy()
            Xtr["novelty"] = _novelty(sc.transform(X_base.iloc[tr].values), nn, k)
            Xte["novelty"] = _novelty(sc.transform(X_base.iloc[te].values), nn, k)
            m = ConformalPriceModelV2(weight_power=weight_power, seed=s).fit(Xtr, fp[tr], oe[tr])
            out[te] = m.predict(Xte, oe[te])
        acc += out
    acc /= len(seeds)
    return acc[:, 0], acc[:, 1], acc[:, 2]


def main(scope_backend_label: str = "deterministic"):
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(PRED_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)

    df = load_dataset()
    # v2: LLM scope adds nothing over deterministic features (JOURNAL R3/R5: 10.78 vs 10.74,
    # within noise) — train scope-free for zero train/serve skew and no LLM dependency.
    scope_all = None
    census = _census()
    lab = labeled(df).reset_index(drop=True)
    lab_idx = df.index[df["is_labeled"]].tolist()
    scope_lab = scope_all.reindex(lab_idx).reset_index(drop=True) if scope_all is not None else None

    # ---- base features; novelty is added leakage-safely (per fold for OOF, full index for serving) ----
    from sklearn.preprocessing import StandardScaler
    from sklearn.neighbors import NearestNeighbors
    from .predict import _novelty
    NOVELTY_K = 10
    X_base, base_names = build_features(lab, scope_df=scope_lab, census_df=census)
    fp_lab = lab["final_price"].values
    oe_lab = lab["original_estimate"].values

    # ---- Bagged OOF (leakage-free) WITH a per-fold novelty feature (JOURNAL R16/R17) ----
    lo_oof, mid_oof, hi_oof = _oof_bagged_with_novelty(lab, X_base, fp_lab, oe_lab,
                                                       seeds=range(6), k=NOVELTY_K)
    base = ape(lab["original_estimate"], lab["final_price"])
    real_mask = base > REAL_THR
    blended = mape(mid_oof, lab["final_price"])
    real = mape(mid_oof[real_mask], lab["final_price"].values[real_mask])
    base_blended = baseline_blended(lab)
    base_real = 100 * base[real_mask].mean()
    cov = float(((fp_lab >= lo_oof) & (fp_lab <= hi_oof)).mean())

    # ---- Novelty index (fit on BASE features of all labeled) + full model trained WITH novelty ----
    nov_scaler = StandardScaler().fit(X_base.values)
    nov_nn = NearestNeighbors(n_neighbors=NOVELTY_K + 1).fit(nov_scaler.transform(X_base.values))
    train_nov = _novelty(nov_scaler.transform(X_base.values), nov_nn, NOVELTY_K)
    X_lab = X_base.copy()
    X_lab["novelty"] = train_nov
    names = list(X_lab.columns)
    full = ConformalPriceModelV2(weight_power=0.5).fit(X_lab, fp_lab, oe_lab)
    observed_ranges = (df["estimate_hi"] - df["estimate_lo"]).dropna().values  # all observed ranges
    cat_counts = lab["category"].value_counts().to_dict()  # data-density for confidence
    cal = ConfidenceCalibrator.fit(lo_oof, hi_oof, mid_oof, observed_ranges, cat_counts=cat_counts)
    cal.novelty_ref = float(np.median(train_nov))
    cal.novelty_p95 = float(np.quantile(train_nov, 0.95))
    # Category price anchors (full-dataset original_estimate medians) so requests WITHOUT an
    # original_estimate (optional per Appendix A) still get a sane anchor to correct from.
    cat_anchor = df.groupby("category")["original_estimate"].median().dropna().to_dict()
    global_anchor = float(df["original_estimate"].median())
    bundle = {
        "model": full, "calibrator": cal, "feature_names": names, "census": census,
        "model_version": MODEL_VERSION, "scope_backend": scope_backend_label,
        "median_range": cal.median_range, "trained_rows": int(len(lab)),
        "cat_anchor": {k: float(v) for k, v in cat_anchor.items()}, "global_anchor": global_anchor,
        "scaler": nov_scaler, "novelty_nn": nov_nn, "novelty_k": NOVELTY_K,
    }
    with open(os.path.join(MODEL_DIR, "bundle.pkl"), "wb") as fh:
        pickle.dump(bundle, fh)

    # ---- predictions.csv: OOF for labeled rows, full-model for unlabeled ----
    all_lo = np.full(len(df), np.nan); all_mid = np.full(len(df), np.nan); all_hi = np.full(len(df), np.nan)
    for j, i in enumerate(lab_idx):
        all_lo[i], all_mid[i], all_hi[i] = lo_oof[j], mid_oof[j], hi_oof[j]
    unlab_idx = df.index[~df["is_labeled"]].tolist()
    nov_all = np.full(len(df), np.nan)
    for j, i in enumerate(lab_idx):
        nov_all[i] = train_nov[j]
    if unlab_idx:
        from .features import align_to
        sub = df.loc[unlab_idx].reset_index(drop=True)
        scope_un = scope_all.reindex(unlab_idx).reset_index(drop=True) if scope_all is not None else None
        Xu_base = align_to(build_features(sub, scope_df=scope_un, census_df=census)[0], base_names)
        nov_u = _novelty(nov_scaler.transform(Xu_base.values), nov_nn, NOVELTY_K)
        Xu = Xu_base.copy()
        Xu["novelty"] = nov_u
        pu = full.predict(align_to(Xu, names), sub["original_estimate"].values)
        for k, i in enumerate(unlab_idx):
            all_lo[i], all_mid[i], all_hi[i] = pu[k, 0], pu[k, 1], pu[k, 2]
            nov_all[i] = nov_u[k]
    confs = []
    for i in range(len(df)):
        c, _ = cal.score(all_lo[i], all_hi[i], all_mid[i], bool(df["in_production"].iloc[i]),
                         category=df["category"].iloc[i], novelty=nov_all[i])
        confs.append(c)
    out = pd.DataFrame({
        "job_id": df["job_id"], "service_category": df["category"],
        "estimate_lo": np.round(all_lo, 2), "estimate_hi": np.round(all_hi, 2),
        "estimate_midpoint": np.round(all_mid, 2), "confidence": confs,
        "is_labeled": df["is_labeled"].values, "model_version": MODEL_VERSION,
    })
    out.to_csv(PRED_PATH, index=False)

    report = f"""# Eval report — {MODEL_VERSION}

Leakage-free 5-fold out-of-fold on the {len(lab)} labeled rows. Scope backend: **{scope_backend_label}**.

| Metric | Model | Baseline | Pass |
|---|---|---|---|
| Blended MAPE (all {len(lab)}) | **{blended:.2f}%** | {base_blended:.2f}% | {'✅' if blended < base_blended else '❌'} |
| Real-only MAPE (n={int(real_mask.sum())}, base_ape>{REAL_THR:.0%}) | **{real:.2f}%** | {base_real:.2f}% | {'✅' if real < base_real else '❌'} |
| Interval coverage (target {int((HI_Q-LO_Q)*100)}%) | {cov*100:.1f}% | — | {'✅' if cov >= (HI_Q-LO_Q) - 0.05 else '⚠️'} |

predictions.csv: {len(lab)} labeled rows are OOF (leakage-free); {len(df)-len(lab)} unlabeled use the full model.
"""
    with open(REPORT_PATH, "w") as fh:
        fh.write(report)
    print(report)
    print(f"saved model/bundle.pkl, {PRED_PATH}, {REPORT_PATH}")
    return dict(blended=blended, real=real, base_blended=base_blended, base_real=base_real, coverage=cov)


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "deterministic")
