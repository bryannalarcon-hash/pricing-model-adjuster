"""Option 1 — novelty / k-NN-reference / category-relative-uncertainty as POINT-ESTIMATE features.

All three computed LEAKAGE-SAFE per fold (neighbors & category stats from the TRAIN split only;
the k-NN reference residual uses train labels only). Paired multi-seed OOF, adopt/reject per JOURNAL.

  novelty : mean distance to K nearest TRAIN rows in standardized feature space (atypicality).
  knn_ref : mean residual log(final/est) of the K nearest TRAIN rows (data-driven correction signal).
  cat_unc : z-score of rel_range within its category (train stats) — "unusually unsure for this type".
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import make_folds, ape, mape

K = 10
N_SEEDS = 6

df = load_dataset(); lab = labeled(df).reset_index(drop=True)
baseX, _ = build_features(lab)
oe = lab["original_estimate"].values.astype(float)
fp = lab["final_price"].values.astype(float)
real = ape(oe, fp) > 0.20
resid = np.log(fp / np.clip(oe, 1, None))
cat = lab["category"].values
relrange = baseX["rel_range"].values


def fold_feats(tr, te):
    """Return dicts of {name: array} for train and test, all from train-only info."""
    sc = StandardScaler().fit(baseX.iloc[tr].values)
    Ztr, Zte = sc.transform(baseX.iloc[tr].values), sc.transform(baseX.iloc[te].values)
    nn = NearestNeighbors(n_neighbors=K + 1).fit(Ztr)
    dtr, itr = nn.kneighbors(Ztr)                       # train: self at col 0
    dte, ite = nn.kneighbors(Zte, n_neighbors=K)        # test: K nearest train
    r_tr = resid[tr]
    ftr = {"novelty": dtr[:, 1:].mean(1), "knn_ref": r_tr[itr[:, 1:]].mean(1)}
    fte = {"novelty": dte.mean(1), "knn_ref": r_tr[ite].mean(1)}
    # category-relative rel_range z-score (train stats)
    s = pd.Series(relrange[tr], index=cat[tr])
    cm, cs = s.groupby(level=0).mean().to_dict(), s.groupby(level=0).std().to_dict()
    gmean = float(np.mean(relrange[tr]))
    def z(idx):
        c = cat[idx]
        mu = np.array([cm.get(cc, gmean) for cc in c])
        sg = np.array([cs.get(cc, 1.0) for cc in c]); sg = np.where((sg > 0) & np.isfinite(sg), sg, 1.0)
        return (relrange[idx] - mu) / sg
    ftr["cat_unc"], fte["cat_unc"] = z(tr), z(te)
    return ftr, fte


def oof_mid(cols, seed):
    out = np.full(len(lab), np.nan)
    for tr, te in make_folds(lab, k=5, seed=seed):
        ftr, fte = fold_feats(tr, te)
        Xtr, Xte = baseX.iloc[tr].copy(), baseX.iloc[te].copy()
        for c in cols:
            Xtr[c] = ftr[c]; Xte[c] = fte[c]
        m = ConformalPriceModelV2(weight_power=0.5, seed=seed).fit(Xtr, fp[tr], oe[tr])
        out[te] = m.predict(Xte, oe[te])[:, 1]
    return out


def run():
    conds = {"novelty": ["novelty"], "knn_ref": ["knn_ref"], "cat_unc": ["cat_unc"],
             "novelty+knn_ref": ["novelty", "knn_ref"], "ALL": ["novelty", "knn_ref", "cat_unc"]}
    seeds = list(range(N_SEEDS))
    base = np.array([(lambda m: (mape(m, fp), mape(m[real], fp[real])))(oof_mid([], s)) for s in seeds])
    bl0, rl0 = base[:, 0], base[:, 1]
    print(f"OPTION 1 — novelty/k-NN/cat-uncertainty as point features  ({N_SEEDS}-seed paired OOF)\n")
    print(f"{'condition':18s} {'blended':>8s} {'Δbl(σ)':>13s} {'real':>8s} {'Δreal(σ)':>14s}")
    print(f"{'baseline':18s} {bl0.mean():>7.2f}% {'—':>13s} {rl0.mean():>7.2f}% {'—':>14s}")
    for name, cols in conds.items():
        m = np.array([(lambda mm: (mape(mm, fp), mape(mm[real], fp[real])))(oof_mid(cols, s)) for s in seeds])
        bl, rl = m[:, 0], m[:, 1]
        dbl, drl = bl0 - bl, rl0 - rl
        sb = dbl.std() / np.sqrt(len(dbl)) + 1e-9
        sr = drl.std() / np.sqrt(len(drl)) + 1e-9
        print(f"{name:18s} {bl.mean():>7.2f}% {dbl.mean():>+6.2f} ({abs(dbl.mean())/sb:>3.1f}) "
              f"{rl.mean():>7.2f}% {drl.mean():>+6.2f} ({abs(drl.mean())/sr:>3.1f})")
    print("\n(Δ positive = better than baseline. Adopt only if Δ>0 by >~1σ AND robust.)")


if __name__ == "__main__":
    run()
