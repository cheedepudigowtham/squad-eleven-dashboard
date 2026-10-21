(async () => {
  /* Squad Eleven updater. Runs on a cricclubs.com page in your own browser.
     __CONFIG__ is filled in by build.py from config.json. */
  const CFG = __CONFIG__;
  const TEAM = new RegExp(CFG.aliases.map(a => a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "i");
  const BLOCK = /just a moment|performing security verification|cf-chl|checking your browser/i;

  if (!/(^|\.)cricclubs\.com$/.test(location.hostname)) {
    alert("Open any cricclubs.com page first (for example cricclubs.com/MichCA), then click the Squad Eleven Update button again.");
    return;
  }
  if (window.__squadRunning) return;
  window.__squadRunning = true;

  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:2147483647;top:16px;right:16px;width:360px;max-width:calc(100vw - 32px);" +
    "background:#111;color:#fff;font:14px/1.45 system-ui,sans-serif;padding:14px 16px;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.45)";
  document.body.appendChild(box);
  const say = html => { box.innerHTML = "<div style='font-weight:700;margin-bottom:4px'>Squad Eleven update</div>" + html; };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const esc = s => String(s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const parse = h => new DOMParser().parseFromString(h, "text/html");

  async function get(url) {
    let last = "";
    for (let i = 0; i < 3; i++) {
      try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 25000);
        const r = await fetch(url, { credentials: "include", signal: ctl.signal });
        const t = await r.text();
        clearTimeout(timer);
        if (r.ok && !BLOCK.test(t.slice(0, 4000))) return t;
        last = r.ok ? "security check page" : "HTTP " + r.status;
      } catch (e) { last = String(e); }
      await sleep(2500 * (i + 1));
    }
    throw new Error(last + " for " + url);
  }

  function matchKey(href) {
    const u = new URL(href);
    return (u.pathname.split("/").filter(Boolean)[0] || "club") + "_" + (u.searchParams.get("matchId") || "x");
  }

  function cardsIn(doc, base) {
    const out = [], seen = new Set();
    for (const a of doc.querySelectorAll('a[href*="viewScorecard"]')) {
      const href = new URL(a.getAttribute("href"), base).href;
      if (seen.has(href)) continue;
      seen.add(href);
      const links = el => new Set([...el.querySelectorAll('a[href*="viewScorecard"]')].map(x => x.getAttribute("href"))).size;
      let el = a;
      for (let i = 0; i < 12 && el.parentElement && el.parentElement !== doc.body && links(el.parentElement) <= 1; i++) el = el.parentElement;
      const txt = (el.textContent || "").replace(/\s+/g, " ").trim();
      out.push({ href, card: txt.slice(0, 1500) });
    }
    return out;
  }

  function slim(html) {
    const d = parse(html);
    const title = d.title || "";
    const m = d.querySelector('meta[name="description"]') || d.querySelector('meta[property="og:description"]');
    const desc = m ? m.getAttribute("content") : "";
    d.querySelectorAll("script,style,svg,img,iframe,noscript,link,video,audio,canvas,select,input,button,form,textarea").forEach(e => e.remove());
    d.body.querySelectorAll("*").forEach(e => { for (const at of [...e.attributes]) e.removeAttribute(at.name); });
    return "<html><head><title>" + esc(title) + "</title><meta name=\"description\" content=\"" + esc(desc) + "\"></head><body>" +
      d.body.innerHTML.replace(/\s+/g, " ") + "</body></html>";
  }

  const wanted = new Map();
  const sources = [];
  const add = (c, league) => {
    if (!TEAM.test(c.card)) return 0;
    const k = matchKey(c.href);
    if (wanted.has(k)) return 0;
    wanted.set(k, { url: c.href, league, card: c.card });
    return 1;
  };

  try {
    say("Checking what is already saved…");
    let known = {};
    try {
      const r = await fetch("https://raw.githubusercontent.com/" + CFG.repo + "/main/data/index.json?t=" + Date.now());
      if (r.ok) known = await r.json();
    } catch (e) { known = {}; }
    const FINAL = /won by|abandon|no result|tied|cancel|forfeit|conceded|walkover/i;
    const clubOf = u => (new URL(u, location.href).pathname.split("/").filter(Boolean)[0] || "").toLowerCase();

    function seriesIds(doc, base, club) {
      const ids = new Set();
      for (const a of doc.querySelectorAll('a[href*="league="]')) {
        const href = a.getAttribute("href") || "";
        const m = href.match(/[?&]league=(\d+)/);
        if (m && m[1] !== "0" && clubOf(new URL(href, base).href) === club) ids.add(m[1]);
      }
      for (const o of doc.querySelectorAll("option")) {
        const v = (o.getAttribute("value") || "").trim();
        const m = v.match(/(?:^|[?&]league=)(\d+)$/);
        const sel = o.closest("select");
        const hint = ((sel && (sel.getAttribute("name") || "") + (sel.getAttribute("id") || "")) || "") + " " + (o.textContent || "");
        if (m && m[1] !== "0" && /league|series|20\d\d/i.test(hint)) ids.add(m[1]);
      }
      return ids;
    }

    for (const src of CFG.sources) {
      const club = clubOf(src.url);
      const clubPath = new URL(src.url).pathname.split("/").filter(Boolean)[0];
      const entry = { league: src.league, url: src.url, found: 0, series: 0, error: null };
      const tried = new Set();
      const ids = new Set();
      const scan = async u => {
        if (tried.has(u)) return;
        tried.add(u);
        const doc = parse(await get(u));
        for (const c of cardsIn(doc, u)) entry.found += add(c, src.league);
        seriesIds(doc, u, club).forEach(i => ids.add(i));
      };
      say("Reading results for " + esc(src.league) + "…");
      try {
        const main = /listMatches/.test(src.url) ? src.url
          : "https://" + location.host + "/" + clubPath + "/listMatches.do?league=0&clubId=" + src.club_id;
        await scan(main);
        await scan("https://" + location.host + "/" + clubPath);
        if (clubOf(location.href) === club) {
          seriesIds(document, location.href, club).forEach(i => ids.add(i));
          const m = location.search.match(/[?&]league=(\d+)/);
          if (m && m[1] !== "0") ids.add(m[1]);
        }
        const list = [...ids].sort((a, b) => b - a).slice(0, 120);
        entry.series = list.length;
        let n = 0;
        for (const id of list) {
          n++;
          say("Checking " + esc(src.league) + " series " + n + " of " + list.length + "…");
          try { await scan("https://" + location.host + "/" + clubPath + "/listMatches.do?league=" + id + "&clubId=" + src.club_id); }
          catch (e) { /* one series failing should not stop the rest */ }
          await sleep(350);
        }
        if (!entry.found) entry.error = "No Squad Eleven matches found";
      } catch (e) { entry.error = String(e.message || e).slice(0, 300); }
      sources.push(entry);
    }

    const here = clubOf(location.href);
    const hereSrc = CFG.sources.find(s => clubOf(s.url) === here);
    let extra = 0;
    for (const c of cardsIn(document, location.href)) extra += add(c, hereSrc ? hereSrc.league : "Other");
    if (extra) sources.push({ league: "This page", url: location.href, found: extra, error: null });

    const saved = [...wanted.keys()].filter(k => known[k] && FINAL.test(known[k].card || ""));
    const items = [...wanted.entries()].filter(([k]) => !saved.includes(k));
    const total = items.length;
    const matches = {};
    let done = 0, failed = 0;
    async function worker() {
      while (items.length) {
        const [k, w] = items.shift();
        try { matches[k] = { ...w, html: slim(await get(w.url)) }; }
        catch (e) { failed++; }
        done++;
        say("Downloading new scorecards: " + done + " of " + total + (failed ? " (" + failed + " failed)" : "") + "…");
        await sleep(400);
      }
    }
    await Promise.all([worker(), worker(), worker()]);

    const close = "<a href='#' style='color:#bbb;margin-left:10px' onclick='this.closest(\"div\").remove();return false'>Close</a>";
    const problems = sources.filter(s => s.error).map(s => "<br>⚠️ " + esc(s.league) + ": " + esc(s.error)).join("");
    const summary = "Found " + wanted.size + " Squad Eleven matches (" + saved.length + " already saved, " +
      Object.keys(matches).length + " new)." + problems;
    if (!Object.keys(matches).length) {
      say(summary + "<br><br>Everything is already up to date, so there is nothing to upload." + "<br>" + close);
      return;
    }

    const bundle = { version: 1, generated: new Date().toISOString(), sources, matches };
    const blob = new Blob([JSON.stringify(bundle)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "squad-data.json";
    document.body.appendChild(a);
    a.click();

    say(summary + "<br>Saved <b>squad-data.json</b>." +
      "<br><br>Next: upload it to GitHub and the dashboard updates in about a minute.<br>" +
      "<a href='https://github.com/" + CFG.repo + "/upload/main' target='_blank' rel='noopener' " +
      "style='display:inline-block;margin-top:8px;background:#2ea043;color:#fff;padding:6px 12px;border-radius:8px;text-decoration:none'>Open GitHub upload</a> " + close);
  } catch (e) {
    say("Something went wrong: " + esc(e.message || e) + "<br><a href='#' style='color:#bbb' onclick='this.closest(\"div\").remove();return false'>Close</a>");
  } finally {
    window.__squadRunning = false;
  }
})();
