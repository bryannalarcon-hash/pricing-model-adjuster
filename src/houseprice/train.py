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

    # ---- Bagged OOF predictions for the labeled rows (honest, leakage-free, low-variance) ----
    lo_oof, mid_oof, hi_oof = oof_predict_bagged(lab, build_features, scope_df=scope_lab,
                                                 census_df=census, seeds=range(6))
    base = ape(lab["original_estimate"], lab["final_price"])
    real_mask = base > REAL_THR
    blended = mape(mid_oof, lab["final_price"])
    real = mape(mid_oof[real_mask], lab["final_price"].values[real_mask])
    base_blended = baseline_blended(lab)
    base_real = 100 * base[real_mask].mean()
    cov = float(((lab["final_price"].values >= lo_oof) & (lab["final_price"].values <= hi_oof)).mean())

    # ---- Full model on all labeled (deployed) ----
    X_lab, names = build_features(lab, scope_df=scope_lab, census_df=census)
    full = ConformalPriceModelV2(weight_power=0.5).fit(
        X_lab, lab["final_price"].values, lab["original_estimate"].values)
    observed_ranges = (df["estimate_hi"] - df["estimate_lo"]).dropna().values  # all observed ranges
    cal = ConfidenceCalibrator.fit(lo_oof, hi_oof, mid_oof, observed_ranges)
    # Category price anchors (full-dataset original_estimate medians) so requests WITHOUT an
    # original_estimate (optional per Appendix A) still get a sane anchor to correct from.
    cat_anchor = df.groupby("category")["original_estimate"].median().dropna().to_dict()
    global_anchor = float(df["original_estimate"].median())
    bundle = {
        "model": full, "calibrator": cal, "feature_names": names, "census": census,
        "model_version": MODEL_VERSION, "scope_backend": scope_backend_label,
        "median_range": cal.median_range, "trained_rows": int(len(lab)),
        "cat_anchor": {k: float(v) for k, v in cat_anchor.items()}, "global_anchor": global_anchor,
    }
    with open(os.path.join(MODEL_DIR, "bundle.pkl"), "wb") as fh:
        pickle.dump(bundle, fh)

    # ---- predictions.csv: OOF for labeled rows, full-model for unlabeled ----
    all_lo = np.full(len(df), np.nan); all_mid = np.full(len(df), np.nan); all_hi = np.full(len(df), np.nan)
    for j, i in enumerate(lab_idx):
        all_lo[i], all_mid[i], all_hi[i] = lo_oof[j], mid_oof[j], hi_oof[j]
    unlab_idx = df.index[~df["is_labeled"]].tolist()
    if unlab_idx:
        sub = df.loc[unlab_idx].reset_index(drop=True)
        scope_un = scope_all.reindex(unlab_idx).reset_index(drop=True) if scope_all is not None else None
        Xu, _ = build_features(sub, scope_df=scope_un, census_df=census)
        from .features import align_to
        pu = full.predict(align_to(Xu, names), sub["original_estimate"].values)
        for k, i in enumerate(unlab_idx):
            all_lo[i], all_mid[i], all_hi[i] = pu[k, 0], pu[k, 1], pu[k, 2]

    confs = []
    for i in range(len(df)):
        c, _ = cal.score(all_lo[i], all_hi[i], all_mid[i], bool(df["in_production"].iloc[i]))
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
