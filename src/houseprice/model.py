"""Model layer: residual-quantile LightGBM + Conformalized Quantile Regression (CQR).

Target = log(final_price / original_estimate). Predicting the *correction* to the old estimate
means synthetic rows (final_price ~ estimate) get a near-zero prediction (we stay close to the
strong baseline) while genuinely-real rows get a learned correction from scope/text/zip signals.

CQR (Romano, Patterson, Candès 2019) gives the prediction interval finite-sample coverage:
  fit q_lo,q_hi on train-proper -> conformity E = max(q_lo - y, y - q_hi) on a calibration split
  -> widen by the (1-alpha) quantile of E. Nested inside every fold => no leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

LO_Q, HI_Q = 0.1, 0.9          # 80% target central interval
_BASE = dict(
    objective="quantile", n_estimators=400, learning_rate=0.03, num_leaves=15,
    min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
    reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2,
)


def _resid_target(final_price, original_estimate):
    return np.log(np.asarray(final_price, float) / np.clip(np.asarray(original_estimate, float), 1, None))


def _fit_q(X, y, alpha):
    m = lgb.LGBMRegressor(alpha=alpha, **_BASE)
    m.fit(X, y)
    return m


class ConformalPriceModel:
    """Fit on a labeled training frame; predict lo/mid/hi prices for new rows."""

    def __init__(self, lo_q=LO_Q, hi_q=HI_Q, cal_frac=0.25, seed=42):
        self.lo_q, self.hi_q, self.cal_frac, self.seed = lo_q, hi_q, cal_frac, seed

    def fit(self, X: pd.DataFrame, final_price, original_estimate):
        y = _resid_target(final_price, original_estimate)
        Xtr, Xcal, ytr, ycal = train_test_split(
            X, y, test_size=self.cal_frac, random_state=self.seed
        )
        self.m_lo = _fit_q(Xtr, ytr, self.lo_q)
        self.m_md = _fit_q(Xtr, ytr, 0.5)
        self.m_hi = _fit_q(Xtr, ytr, self.hi_q)
        # CQR conformity on calibration split
        qlo = self.m_lo.predict(Xcal)
        qhi = self.m_hi.predict(Xcal)
        E = np.maximum(qlo - ycal, ycal - qhi)
        n = len(E)
        level = min(1.0, np.ceil((n + 1) * (self.hi_q - self.lo_q)) / n)
        self.cqr_pad = float(np.quantile(E, level, method="higher"))
        self.feature_names = list(X.columns)
        return self

    def predict(self, X: pd.DataFrame, original_estimate):
        oe = np.clip(np.asarray(original_estimate, float), 1, None)
        r_lo = self.m_lo.predict(X) - self.cqr_pad
        r_md = self.m_md.predict(X)
        r_hi = self.m_hi.predict(X) + self.cqr_pad
        r_lo = np.minimum(r_lo, r_md)
        r_hi = np.maximum(r_hi, r_md)
        lo = oe * np.exp(r_lo)
        mid = oe * np.exp(r_md)
        hi = oe * np.exp(r_hi)
        return np.vstack([lo, mid, hi]).T  # (n,3)


def oof_predict(df_lab, build_features_fn, scope_df=None, census_df=None, k=5, seed=42):
    """Leakage-free out-of-fold predictions for all labeled rows. Returns (lo,mid,hi) arrays."""
    from .eval import make_folds
    X_all, _ = build_features_fn(df_lab, scope_df=scope_df, census_df=census_df)
    n = len(df_lab)
    out = np.full((n, 3), np.nan)
    for tr, te in make_folds(df_lab, k=k, seed=seed):
        m = ConformalPriceModel(seed=seed).fit(
            X_all.iloc[tr], df_lab["final_price"].values[tr], df_lab["original_estimate"].values[tr]
        )
        out[te] = m.predict(X_all.iloc[te], df_lab["original_estimate"].values[te])
    return out[:, 0], out[:, 1], out[:, 2]
