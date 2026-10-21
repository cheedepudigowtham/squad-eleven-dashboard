"""Run this to refresh the dashboard: downloads new scorecards, then rebuilds site/index.html."""
import sys

import build
import scrape

if __name__ == "__main__":
    ok = scrape.main(headed="--headed" in sys.argv)
    build.main()
    if not ok:
        print("\nWARNING: no matches were read from CricClubs this run. "
              "The dashboard was rebuilt from previously saved data. "
              "Try: python update.py --headed")
