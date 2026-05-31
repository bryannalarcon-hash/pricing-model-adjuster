"""Full scrape+clean pipeline (browser-control). Crawls accessible home-service sites, keeps ONLY
posts whose job text matches our existing 411 job_descriptions (TF-IDF cosine), extracts a price +
provenance, range-filters to our marketplace, dedups, inflation-adjusts. Writes a CSV.

Target 400 matched entries; writes incrementally so a partial run still yields a usable CSV.
"""
import re, csv, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from playwright.sync_api import sync_playwright
from houseprice.data_load import load_dataset, labeled

TARGET = 400
SIM_THRESH = 0.15            # TF-IDF cosine of post title to nearest existing description
PRICE_MIN, PRICE_MAX = 60, 7300   # our observed final_price range ($46-$7266)
MAX_VISITS = 700            # crawl budget (post pages opened)
OUT = "data/external/scraped_pilot.csv"
BASE_YEAR = 2024

lab = labeled(load_dataset())
OUR_DESC = lab["job_description"].fillna("").astype(str).tolist()
VEC = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english").fit(OUR_DESC)
OURM = VEC.transform(OUR_DESC)

def match(text):
    sims = cosine_similarity(VEC.transform([text]), OURM)[0]
    i = int(sims.argmax())
    return float(sims[i]), OUR_DESC[i]

PRICE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,5})(?:\.\d{2})?")
ZIP = re.compile(r"\b(\d{5})\b")
CAT_KW = {
    "Plumbing": ["plumb", "water heater", "faucet", "drain", "pipe", "toilet", "sewer", "sump"],
    "HVAC": ["hvac", "furnace", "a/c", "air condition", "heat pump", "mini split", "ac ", "duct", "ac tune"],
    "Electrical": ["electric", "panel", "wiring", "outlet", "breaker", "ev charger"],
    "Roofing": ["roof", "shingle", "gutter"], "Flooring": ["floor", "tile", "hardwood", "carpet"],
    "Landscaping": ["landscap", "lawn", "yard", "mow", "tree", "leaf"],
    "Appliance Repair": ["fridge", "refrigerator", "washer", "dryer", "dishwasher", "oven", "appliance"],
    "Pest Control": ["pest", "termite", "mosquito", "extermin", "rodent"],
    "Cleaning": ["clean", "wash", "gutter clean"], "Moving": ["moving", "movers", "haul"],
    "Handyman": ["handyman", "install", "mount", "drywall", "repair", "fix"],
}
def categorize(t):
    t = t.lower()
    for c, ks in CAT_KW.items():
        if any(k in t for k in ks):
            return c
    return ""

def pick_price(text):
    best = None
    for m in PRICE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if not (PRICE_MIN <= v <= PRICE_MAX):
            continue
        ctx = text[max(0, m.start() - 55):m.end() + 22]
        low = ctx.lower()
        ptype = ("final" if any(w in low for w in ["paid", "final", "ended up", "cost me", "charged", "total was"])
                 else "quote" if any(w in low for w in ["quote", "estimate", "bid"]) else "mention")
        rank = {"final": 3, "quote": 2, "mention": 1}[ptype]
        if best is None or rank > best[3] or (rank == best[3] and v > best[0]):
            best = (v, ptype, ctx.replace("\n", " ").strip(), rank)
    return best

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
SUBS = ["hvac", "Plumbing", "electricians", "HomeImprovement", "Handyman", "Roofing", "Flooring",
        "lawncare", "AppliancRepair", "Pestcontrol", "HomeMaintenance", "DIY"]
QUERIES = ["quote cost", "paid installed", "estimate replace"]

rows, seen, visits = [], set(), [0]
fields = ["source_site", "source_url", "service_category", "job_description", "matched_existing",
          "match_sim", "price_raw", "price_adj", "price_type", "year", "zip_code", "price_context"]

def write():
    os.makedirs("data/external", exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)

def consider(page, source, url, title):
    sim, near = match(title)
    if sim < SIM_THRESH:
        return
    if visits[0] >= MAX_VISITS or len(rows) >= TARGET:
        return
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000); page.wait_for_timeout(700)
        visits[0] += 1
        body = page.inner_text("body")[:18000]
    except Exception:
        return
    pr = pick_price(title + "\n" + body)
    if not pr:
        return
    key = (round(pr[0]), title[:40].lower())
    if key in seen:
        return
    seen.add(key)
    yr = BASE_YEAR
    ym = re.search(r"\b(20[01]\d|202[0-5])\b", body)
    if ym:
        yr = int(ym.group(1))
    z = ZIP.search(body)
    adj = round(pr[0] * (1.03 ** (BASE_YEAR - yr)), 2)
    rows.append({"source_site": source, "source_url": url, "service_category": categorize(title + " " + near),
                 "job_description": title[:200], "matched_existing": near[:90], "match_sim": round(sim, 3),
                 "price_raw": pr[0], "price_adj": adj, "price_type": pr[1], "year": yr,
                 "zip_code": z.group(1) if z else "", "price_context": pr[2][:130]})
    if len(rows) % 20 == 0:
        write(); print(f"  ...{len(rows)} matched (visits={visits[0]})", flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}).new_page()
    # --- Reddit (old.reddit), multiple subs x queries x pagination ---
    for sub in SUBS:
        if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
            break
        for q in QUERIES:
            url = f"https://old.reddit.com/r/{sub}/search/?q={q.replace(' ', '%20')}&restrict_sr=on&sort=relevance&t=all"
            for _ in range(3):  # up to 3 pages
                if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
                    break
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=22000); pg.wait_for_timeout(1300)
                    items = pg.eval_on_selector_all(
                        "a.search-title", "els => els.map(e => ({t:e.innerText, u:e.href}))")
                    nxt = pg.eval_on_selector_all(".nav-buttons .next-button a, a[rel~='next']",
                                                  "els => els.length ? els[0].href : null")
                except Exception:
                    break
                for it in items:
                    consider(pg, f"reddit/r/{sub}", it["u"], it["t"])
                    if len(rows) >= TARGET or visits[0] >= MAX_VISITS:
                        break
                if not nxt:
                    break
                url = nxt
    b.close()

write()
import statistics as st
print(f"\n=== SCRAPE PIPELINE DONE ===")
print(f"matched entries: {len(rows)} (target {TARGET}, visits {visits[0]})")
if rows:
    by_src = {}; by_cat = {}; by_type = {}
    for r in rows:
        by_src[r["source_site"]] = by_src.get(r["source_site"], 0) + 1
        by_cat[r["service_category"] or "?"] = by_cat.get(r["service_category"] or "?", 0) + 1
        by_type[r["price_type"]] = by_type.get(r["price_type"], 0) + 1
    pa = [r["price_adj"] for r in rows]
    print(f"price_adj: median ${st.median(pa):.0f}  range ${min(pa):.0f}-${max(pa):.0f}  (ours: median $302)")
    print(f"by source: {by_src}")
    print(f"by category: {by_cat}")
    print(f"by price_type: {by_type}")
    print(f"\nwrote {OUT}")
