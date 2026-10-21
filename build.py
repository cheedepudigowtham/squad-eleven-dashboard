"""Step 2: turn saved scorecards into the dashboard.

Reads data/raw/*.html (saved by scrape.py), pulls out the result, scores,
batting, bowling and fielding for Squad Eleven, writes data/matches.json,
and builds site/index.html from template.html.
"""
import json
import pathlib
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "data" / "index.json"
STATUS = ROOT / "data" / "status.json"
OUT_JSON = ROOT / "data" / "matches.json"
SITE = ROOT / "site"

SKIP_ROWS = re.compile(r"^(extras|total|did not bat|yet to bat|fall of|to bat|bowling|batting)", re.I)


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def clean_name(s):
    s = re.sub(r"Watch (Ball|Player Highlight) Video", " ", s)
    s = re.sub(r"\((c|wk|vc|c\s*&\s*wk)\)", " ", s, flags=re.I)
    s = re.sub(r"[†*+]", " ", s)
    return ws(s).strip(" ·-")


def clean_dismissal(s):
    s = ws(re.sub(r"Watch (Ball|Player Highlight) Video", " ", s))
    # Mobile + desktop copies are sometimes joined: "b X b X" -> "b X"
    half = len(s) // 2
    if len(s) > 6 and s[:half].strip() == s[half:].strip():
        s = s[:half].strip()
    return s


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def overs_to_balls(o):
    whole = int(o)
    return whole * 6 + round((o - whole) * 10)


