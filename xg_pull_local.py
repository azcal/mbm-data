"""
xg_pull_local.py: run this on YOUR computer, not in GitHub Actions. Understat and FBref
block datacentre addresses, and a home connection is what gets through.

    pip install soccerdata pandas
    python xg_pull_local.py                 # Understat, Big 5, 2014-15 onward
    python xg_pull_local.py --source fbref  # FBref instead (opens a browser window, needs Chrome)

Writes xg/understat_big5.csv (or xg/fbref_big5.csv): one row per match with home_xg and
away_xg. Then upload that file into the xg/ folder of the mbm-data repo.
"""
import argparse, os, sys
import pandas as pd

LEAGUES = ["ENG-Premier League", "ESP-La Liga", "ITA-Serie A", "GER-Bundesliga", "FRA-Ligue 1"]
ap = argparse.ArgumentParser(); ap.add_argument("--source", default="understat", choices=["understat", "fbref"])
ap.add_argument("--from_season", type=int, default=2014); ap.add_argument("--to_season", type=int, default=2025)
ap.add_argument("--seasons", default="", help="explicit list like 2122,2223 (overrides from/to); use this form, the package reads a bare 2021 as 2020-21")
a = ap.parse_args()
try:
    import soccerdata as sd
except ImportError:
    sys.exit("run: pip install soccerdata pandas")
# four-digit labels like "2122" are unambiguous; bare years are not (2021 became 2020-21 and 2021-22 was skipped)
seasons = a.seasons.split(",") if a.seasons else [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(a.from_season, a.to_season + 1)]
os.makedirs("xg", exist_ok=True)
if a.source == "understat":
    rd = sd.Understat(leagues=LEAGUES, seasons=seasons)
    df = rd.read_schedule(include_matches_without_data=False).reset_index()
    out = "xg/understat_big5.csv"
else:
    rd = sd.FBref(leagues=LEAGUES, seasons=seasons)
    df = rd.read_schedule().reset_index()
    out = "xg/fbref_big5.csv"
if "game_id" in df.columns:
    df = df.drop_duplicates("game_id")
if os.path.exists(out) and a.seasons:          # merge a top-up pull into the existing file
    old = pd.read_csv(out)
    df = pd.concat([old, df]).drop_duplicates("game_id") if "game_id" in old.columns else pd.concat([old, df])
df.to_csv(out, index=False)
print(f"{len(df)} matches -> {out}")
print(df.head(3).to_string())
