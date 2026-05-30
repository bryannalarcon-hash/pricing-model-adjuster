"""Production model v2 (from the research program).

Key changes vs v1 (documented in experiments/JOURNAL.md):
  - Point estimate trained on ALL data (v1 wasted 25% on the conformal split).
  - Loss = L2 on residual log(final/original) with MAPE-aligned sample weight 1/final_price^p
    (p≈0.5) — best blended/real-only balance found.
  - Intervals via CROSS-CONFORMAL quantile regression: quantile models use all data; the CQR pad
    is calibrated by K-fold cross-fitting -> valid coverage with no data wasted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import KFold

LO_Q, HI_Q = 0.1, 0.9
_POINT = dict(objective="regression", n_estimators=400, learning_rate=0.03, num_leaves=15,
              min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2)
_QUANT = dict(objective="quantile", n_estimators=300, learning_rate=0.03, num_leaves=15,
              min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2)


def _resid(fp, oe):
    return np.log(np.asarray(fp, float) / np.clip(np.asarray(oe, float), 1, None))


def _weights(fp, power):
    if not power:
        return None
    w = 1.0 / np.clip(np.asarray(fp, float), 1, None) ** power
    return w / w.mean()


class ConformalPriceModelV2:
    def __init__(self, weight_power=0.5, lo_q=LO_Q, hi_q=HI_Q, n_folds=5, seed=42, normalized=True):
        self.weight_power, self.lo_q, self.hi_q = weight_power, lo_q, hi_q
        self.n_folds, self.seed, self.normalized = n_folds, seed, normalized

    @staticmethod
    def _scale(qlo, qhi):
        # local uncertainty scale = predicted central interval width (floored)
        return np.maximum(qhi - qlo, 0.05)

    def fit(self, X: pd.DataFrame, final_price, original_estimate):
        X = X.reset_index(drop=True)
        r = _resid(final_price, original_estimate)
        w = _weights(final_price, self.weight_power)
        # point model on ALL data, MAPE-aligned weighting
        self.m_point = lgb.LGBMRegressor(**_POINT).fit(X, r, sample_weight=w)
        # quantile models on ALL data
        self.m_lo = lgb.LGBMRegressor(alpha=self.lo_q, **_QUANT).fit(X, r)
        self.m_hi = lgb.LGBMRegressor(alpha=self.hi_q, **_QUANT).fit(X, r)
        # cross-conformal pad: conformity scores from held-out folds, models refit per fold.
        # Normalized (Mondrian-free adaptive) CQR scales the score by the local predicted spread,
        # so the pad widens for high-uncertainty rows -> better conditional coverage on the sparse,
        # high-variance real categories (e.g. Handyman/Plumbing).
        E = []
        for tr, cal in KFold(self.n_folds, shuffle=True, random_state=self.seed).split(X):
            lo_m = lgb.LGBMRegressor(alpha=self.lo_q, **_QUANT).fit(X.iloc[tr], r[tr])
            hi_m = lgb.LGBMRegressor(alpha=self.hi_q, **_QUANT).fit(X.iloc[tr], r[tr])
            qlo, qhi = lo_m.predict(X.iloc[cal]), hi_m.predict(X.iloc[cal])
            raw = np.maximum(qlo - r[cal], r[cal] - qhi)
            E.append(raw / self._scale(qlo, qhi) if self.normalized else raw)
        E = np.concatenate(E)
        n = len(E)
        level = min(1.0, np.ceil((n + 1) * (self.hi_q - self.lo_q)) / n)
        self.cqr_pad = float(np.quantile(E, level, method="higher"))
        self.feature_names = list(X.columns)
        return self

    def predict(self, X: pd.DataFrame, original_estimate):
        oe = np.clip(np.asarray(original_estimate, float), 1, None)
        r_pt = self.m_point.predict(X)
        qlo, qhi = self.m_lo.predict(X), self.m_hi.predict(X)
        pad = self.cqr_pad * (self._scale(qlo, qhi) if getattr(self, "normalized", True) else 1.0)
        r_lo = np.minimum(qlo - pad, r_pt)
        r_hi = np.maximum(qhi + pad, r_pt)
        return np.vstack([oe * np.exp(r_lo), oe * np.exp(r_pt), oe * np.exp(r_hi)]).T


def oof_predict(df_lab, build_features_fn, scope_df=None, census_df=None, k=5, seed=42,
                weight_power=0.5, X_all=None):
    """Leakage-free out-of-fold (lo,mid,hi) for all labeled rows using model_v2."""
    from .eval import make_folds
    if X_all is None:
        X_all, _ = build_features_fn(df_lab, scope_df=scope_df, census_df=census_df)
    n = len(df_lab)
    out = np.full((n, 3), np.nan)
    for tr, te in make_folds(df_lab, k=k, seed=seed):
        m = ConformalPriceModelV2(weight_power=weight_power, seed=seed).fit(
            X_all.iloc[tr], df_lab["final_price"].values[tr], df_lab["original_estimate"].values[tr])
        out[te] = m.predict(X_all.iloc[te], df_lab["original_estimate"].values[te])
    return out[:, 0], out[:, 1], out[:, 2]


def oof_predict_bagged(df_lab, build_features_fn, scope_df=None, census_df=None, k=5,
                       seeds=range(6), weight_power=0.5):
    """Bagged OOF: average each row's out-of-fold (lo,mid,hi) across repeated CV seeds. Every
    prediction is still leakage-free (the row is held out in each seed's split) but lower-variance,
    which both stabilizes and improves the submission vs a single split."""
    X_all, _ = build_features_fn(df_lab, scope_df=scope_df, census_df=census_df)
    acc = np.zeros((len(df_lab), 3))
    seeds = list(seeds)
    for s in seeds:
        lo, mid, hi = oof_predict(df_lab, build_features_fn, k=k, seed=s,
                                  weight_power=weight_power, X_all=X_all)
        acc += np.vstack([lo, mid, hi]).T
    acc /= len(seeds)
    return acc[:, 0], acc[:, 1], acc[:, 2]