def row_cells(tr):
    return [ws(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"], recursive=False)]


def table_kind(header):
    labels = {h.strip() for h in header}
    if {"R", "B", "4s", "6s", "SR"} <= labels:
        return "bat"
    if {"O", "M", "R", "W"} <= labels:
        return "bowl"
    return None


def from_end(header, row, label):
    """Value for a header label, counted from the right so extra leading cells don't shift it."""
    try:
        i = len(header) - 1 - header.index(label)
    except ValueError:
        return None
    return num(row[-1 - i]) if len(row) > i else None


def innings_team(table, header):
    label = header[0] if header and "innings" in header[0].lower() else ""
    if not label:
        prev = table.find_previous(string=re.compile(r"innings", re.I))
        label = ws(prev) if prev else ""
    m = re.match(r"(.*?)\s+innings", label, re.I)
    return ws(m.group(1)) if m else label


def parse_tables(soup, team_re):
    """Returns our batting rows, our bowling rows, and the opponent's dismissal texts."""
    batting, bowling, opp_dismissals = [], [], []
    seen = set()
    last_batting_is_us = None
    for table in soup.find_all("table"):
        if table.find("table"):
            continue
        rows = table.find_all("tr")
        if not rows:
            continue
        header = row_cells(rows[0])
        kind = table_kind(header)
        if not kind:
            continue
        body = [row_cells(r) for r in rows[1:]]
        sig = (kind, tuple(clean_name(r[0]) for r in body if r))
        if sig in seen:  # duplicate copy of the same table (mobile view)
            continue
        seen.add(sig)

        if kind == "bat":
            team = innings_team(table, header)
            is_us = bool(team_re.search(team))
            last_batting_is_us = is_us
            for r in body:
                if len(r) < 3 or SKIP_ROWS.match(r[0]):
                    continue
                runs, balls = from_end(header, r, "R"), from_end(header, r, "B")
                if runs is None or balls is None:
                    continue
                name = clean_name(r[0])
                dis = clean_dismissal(r[1]) if len(r) > 1 else ""
                if is_us:
                    batting.append({
                        "name": name, "r": int(runs), "b": int(balls),
                        "f4": int(from_end(header, r, "4s") or 0),
                        "f6": int(from_end(header, r, "6s") or 0),
                        "out": not re.search(r"not out|retired hurt|^$", dis, re.I),
                        "dis": dis,
                    })
                else:
                    opp_dismissals.append(dis)
        else:
            # A bowling table follows the batting innings it belongs to,
            # so it is ours when the side batting was the opponent.
            if last_batting_is_us is not False:
                continue
            for r in body:
                if len(r) < 4 or SKIP_ROWS.match(r[0]):
                    continue
                o, w, runs = from_end(header, r, "O"), from_end(header, r, "W"), from_end(header, r, "R")
                if o is None or w is None or runs is None:
                    continue
                bowling.append({"name": clean_name(r[0]), "o": o,
                                "m": int(from_end(header, r, "M") or 0),
                                "r": int(runs), "w": int(w)})
    return batting, bowling, opp_dismissals


def resolve(abbr, roster):
    """Map a scorecard short name like 'Gowtham Reddy P' to a full roster name."""
    abbr = clean_name(abbr)
    if not abbr:
        return None
    low = abbr.lower()
    for full in roster:
        if full.lower() == low:
            return full
    a = low.split()
    hits = []
    for full in roster:
        f = full.lower().split()
        if len(a) >= 2 and f[: len(a) - 1] == a[:-1] and any(t.startswith(a[-1]) for t in f[len(a) - 1:]):
            hits.append(full)
        elif len(a) == 1 and (f[0] == a[0] or f[-1] == a[0]):
            hits.append(full)
    return hits[0] if len(hits) == 1 else None


def fielding(opp_dismissals, roster):
    tally = {}

    def add(who, kind):
        full = resolve(who, roster)
        if full:
            tally.setdefault(full, {"name": full, "ct": 0, "st": 0, "ro": 0})[kind] += 1

    for d in opp_dismissals:
        if m := re.match(r"c\s*&\s*b\s+(.+)", d, re.I):
            add(m.group(1), "ct")
        elif m := re.match(r"c\s+[†+]?\s*(.+?)\s+b\s+", d, re.I):
            add(m.group(1), "ct")
        elif m := re.match(r"st\s+[†+]?\s*(.+?)\s+b\s+", d, re.I):
            add(m.group(1), "st")
        elif m := re.search(r"run\s*out\s*\(\s*[†+]?([^)/]+)", d, re.I):
            add(m.group(1), "ro")
    return list(tally.values())


SCORE = r"(\d+)/(\d+)\s*\(([\d.]+)\s*overs?\)"


def parse_match(key, meta, team_re):
    html = (RAW / f"{key}.html").read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    text = ws(soup.get_text(" "))
    card = meta.get("card", "")

    # Teams and scores: CricClubs puts "Result;TeamA 123/7(15 overs) TeamB 117/4(15 overs)" in the description.
    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    desc = ws(desc_tag["content"]) if desc_tag and desc_tag.get("content") else ""
    teams, scores = [], []
    m = re.search(r";\s*(.+?)\s+" + SCORE + r"\s+(.+?)\s+" + SCORE, desc)
    if m:
        g = m.groups()
        teams = [ws(g[0]), ws(g[4])]
        scores = [{"r": int(g[1]), "w": int(g[2]), "o": float(g[3])},
                  {"r": int(g[5]), "w": int(g[6]), "o": float(g[7])}]
    if not teams:
        t = soup.title.get_text() if soup.title else ""
        m = re.search(r":\s*(.+?)\s+vs\s+(.+?)\s+-\s+", t)
        if m:
            teams = [ws(m.group(1)), ws(m.group(2))]
    if not teams:
        return None
    us_idx = 0 if team_re.search(teams[0]) else 1 if team_re.search(teams[1]) else None
    if us_idx is None:
        return None
    opponent = teams[1 - us_idx]

    result_src = desc or text
    rm = re.search(r"(.+?)\s+won by\s+([\d]+\s+(?:runs?|wickets?)(?:\s*\(D/?L\))?)", result_src, re.I)
    if rm:
        result = "W" if team_re.search(rm.group(1)) else "L"
        margin = "by " + rm.group(2)
    elif re.search(r"\btied\b", result_src, re.I):
        result, margin = "T", "Tied"
    elif re.search(r"no result|abandon|cancel", result_src, re.I):
        result, margin = "NR", "No result"
    else:
        return None  # not played yet

    dm = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", text)
    date = f"{dm.group(3)}-{dm.group(1)}-{dm.group(2)}" if dm else ""

    series = ""
    for h in soup.find_all(["h2", "h3", "h4", "h5"]):
        t = ws(h.get_text(" "))
        if re.match(r"^20\d\d\b", t) and "won" not in t.lower() and len(t) < 80:
            series = t
            break
    if not series:
        for line in card.splitlines():
            if re.match(r"^\s*20\d\d\b", line) and "won" not in line.lower():
                series = ws(line)
                break

    batting, bowling, opp_dis = parse_tables(soup, team_re)
    roster = sorted({p["name"] for p in batting} | {p["name"] for p in bowling})
    return {
        "id": key, "url": meta.get("url", ""), "league": meta.get("league", ""),
        "series": series, "date": date, "opponent": opponent,
        "batted_first": us_idx == 0, "result": result, "margin": margin,
        "us": scores[us_idx] if scores else None,
        "them": scores[1 - us_idx] if scores else None,
        "batting": batting, "bowling": bowling,
        "fielding": fielding(opp_dis, roster),
    }


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    team_re = re.compile("|".join(re.escape(a) for a in cfg["team_aliases"]), re.I)
    index = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    status = json.loads(STATUS.read_text()) if STATUS.exists() else {}

    matches, problems = [], []
    for key, meta in index.items():
        if not (RAW / f"{key}.html").exists():
            continue
        try:
            m = parse_match(key, meta, team_re)
        except Exception as e:
            problems.append(f"{key}: {e}")
            continue
        if m and m["date"][:4] >= str(cfg.get("seasons_from", 0)):
            if not m["batting"] and not m["bowling"] and m["result"] != "NR":
                problems.append(f"{key}: result found but no player tables")
            matches.append(m)
    matches.sort(key=lambda m: m["date"], reverse=True)

    OUT_JSON.write_text(json.dumps(matches, indent=1), encoding="utf-8")
    data = {"team": cfg["team_name"], "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "status": status, "matches": matches}
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    page = page.replace("/*__DATA__*/null", json.dumps(data).replace("</", "<\\/"))
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")

    print(f"Built site/index.html with {len(matches)} matches.")
    for p in problems:
        print("  check:", p)


if __name__ == "__main__":
    main()
