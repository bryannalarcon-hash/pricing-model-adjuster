"""Probe Angi / Yelp / Trustpilot / Google Reviews for REAL final prices in customer reviews
("paid $X", "cost me $X for the job"). Target 5 per site; log the exact barrier when blocked."""
import re
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
PRICE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})*|\d{2,5})")
CUE = ["paid", "cost me", "charged", "spent", "final", "bill", "ended up", "came to", "total"]

def finals(text):
    out = []
    for m in PRICE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if not (50 <= v <= 8000):
            continue
        ctx = text[max(0, m.start() - 60):m.end() + 25]
        if any(c in ctx.lower() for c in CUE):
            out.append((v, re.sub(r"\s+", " ", ctx).strip()))
    return out

def grab(pg, url, scroll=4, waitsel=None):
    resp = pg.goto(url, wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(3000)
    for _ in range(scroll):
        pg.mouse.wheel(0, 4000); pg.wait_for_timeout(1200)
    return (resp.status if resp else "?"), pg.inner_text("body")

def probe_angi(pg):
    try:
        st, body = grab(pg, "https://www.angi.com/companylist/us/tx/austin/plumbing.htm")
        links = pg.eval_on_selector_all("a[href*='/companyprofile/']", "els=>[...new Set(els.map(e=>e.href))].slice(0,4)")
        f = finals(body); reached = len(body) > 1500
        for l in links[:3]:
            try:
                _, b = grab(pg, l, scroll=6); f += finals(b)
            except Exception:
                pass
        bar = "none" if f else ("provider profiles found but reviews omit prices" if links else
                                ("page loaded but no provider links / reviews are JS-gated" if reached else f"blocked HTTP {st}"))
        return st, len(links), f[:5], bar
    except Exception as e:
        return "ERR", 0, [], str(e)[:80]

def probe_yelp(pg):
    try:
        st, body = grab(pg, "https://www.yelp.com/search?find_desc=plumber&find_loc=Austin%2C+TX", scroll=2)
        f = finals(body)
        bar = "none" if f else (f"hard bot-block HTTP {st}" if st == 403 or len(body) < 800 else "loaded but no price in review snippets")
        return st, "-", f[:5], bar
    except Exception as e:
        return "ERR", "-", [], str(e)[:80]

def probe_trustpilot(pg):
    try:
        st, body = grab(pg, "https://www.trustpilot.com/categories/plumber")
        links = pg.eval_on_selector_all("a[href*='/review/']", "els=>[...new Set(els.map(e=>e.href))].slice(0,5)")
        f = finals(body); reached = len(body) > 1500
        for l in links[:4]:
            try:
                _, b = grab(pg, l, scroll=6); f += finals(b)
            except Exception:
                pass
        bar = "none" if f else (f"{len(links)} companies reached but reviews omit $ amounts" if links else
                                (f"category loaded but no company links" if reached else f"blocked HTTP {st}"))
        return st, len(links), f[:5], bar
    except Exception as e:
        return "ERR", 0, [], str(e)[:80]

def probe_google(pg):
    try:
        st, body = grab(pg, "https://www.google.com/maps/search/plumber+austin+tx", scroll=3)
        low = body.lower()
        consent = "before you continue" in low or "accept all" in low or "consent" in low
        f = finals(body)
        bar = "none" if f else ("consent/captcha wall" if consent else
                                ("loaded but reviews need click-through + rarely cite $" if len(body) > 1500 else f"blocked HTTP {st}"))
        return st, "-", f[:5], bar
    except Exception as e:
        return "ERR", "-", [], str(e)[:80]

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 1600}, locale="en-US").new_page()
    print("REVIEW-SITE FINAL-PRICE PROBE (target 5 finals each):\n")
    for name, fn in [("Angi", probe_angi), ("Yelp", probe_yelp), ("Trustpilot", probe_trustpilot), ("Google Reviews", probe_google)]:
        st, links, f, bar = fn(pg)
        print(f"=== {name} ===")
        print(f"  HTTP {st} | sub-pages={links} | FINALS FOUND: {len(f)}")
        for v, c in f[:5]:
            print(f"     ${v:.0f}  | {c[:95]}")
        print(f"  BARRIER: {bar}\n")
    b.close()
