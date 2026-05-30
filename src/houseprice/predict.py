"""Inference core: load a trained bundle and price a single booking dict.

Shared by infer_service.py (sidecar) and predict_cli.py (batch). Pure function of the request
fields (Appendix A) — no final_price. Scope features come from the active ScopeExtractor backend
so the same code serves training-quality (claude_cli/api) and deploy-floor (deterministic).
"""
from __future__ import annotations

import os
import pickle
import numpy as np
import pandas as pd

from . import MODEL_VERSION
from .data_load import normalize_category, is_production_category
from .features import build_features, align_to
from .confidence import ConfidenceCalibrator, uncertainties_text
from .scope import ScopeExtractor, SCHEMA_KEYS

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "model", "bundle.pkl"
)


def load_bundle(path: str | None = None) -> dict:
    with open(path or MODEL_PATH, "rb") as fh:
        return pickle.load(fh)


def _row_df(booking: dict, anchor: float | None = None) -> pd.DataFrame:
    """Normalize a single booking dict into the load_dataset() schema (1-row frame).

    `anchor` is the category-median price used when the request omits original_estimate
    (an optional field per Appendix A) — so the model can still price from the 4 required
    fields alone instead of dividing by NaN.
    """
    g = lambda k, d="": booking.get(k, d)
    cat = normalize_category(g("service_category"))
    row = {
        "service_category": g("service_category"), "category": cat,
        "service_subtype": str(g("service_subtype") or ""),
        "zip_code": str(g("zip_code") or ""),
        "booking_month": str(g("booking_month") or ""),
        "job_description": str(g("job_description") or ""),
        "deadline": str(g("deadline") or ""),
        "in_production": is_production_category(cat),
    }
    for k in ("estimate_lo", "estimate_hi", "original_estimate",
              "original_estimate_lo", "original_estimate_hi"):
        row[k] = pd.to_numeric(booking.get(k), errors="coerce")
    if pd.isna(row["estimate_lo"]):
        row["estimate_lo"] = row.get("original_estimate_lo")
    if pd.isna(row["estimate_hi"]):
        row["estimate_hi"] = row.get("original_estimate_hi")
    df = pd.DataFrame([row])
    # Establish original_estimate: request value -> midpoint of provided lo/hi -> category anchor.
    oe = df["original_estimate"].fillna(df[["estimate_lo", "estimate_hi"]].mean(axis=1))
    if pd.isna(oe.iloc[0]) and anchor is not None:
        oe = pd.Series([float(anchor)])
    df["original_estimate"] = oe
    df["estimate_lo"] = df["estimate_lo"].fillna(df["original_estimate"] * 0.8)
    df["estimate_hi"] = df["estimate_hi"].fillna(df["original_estimate"] * 1.2)
    return df


def _scope_df_for(df: pd.DataFrame, backend: str) -> pd.DataFrame:
    ex = ScopeExtractor(backend=backend)
    recs = [ex.extract(d, c) for d, c in zip(df["job_description"], df["category"])]
    return pd.DataFrame(recs, index=df.index)


def predict_one(bundle: dict, booking: dict, scope_backend: str | None = None) -> dict:
    cat = normalize_category(booking.get("service_category"))
    anchor = bundle.get("cat_anchor", {}).get(cat, bundle.get("global_anchor", 300.0))
    df = _row_df(booking, anchor=anchor)
    backend = scope_backend or os.environ.get("SCOPE_BACKEND", "deterministic")
    scope_df = _scope_df_for(df, backend)
    X, _ = build_features(df, scope_df=scope_df, census_df=bundle.get("census"))
    X = align_to(X, bundle["feature_names"])
    lo, mid, hi = bundle["model"].predict(X, df["original_estimate"].values)[0]
    lo, mid, hi = float(lo), float(mid), float(hi)
    lo, hi = min(lo, mid), max(hi, mid)
    cal: ConfidenceCalibrator = bundle["calibrator"]
    in_prod = bool(df["in_production"].iloc[0])
    conf, flags = cal.score(lo, hi, mid, in_prod)
    rel_width = (hi - lo) / max(mid, 1.0)
    return {
        "estimate_lo": round(lo, 2), "estimate_hi": round(hi, 2),
        "estimate_midpoint": round(mid, 2), "confidence": conf,
        "coverage": _coverage_text(df, scope_df),
        "uncertainties": uncertainties_text(flags, rel_width),
        "model_version": bundle.get("model_version", MODEL_VERSION),
        "ood": flags,
    }


def _coverage_text(df: pd.DataFrame, scope_df: pd.DataFrame) -> str:
    cat = df["category"].iloc[0]
    s = scope_df.iloc[0]
    bits = [f"{cat} job"]
    if s.get("scope_fixture_count", -1) and s["scope_fixture_count"] > 0:
        bits.append(f"~{int(s['scope_fixture_count'])} unit(s)")
    if s.get("scope_sqft", -1) and s["scope_sqft"] > 0:
        bits.append(f"~{int(s['scope_sqft'])} sq ft")
    lvl = {0: "basic", 1: "standard", 2: "extensive"}.get(int(s.get("scope_complexity", 1)), "standard")
    bits.append(f"{lvl} scope")
    return ", ".join(bits)
