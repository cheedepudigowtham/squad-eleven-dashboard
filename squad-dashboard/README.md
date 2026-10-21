# Squad Eleven Dashboard

One page with Squad Eleven's results, batting, bowling and fielding from
**Michigan Cricket Association** and **Farmington CC** on CricClubs.
It updates itself every morning and lives at a free link you can share with the team.

## How it works

1. `scrape.py` opens each CricClubs results link in `config.json`, finds every
   Squad Eleven match and saves its scorecard into `data/raw/`. Saved scorecards
   are reused, so each run only downloads new games.
2. `build.py` reads those scorecards and builds `site/index.html`, the dashboard.
3. GitHub runs both every day and publishes the page with GitHub Pages (free).

## One-time setup (about 10 minutes, no coding)

1. **Make a free GitHub account** at github.com if you don't have one.
2. **Create a repository**: click **New**, name it `squad-eleven-dashboard`,
   choose **Public** (free Pages needs public; CricClubs stats are public anyway), click **Create**.
3. **Upload the files**: on the new repo page click **uploading an existing file**,
   then drag in everything from this folder.
   - The `.github` folder is hidden on Mac/Windows and is often skipped. Check it's there
     after uploading. If not: **Add file → Create new file**, type the name
     `.github/workflows/update.yml`, paste in the contents of that file and commit.
4. **Turn on Pages**: **Settings → Pages → Source: GitHub Actions**.
5. **Allow the bot to save data**: **Settings → Actions → General → Workflow permissions →
   Read and write permissions → Save**.
6. **Run it the first time**: **Actions** tab → **Update dashboard** → **Run workflow**.
   After about 3 minutes your dashboard is live at
   `https://<your-github-username>.github.io/squad-eleven-dashboard/`

From then on it refreshes every day around 7am. You can press **Run workflow** any time,
for example right after a match.

## Changing what it reads

Everything is in `config.json` (edit it on GitHub with the pencil icon):

- `sources`: CricClubs results links, one per league. Paste any results/match-list link
  from CricClubs. If older games are missing, add the results link for that specific series too.
- `team_aliases`: the ways the team is named on CricClubs. Add any new spelling.
- `extra_scorecards`: paste single scorecard links here to force-include a match.
- `seasons_from`: ignore matches before this year.

## If the update can't read CricClubs

CricClubs sometimes blocks automated browsers. The run log (Actions tab → latest run →
"Pull CricClubs data") will say so, and the dashboard shows a yellow notice while
keeping the last saved data. The fix is to run it once from your own computer:

```
pip install -r requirements.txt
python -m playwright install chromium
python update.py --headed
```

This opens a visible Chrome window. Then open `site/index.html` to check it, and upload the
new files in `data/raw/` to GitHub so the daily run builds from them.

## Run it locally only (no GitHub)

Same three commands as above, then open `site/index.html` in your browser.
