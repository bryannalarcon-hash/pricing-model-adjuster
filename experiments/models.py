"""Model-architecture factories for the experiment harness.

All predict the POINT midpoint. Most model the residual r = log(final/original) and map back
mid = original*exp(r). Each exposes fit(lab_df) / predict(lab_df) -> midpoint array.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from houseprice.features import build_features, align_to
import lightgbm as lgb

SCOPE_COLS = ["scope_sqft", "scope_fixture_count", "scope_complexity", "scope_urgency"]


def _resid(fp, oe):
    return np.log(np.asarray(fp, float) / np.clip(np.asarray(oe, float), 1, None))


def _X(lab, names=None):
    scope = lab[SCOPE_COLS] if set(SCOPE_COLS).issubset(lab.columns) else None
    X, _ = build_features(lab, scope_df=scope)
    return align_to(X, names) if names is not None else X


# ---------------- LightGBM residual (multiple losses) ----------------
class LGBMResidual:
    def __init__(self, objective="quantile", alpha=0.5, **kw):
        self.p = dict(objective=objective, n_estimators=400, learning_rate=0.03, num_leaves=15,
                      min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                      reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2)
        if objective == "quantile":
            self.p["alpha"] = alpha
        self.p.update(kw)

    def fit(self, lab):
        X = _X(lab); self.names = list(X.columns)
        self.m = lgb.LGBMRegressor(**self.p)
        self.m.fit(X, _resid(lab["final_price"], lab["original_estimate"]))
        return self

    def predict(self, lab):
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(_X(lab, self.names)))


# ---------------- Custom MAPE-objective LightGBM (residual space) ----------------
class MAPEObjLGBM:
    """Predict residual r̂; train with the EXACT MAPE loss in ratio space L(δ)=|e^δ−1|,
    δ=r̂−r_true. grad=sign(e^δ−1)·e^δ, hess≈e^δ. This directly minimizes |mid−fp|/fp."""
    def __init__(self, **kw):
        self.p = dict(n_estimators=500, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                      reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2); self.p.update(kw)

    @staticmethod
    def _obj(y_true, y_pred):
        d = y_pred - y_true
        ed = np.exp(np.clip(d, -10, 10))
        grad = np.sign(ed - 1.0) * ed
        hess = ed  # |e^δ-1| has hess ~ e^δ (use convex surrogate)
        return grad, hess

    def fit(self, lab):
        X = _X(lab); self.names = list(X.columns)
        self.m = lgb.LGBMRegressor(objective=self._obj, **self.p)
        self.m.fit(X, _resid(lab["final_price"], lab["original_estimate"]))
        return self

    def predict(self, lab):
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(_X(lab, self.names)))


class WeightedLGBM:
    """L1 (or L2) on residual with per-sample weight ∝ 1/final_price — aligns the loss with MAPE."""
    def __init__(self, objective="mae", power=1.0, **kw):
        self.power = power
        self.p = dict(objective=objective, n_estimators=400, learning_rate=0.03, num_leaves=15,
                      min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                      reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2); self.p.update(kw)

    def fit(self, lab):
        X = _X(lab); self.names = list(X.columns)
        w = 1.0 / np.clip(lab["final_price"].values.astype(float), 1, None) ** self.power
        w = w / w.mean()
        self.m = lgb.LGBMRegressor(**self.p)
        self.m.fit(X, _resid(lab["final_price"], lab["original_estimate"]), sample_weight=w)
        return self

    def predict(self, lab):
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(_X(lab, self.names)))


# ---------------- CatBoost residual with native categoricals ----------------
class CatBoostResidual:
    CAT = ["category", "service_subtype", "zip3s"]

    def __init__(self, loss="MAE", **kw):
        self.kw = dict(loss_function=loss, iterations=600, learning_rate=0.03, depth=5,
                       l2_leaf_reg=3.0, random_seed=0, verbose=False); self.kw.update(kw)

    def _frame(self, lab):
        X = _X(lab)
        X = X[[c for c in X.columns if not c.startswith("cat_")]].copy()  # drop one-hots (use native cats)
        X["category"] = lab["category"].astype(str).values
        X["service_subtype"] = lab["service_subtype"].astype(str).values
        X["zip3s"] = lab["zip_code"].fillna("000").astype(str).str[:3].values
        return X

    def fit(self, lab):
        from catboost import CatBoostRegressor, Pool
        X = self._frame(lab)
        cat_idx = [X.columns.get_loc(c) for c in self.CAT]
        self.cols = list(X.columns); self.cat_idx = cat_idx
        self.m = CatBoostRegressor(**self.kw)
        self.m.fit(Pool(X, _resid(lab["final_price"], lab["original_estimate"]), cat_features=cat_idx))
        return self

    def predict(self, lab):
        from catboost import Pool
        X = self._frame(lab)[self.cols]
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(Pool(X, cat_features=self.cat_idx)))


# ---------------- XGBoost residual ----------------
class XGBResidual:
    def __init__(self, **kw):
        self.kw = dict(n_estimators=400, learning_rate=0.03, max_depth=4, subsample=0.8,
                       colsample_bytree=0.8, reg_lambda=1.0, reg_alpha=0.5, n_jobs=2,
                       objective="reg:absoluteerror"); self.kw.update(kw)

    def fit(self, lab):
        import xgboost as xgb
        X = _X(lab); self.names = list(X.columns)
        self.m = xgb.XGBRegressor(**self.kw)
        self.m.fit(X, _resid(lab["final_price"], lab["original_estimate"]))
        return self

    def predict(self, lab):
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(_X(lab, self.names)))


# ---------------- LightGBM + TF-IDF/SVD latent text features (lightweight, no torch) ----------------
class LGBMResidualTFIDF:
    def __init__(self, n_svd=24, objective="regression", **kw):
        self.n_svd = n_svd
        self.p = dict(objective=objective, n_estimators=400, learning_rate=0.03, num_leaves=15,
                      min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                      reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2)
        self.p.update(kw)

    def _text(self, lab, fit):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        docs = (lab["job_description"].astype(str) + " " + lab["service_subtype"].astype(str)).values
        if fit:
            self.tfidf = TfidfVectorizer(max_features=800, ngram_range=(1, 2), min_df=2, stop_words="english")
            tf = self.tfidf.fit_transform(docs)
            k = min(self.n_svd, tf.shape[1] - 1) if tf.shape[1] > 1 else 1
            self.svd = TruncatedSVD(n_components=max(k, 1), random_state=0)
            emb = self.svd.fit_transform(tf)
        else:
            emb = self.svd.transform(self.tfidf.transform(docs))
        return pd.DataFrame(emb, columns=[f"tf{i}" for i in range(emb.shape[1])], index=lab.index)

    def fit(self, lab):
        X = pd.concat([_X(lab), self._text(lab, True)], axis=1)
        self.names = list(X.columns)
        self.m = lgb.LGBMRegressor(**self.p)
        self.m.fit(X, _resid(lab["final_price"], lab["original_estimate"]))
        return self

    def predict(self, lab):
        X = pd.concat([_X(lab), self._text(lab, False)], axis=1)
        X = X.reindex(columns=self.names, fill_value=0)
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(X))


# ---------------- Target-encoded LightGBM (leakage-safe OOF encoding) ----------------
def _oof_target_encode(keys, resid, n_splits=5, smoothing=10.0, seed=0):
    """Out-of-fold mean-residual encoding with Bayesian smoothing. Returns (oof_enc, full_map, prior)."""
    from sklearn.model_selection import KFold
    keys = np.asarray(keys).astype(str)
    resid = np.asarray(resid, float)
    prior = resid.mean()
    oof = np.full(len(keys), prior)
    for tr, te in KFold(n_splits, shuffle=True, random_state=seed).split(keys):
        df = pd.DataFrame({"k": keys[tr], "r": resid[tr]})
        agg = df.groupby("k")["r"].agg(["mean", "count"])
        enc = (agg["mean"] * agg["count"] + prior * smoothing) / (agg["count"] + smoothing)
        m = {k: v for k, v in enc.items()}
        oof[te] = [m.get(k, prior) for k in keys[te]]
    df = pd.DataFrame({"k": keys, "r": resid})
    agg = df.groupby("k")["r"].agg(["mean", "count"])
    full = (agg["mean"] * agg["count"] + prior * smoothing) / (agg["count"] + smoothing)
    return oof, {k: v for k, v in full.items()}, prior


class LGBMResidualTE:
    """LightGBM L2 on residual + OOF target encodings of service_subtype and zip3 — strong signal
    for sparse categories without leakage."""
    TE_COLS = ["service_subtype", "zip3", "category"]

    def __init__(self, smoothing=10.0, weight_power=0.0, **kw):
        self.smoothing = smoothing; self.weight_power = weight_power
        self.p = dict(objective="regression", n_estimators=400, learning_rate=0.03, num_leaves=15,
                      min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                      reg_lambda=1.0, reg_alpha=0.5, max_depth=4, verbose=-1, n_jobs=2); self.p.update(kw)

    def _keys(self, lab, col):
        if col == "zip3":
            return lab["zip_code"].fillna("000").astype(str).str[:3]
        return lab[col].astype(str)

    def fit(self, lab):
        r = _resid(lab["final_price"], lab["original_estimate"])
        X = _X(lab); self.maps = {}; self.priors = {}
        for col in self.TE_COLS:
            oof, full, prior = _oof_target_encode(self._keys(lab, col), r, smoothing=self.smoothing)
            X[f"te_{col}"] = oof
            self.maps[col] = full; self.priors[col] = prior
        self.names = list(X.columns)
        w = None
        if self.weight_power:
            w = 1.0 / np.clip(lab["final_price"].values.astype(float), 1, None) ** self.weight_power
            w = w / w.mean()
        self.m = lgb.LGBMRegressor(**self.p)
        self.m.fit(X, r, sample_weight=w)
        return self

    def predict(self, lab):
        X = _X(lab)
        for col in self.TE_COLS:
            keys = self._keys(lab, col).astype(str)
            X[f"te_{col}"] = [self.maps[col].get(k, self.priors[col]) for k in keys]
        X = X.reindex(columns=self.names, fill_value=0)
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        return oe * np.exp(self.m.predict(X))


# ---------------- Ensemble (geometric mean of residual models) ----------------
class Ensemble:
    def __init__(self, factories):
        self.factories = factories

    def fit(self, lab):
        self.models = [f().fit(lab) for f in self.factories]
        return self

    def predict(self, lab):
        oe = np.clip(lab["original_estimate"].values.astype(float), 1, None)
        # average in log-residual space (geometric mean of ratios)
        rs = [np.log(np.clip(m.predict(lab), 1, None) / oe) for m in self.models]
        return oe * np.exp(np.mean(rs, axis=0))


# ---------------- Per-category multiplicative bias correction (MAPE-targeted) ----------------
class BiasCorrected:
    """Wrap a base factory; learn a per-category scalar c minimizing MAPE on an inner OOF split,
    then mid *= c. MAPE is scale-sensitive, so a small systematic correction can help."""
    def __init__(self, base_factory, min_n=8):
        self.base_factory = base_factory; self.min_n = min_n

    def fit(self, lab):
        from sklearn.model_selection import KFold
        self.m = self.base_factory().fit(lab)
        # inner OOF predictions to estimate per-category bias
        oof = np.full(len(lab), np.nan)
        for tr, te in KFold(5, shuffle=True, random_state=0).split(lab):
            oof[te] = self.base_factory().fit(lab.iloc[tr].reset_index(drop=True)).predict(
                lab.iloc[te].reset_index(drop=True))
        fp = lab["final_price"].values
        self.global_c = _opt_c(oof, fp)
        self.cat_c = {}
        for cat, idx in lab.groupby("category").groups.items():
            idx = list(idx)
            if len(idx) >= self.min_n:
                self.cat_c[cat] = _opt_c(oof[idx], fp[idx])
        return self

    def predict(self, lab):
        mid = self.m.predict(lab)
        c = lab["category"].map(lambda k: self.cat_c.get(k, self.global_c)).values
        return mid * c


def _opt_c(pred, actual):
    """Scalar c minimizing MAPE of c*pred vs actual. Grid + refine."""
    pred = np.asarray(pred, float); actual = np.asarray(actual, float)
    ok = np.isfinite(pred) & (actual > 0)
    pred, actual = pred[ok], actual[ok]
    if len(pred) < 3:
        return 1.0
    grid = np.linspace(0.85, 1.15, 61)
    errs = [np.mean(np.abs(c * pred - actual) / actual) for c in grid]
    return float(grid[int(np.argmin(errs))])
