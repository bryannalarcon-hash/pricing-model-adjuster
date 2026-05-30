"""Feature layer: build the model matrix from a booking row.

Every feature here is computable at inference time from the API request (Appendix A) — no
use of final_price. Optional `scope_df` (LLM/deterministic scope) and `census_df` (ZIP ACS)
are joined when present; absent, their columns are filled with neutral values so the same
code path serves training, OOF eval, and the live sidecar.
"""
from __future__ import annotations

import re
import numpy as np
import pandas as pd

DEADLINE_URGENCY = {
    "As soon as possible": 3, "Within 1 week": 2, "Within 1-2 weeks": 2,
    "Within 1 month": 1, "I'm flexible": 0, "Flexible": 0, "": 1,
}

# Scope-signal keywords mined from job_description (cheap, deterministic, deploy-safe).
KW = {
    "kw_replace": r"\breplace|replacement|new\b",
    "kw_repair": r"\brepair|fix|patch\b",
    "kw_install": r"\binstall|mount|hook ?up\b",
    "kw_emergency": r"\bemergency|asap|urgent|today|tonight|right now\b",
    "kw_leak": r"\bleak|burst|flood|water damage\b",
    "kw_full": r"\bwhole|entire|full|complete|all\b",
    "kw_small": r"\bsmall|minor|single|one |1 \b",
    "kw_large": r"\blarge|big|major|multiple|several|many\b",
    "kw_supply": r"\byou supply|i have|provided|own (the )?(part|valve|material)\b",
}
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"(\d+)\s*(sq|square|gallon|gal|br|bed|bath|story|stories|window|room|ft|foot|feet)", re.I)


def _text_feats(desc: str) -> dict:
    d = (desc or "").lower()
    nums = [float(x) for x in NUM_RE.findall(d)] or [0.0]
    units = UNIT_RE.findall(d)
    feats = {
        "desc_len": len(d),
        "desc_words": len(d.split()),
        "n_numbers": len(NUM_RE.findall(d)),
        "max_number": float(np.max(nums)),
        "sum_numbers": float(np.sum(nums)),
        "n_unit_mentions": len(units),
    }
    for name, pat in KW.items():
        feats[name] = int(bool(re.search(pat, d)))
    return feats


def build_features(
    df: pd.DataFrame, scope_df: pd.DataFrame | None = None, census_df: pd.DataFrame | None = None
):
    """Return (X: DataFrame, feature_names: list[str]). Index-aligned to df."""
    f = pd.DataFrame(index=df.index)

    oe = df["original_estimate"].astype(float)
    lo = df["estimate_lo"].astype(float)
    hi = df["estimate_hi"].astype(float)
    f["log_orig"] = np.log(oe.clip(lower=1))
    f["orig"] = oe
    f["rel_range"] = (hi - lo) / oe.clip(lower=1)
    f["range"] = (hi - lo)
    f["log_lo"] = np.log(lo.clip(lower=1))
    f["log_hi"] = np.log(hi.clip(lower=1))

    # urgency / timing
    f["urgency"] = df["deadline"].map(lambda x: DEADLINE_URGENCY.get(str(x), 1)).astype(int)
    bm = pd.to_datetime(df["booking_month"], format="%Y-%m", errors="coerce")
    f["month"] = bm.dt.month.fillna(0).astype(int)
    f["is_summer"] = f["month"].isin([5, 6, 7, 8]).astype(int)

    # subtype signal
    f["has_subtype"] = (df["service_subtype"].str.len() > 0).astype(int)
    f["subtype_diff"] = (
        df["service_subtype"].str.lower().str.strip()
        != df["category"].str.lower().str.strip()
    ).astype(int)

    # text/scope-from-description
    tf = df["job_description"].map(_text_feats).apply(pd.Series)
    f = pd.concat([f, tf], axis=1)

    # ZIP-region geography (self-contained; coarse cost-of-living proxy, no external dep).
    z = df["zip_code"].fillna("00000").astype(str).str.zfill(5)
    f["zip1"] = pd.to_numeric(z.str[0], errors="coerce").fillna(0).astype(int)  # USPS region
    f["zip2"] = pd.to_numeric(z.str[:2], errors="coerce").fillna(0).astype(int)
    f["zip3"] = pd.to_numeric(z.str[:3], errors="coerce").fillna(0).astype(int)

    # category one-hot (few categories; avoids target-encoding leakage)
    cats = pd.get_dummies(df["category"], prefix="cat")
    f = pd.concat([f, cats], axis=1)
    f["in_production"] = df["in_production"].astype(int)

    # optional LLM/deterministic scope features
    if scope_df is not None:
        s = scope_df.reindex(df.index)
        for col in ["scope_sqft", "scope_fixture_count", "scope_complexity", "scope_urgency"]:
            f[col] = pd.to_numeric(s.get(col), errors="coerce").fillna(-1)
    # optional census features
    if census_df is not None:
        c = census_df.set_index("zip_code") if "zip_code" in census_df.columns else census_df
        j = df["zip_code"].map(c["median_income"]) if "median_income" in c else np.nan
        f["zip_median_income"] = pd.to_numeric(j, errors="coerce").fillna(c["median_income"].median() if "median_income" in c else 0)
        if "median_home_value" in c:
            f["zip_home_value"] = pd.to_numeric(df["zip_code"].map(c["median_home_value"]), errors="coerce").fillna(c["median_home_value"].median())

    f = f.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return f, list(f.columns)
