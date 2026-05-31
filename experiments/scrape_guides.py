"""Volume pivot: crawl fixr.com + homeguide.com cost guides for (service, lo-hi) line items that
match our job descriptions, in-range. Merge with the preserved Reddit real-quote rows. Target 400
total. Writes unified data/external/scraped_pilot.csv with provenance + honest price_type tags."""
import re, csv, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from playwright.sync_api import sync_playwright
from houseprice.data_load import load_dataset, labeled

TARGET = 400
SIM_THRESH = 0.13
PRICE_MIN, PRICE_MAX = 60, 7300
OUT = "data/external/scraped_pilot.csv"
FIELDS = ["source_site", "source_url", "service_category", "job_description", "matched_existing",
          "match_sim", "estimate_lo", "estimate_hi", "price_raw", "price_adj", "price_type",
          "year", "zip_code", "price_context"]

lab = labeled(load_dataset())
OUR = lab["job_description"].fillna("").astype(str).tolist()
VEC = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english").fit(OUR)
OURM = VEC.transform(OUR)
def match(t):
    s = cosine_similarity(VEC.transform([t]), OURM)[0]; i = int(s.argmax()); return float(s[i]), OUR[i]

CAT_KW = {
    "Plumbing": ["plumb", "water heater", "faucet", "drain", "pipe", "toilet", "sewer", "sump", "garbage disposal"],
    "HVAC": ["hvac", "furnace", "a/c", "air condition", "heat pump", "mini split", "ac ", "duct", "boiler", "thermostat"],
    "Electrical": ["electric", "panel", "wiring", "outlet", "breaker", "ceiling fan", "light fixture", "ev charger"],
    "Roofing": ["roof", "shingle", "gutter"], "Flooring": ["floor", "tile", "hardwood", "carpet", "laminate"],
    "Landscaping": ["landscap", "lawn", "yard", "mow", "tree", "leaf", "sod", "mulch", "irrigation", "sprinkler"],
    "Appliance Repair": ["fridge", "refrigerator", "washer", "dryer", "dishwasher", "oven", "appliance", "disposal"],
    "Pest Control": ["pest", "termite", "mosquito", "extermin", "rodent", "bed bug"],
    "Cleaning": ["clean", "wash", "maid"], "Moving": ["moving", "movers", "haul"],
    "Painting": ["paint"], "Handyman": ["handyman", "install", "mount", "drywall", "repair", "fix", "assembly"],
}
def categorize(t):
    t = t.lower()
    for c, ks in CAT_KW.items():
        if any(k in t for k in ks):
            return c
    return ""

FIXR = ["plumbing", "hvac", "electrical", "roofing", "flooring", "landscaping", "house-cleaning",
        "appliance-repair", "pest-control", "interior-painting", "handyman", "lawn-care",
        "gutter-cleaning", "tree-removal", "carpet-cleaning", "window-cleaning", "water-heater",
        "drain-cleaning", "toilet-installation", "faucet-installation", "ac-repair",
        "ceiling-fan-installation", "garbage-disposal-installation", "furnace-replacement",
        "deck", "fence", "siding", "window-installation", "door-installation", "water-heater-repair",
        "sump-pump-installation", "pressure-washing", "junk-removal", "dryer-vent-cleaning",
        "chimney-sweep", "mini-split-installation", "insulation", "sewer-line-replacement",
        "window-replacement", "sod-installation", "mulch-installation", "power-washing"]
HG = ["plumber-cost", "hvac-repair-cost", "electrician-cost", "roof-repair-cost",
      "flooring-installation-cost", "landscaping-cost", "house-cleaning-cost", "appliance-repair-cost",
      "pest-control-cost", "interior-painting-cost", "handyman-cost", "lawn-mowing-cost",
      "gutter-cleaning-cost", "tree-removal-cost", "carpet-cleaning-cost", "drain-cleaning-cost",
      "water-heater-installation-cost", "furnace-replacement-cost", "ac-repair-cost",
      "toilet-installation-cost", "garbage-disposal-installation-cost", "ceiling-fan-installation-cost",
      "deck-cost", "fence-installation-cost", "pressure-washing-cost", "junk-removal-cost",
      "dryer-vent-cleaning-cost", "window-replacement-cost", "sump-pump-installation-cost",
      "siding-installation-cost", "mini-split-installation-cost", "chimney-sweep-cost",
      "sewer-line-replacement-cost", "faucet-installation-cost", "sod-installation-cost",
      "window-cleaning-cost", "pest-inspection-cost", "mattress-removal-cost"]
