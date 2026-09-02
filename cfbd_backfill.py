"""
cfbd_backfill.py: one-time pull of CFBD betting lines and games, 2015 to last season.
Needs CFBD_KEY. Writes cfbd/lines_<year>.csv (one row per game per provider) and
cfbd/games_<year>.csv. Run it once from the Actions tab (workflow_dispatch).
"""
import csv, os, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("CFBD_KEY", "").strip()
if not KEY:
    sys.exit("CFBD_KEY is empty")
HD = {"Authorization": f"Bearer {KEY}"}
os.makedirs(os.path.join(HERE, "cfbd"), exist_ok=True)
years = range(int(os.environ.get("FROM_YEAR", 2015)), int(os.environ.get("TO_YEAR", 2025)) + 1)
for yr in years:
    rows, games = [], []
    for st in ("regular", "postseason"):
        r = requests.get("https://api.collegefootballdata.com/lines", params=dict(year=yr, seasonType=st), headers=HD, timeout=120)
        if r.status_code != 200:
            print(f"{yr} {st} lines: HTTP {r.status_code} {r.text[:100]}"); continue
        for g in r.json():
            for ln in g.get("lines", []):
                rows.append(dict(year=yr, season_type=st, game_id=g.get("id"), week=g.get("week"),
                                 start=g.get("startDate"), home=g.get("homeTeam"), away=g.get("awayTeam"),
                                 home_score=g.get("homeScore"), away_score=g.get("awayScore"),
                                 provider=ln.get("provider"), spread=ln.get("spread"), spread_open=ln.get("spreadOpen"),
                                 total=ln.get("overUnder"), total_open=ln.get("overUnderOpen"),
                                 home_ml=ln.get("homeMoneyline"), away_ml=ln.get("awayMoneyline")))
        g2 = requests.get("https://api.collegefootballdata.com/games", params=dict(year=yr, seasonType=st), headers=HD, timeout=120)
        if g2.status_code == 200:
            games += [dict(year=yr, season_type=st, **{k: g.get(k) for k in ("id", "week", "startDate", "neutralSite",
                       "homeTeam", "homeConference", "homePoints", "awayTeam", "awayConference", "awayPoints")}) for g in g2.json()]
        time.sleep(1)
    for name, data in (("lines", rows), ("games", games)):
        if not data:
            continue
        p = os.path.join(HERE, "cfbd", f"{name}_{yr}.csv")
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys())); w.writeheader(); w.writerows(data)
        print(f"{yr}: {len(data)} {name} rows -> cfbd/{name}_{yr}.csv")
