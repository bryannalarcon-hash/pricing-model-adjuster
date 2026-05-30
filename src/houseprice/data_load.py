"""Data layer: load + normalize the HouseAccount pricing dataset.

Single source of truth for category normalization, the 10 production verticals, and typing.
Importable by features, eval, the sidecar, and tests. No model logic here.
"""
from __future__ import annotations

import os
import re
import pandas as pd

# Resolve the raw dataset regardless of caller CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
RAW_CSV = os.path.join(_ROOT, "data", "raw", "houseaccount_pricing_sample.csv")
if not os.path.exists(RAW_CSV):
    RAW_CSV = os.path.join(_ROOT, "houseaccount_pricing_sample.csv")

# The 10 current production verticals (kebab slugs, per Appendix A / seeds).
PRODUCTION_VERTICALS = frozenset({
    "electrical", "exterior-cleaning", "handyman", "hvac", "indoor-cleaning",
    "irrigation", "landscaping-lawn", "pest-control", "plumbing", "tick-mosquito-treatment",
})

# Map dataset title-case categories -> production vertical slug when they correspond to a
# current production vertical. Categories not in production map to None (in-distribution by
# training, but flagged out-of-production for confidence). Cleaning maps to indoor-cleaning
# as the closest production analogue (exterior-cleaning also exists; we treat Cleaning as
# production-covered). This mapping is used ONLY for the OOD "outside production set" signal.
CATEGORY_TO_PRODUCTION = {
    "Electrical": "electrical",
    "Cleaning": "indoor-cleaning",
    "Handyman": "handyman",
    "HVAC": "hvac",
    "Landscaping": "landscaping-lawn",
    "Pest Control": "pest-control",
    "Plumbing": "plumbing",
    # Categories present in training but OUTSIDE the 10 production verticals:
    "Appliance Repair": None, "Auto": None, "Chimney": None, "Exterior": None,
    "Flooring": None, "General Contractor": None, "Moving": None, "Painting": None,
    "Pool": None, "Remodeling": None, "Roofing": None,
}

DEADLINES = ("As soon as possible", "Within 1-2 weeks", "Within 1 month", "I'm flexible")

NUMERIC_COLS = ["estimate_lo", "estimate_hi", "original_estimate", "final_price"]


def normalize_category(raw: str) -> str:
    """Title-case canonical form. Handles kebab/lower production slugs and stray casing."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Unknown"
    s = str(raw).strip()
    slug = s.lower().replace("_", "-").replace(" ", "-")
    slug_to_title = {
        "electrical": "Electrical", "exterior-cleaning": "Cleaning", "indoor-cleaning": "Cleaning",
        "handyman": "Handyman", "hvac": "HVAC", "irrigation": "Landscaping",
        "landscaping-lawn": "Landscaping", "pest-control": "Pest Control", "plumbing": "Plumbing",
        "tick-mosquito-treatment": "Pest Control",
    }
    if slug in slug_to_title:
        return slug_to_title[slug]
    if s.upper() == "HVAC":
        return "HVAC"
    return s.title().replace("Hvac", "HVAC")


def is_production_category(cat_title: str) -> bool:
    """True if the (title-case) category maps to one of the 10 production verticals."""
    return CATEGORY_TO_PRODUCTION.get(normalize_category(cat_title), "____") is not None


def load_dataset(path: str | None = None) -> pd.DataFrame:
    """Load + normalize. Returns a typed DataFrame with helper columns.

    Added columns:
      category        normalized title-case service_category
      in_production   bool — category ∈ 10 production verticals
      is_labeled      bool — final_price present
      orig_range      estimate_hi - estimate_lo
    """
    df = pd.read_csv(path or RAW_CSV, dtype={"zip_code": str})
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["zip_code"] = df["zip_code"].astype(str).str.extract(r"(\d{5})", expand=False)
    df["category"] = df["service_category"].map(normalize_category)
    df["in_production"] = df["category"].map(is_production_category)
    df["is_labeled"] = df["final_price"].notna()
    df["job_description"] = df["job_description"].fillna("").astype(str)
    df["service_subtype"] = df.get("service_subtype", "").fillna("").astype(str)
    df["deadline"] = df.get("deadline", "").fillna("").astype(str)
    df["orig_range"] = df["estimate_hi"] - df["estimate_lo"]
    return df


def labeled(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["is_labeled"]].copy().reset_index(drop=True)


if __name__ == "__main__":
    d = load_dataset()
    print("rows:", len(d), "labeled:", int(d.is_labeled.sum()))
    print("categories:", d.category.nunique())
    print(d.category.value_counts().to_string())
