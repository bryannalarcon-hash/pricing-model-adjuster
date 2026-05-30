#!/usr/bin/env python3
"""Parallel experiment runner. Evaluates a named registry of model factories with multi-seed OOF,
appends results to experiments/results.csv, prints unbuffered. Trees run single-threaded so the
parallelism is across configs (one process per config).

Usage: python3 -u experiments/run_batch.py <group> [seeds]
"""
import os
import sys
import csv
import time
import multiprocessing as mp

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from harness import evaluate, get_labeled
import models as M

RESULTS = os.path.join(os.path.dirname(__file__), "results.csv")


def _lgbm(obj, **kw):
    return lambda: M.LGBMResidual(objective=obj, n_jobs=1, **kw)


# Module-level registry (picklable via name dispatch).
def reg():
    R = {}
    R["lgbm_q50"] = _lgbm("quantile", alpha=0.5)
    R["lgbm_l1"] = _lgbm("mae")
    R["lgbm_l2"] = _lgbm("regression")
    R["lgbm_l2_tuned"] = _lgbm("regression", num_leaves=31, n_estimators=700, learning_rate=0.02)
    R["lgbm_l2_deep"] = _lgbm("regression", max_depth=6, num_leaves=31)
    R["lgbm_l2_shallow"] = _lgbm("regression", max_depth=3, num_leaves=7, n_estimators=600)
    R["lgbm_huber"] = _lgbm("huber", alpha=0.9)
    R["lgbm_fair"] = _lgbm("fair")
    R["lgbm_tweedie"] = _lgbm("tweedie")
    R["mape_obj"] = lambda: M.MAPEObjLGBM(n_jobs=1)
    R["wl1_pow1"] = lambda: M.WeightedLGBM(objective="mae", power=1.0, n_jobs=1)
    R["wl2_pow1"] = lambda: M.WeightedLGBM(objective="regression", power=1.0, n_jobs=1)
    R["wl2_pow0.5"] = lambda: M.WeightedLGBM(objective="regression", power=0.5, n_jobs=1)
    R["catboost_rmse"] = lambda: M.CatBoostResidual(loss="RMSE", thread_count=1)
    R["catboost_mae"] = lambda: M.CatBoostResidual(loss="MAE", thread_count=1)
    R["xgb_l2"] = lambda: M.XGBResidual(objective="reg:squarederror", n_jobs=1)
    R["tfidf_l2"] = lambda: M.LGBMResidualTFIDF(objective="regression", n_jobs=1)
    # weighting power sweep
    R["wl2_pow0.3"] = lambda: M.WeightedLGBM(objective="regression", power=0.3, n_jobs=1)
    R["wl2_pow0.7"] = lambda: M.WeightedLGBM(objective="regression", power=0.7, n_jobs=1)
    # target encoding (+ optional weighting)
    R["te_w0"] = lambda: M.LGBMResidualTE(weight_power=0.0, n_jobs=1)
    R["te_w0.5"] = lambda: M.LGBMResidualTE(weight_power=0.5, n_jobs=1)
    R["te_w1"] = lambda: M.LGBMResidualTE(weight_power=1.0, n_jobs=1)
    R["tfidf_w0.5"] = lambda: M.LGBMResidualTFIDF(objective="regression", n_jobs=1)
    # ensembles of the strong levers
    R["ens_wl2_cat_te"] = lambda: M.Ensemble([
        lambda: M.WeightedLGBM(objective="regression", power=0.5, n_jobs=1),
        lambda: M.CatBoostResidual(loss="RMSE", thread_count=1),
        lambda: M.LGBMResidualTE(weight_power=0.5, n_jobs=1)])
    R["ens_wl2_te"] = lambda: M.Ensemble([
        lambda: M.WeightedLGBM(objective="regression", power=0.5, n_jobs=1),
        lambda: M.LGBMResidualTE(weight_power=0.5, n_jobs=1)])
    R["ens_l2_cat_xgb"] = lambda: M.Ensemble([_lgbm("regression"),
                                              lambda: M.CatBoostResidual(loss="RMSE", thread_count=1),
                                              lambda: M.XGBResidual(objective="reg:squarederror", n_jobs=1)])
    R["ens_l2_tfidf"] = lambda: M.Ensemble([_lgbm("regression"),
                                            lambda: M.LGBMResidualTFIDF(objective="regression", n_jobs=1)])
    def wl2(**kw):
        return lambda: M.WeightedLGBM(objective="regression", power=0.5, n_jobs=1, **kw)
    R["hp_leaves7"] = wl2(num_leaves=7, max_depth=3)
    R["hp_leaves31"] = wl2(num_leaves=31, max_depth=6)
    R["hp_lr02_n700"] = wl2(learning_rate=0.02, n_estimators=700)
    R["hp_lr05_n250"] = wl2(learning_rate=0.05, n_estimators=250)
    R["hp_mcs10"] = wl2(min_child_samples=10)
    R["hp_mcs40"] = wl2(min_child_samples=40)
    R["hp_reg_hi"] = wl2(reg_lambda=3.0, reg_alpha=1.0)
    R["hp_ff06"] = wl2(colsample_bytree=0.6)
    R["wl2_pow0.4"] = lambda: M.WeightedLGBM(objective="regression", power=0.4, n_jobs=1)
    R["wl2_pow0.6"] = lambda: M.WeightedLGBM(objective="regression", power=0.6, n_jobs=1)
    R["hp_leaves31_mcs40"] = wl2(num_leaves=31, max_depth=6, min_child_samples=40)
    R["hp_n1000_lr015"] = wl2(n_estimators=1000, learning_rate=0.015)
    return R


