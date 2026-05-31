"""Compliant multi-site PoC: get ONE real customer final-price row from each permissive / international
home-service review site (normal browser, robots-respecting: no login/checkout/json paths). Prefers a
structured cost field ('approximate cost', 'job value'), else a 'paid/cost X' mention in review text.
Reports one row per site or the barrier."""
import re
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
CUR = re.compile(r"(?:US\$|CA\$|A\$|AU\$|\$|£|€)\s?(\d{2,3}(?:,\d{3})*|\d{2,6})")
COSTLBL = ["approximate cost", "cost of services", "cost of service", "job cost", "project cost",
           "job value", "total cost", "price paid", "amount paid", "cost:"]
CUE = ["paid", "cost", "charged", "spent", "quote", "invoice", "bill", "job was", "came to", "fee"]

# (name, entry_url, link-substring to follow into a company/review page)
SITES = [
    ("HomeStars (CA)", "https://homestars.com/companies/2900-plumbing", "/companies/"),
    ("HomeStars-cat (CA)", "https://homestars.com/on/toronto/plumbing", "/companies/"),
    ("Checkatrade (UK)", "https://www.checkatrade.com/trades/plumbers/london", "/trades/"),
    ("MyBuilder (UK)", "https://www.mybuilder.com/tradesmen/london/plumbers", "/profile/"),
    ("RatedPeople (UK)", "https://www.ratedpeople.com/find/plumbers", "/profile"),
    ("hipages (AU)", "https://www.hipages.com.au/find/plumbers/loc/sydney-nsw", "/connect/"),
    ("Oneflare (AU)", "https://www.oneflare.com.au/plumbers", "/business/"),
    ("Werkspot (NL)", "https://www.werkspot.nl/loodgieter", "/profiel/"),
]

def log(m): print(m, flush=True)

def accept(pg):
    for sel in ["button:has-text('Accept')", "button:has-text('Agree')", "button:has-text('Allow')",
                "button:has-text('Akkoord')", "button:has-text('Alle')", "[id*='accept']", "[aria-label*='accept' i]"]:
        try:
            el = pg.query_selector(sel)
            if el and el.is_visible(): el.click(); pg.wait_for_timeout(600); return
        except Exception: pass

def extract(text):
    low = text.lower()
    # prefer a cost-field labelled price
    for lbl in COSTLBL:
        i = low.find(lbl)
        if i >= 0:
            m = CUR.search(text[i:i + 80])
            if m:
                v = float(m.group(1).replace(",", ""))
                if 30 <= v <= 50000:
                    return v, lbl, re.sub(r"\s+", " ", text[i:i + 90]).strip()
    # else a cue-context price
    for m in CUR.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if 30 <= v <= 50000:
            ctx = text[max(0, m.start() - 55):m.end() + 20]
            if any(c in ctx.lower() for c in CUE):
                return v, "review-text", re.sub(r"\s+", " ", ctx).strip()
    return None

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 1200}).new_page()
    log("COMPLIANT MULTI-SITE PoC — one final-price row per site:\n")
    for name, url, follow in SITES:
        try:
            r = pg.goto(url, wait_until="domcontentloaded", timeout=20000)
            st = r.status if r else "?"
            pg.wait_for_timeout(2500); accept(pg)
            for _ in range(4): pg.mouse.wheel(0, 3000); pg.wait_for_timeout(700)
            body = pg.inner_text("body")
            row = extract(body)
            if not row and follow:  # follow one company/review link
                links = pg.eval_on_selector_all(f"a[href*='{follow}']", "els=>[...new Set(els.map(e=>e.href))].slice(0,3)")
                for l in links:
                    try:
                        pg.goto(l, wait_until="domcontentloaded", timeout=18000); pg.wait_for_timeout(2000); accept(pg)
                        for _ in range(5): pg.mouse.wheel(0, 3000); pg.wait_for_timeout(600)
                        row = extract(pg.inner_text("body"))
                        if row: break
                    except Exception: pass
            if row:
                log(f"=== {name} === HTTP {st}  ✅ ROW: {row[0]:.0f} via [{row[1]}] | {row[2][:80]}")
            else:
                barrier = (f"blocked HTTP {st}" if st in (403, 429) or len(body) < 800
                           else "loaded but no price/cost-field found (reviews omit amounts)")
                log(f"=== {name} === HTTP {st}  ✗ no row | barrier: {barrier}")
        except Exception as e:
            log(f"=== {name} === FAILED: {str(e)[:75]}")
    b.close()
