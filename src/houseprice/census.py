"""External data: US Census ACS 5-year by ZCTA (≈ZIP), cached to data/external/zip_acs.csv.

Keyless light use (one bulk request). Variables:
  B19013_001E median household income, B25077_001E median home value,
  B01003_001E total population, B25064_001E median gross rent.
ZIP→ZCTA: we treat the 5-digit ZIP as its ZCTA (true for the large majority of residential ZIPs;
a small fraction of PO-box/point ZIPs lack a ZCTA and fall back to the national median). Stated
in ASSUMPTIONS.md (A6).
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
import pandas as pd

OUT = os.path.join("data", "external", "zip_acs.csv")
YEAR = 2022
VARS = {
    "B19013_001E": "median_income",
    "B25077_001E": "median_home_value",
    "B01003_001E": "population",
    "B25064_001E": "median_rent",
}
def _url() -> str:
    base = (
        f"https://api.census.gov/data/{YEAR}/acs/acs5"
        f"?get={','.join(VARS)}&for=zip%20code%20tabulation%20area:*"
    )
    key = os.environ.get("CENSUS_API_KEY")
    return base + (f"&key={key}" if key else "")


def fetch_acs(force: bool = False) -> pd.DataFrame:
    """Fetch ACS by ZCTA. As of 2026 the Census API requires CENSUS_API_KEY; without it this
    raises and the pipeline proceeds on self-contained ZIP-region features instead (documented)."""
    if os.path.exists(OUT) and not force:
        return pd.read_csv(OUT, dtype={"zip_code": str})
    if not os.environ.get("CENSUS_API_KEY"):
        raise RuntimeError("CENSUS_API_KEY not set — Census API requires a key; skipping ACS join.")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with urllib.request.urlopen(_url(), timeout=120) as r:
        rows = json.loads(r.read().decode())
    header, data = rows[0], rows[1:]
    df = pd.DataFrame(data, columns=header)
    zip_col = "zip code tabulation area" if "zip code tabulation area" in df.columns else header[-1]
    df = df.rename(columns={zip_col: "zip_code", **VARS})
    df["zip_code"] = df["zip_code"].astype(str).str.zfill(5)
    for v in VARS.values():
        df[v] = pd.to_numeric(df[v], errors="coerce")
        df.loc[df[v] < 0, v] = pd.NA  # census uses negative sentinels for missing
    df = df[["zip_code", *VARS.values()]]
    df.to_csv(OUT, index=False)
    return df


if __name__ == "__main__":
    d = fetch_acs(force="--force" in os.sys.argv)
    print("ACS ZCTAs:", len(d))
    print(d.head().to_string())
    print("medians:", d[["median_income", "median_home_value"]].median().to_dict())
