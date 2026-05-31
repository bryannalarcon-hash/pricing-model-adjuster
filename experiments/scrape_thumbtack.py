"""Marketplace crawler — Thumbtack well-reviewed pros (mimics HouseAccount: reviewed providers,
marketplace-scale prices). For each (city, category): open the category page, visit high-rated pro
profiles, extract the displayed price + rating. Keep rating>=4.5 and price in our range. Tag
price_type='marketplace'. Args: shard cities ("tx/austin,il/chicago"), output path."""
import re, csv, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from playwright.sync_api import sync_playwright
from houseprice.data_load import load_dataset, labeled, normalize_category, is_production_category

CITIES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["tx/austin"]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data/external/_tt.csv"
PMIN, PMAX = 50, 7300
PER_CAT_PROS = 7
MAX_VISITS = 150
MIN_RATING = 4.5
CATS = {  # thumbtack slug -> our category
    "house-cleaning": "Cleaning", "handyman": "Handyman", "plumbing": "Plumbing",
    "electrical": "Electrical", "hvac": "HVAC", "lawn-care": "Landscaping",
    "pest-control": "Pest Control", "roofing": "Roofing", "flooring": "Flooring",
    "appliance-repair": "Appliance Repair", "interior-painting": "Painting",
    "landscaping": "Landscaping", "carpet-cleaning": "Cleaning", "window-cleaning": "Cleaning",
    "junk-removal": "Moving", "local-moving": "Moving", "tree-trimming": "Landscaping",
    "gutter-cleaning": "Cleaning", "drain-cleaning": "Plumbing", "tv-mounting": "Handyman",
}
lab = labeled(load_dataset()); OURD = lab["job_description"].fillna("").astype(str).tolist()
VEC = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit(OURD); OURM = VEC.transform(OURD)
def near(t):
    s = cosine_similarity(VEC.transform([t]), OURM)[0]; i = int(s.argmax()); return OURD[i]

PRICE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})*|\d{2,5})")
RATING = re.compile(r"\b([45]\.\d)\b")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
FIELDS = ["source_site", "source_url", "service_category", "job_description", "matched_existing",
          "rating", "final_price", "price_type", "zip_code", "city", "price_context"]
rows, seen, visits = [], set(), [0]

def write():
    os.makedirs("data/external", exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 1600}).new_page()
    for city in CITIES:
        for slug, ourcat in CATS.items():
            if visits[0] >= MAX_VISITS:
                break
            cat_url = f"https://www.thumbtack.com/{city}/{slug}/"
            try:
                pg.goto(cat_url, wait_until="domcontentloaded", timeout=30000); pg.wait_for_timeout(2500)
                links = pg.eval_on_selector_all(
                    f"a[href*='/{city}/{slug}/']",
                    "els=>[...new Set(els.map(e=>e.href))]")
                links = [l for l in links if l.rstrip("/") != cat_url.rstrip("/")][:PER_CAT_PROS]
            except Exception:
                continue
            for l in links:
                if visits[0] >= MAX_VISITS:
                    break
                try:
                    pg.goto(l, wait_until="domcontentloaded", timeout=18000); pg.wait_for_timeout(1500)
                    visits[0] += 1
                    body = pg.inner_text("body")[:14000]
                except Exception:
                    continue
                rmatch = RATING.search(body)
                rating = float(rmatch.group(1)) if rmatch else 0.0
                if 0 < rating < MIN_RATING:   # Thumbtack-listed pros are pre-ranked by quality;
                    continue                  # only drop confirmed-low ratings, keep unparsed ones
                pr = [float(x.replace(",", "")) for x in PRICE.findall(body)]
                pr = [v for v in pr if PMIN <= v <= PMAX]
                if not pr:
                    continue
                price = sorted(pr)[len(pr) // 2]  # median displayed price
                key = (round(price), slug, l.split("/")[-1][:24])
                if key in seen:
                    continue
                seen.add(key)
                ctx = body[max(0, body.find("$")):body.find("$") + 60].replace("\n", " ").strip()
                rows.append({"source_site": "thumbtack.com", "source_url": l, "service_category": ourcat,
                             "job_description": slug.replace("-", " "), "matched_existing": near(slug.replace("-", " "))[:90],
                             "rating": rating, "final_price": price, "price_type": "marketplace",
                             "zip_code": "", "city": city, "price_context": ctx[:120]})
                if len(rows) % 15 == 0:
                    write(); print(f"  ...{len(rows)} (visits {visits[0]})", flush=True)
        print(f"[{city}] total={len(rows)} visits={visits[0]}", flush=True)
    b.close()
write()
import statistics as st
fp = [r["final_price"] for r in rows]
print(f"\nTHUMBTACK shard done: {len(rows)} well-reviewed marketplace prices")
if fp:
    print(f"  price median ${st.median(fp):.0f} range ${min(fp):.0f}-${max(fp):.0f} | avg rating {st.mean([r['rating'] for r in rows]):.2f}")
    by = {}
    for r in rows: by[r["service_category"]] = by.get(r["service_category"], 0) + 1
    print(f"  by category: {by}")
print(f"wrote {OUT}")
