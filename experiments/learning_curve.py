"""Data-scaling diagnostic: is the model data-limited or model-limited?

Fix a stratified held-out test set, train on increasing fractions of the remaining
pool, measure test MAPE. Repeat over many seeds and average. If test MAPE keeps
falling as train size grows, MORE DATA is the lever (not features/architecture).
Real-only is the subset that matters (base_ape>0.20 on the test rows).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit

from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.model_v2 import ConformalPriceModelV2
from houseprice.eval import ape, mape, stratify_key

FRACS = [0.25, 0.40, 0.55, 0.70, 0.85, 1.0]
N_SEEDS = 30
TEST_FRAC = 0.25
REAL_THR = 0.20


def run():
    df = load_dataset()
    lab = labeled(df).reset_index(drop=True)
    X_all, _ = build_features(lab)
    fp = lab["final_price"].values.astype(float)
    oe = lab["original_estimate"].values.astype(float)
    skey = stratify_key(lab).values
    base = ape(oe, fp)  # baseline APE per row

    # results[frac] = list of (blended, real, n_train, n_real_test) per seed
    blended = {f: [] for f in FRACS}
    realm = {f: [] for f in FRACS}
    ntr = {f: [] for f in FRACS}

    for seed in range(N_SEEDS):
        sss = StratifiedShuffleSplit(n_splits=1, test_size=TEST_FRAC, random_state=seed)
        pool_idx, test_idx = next(sss.split(X_all, skey))
        test_real = base[test_idx] > REAL_THR
        rng = np.random.RandomState(1000 + seed)
        order = rng.permutation(pool_idx)
        for f in FRACS:
            k = max(20, int(round(len(order) * f)))
            tr = order[:k]
            m = ConformalPriceModelV2(weight_power=0.5, seed=seed).fit(
                X_all.iloc[tr], fp[tr], oe[tr])
            pred = m.predict(X_all.iloc[test_idx], oe[test_idx])[:, 1]
            blended[f].append(mape(pred, fp[test_idx]))
            ntr[f].append(k)
            if test_real.sum() > 0:
                realm[f].append(mape(pred[test_real], fp[test_idx][test_real]))

    # baseline on the same held-out (averaged) for reference
    print(f"Learning curve  ({N_SEEDS} seeds, {int((1-TEST_FRAC)*len(lab))}-row pool, "
          f"{int(TEST_FRAC*len(lab))}-row test)\n")
    print(f"{'train_n':>8} {'blended_MAPE':>14} {'real_MAPE':>12}")
    for f in FRACS:
        b = np.mean(blended[f]); bs = np.std(blended[f]) / np.sqrt(len(blended[f]))
        r = np.mean(realm[f]); rs = np.std(realm[f]) / np.sqrt(len(realm[f]))
        print(f"{int(np.mean(ntr[f])):>8} {b:>8.2f} ±{bs:.2f}   {r:>7.2f} ±{rs:.2f}")
    # slope between last two points = "is the curve still falling at full data?"
    db = np.mean(blended[FRACS[-2]]) - np.mean(blended[FRACS[-1]])
    dr = np.mean(realm[FRACS[-2]]) - np.mean(realm[FRACS[-1]])
    print(f"\nSlope over last step (+{int(np.mean(ntr[FRACS[-1]]))-int(np.mean(ntr[FRACS[-2]]))} rows): "
          f"blended {db:+.2f}pp, real {dr:+.2f}pp  (negative = still improving with data)")


if __name__ == "__main__":
    run()
