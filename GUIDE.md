# mbm-data: build guide

Everything below is in order. Do a step, send me the output it asks for, and I'll confirm before you move on. Times are rough. Nothing here costs money except the optional odds-history purchase in Step 8.

What this repo does once it is running:

- `odds_snapshot.py` archives prices from The Odds API near kickoff. After one season you own a closing-line history for every board, free.
- `states_snapshot.py` archives injury reports, slates, NHL projected goalies and CFBD lines every morning. This is the "what was known before the game" record that makes future backtests honest.
- `cfbd_backfill.py` pulls ten seasons of college football lines in one go, so NCAAF gets its market test now.
- `xg_pull_local.py` runs on your own computer and pulls Big 5 xG history, because the two xG sites block GitHub's servers.
- `backtest.py` is the one harness every model repo will use to score a holdout once against pre-registered bars.

---

## Step 1. Create the repository (5 minutes)

1. Go to github.com and sign in.
2. Top right, click the **+** icon, then **New repository**.
3. Repository name: `mbm-data`. Set it to **Private**. Leave "Add a README file" unchecked. Click **Create repository**.
4. You land on an empty repo page. Keep it open.

## Step 2. Upload the files (10 minutes)

The zip I gave you unpacks into a folder called `mbm-data`. Inside it: `config.json`, five `.py` files, `README.md`, `GUIDE.md`, and a hidden folder `.github/workflows/` with three `.yml` files.

**Upload the visible files first.**

1. On the empty repo page click **uploading an existing file** (or, on a repo that already has files, **Add file** → **Upload files**).
2. Open the unpacked `mbm-data` folder on your computer, select `config.json`, `odds_snapshot.py`, `states_snapshot.py`, `cfbd_backfill.py`, `xg_pull_local.py`, `backtest.py`, `README.md`, `GUIDE.md` and drag them onto the page.
3. Scroll down, click **Commit changes**.

**Now the workflows.** Hidden folders don't always drag cleanly, so create these three by hand:

1. Click **Add file** → **Create new file**.
2. In the file name box type exactly: `.github/workflows/odds.yml` (typing the slashes creates the folders).
3. On your computer open `.github/workflows/odds.yml` in Notepad, select all, copy, and paste into the big editor box on GitHub.
4. Click **Commit changes** (top right), then **Commit changes** again in the dialog.
5. Repeat for `.github/workflows/states.yml` and `.github/workflows/cfbd_backfill.yml`.

**Send me:** a screenshot or a copy of the file list on the repo's main page. I'm checking that `.github/workflows` shows three files.

## Step 3. Add the API key as a secret (3 minutes)

