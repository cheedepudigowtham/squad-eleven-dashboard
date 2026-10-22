"""Step 2: turn saved scorecards into the dashboard.

Reads data/raw/*.html (saved by scrape.py), pulls out the result, scores,
batting, bowling and fielding for Squad Eleven, writes data/matches.json,
and builds site/index.html from template.html.
"""
import collections
import json
import pathlib
import re
from datetime import datetime, timezone
from urllib.parse import quote

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


def player_name(cell, dis):
    """CricClubs puts the name and the dismissal in the same cell; the name is the bold/linked part."""
    for tag in ("b", "a"):
        t = cell.find(tag)
        if t and clean_name(t.get_text(" ")):
            return clean_name(t.get_text(" "))
    n, d = clean_name(cell.get_text(" ")), clean_name(dis)
    if d and n.lower().endswith(d.lower()):
        n = n[: -len(d)].strip()
    return n


def total_from_row(text, runs):
    """'Total (10 wickets, 20 overs)' or '(all out, 19.2 overs)' -> {'r', 'w', 'o'}."""
    if runs is None:
        return None
    w = re.search(r"(\d+)\s*wkts?|(\d+)\s*wickets?", text, re.I)
    wk = int(w.group(1) or w.group(2)) if w else (10 if re.search(r"all out", text, re.I) else 0)
    o = re.search(r"([\d.]+)\s*(?:overs?|ov)\b", text, re.I)
    return {"r": int(runs), "w": wk, "o": float(o.group(1)) if o else None}


