"""Browser-control feasibility probe: which home-service price sources load in a real headless
Chromium (vs WebFetch's blocks)? Reports per-site: load status, title, body size, $-mention count."""
import re
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

SITES = {
    "reddit_old":   "https://old.reddit.com/r/hvac/search/?q=quote%20installed&restrict_sr=on&sort=new",
    "reddit_www":   "https://www.reddit.com/r/hvac/search/?q=quote%20installed&restrict_sr=on",
    "diy_stackex":  "https://diy.stackexchange.com/search?q=cost+quote+paid",
    "hvac_talk":    "https://hvac-talk.com/vbb/",
    "terry_love":   "https://terrylove.com/forums/",
    "yelp":         "https://www.yelp.com/search?find_desc=plumbing&find_loc=Austin%2C+TX",
}

def probe(page, name, url):
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        status = resp.status if resp else "?"
        page.wait_for_timeout(2500)
        body = page.inner_text("body")[:200000]
        dollars = re.findall(r"\$\s?\d[\d,]{1,7}", body)
        title = (page.title() or "")[:60]
        print(f"  {name:14s} HTTP {status} | title={title!r} | body={len(body)}c | $mentions={len(dollars)} "
              f"| sample={dollars[:5]}")
    except Exception as e:
        print(f"  {name:14s} FAILED: {str(e)[:90]}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    print("BROWSER-CONTROL ACCESS PROBE:")
    for name, url in SITES.items():
        probe(page, name, url)
    browser.close()