1. On the repo page click the **Settings** tab (far right of the tab row; if you don't see it, widen the window).
2. In the left sidebar scroll to **Secrets and variables** and click it, then click **Actions**.
3. Click the green **New repository secret** button.
4. Name: `ODDS_API_KEY`. Secret: paste your Odds API key. Click **Add secret**.

Do not put the key anywhere else. The workflow file passes it to the script through the `env:` block, which is the only way a secret becomes visible to a step.

## Step 4. Let workflows write to the repo (2 minutes)

The snapshot jobs commit files back. GitHub blocks that by default.

1. Still in **Settings**, left sidebar, click **Actions**, then **General**.
2. Scroll to **Workflow permissions**. Select **Read and write permissions**. Click **Save**.

## Step 5. Run the first snapshot by hand and read the log (5 minutes)

1. Click the **Actions** tab. If it asks you to enable workflows, click the green button.
2. In the left list click **odds-snapshots**.
3. On the right, click **Run workflow**. In the `force_sport` box type `americanfootball_nfl`. Click the green **Run workflow**.
4. Wait about a minute, refresh, click the run that appears, then click the **snap** job on the left.
5. Expand the step **Run python odds_snapshot.py**.

You want a line like `americanfootball_nfl: 16 events, 1900 rows -> odds/americanfootball_nfl/2026-09.csv; 497 credits left`. Then click the **Code** tab and confirm a folder `odds/` now exists.

**Send me:** the last 10 lines of that step's log. If it says HTTP 401, the key is wrong or not saved under the exact name `ODDS_API_KEY`. If it says nothing was snapshotted and the credits line is missing, the `env:` block didn't reach the step; paste me the log and I'll tell you what line to fix.

From here the schedule in `config.json` runs itself. It is about 180 credits a month with NBA and NHL in season, well under the 500. `odds/usage.json` shows the running tally.

## Step 6. Run the states job once (3 minutes)

1. **Actions** tab → **pregame-states** → **Run workflow** → **Run workflow**.
2. Open the run, the **states** job, the **Run python states_snapshot.py** step.

Expected: one line per league per feed with a file size, a DailyFaceoff line (empty `data` in the offseason is normal), and `cfbd: no CFBD_KEY, skipping` until Step 7. **Send me** that step's log.

## Step 7. College football lines, ten seasons, free (10 minutes)

1. Go to collegefootballdata.com. Top menu, **API**, then **Register for an API key** (or the "Get API key" link on the home page). Enter your email. The key arrives by email.
2. Add it exactly as in Step 3 with the name `CFBD_KEY`.
3. **Actions** → **cfbd-backfill** → **Run workflow**. Leave 2015 and 2025. Click **Run workflow**. It takes a few minutes.
4. **Code** tab: the `cfbd/` folder should show `lines_2015.csv` through `lines_2025.csv` and the matching `games_` files.

**Send me:** the last 15 lines of the log. Each year should report a few thousand line rows. That file is the NCAAF market test; it plugs straight into the harness in Step 9.

## Step 8. Decide on odds history for the rest (your call)

NFL, Big 5 and the Americas leagues already have free closing lines (nflverse and football-data). NCAAF now has CFBD. NBA, NHL, WNBA, MMA and CS2 do not, and Step 5 only starts collecting them from today. The Odds API sells historical snapshots on its paid plans; check the current price on their pricing page before deciding. Alternative is to wait a season for the archive to fill. Either is fine; tell me which so I know when those boards can be tested.

## Step 9. The xG pull on your own computer (30 minutes, once)

Understat and FBref reject requests from GitHub's servers and from the sandbox I work in. Your home connection gets through.

**Install Python (Windows).**
1. Go to python.org → **Downloads** → click the big yellow **Download Python 3.x** button.
2. Run the installer. On the first screen tick **Add python.exe to PATH** at the bottom, then **Install Now**.

**Install the package.**
1. Press the Windows key, type `PowerShell`, press Enter. A blue window opens with a blinking cursor. You type commands there and press Enter to run them.
2. Type `python -m pip install soccerdata pandas` and press Enter. Wait for it to finish (it installs a browser driver as well; that is normal). The `python -m pip` form matters on Windows: plain `pip install` fails partway with `ERROR: To modify pip, please run the following command`, because one of the packages tries to update pip while pip is the program running. If you already saw that error, nothing is broken; run the `python -m pip` command and it finishes the job. The yellow `[notice] A new release of pip is available` lines are just an advert; ignore them.

**Open PowerShell inside the right folder.** PowerShell runs commands in whatever folder it is "standing in", and the script has to be run from the folder that holds it. The usual way is a command called `cd`, short for "change directory", which moves PowerShell into a folder you name. There is an easier way that skips it:
3. Open File Explorer (the yellow folder icon on the taskbar) and click your way into the unpacked `mbm-data` folder, so you can see `xg_pull_local.py` in the file list.
4. Click once in the address bar at the top of that window (the bar showing the folder path). The path turns into selectable text. Delete it, type `powershell`, and press Enter. A new PowerShell window opens already standing in that folder. You can check: the line before the cursor ends with `\mbm-data>`.
   (If you would rather use `cd`: in the address bar, right-click and choose **Copy address as text**, then in PowerShell type `cd "` , paste, type `"` and press Enter. The quotes matter if the path has spaces.)
5. Type `python xg_pull_local.py` and press Enter. It prints progress per league and season and ends with a line like `13200 matches -> xg/understat_big5.csv` and three sample rows.
6. If it stalls or errors with a Cloudflare or 403 message, run `python xg_pull_local.py --source fbref` instead. A Chrome window opens and drives itself; leave it alone. It is slower (the site allows about one page every seven seconds).

**Upload.** On GitHub: **Add file** → **Create new file**, name it `xg/README.md`, type anything, commit. Then **Add file** → **Upload files**, drag `understat_big5.csv` from your computer's `xg/` folder, commit.

**Send me:** the last 5 lines of the PowerShell output and the first 3 rows of the CSV (open it in Excel, copy the header plus two rows). With that file I rebuild the Big 5 states on xG and run the holdout once. The number to beat is 0.5610.

## Step 10. The backtest harness in each model repo (the part that gives you confidence)

`backtest.py` never trains. A board writes one predictions file, the harness scores it once, writes `backtest_report.json` with the input's SHA-256 hash, and exits 1 if a pre-registered bar is breached. Commit the bars before you score; never edit them after.

**Predictions file** (`predictions.csv`), one row per game:

| column | required | meaning |
|---|---|---|
| date, season, y, p_model | yes | outcome 1/0 for the modelled side, model probability |
| p_incumbent | no | the frozen model you are trying to beat |
| p_elo | no | the rating floor |
| p_market | no | de-vigged closing probability, same side |
| price_home, price_away | no | decimal closing prices, for the ledger |
| holdout | no | 1 on the rows the bars judge; omit to judge every row |

**Bars file** (`bars.json`), written before you look:

```json
{"min_gain_vs_incumbent": 0.005, "ci_clear_of_zero": true, "max_gap_vs_market": 0.010,
 "blend_coef_min": 0.0, "magnitude_pass": true, "calibration_2se": true}
```

**Run:** `python backtest.py predictions.csv --bars bars.json --out report.json`

**What it prints:** per-season log loss for model, incumbent, Elo, base rate and market; the paired-bootstrap gain over the incumbent with a 95% interval; the gap to the market with an interval; the magnitude table (model minus market buckets, with actual); the walk-forward blend coefficient per season; the ledger by claimed edge; and `BREACHES:`.

I ran it on the NFL 2024-25 holdout as the first test. It reports gain over Elo +0.0227 (interval +0.003 to +0.042), gap to the closing line +0.0243 (interval +0.010 to +0.038), magnitude outer buckets failing, blend coefficient -0.70 in 2024, and three breaches. That is the current state, measured by the tool you'll measure every change with.

**How a change earns the live board:**
1. Build it on training seasons only. Tune with rolling-origin cross-validation across those seasons, never on the holdout.
2. Write `bars.json`. Commit it.
3. Produce `predictions.csv` for the holdout seasons with the frozen incumbent alongside. Run the harness once. Commit the report.
4. Exit 0: it goes live in shadow (predicted and logged, not bet) for a window you fix in advance, then the harness runs again on the live rows. Exit 0 again: small stakes, and the ledger decides scaling.
5. Exit 1: it does not go live. You may build a different change; you may not rerun the same one against the same holdout with new settings, because the second look is the first step to fooling yourself.

Sample-size rule so you don't chase noise: about 500 games to confirm a 0.010 log-loss gain, about 2,000 for 0.005. A change smaller than the games you have cannot be confirmed and should not be attempted.

## What to send me at each step

| after step | send |
|---|---|
| 2 | the file list on the repo main page |
| 5 | last 10 lines of the odds job log |
| 6 | the states job log |
| 7 | last 15 lines of the cfbd-backfill log |
| 8 | your decision on odds history |
| 9 | last 5 lines of PowerShell output and 3 rows of the CSV |
| 10 | nothing yet; the harness goes into each model repo when the first change is ready |

Wrong outputs are as useful as right ones. Paste whatever the screen shows.