GROUPS = {
    "losses": ["lgbm_q50", "lgbm_l1", "lgbm_l2", "lgbm_huber", "lgbm_fair", "lgbm_tweedie",
               "mape_obj", "wl1_pow1", "wl2_pow1", "wl2_pow0.5"],
    "depth": ["lgbm_l2", "lgbm_l2_tuned", "lgbm_l2_deep", "lgbm_l2_shallow"],
    "arch": ["lgbm_l2", "catboost_rmse", "xgb_l2", "tfidf_l2", "ens_l2_cat_xgb", "ens_l2_tfidf"],
    "feat": ["wl2_pow0.3", "wl2_pow0.5", "wl2_pow0.7", "te_w0", "te_w0.5", "te_w1",
             "tfidf_w0.5", "ens_wl2_cat_te", "ens_wl2_te"],
    "hp": ["wl2_pow0.5", "wl2_pow0.4", "wl2_pow0.6", "hp_leaves7", "hp_leaves31", "hp_lr02_n700",
           "hp_lr05_n250", "hp_mcs10", "hp_mcs40", "hp_reg_hi", "hp_ff06", "hp_leaves31_mcs40",
           "hp_n1000_lr015"],
}


def _work(args):
    name, seeds = args
    R = reg()
    t0 = time.time()
    try:
        r = evaluate(R[name], seeds=range(seeds))
        r["name"] = name; r["secs"] = round(time.time() - t0, 1); r["err"] = ""
    except Exception as e:
        r = {"name": name, "blended": float("nan"), "real": float("nan"), "err": str(e)[:80]}
    return r


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else "losses"
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    names = GROUPS.get(group, [group])  # allow a single name
    get_labeled()  # warm cache
    print(f"[batch] group={group} seeds={seeds} configs={len(names)}", flush=True)
    with mp.Pool(min(len(names), max(1, mp.cpu_count() - 1))) as pool:
        results = pool.map(_work, [(n, seeds) for n in names])
    results = [r for r in results if r]
    results.sort(key=lambda r: (r.get("real", 1e9)))
    new = not os.path.exists(RESULTS)
    with open(RESULTS, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "blended", "blended_std", "real", "real_std",
                                           "base_blended", "base_real", "n_real", "secs", "err"])
        if new:
            w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    print(f"{'name':22s} {'blended':>14s} {'real-only':>14s}", flush=True)
    for r in results:
        if r.get("err"):
            print(f"{r['name']:22s}  ERROR: {r['err']}", flush=True)
        else:
            print(f"{r['name']:22s} {r['blended']:6.2f}±{r['blended_std']:.2f}  "
                  f"{r['real']:6.2f}±{r['real_std']:.2f}", flush=True)


if __name__ == "__main__":
    main()
