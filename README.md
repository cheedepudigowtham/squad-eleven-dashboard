# Squad Eleven Dashboard

One page with Squad Eleven's results, batting, bowling and fielding from
**Michigan Cricket Association** and **Farmington CC** on CricClubs, at a free link
you can share with the team.

## Updating it (after each match, about 1 minute)

CricClubs blocks automated servers (Cloudflare), so the data is collected by a
bookmark button that runs in **your own browser**.

1. **One time only:** open `update.html` on your dashboard site
   (https://cheedepudigowtham.github.io/squad-eleven-dashboard/update.html) and drag the green
   **Squad Eleven Update** button to your bookmarks bar. The dashboard itself doesn't link to this page.
2. Open any CricClubs page, e.g. cricclubs.com/MichCA, and click **Squad Eleven Update**.
   A box shows progress, then `squad-data.json` downloads.
3. Click **Open GitHub upload** in that box, drag in `squad-data.json`, click **Commit changes**.
4. About a minute later the dashboard is updated.

The button reads each league's results for every year from `seasons_from` onwards, plus any
series it can find, and shows how many Squad Eleven matches it found per year.
Matches already saved are skipped, so later clicks are quick.

## How it works

- `update.html`: the page with the button (built into the site, not linked from the dashboard).
- `bookmarklet.js`: the button. It reads the results pages in `config.json`, downloads every
  Squad Eleven scorecard and saves them into `squad-data.json`.
- Uploading `squad-data.json` starts the GitHub workflow (`.github/workflows/update.yml`), which runs
  `import_bundle.py` (saves the scorecards into `data/`) and `build.py` (builds the page) and publishes it.
- Matches from earlier uploads are kept, so a partial upload never loses data.

## Changing what it reads

Edit `config.json` on GitHub (pencil icon); the dashboard rebuilds automatically.
After changing `sources` or `team_aliases`, drag the button to your bookmarks bar again
(delete the old one), because the button carries these settings.

- `sources`: one CricClubs link per league, with its `club_id`.
- `team_aliases`: the ways the team is named on CricClubs.
- `seasons_from`: ignore matches before this year.

## Files for running it on a computer you own (optional)

`scrape.py` and `update.py` collect the data with an automated browser instead of the button
(`pip install -r requirements.txt`, `python -m playwright install chromium`, `python update.py --headed`).
They don't work from GitHub's servers because CricClubs blocks them.
