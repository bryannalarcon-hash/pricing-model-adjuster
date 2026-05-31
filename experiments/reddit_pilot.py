"""Reddit pilot crawler (browser-control). Pulls price-bearing posts from home-service subreddits
via old.reddit (which loads in headless Chromium), extracts $-amounts + context + a keyword category.
Raw candidate extraction (the 'without-LLM' arm); LLM cleaning is a separate downstream step.
Writes data/external/reddit_pilot.csv and prints yield + sample + price distribution."""
import re, csv, os
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
SUBS = ["hvac", "Plumbing", "HomeImprovement", "electricians"]
QUERY = "quote installed replaced cost"
PER_SUB = 20                       # search results visited per subreddit
PRICE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,6})(?:\.\d{2})?")
CAT_KW = {  # crude keyword -> our category (the deterministic 'no-LLM' category)
    "Plumbing": ["plumb", "water heater", "faucet", "drain", "pipe", "toilet", "sewer"],
    "HVAC": ["hvac", "furnace", "ac ", "a/c", "air condition", "heat pump", "mini split", "ductwork"],
    "Electrical": ["electric", "panel", "wiring", "outlet", "breaker"],
    "Roofing": ["roof", "shingle"],
    "Handyman": ["handyman", "install", "mount", "drywall"],
    "Cleaning": ["clean"], "Landscaping": ["landscap", "lawn", "yard"], "Flooring": ["floor", "tile"],
}

def categorize(t):
    t = t.lower()
    for cat, kws in CAT_KW.items():
        if any(k in t for k in kws):
            return cat
    return ""

def prices(text):
    out = []
    for m in PRICE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if 50 <= v <= 60000:                       # plausible home-service range
            s = max(0, m.start() - 55); out.append((v, text[s:m.end() + 25].replace("\n", " ").strip()))
    return out

rows = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}).new_page()
    for sub in SUBS:
        url = f"https://old.reddit.com/r/{sub}/search/?q={QUERY.replace(' ', '%20')}&restrict_sr=on&sort=relevance&t=all"
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=25000); pg.wait_for_timeout(1800)
            links = pg.eval_on_selector_all("a.search-title",
                                            "els => els.map(e => e.href)") or \
                    pg.eval_on_selector_all('a[href*="/comments/"]', "els => els.map(e => e.href)")
            links = list(dict.fromkeys(links))[:PER_SUB]
        except Exception as e:
            print(f"[{sub}] search failed: {str(e)[:70]}"); continue
        print(f"[{sub}] {len(links)} posts")
        for link in links:
            try:
                pg.goto(link, wait_until="domcontentloaded", timeout=22000); pg.wait_for_timeout(900)
                title = (pg.title() or "")
                body = pg.inner_text("body")[:20000]
                pr = prices(title + "\n" + body)
                if not pr:
                    continue
                cat = categorize(title)
                vals = [v for v, _ in pr]
                rows.append({"source": "reddit", "subreddit": sub, "url": link, "category_kw": cat,
                             "n_prices": len(pr), "min_price": min(vals), "max_price": max(vals),
                             "title": title[:120], "price_contexts": " || ".join(c for _, c in pr[:4])})
            except Exception:
                continue
    b.close()

os.makedirs("data/external", exist_ok=True)
with open("data/external/reddit_pilot.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                       ["source", "subreddit", "url", "category_kw", "n_prices", "min_price", "max_price", "title", "price_contexts"])
    w.writeheader(); w.writerows(rows)

print(f"\n=== REDDIT PILOT YIELD ===\nposts with >=1 plausible price: {len(rows)}")
import statistics as st
allv = [r["min_price"] for r in rows]
if allv:
    print(f"price range: ${min(allv):.0f}-${max(allv):.0f}  median(min): ${st.median(allv):.0f}")
    print(f"with a keyword category: {sum(1 for r in rows if r['category_kw'])}/{len(rows)}")
    print("\nsample rows:")
    for r in rows[:8]:
        print(f"  [{r['subreddit']}/{r['category_kw'] or '?'}] ${r['min_price']:.0f}-${r['max_price']:.0f} | {r['price_contexts'][:90]}")
print("\nsaved data/external/reddit_pilot.csv")
