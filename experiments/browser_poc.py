"""PoC (instrumented, single target): can stealth headless read a Trustpilot review page that 403'd?
Prints each step so we see exactly where it gets / blocks."""
import re, sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.trustpilot.com/review/www.fantasticservices.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
STEALTH = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
window.chrome={runtime:{}};
"""
def log(m): print(m, flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled",
                                                "--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900},
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
    ctx.add_init_script(STEALTH)
    pg = ctx.new_page()
    log(f"launched; navigating {URL}")
    try:
        r = pg.goto(URL, wait_until="domcontentloaded", timeout=25000)
        log(f"  HTTP {r.status if r else '?'}")
    except Exception as e:
        log(f"  goto failed: {str(e)[:80]}"); b.close(); sys.exit()
    pg.wait_for_timeout(3000)
    for sel in ["button:has-text('Accept')", "[id*='accept']", "button:has-text('Agree')"]:
        try:
            el = pg.query_selector(sel)
            if el and el.is_visible(): el.click(); log(f"  clicked cookie: {sel}"); pg.wait_for_timeout(800); break
        except Exception: pass
    for i in range(4):
        pg.mouse.wheel(0, 2500); pg.wait_for_timeout(700)
    body = pg.inner_text("body")
    rev = sum(body.lower().count(k) for k in ["review", "stars", "rated", "verified"])
    pr = re.findall(r"[$£€]\s?\d{2,5}", body)
    log(f"  body={len(body)}c | review-signals={rev} | currency-mentions={len(pr)} {pr[:6]}")
    low = body.lower()
    log(f"  blocked? 403/challenge={'403' in low or 'are you a robot' in low or 'enable javascript' in low[:500] or len(body)<800}")
    log(f"  VERDICT: {'READABLE — barrier defeated' if len(body)>4000 and rev>5 else 'still blocked'}")
    b.close()
