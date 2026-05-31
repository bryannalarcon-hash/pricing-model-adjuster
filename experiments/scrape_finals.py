"""Finals-only crawler. Targets community-board posts that state an ACTUAL PAID price ("I paid $X",
"final bill", "ended up costing"), matched to our job descriptions. Extracts final_price (required)
and quoted_price (optional -> a real estimate->final pair). Writes data/external/scraped_pilot.csv.
Seeds with the 12 real 'final' Reddit rows already found. Pivots per /goal: get the full data."""
import re, csv, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from playwright.sync_api import sync_playwright
from houseprice.data_load import load_dataset, labeled

TARGET = 220
SIM_THRESH = 0.04
PMIN, PMAX = 60, 7300
MAX_VISITS = 900
OUT = sys.argv[2] if len(sys.argv) > 2 else "data/external/scraped_pilot.csv"
FIELDS = ["source_site", "source_url", "service_category", "job_description", "matched_existing",
          "match_sim", "quoted_price", "final_price", "year", "zip_code", "price_context"]

lab = labeled(load_dataset())
OUR = lab["job_description"].fillna("").astype(str).tolist()
VEC = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english").fit(OUR)
OURM = VEC.transform(OUR)
def match(t):
    s = cosine_similarity(VEC.transform([t]), OURM)[0]; i = int(s.argmax()); return float(s[i]), OUR[i]

CAT_KW = {
    "Plumbing": ["plumb", "water heater", "faucet", "drain", "pipe", "toilet", "sewer", "sump", "disposal"],
    "HVAC": ["hvac", "furnace", "a/c", "air condition", "heat pump", "mini split", "ac ", "duct", "boiler"],
    "Electrical": ["electric", "panel", "wiring", "outlet", "breaker", "fan", "ev charger"],
    "Roofing": ["roof", "shingle", "gutter"], "Flooring": ["floor", "tile", "hardwood", "carpet"],
    "Landscaping": ["landscap", "lawn", "yard", "mow", "tree", "sod", "mulch", "sprinkler", "irrigation"],
    "Appliance Repair": ["fridge", "refrigerator", "washer", "dryer", "dishwasher", "oven", "appliance"],
    "Pest Control": ["pest", "termite", "mosquito", "extermin", "rodent", "bed bug"],
    "Cleaning": ["clean", "maid"], "Moving": ["moving", "movers", "haul"], "Painting": ["paint"],
    "Handyman": ["handyman", "install", "mount", "drywall", "repair", "fix"],
}
def categorize(t):
    t = t.lower()
    for c, ks in CAT_KW.items():
        if any(k in t for k in ks):
            return c
    return ""

PRICE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,5})(?:\.\d{2})?")
ZIP = re.compile(r"\b(\d{5})\b")
FINAL_CUES = ["i paid", "we paid", "paid ", "final bill", "final cost", "ended up", "charged me",
              "cost me", "came to", "total was", "total came", "ended up costing", "all in"]
QUOTE_CUES = ["quote", "quoted", "estimate", "estimated", "bid ", "they wanted", "asking"]

def classify_prices(text):
    final, quote = None, None
    for m in PRICE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if not (PMIN <= v <= PMAX):
            continue
        ctx = text[max(0, m.start() - 55):m.end() + 20]; low = ctx.lower()
        if any(c in low for c in FINAL_CUES):
            if final is None or v > final[0]:
                final = (v, ctx.replace("\n", " ").strip())
        elif any(c in low for c in QUOTE_CUES):
            if quote is None or v > quote[0]:
                quote = (v, ctx.replace("\n", " ").strip())
    return final, quote

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
_DEFAULT_SUBS = ["hvac", "Plumbing", "electricians", "HomeImprovement", "Handyman", "Roofing", "Flooring",
        "lawncare", "landscaping", "AppliancRepair", "Pestcontrol", "HomeMaintenance", "DIY",
        "hvacadvice", "Construction", "Renovations"]
SUBS = sys.argv[1].split(",") if len(sys.argv) > 1 else _DEFAULT_SUBS
SORT = sys.argv[3] if len(sys.argv) > 3 else "relevance"
QUERIES = ["total was", "came out to", "invoice for", "spent on", "ended up at", "cost was",
           "price came to", "they charged", "quote came in", "estimate was"]

rows, seen, visits = [], set(), [0]   # shard worker: no seeding (merge step handles seed + dedup)

def write():
    os.makedirs("data/external", exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

def consider(pg, source, url, title):
    sim, near = match(title)
    cat0 = categorize(title)
    if (sim < SIM_THRESH and not cat0) or visits[0] >= MAX_VISITS or len(rows) >= TARGET:
        return
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=18000); pg.wait_for_timeout(650)
        visits[0] += 1
        body = pg.inner_text("body")[:18000]
    except Exception:
        return
    final, quote = classify_prices(title + "\n" + body)
    if not final:
        return
    key = (round(final[0]), title[:40].lower())
    if key in seen:
        return
    seen.add(key)
    yr = 2024
    ym = re.search(r"\b(20[01]\d|202[0-5])\b", body)
    if ym:
        yr = int(ym.group(1))
    z = ZIP.search(body)
    rows.append({"source_site": source, "source_url": url,
                 "service_category": categorize(title + " " + near), "job_description": title[:160],
                 "matched_existing": near[:90], "match_sim": round(sim, 3),
                 "quoted_price": quote[0] if quote else "", "final_price": final[0],
                 "year": yr, "zip_code": z.group(1) if z else "", "price_context": final[1][:130]})
    if len(rows) % 15 == 0:
        write(); print(f"  ...{len(rows)} finals (visits={visits[0]})", flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}).new_page()
    for sub in SUBS:
        if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
            break
        for q in QUERIES:
            if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
                break
            url = f"https://old.reddit.com/r/{sub}/search/?q={q.replace(' ', '%20')}&restrict_sr=on&sort={SORT}&t=all"
            for _ in range(3):
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=20000); pg.wait_for_timeout(1100)
                    items = pg.eval_on_selector_all("a.search-title", "els=>els.map(e=>({t:e.innerText,u:e.href}))")
                    nxt = pg.eval_on_selector_all(".nav-buttons .next-button a, a[rel~='next']",
                                                  "els=>els.length?els[0].href:null")
                except Exception:
                    break
                for it in items:
                    consider(pg, f"reddit/r/{sub}", it["u"], it["t"])
                    if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
                        break
                if not nxt or len(rows) >= TARGET or visits[0] >= MAX_VISITS:
                    break
                url = nxt
        print(f"[{sub}] running total finals={len(rows)} visits={visits[0]}", flush=True)
    b.close()

write()
import statistics as st
pairs = sum(1 for r in rows if r["quoted_price"] != "")
fp = [float(r["final_price"]) for r in rows]
print(f"\n=== FINALS-ONLY DATASET ===\nrows with a real final_price: {len(rows)} (target {TARGET}, visits {visits[0]})")
if fp:
    print(f"final_price median ${st.median(fp):.0f} range ${min(fp):.0f}-${max(fp):.0f} (ours median $302)")
    print(f"rows that ALSO have a quote (estimate->final pair): {pairs}")
    by = {}
    for r in rows:
        s = r["source_site"].split("/")[0]; by[s] = by.get(s, 0) + 1
    print(f"by source: {by}")
print(f"wrote {OUT}")