URLS = [("fixr.com", f"https://www.fixr.com/costs/{s}") for s in FIXR] + \
       [("homeguide.com", f"https://homeguide.com/costs/{s}") for s in HG]

RANGE = re.compile(r"([A-Za-z][A-Za-z0-9 /&'\-]{3,55}?)\s*[:\-–]?\s*\$\s?(\d[\d,]{1,5})\s*(?:[-–]|to)\s*\$?\s?(\d[\d,]{1,6})")

rows, seen = [], set()

# --- preserve Reddit real-quote rows ---
if os.path.exists("data/external/_reddit_rows.csv"):
    import csv as _csv
    with open("data/external/_reddit_rows.csv") as fh:
        for r in _csv.DictReader(fh):
            r.setdefault("estimate_lo", ""); r.setdefault("estimate_hi", "")
            rows.append({k: r.get(k, "") for k in FIELDS})
            seen.add((round(float(r.get("price_raw") or 0)), (r.get("job_description") or "")[:40].lower()))
print(f"loaded {len(rows)} preserved Reddit rows")

def write():
    os.makedirs("data/external", exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                       viewport={"width": 1280, "height": 900}).new_page()
    for site, url in URLS:
        if len(rows) >= TARGET:
            break
        try:
            r = pg.goto(url, wait_until="domcontentloaded", timeout=22000)
            if not r or r.status >= 400:
                continue
            pg.wait_for_timeout(1500)
            body = pg.inner_text("body")[:300000]
        except Exception:
            continue
        n0 = len(rows)
        for m in RANGE.finditer(body):
            label = re.sub(r"\s+", " ", m.group(1)).strip(" :-–").strip()
            lo = float(m.group(2).replace(",", "")); hi = float(m.group(3).replace(",", ""))
            if len(label) < 4 or lo >= hi or not (PRICE_MIN <= lo and hi <= PRICE_MAX):
                continue
            if any(w in label.lower() for w in ["average", "national", "cost", "range", "table", "per "]):
                continue
            sim, near = match(label)
            if sim < SIM_THRESH:
                continue
            mid = round((lo + hi) / 2, 2)
            key = (round(mid), label[:40].lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"source_site": site, "source_url": url,
                         "service_category": categorize(label + " " + near), "job_description": label[:160],
                         "matched_existing": near[:90], "match_sim": round(sim, 3),
                         "estimate_lo": lo, "estimate_hi": hi, "price_raw": mid, "price_adj": mid,
                         "price_type": "guide_range", "year": 2024, "zip_code": "",
                         "price_context": m.group(0)[:130]})
            if len(rows) >= TARGET:
                break
        print(f"  {site} {url.split('/')[-1]:32s} +{len(rows)-n0}  total={len(rows)}", flush=True)
        if len(rows) % 40 < 5:
            write()
    b.close()

write()
import statistics as st
by_src, by_cat, by_type = {}, {}, {}
for r in rows:
    by_src[r["source_site"]] = by_src.get(r["source_site"], 0) + 1
    by_cat[r["service_category"] or "?"] = by_cat.get(r["service_category"] or "?", 0) + 1
    by_type[r["price_type"]] = by_type.get(r["price_type"], 0) + 1
pa = [float(r["price_adj"]) for r in rows if r["price_adj"]]
print(f"\n=== UNIFIED SCRAPED DATASET ===\nTOTAL ROWS: {len(rows)} (target {TARGET})")
print(f"price median ${st.median(pa):.0f} range ${min(pa):.0f}-${max(pa):.0f} (ours median $302)")
print(f"by source: {by_src}\nby price_type: {by_type}\nby category: {by_cat}")
print(f"wrote {OUT}")
