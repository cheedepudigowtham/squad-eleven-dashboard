"""Merge squad-data.json (made by the Squad Eleven Update button) into data/.

Each scorecard is saved to data/raw/, the match list in data/index.json is
updated, and data/status.json records what the button reported.
Matches from earlier uploads are kept, so nothing is lost if one upload is partial.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
BUNDLE = ROOT / "squad-data.json"
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "data" / "index.json"
STATUS = ROOT / "data" / "status.json"


def main():
    if not BUNDLE.exists():
        print("No squad-data.json uploaded yet; building from saved data.")
        return
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    RAW.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text()) if INDEX.exists() else {}

    added = 0
    for key, m in bundle.get("matches", {}).items():
        key = re.sub(r"[^A-Za-z0-9_-]", "_", key)
        if not m.get("html"):
            continue
        (RAW / f"{key}.html").write_text(m["html"], encoding="utf-8")
        added += key not in index
        index[key] = {"url": m.get("url", ""), "league": m.get("league", ""), "card": m.get("card", "")}

    INDEX.write_text(json.dumps(index, indent=1), encoding="utf-8")
    STATUS.write_text(json.dumps({"time": bundle.get("generated"), "sources": bundle.get("sources", []),
                                  "new": added, "via": "button"}, indent=1), encoding="utf-8")
    print(f"Imported {len(bundle.get('matches', {}))} scorecards ({added} new). {len(index)} matches saved in total.")


if __name__ == "__main__":
    main()
