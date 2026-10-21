"""Step 1: download Squad Eleven scorecards from CricClubs.

Opens each results page listed in config.json in a real (headless) Chrome,
finds every match card that mentions the team, and saves each scorecard page
to data/raw/. Finished scorecards are cached, so later runs only download
new matches.

Run directly:   python scrape.py            (headless)
                python scrape.py --headed   (shows the browser; helps if the
                                             site blocks headless browsers)
"""
import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "data" / "index.json"
STATUS = ROOT / "data" / "status.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

# For each scorecard link, walk up the page to the element that holds the
# whole match card (team names, series, result) and return its text.
JS_CARDS = r"""() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="viewScorecard.do"]')) {
    const href = a.href;
    if (seen.has(href)) continue;
    seen.add(href);
    let el = a, txt = '';
    for (let i = 0; i < 10 && el.parentElement; i++) {
      el = el.parentElement;
      txt = el.innerText || '';
      if (/\sv(s)?\s/i.test(txt) && txt.length > 40) break;
    }
    out.push({ href, card: txt.slice(0, 1500) });
  }
  return out;
}"""

FINISHED = re.compile(r"won by|match tied|tied|no result|abandon|cancel|forfeit|conceded", re.I)
BLOCKED = re.compile(r"access denied|captcha|are you a robot|attention required|verify you are human", re.I)


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def match_key(url):
    """'https://cricclubs.com/MichCA/viewScorecard.do?matchId=4370&clubId=2119' -> 'MichCA_4370'."""
    p = urlparse(url)
    club = p.path.strip("/").split("/")[0] or "club"
    mid = parse_qs(p.query).get("matchId", ["x"])[0]
    return f"{club}_{mid}"


def open_page(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


def expand_results(page):
    """Scroll and press any 'load more' button so older matches appear."""
    for _ in range(15):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(700)
        more = page.locator("text=/^(load|show|view) more/i")
        if more.count() and more.first.is_visible():
            try:
                more.first.click(timeout=3000)
                page.wait_for_timeout(1500)
                continue
            except Exception:
                pass
        break


def main(headed=False):
    from playwright.sync_api import sync_playwright

    cfg = load_config()
    team_re = re.compile("|".join(re.escape(a) for a in cfg["team_aliases"]), re.I)
    RAW.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    status = {"time": datetime.now(timezone.utc).isoformat(timespec="minutes"), "sources": [], "new": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed,
                                     args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # 1. Collect Squad Eleven scorecard links from each results page.
        wanted = []
        for src in cfg["sources"]:
            entry = {"league": src["league"], "url": src["url"], "found": 0, "error": None}
            try:
                open_page(page, src["url"])
                if "listMatches" not in page.url:
                    # Club home link: follow its "Results" link to the full match list.
                    link = page.evaluate("""() => {
                      const a = [...document.querySelectorAll('a[href*="listMatches.do"]')];
                      const pick = a.find(x => /result/i.test(x.innerText)) || a[0];
                      return pick ? pick.href : null; }""")
                    if link:
                        open_page(page, link)
                expand_results(page)
                html = page.content()
                if BLOCKED.search(html) and "viewScorecard" not in html:
                    raise RuntimeError("CricClubs showed a bot-check page instead of results")
                for c in page.evaluate(JS_CARDS):
                    if team_re.search(c["card"]):
                        wanted.append({"url": urljoin(src["url"], c["href"]),
                                       "league": src["league"], "card": c["card"]})
                        entry["found"] += 1
            except Exception as e:  # keep going with the other leagues
                entry["error"] = str(e)[:300]
            status["sources"].append(entry)
            print(f"[{src['league']}] {entry['found']} Squad Eleven matches"
                  + (f"  ERROR: {entry['error']}" if entry["error"] else ""))

        for url in cfg.get("extra_scorecards", []):
            wanted.append({"url": url, "league": "Other", "card": ""})

        # 2. Download each scorecard not already cached as finished.
        for w in wanted:
            key = match_key(w["url"])
            path = RAW / f"{key}.html"
            prev = index.get(key, {})
            index[key] = {**prev, "url": w["url"], "league": w["league"],
                          "card": w["card"] or prev.get("card", "")}
            if path.exists() and FINISHED.search(path.read_text(encoding="utf-8", errors="ignore")):
                continue
            try:
                open_page(page, w["url"])
                html = page.content()
                if BLOCKED.search(html) and "innings" not in html.lower():
                    print(f"  blocked on {key}")
                    continue
                path.write_text(html, encoding="utf-8")
                status["new"] += 1
                print(f"  saved {key}")
                time.sleep(1.5)  # be polite to CricClubs
            except Exception as e:
                print(f"  failed {key}: {e}")

        browser.close()

    INDEX.write_text(json.dumps(index, indent=1), encoding="utf-8")
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")
    ok = any(s["found"] for s in status["sources"])
    print(f"Done: {len(index)} matches known, {status['new']} downloaded this run.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(headed="--headed" in sys.argv) else 1)
