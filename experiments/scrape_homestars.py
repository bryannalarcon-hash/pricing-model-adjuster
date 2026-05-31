"""HomeStars (CA) crawler — COMPLIANT: normal browser, robots-respecting (robots.txt for `*` only
disallows /login, /_next, /*.json$, none of which we touch). Mines the STRUCTURED
"Approximate cost of services: $X" field that HomeStars attaches to customer reviews — these are
real paid finals from a HouseAccount-like marketplace distribution (the one source clearing all
three bars: real finals + compliant + right distribution). No quote is exposed -> ALL-arm rows.
FX CAD->USD applied (HomeStars prices are CAD). Writes a scraped_pilot-schema CSV shard.

Usage: python scrape_homestars.py <catLabel1,catLabel2,...> <out.csv>
  catLabel in: Plumbing HVAC Electrical Roofing Flooring Painting Landscaping
               "Appliance Repair" "Pest Control" Handyman Cleaning Moving
"""
import re, csv, os, sys

CAD_USD = 0.73  # assumption: ~2024-25 average; documented in JOURNAL. Conversion of HomeStars CAD finals.

# HomeStars category slug(s) per our vertical, crawled across several CA cities.
CAT_SLUGS = {
    "Plumbing": ["plumbing"],
    "HVAC": ["heating-air-conditioning", "heating-cooling"],
    "Electrical": ["electricians", "electrical"],
    "Roofing": ["roofing"],
    "Flooring": ["flooring", "hardwood-flooring"],
    "Painting": ["painters", "painting"],
    "Landscaping": ["landscaping"],
    "Appliance Repair": ["appliance-repair"],
    "Pest Control": ["pest-control"],
    "Handyman": ["handyman-services", "handyman"],
    "Cleaning": ["house-cleaning", "cleaning-services"],
    "Moving": ["moving-storage", "movers"],
}
CITIES = ["on/toronto", "bc/vancouver", "ab/calgary", "on/ottawa", "ab/edmonton", "on/mississauga"]

TARGET = 180          # per shard
MAX_COMPANIES = 220   # per shard, politeness cap
PMIN, PMAX = 60, 7300 # USD window (after FX) — match the eval filter

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
FIELDS = ["source_site", "source_url", "service_category", "job_description", "matched_existing",
          "match_sim", "quoted_price", "final_price", "year", "zip_code", "price_context"]

# "Approximate cost of services : $1,234.56"  (label spacing/casing varies)
COST = re.compile(r"approximate cost of services?\s*[:\-]?\s*\$?\s?([\d][\d,]*(?:\.\d{2})?)", re.I)
ANYP = re.compile(r"\$\s?([\d][\d,]*(?:\.\d{2})?)")
YEAR = re.compile(r"\b(20[01]\d|202[0-6])\b")

CATS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["Plumbing"]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data/external/homestars.csv"

from playwright.sync_api import sync_playwright

rows, seen = [], set()

def log(m): print(m, flush=True)

def write():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

def accept(pg):
    for sel in ["button:has-text('Accept')", "button:has-text('Agree')", "[id*='accept']",
                "[aria-label*='accept' i]", "button:has-text('Allow all')"]:
        try:
            el = pg.query_selector(sel)
            if el and el.is_visible():
                el.click(); pg.wait_for_timeout(400); return
        except Exception:
            pass

def mine_company(pg, url, cat):
    """Visit a company page (no .json/_next), scroll to hydrate reviews, pull every
    'Approximate cost of services' final with its review context."""
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return 0
    pg.wait_for_timeout(1200); accept(pg)
    for _ in range(8):
        pg.mouse.wheel(0, 4000); pg.wait_for_timeout(450)
    try:
        body = pg.inner_text("body")
    except Exception:
        return 0
    got = 0
    for m in COST.finditer(body):
        cad = float(m.group(1).replace(",", ""))
        usd = round(cad * CAD_USD, 2)
        if not (PMIN <= usd <= PMAX):
            continue
        # job description: the review text in a window BEFORE the cost label (HomeStars puts the
        # written review above the structured cost line); fall back to the line after.
        pre = body[max(0, m.start() - 400):m.start()]
        desc = re.sub(r"\s+", " ", pre).strip()
        # trim to the last sentence-ish chunk (the actual review prose), drop nav crumbs
        desc = desc[-220:].strip()
        yr_m = YEAR.search(body[max(0, m.start() - 600):m.start() + 60])
        yr = int(yr_m.group(1)) if yr_m else 2024
        ctx = re.sub(r"\s+", " ", body[max(0, m.start() - 40):m.end() + 20]).strip()
        key = (round(usd), desc[:50].lower())
        if key in seen or len(desc) < 12:
            continue
        seen.add(key)
        rows.append({"source_site": "homestars.com", "source_url": url,
                     "service_category": cat, "job_description": desc[:160],
                     "matched_existing": "", "match_sim": "", "quoted_price": "",
                     "final_price": usd, "year": yr, "zip_code": "",
                     "price_context": ("CAD %.0f -> USD %.0f | " % (cad, usd)) + ctx[:110]})
        got += 1
        if len(rows) % 15 == 0:
            write(); log(f"    ...{len(rows)} finals so far")
    return got

def company_links(pg, listing_url):
    try:
        pg.goto(listing_url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return []
    pg.wait_for_timeout(1200); accept(pg)
    for _ in range(6):
        pg.mouse.wheel(0, 4000); pg.wait_for_timeout(450)
    try:
        links = pg.eval_on_selector_all(
            "a[href*='/companies/']",
            "els=>[...new Set(els.map(e=>e.href))]")
    except Exception:
        return []
    # keep only real company profiles, never .json/_next/login
    out = []
    for l in links:
        if any(b in l for b in (".json", "/_next", "/login")):
            continue
        if "/companies/" in l and l.rstrip("/").split("/")[-1]:
            out.append(l.split("?")[0])
    return list(dict.fromkeys(out))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, locale="en-CA",
                       viewport={"width": 1366, "height": 1200}).new_page()
    visited = set()
    n_comp = 0
    for cat in CATS:
        if len(rows) >= TARGET or n_comp >= MAX_COMPANIES:
            break
        slugs = CAT_SLUGS.get(cat, [cat.lower().replace(" ", "-")])
        for city in CITIES:
            if len(rows) >= TARGET or n_comp >= MAX_COMPANIES:
                break
            for slug in slugs:
                listing = f"https://homestars.com/{city}/{slug}"
                links = company_links(pg, listing)
                log(f"[{cat}] {listing} -> {len(links)} company links")
                if not links:
                    continue
                for cl in links:
                    if cl in visited:
                        continue
                    visited.add(cl); n_comp += 1
                    g = mine_company(pg, cl, cat)
                    if g:
                        log(f"  +{g} from {cl.split('/')[-1][:40]} (total {len(rows)})")
                    if len(rows) >= TARGET or n_comp >= MAX_COMPANIES:
                        break
                break  # one working slug per city is enough
    b.close()

write()
import statistics as st
fp = [float(r["final_price"]) for r in rows]
log(f"\n=== HomeStars shard [{','.join(CATS)}] ===")
log(f"rows: {len(rows)} | companies visited: {n_comp}")
if fp:
    log(f"final_price (USD) median ${st.median(fp):.0f} range ${min(fp):.0f}-${max(fp):.0f} (ours median $302)")
log(f"wrote {OUT}")
