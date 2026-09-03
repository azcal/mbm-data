"""
cfbd_features.py: one-time pull of the CFBD inputs for NCAAF v2, 2015 to last season.
Needs CFBD_KEY. Run from the Actions tab (cfbd-features workflow). Writes one combined
CSV per dataset under cfbd/ so there are seven files to download, not seventy:

  cfbd/adv_game_stats.csv   per team per game: PPA per play, success rate, explosiveness,
                            plays, drives, line yards, havoc, field position (offense + defense)
  cfbd/returning.csv        per team per season: returning production (share of prior-year PPA)
  cfbd/recruiting.csv       per team per season: recruiting class rank and points
  cfbd/talent.csv           per team per season: roster talent composite
  cfbd/coaches.csv          per team per season: head coach, hire date, record
  cfbd/portal.csv           per player per season: transfer origin, destination, rating
  cfbd/sp_ratings.csv       per team per season: final SP+ (use season t as a PRIOR for t+1 only;
                            the season-t number contains season-t results)
"""
import os, sys, time
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("CFBD_KEY", "").strip()
if not KEY:
    sys.exit("CFBD_KEY is empty")
HD = {"Authorization": f"Bearer {KEY}"}
API = "https://api.collegefootballdata.com"
FROM, TO = int(os.environ.get("FROM_YEAR", 2015)), int(os.environ.get("TO_YEAR", 2025))
OUT = os.path.join(HERE, "cfbd"); os.makedirs(OUT, exist_ok=True)


def get(path, **params):
    for attempt in range(3):
        r = requests.get(f"{API}{path}", params=params, headers=HD, timeout=180)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1)); continue
        print(f"  {path} {params}: HTTP {r.status_code} {r.text[:100]}"); return None
    print(f"  {path} {params}: rate limited three times, skipped"); return None


def pull(name, path, per_year_params, tag_year=True):
    frames = []
    for yr in range(FROM, TO + 1):
        for params in per_year_params(yr):
            data = get(path, **params)
            time.sleep(0.6)
            if not data:
                continue
            df = pd.json_normalize(data, sep="_")
            if tag_year and "season" not in df.columns and "year" not in df.columns:
                df.insert(0, "year", yr)
            for k, v in params.items():
                if k != "year" and k not in df.columns:
                    df[k] = v
            frames.append(df)
            print(f"  {name} {params}: {len(df)} rows")
    if not frames:
        print(f"{name}: nothing pulled"); return
    out = pd.concat(frames, ignore_index=True)
    p = os.path.join(OUT, f"{name}.csv"); out.to_csv(p, index=False)
    print(f"{name}: {len(out)} rows, {len(out.columns)} columns -> cfbd/{name}.csv")


print("advanced game stats"); pull("adv_game_stats", "/stats/game/advanced",
                                    lambda y: [dict(year=y, seasonType="regular"), dict(year=y, seasonType="postseason")])
print("returning production"); pull("returning", "/player/returning", lambda y: [dict(year=y)])
print("recruiting"); pull("recruiting", "/recruiting/teams", lambda y: [dict(year=y)])
print("talent"); pull("talent", "/talent", lambda y: [dict(year=y)])
print("coaches"); pull("coaches_raw", "/coaches", lambda y: [dict(year=y)])
print("portal"); pull("portal", "/player/portal", lambda y: [dict(year=y)])
print("SP+ ratings"); pull("sp_ratings", "/ratings/sp", lambda y: [dict(year=y)])

# coaches come back one row per coach with a nested seasons list; flatten to team-season rows
p = os.path.join(OUT, "coaches_raw.csv")
if os.path.exists(p):
    raw = pd.read_csv(p)
    rows = []
    if "seasons" in raw.columns:
        import ast
        for _, r in raw.iterrows():
            try:
                seasons = ast.literal_eval(r["seasons"]) if isinstance(r["seasons"], str) else r["seasons"]
            except Exception:
                continue
            for s in seasons or []:
                rows.append(dict(year=s.get("year"), school=s.get("school"), coach=f"{r.get('firstName', r.get('first_name', ''))} {r.get('lastName', r.get('last_name', ''))}".strip(),
                                 hire_date=r.get("hireDate", r.get("hire_date", "")), games=s.get("games"), wins=s.get("wins"), losses=s.get("losses")))
    if rows:
        pd.DataFrame(rows).drop_duplicates().to_csv(os.path.join(OUT, "coaches.csv"), index=False)
        print(f"coaches: {len(rows)} team-season rows -> cfbd/coaches.csv")
        os.remove(p)
    else:
        os.rename(p, os.path.join(OUT, "coaches.csv")); print("coaches: kept the raw shape")
print("done")