def parse_tables(soup, team_re):
    """Returns our batting rows, our bowling rows, the opponent's dismissal texts and innings totals."""
    batting, bowling, opp_dismissals = [], [], []
    totals, dnb, keeper = {}, [], None
    for t in soup.find_all(string=re.compile(r"did not bat", re.I)):
        el = t.parent
        txt = ws(el.get_text(" "))
        team_el = el.find_previous(string=re.compile(r"innings", re.I))
        if team_el and team_re.search(ws(team_el)):
            names = re.sub(r"^.*?did not bat\s*:?", "", txt, flags=re.I)
            dnb += [clean_name(n) for n in re.split(r",|;", names) if clean_name(n)]
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
        body = [(row_cells(r), r.find_all(["td", "th"], recursive=False)) for r in rows[1:]]
        sig = (kind, tuple(tuple(t) for t, _ in body))
        if sig in seen:  # duplicate copy of the same table (mobile view)
            continue
        seen.add(sig)

        if kind == "bat":
            team = innings_team(table, header)
            is_us = bool(team_re.search(team))
            last_batting_is_us = is_us
            for r, cells in body:
                if len(r) < 3:
                    continue
                if re.match(r"^total", r[0], re.I):
                    totals.setdefault(is_us, total_from_row(" ".join(r[:2]), from_end(header, r, "R")))
                    continue
                if SKIP_ROWS.match(r[0]):
                    continue
                runs, balls = from_end(header, r, "R"), from_end(header, r, "B")
                if runs is None or balls is None:
                    continue
                dis = clean_dismissal(r[1]) if len(r) > 1 else ""
                if is_us and "†" in cells[0].get_text(" "):
                    keeper = player_name(cells[0], dis)
                if is_us:
                    batting.append({
                        "name": player_name(cells[0], dis), "r": int(runs), "b": int(balls),
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
            for r, cells in body:
                if len(r) < 4 or SKIP_ROWS.match(r[0]):
                    continue
                o, w, runs = from_end(header, r, "O"), from_end(header, r, "W"), from_end(header, r, "R")
                name = next((clean_name(c) for c in r[:2] if clean_name(c) and num(clean_name(c)) is None), "")
                if o is None or w is None or runs is None or not name:
                    continue
                bowling.append({"name": name, "o": o, "m": int(from_end(header, r, "M") or 0),
                                "r": int(runs), "w": int(w)})
    return batting, bowling, opp_dismissals, totals, list(dict.fromkeys(dnb)), keeper


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
    if len(hits) == 1:
        return hits[0]
    if not hits and len(a) >= 2:
        # Same words in another order, e.g. "Boyina S" for "Srikanth Boyina" or "Srikanth B" for "Boyina Srikanth".
        for full in roster:
            f = full.lower().split()
            rest = list(f)
            if all(t in rest and not rest.remove(t) for t in a[:-1]) and any(t.startswith(a[-1]) for t in rest):
                hits.append(full)
        if len(hits) == 1:
            return hits[0]
    return None


def fielding(opp_dismissals, roster, squad=(), our_keeper=None):
    """Credit catches, stumpings and run outs. The day's XI is checked first, then the whole squad."""
    tally = {}

    def add(who, kind):
        full = (resolve(who, sorted(set(squad))) or resolve(who, roster)
                or clean_name(re.sub(r"\bsub\b|\(sub\)", "", who)))
        if full and not re.fullmatch(r"[\d\s.]*", full):
            tally.setdefault(full, {"name": full, "ct": 0, "st": 0, "ro": 0})[kind] += 1

    # "c † b X" = caught by the keeper with no name; use the name the keeper has elsewhere in the innings.
    kept = collections.Counter(m.group(1).strip() for d in opp_dismissals
                               if (m := re.match(r"(?:c|[Ss]t)\s*[†+]\s*([^†+]+?)\s+b\s+", d)))
    keeper = kept.most_common(1)[0][0] if kept else our_keeper
    for d in opp_dismissals:
        if re.match(r"c\s*[†+]\s*b\s+", d):
            if keeper:
                add(keeper, "ct")
            continue
        # Initials are capitals ("c Srikanth B b Mithun D"), so only a lowercase "b" means bowled.
        if m := re.match(r"c\s*&\s*b\s+(.+)", d):
            add(m.group(1), "ct")
        elif m := re.match(r"c\s+[†+]?\s*(.+?)\s+b\s+", d):
            add(m.group(1), "ct")
        elif m := re.match(r"[Ss]t\s+[†+]?\s*(.+?)\s+b\s+", d):
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

    won = r"(.+?)\s+won by\s+([\d]+\s+(?:runs?|wickets?)(?:\s*\(D/?L\))?)"
    result_src = desc if re.search(r"won by|super over|tied|no result|abandon", desc, re.I) else text
    rm = re.search(won, result_src, re.I)
    if rm and result_src is text:
        # Page text: the winner's name sits right before "won by", after the score line.
        rm2 = re.search(r"(" + "|".join(re.escape(t) for t in teams) + r")\s+won by\s+([\d]+\s+(?:runs?|wickets?)(?:\s*\(D/?L\))?)", text, re.I)
        rm = rm2 or rm
    so = re.search(r"super over\.?\s*winner\s*:?\s*(.+?)(?:;|$|\s+info\b)", result_src, re.I)
    if so:
        result = "W" if team_re.search(so.group(1)) else "L"
        margin = "Super Over"
    elif rm:
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
    # Scorecard header: <strong>Quik IV 2025-26</strong> <h3>League</h3> <span>02/07/2026</span>
    date_el = soup.find(string=re.compile(r"^\s*\d{2}/\d{2}/\d{4}\s*$"))
    if date_el:
        for prev in date_el.find_all_previous(string=True, limit=8):
            if prev.parent and prev.parent.name in ("strong", "b") and prev.strip() and not re.search(r"\d+/\d+", prev):
                series = ws(prev)
                break
    for h in ([] if series else soup.find_all(["h2", "h3", "h4", "h5"])):
        t = ws(h.get_text(" "))
        if (re.search(r"\b20\d\d\b", t) and len(t) < 80 and not re.search(r"won by|\d+/\d+/|\sv(s)?\s", t, re.I)
                and re.search(r"t20|t30|f40|f15|trophy|cup|league|division|series|glt|premier|contenders|challengers|champions", t, re.I)):
            series = t
            break
    if not series:
        for line in card.splitlines():
            if re.match(r"^\s*20\d\d\b", line) and "won" not in line.lower():
                series = ws(line)
                break

    batting, bowling, opp_dis, totals, dnb, keeper = parse_tables(soup, team_re)
    if not scores:
        # Header shows "Team 126/10 20 /20 ov"; the batting tables' Total rows are the fallback.
        found = []
        for t in teams:
            sm = re.search(re.escape(t) + r"\s*(\d+)\s*/\s*(\d+)\s*\(?\s*([\d.]+)\s*(?:/\s*[\d.]+\s*)?ov", text, re.I)
            found.append({"r": int(sm.group(1)), "w": int(sm.group(2)), "o": float(sm.group(3))} if sm else None)
        tot = [totals.get(True), totals.get(False)] if us_idx == 0 else [totals.get(False), totals.get(True)]
        scores = [found[i] or tot[i] for i in range(2)]
    return {
        "id": key, "url": meta.get("url", ""), "league": meta.get("league", ""),
        "series": series, "date": date, "opponent": opponent,
        "batted_first": us_idx == 0, "result": result, "margin": margin,
        "us": scores[us_idx], "them": scores[1 - us_idx],
        "batting": batting, "bowling": bowling, "dnb": dnb, "_opp_dis": opp_dis, "_keeper": keeper,
    }


def tidy_names(matches):
    """One spelling per player (SREEKANTH REDDY KYPA -> Sreekanth Reddy Kypa), then credit fielders."""
    best = {}
    for m in matches:
        for n in [p["name"] for p in m["batting"] + m["bowling"]] + m.get("dnb", []):
            k = n.lower()
            if k not in best or (best[k].isupper() and not n.isupper()):
                best[k] = n
    show = {k: (v.title() if v.isupper() else v) for k, v in best.items()}
    for m in matches:
        for p in m["batting"] + m["bowling"]:
            p["name"] = show[p["name"].lower()]
        m["dnb"] = [show[n.lower()] for n in m.get("dnb", [])]
    roster = sorted(set(show.values()))
    for m in matches:
        squad = [p["name"] for p in m["batting"] + m["bowling"]] + m["dnb"]
        keeper = m.pop("_keeper", None)
        m["fielding"] = fielding(m.pop("_opp_dis", []), roster, squad, show.get(keeper.lower(), keeper) if keeper else None)


def bookmarklet(cfg):
    """The 'Squad Eleven Update' button, as a javascript: link with config.json baked in."""
    src = (ROOT / "bookmarklet.js").read_text(encoding="utf-8")
    conf = {"aliases": cfg["team_aliases"], "repo": cfg.get("github_repo", ""), "from": cfg.get("seasons_from", 2023),
            "sources": [{"league": s["league"], "url": s["url"], "club_id": s.get("club_id", "")} for s in cfg["sources"]]}
    src = src.replace("__CONFIG__", json.dumps(conf))
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = "\n".join(line.strip() for line in src.splitlines() if line.strip())
    return "javascript:" + quote(src, safe="")


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
    tidy_names(matches)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(matches, indent=1), encoding="utf-8")
    data = {"team": cfg["team_name"], "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "status": status, "matches": matches, "bookmarklet": bookmarklet(cfg),
            "repo": cfg.get("github_repo", "")}
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    page = page.replace("/*__DATA__*/null", json.dumps(data).replace("</", "<\\/"))
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")
    upd = (ROOT / "update.html").read_text(encoding="utf-8")
    (SITE / "update.html").write_text(upd.replace("__BOOKMARKLET__", bookmarklet(cfg).replace("&", "&amp;").replace('"', "&quot;")), encoding="utf-8")

    print(f"Built site/index.html with {len(matches)} matches.")
    for p in problems:
        print("  check:", p)


if __name__ == "__main__":
    main()
