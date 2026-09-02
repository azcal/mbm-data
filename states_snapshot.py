"""
states_snapshot.py: archive what was knowable before the games. Free feeds, no key needed
except CFBD (optional). Runs daily. Everything lands under states/<league>/<date>.json.

  ESPN injuries      nba, wnba, nhl, nfl, college-football
  ESPN scoreboard    same leagues, today's slate with status (so 'was this game on' is answerable)
  DailyFaceoff       NHL projected starting goalies (best effort; page is Next.js, we keep the
                     embedded JSON if the fetch works, and note failure otherwise)
  CFBD lines         current-season lines for every provider, weekly during the season
"""
import datetime as dt, json, os, re
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = dt.datetime.now(dt.timezone.utc)
DAY = NOW.strftime("%Y-%m-%d")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {"nba": "basketball/nba", "wnba": "basketball/wnba", "nhl": "hockey/nhl",
           "nfl": "football/nfl", "ncaaf": "football/college-football"}


def save(league, name, obj):
    d = os.path.join(HERE, "states", league); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{DAY}_{name}.json")
    json.dump(obj, open(p, "w"))
    print(f"  {os.path.relpath(p, HERE)} ({os.path.getsize(p)//1024} KB)")


def espn():
    for lg, path in LEAGUES.items():
        for name in ("injuries", "scoreboard"):
            try:
                r = requests.get(f"{ESPN}/{path}/{name}", timeout=60)   # ESPN 403s any custom User-Agent
                if r.status_code == 200:
                    save(lg, name, r.json())
                else:
                    print(f"  {lg} {name}: HTTP {r.status_code}")
            except Exception as ex:
                print(f"  {lg} {name}: {type(ex).__name__}")


def dailyfaceoff():
    try:
        r = requests.get("https://www.dailyfaceoff.com/starting-goalies/", headers=H, timeout=60)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if r.status_code == 200 and m:
            save("nhl", "dailyfaceoff_goalies", json.loads(m.group(1)))
        else:
            print(f"  dailyfaceoff: HTTP {r.status_code}, embedded json {'found' if m else 'missing'}")
    except Exception as ex:
        print(f"  dailyfaceoff: {type(ex).__name__}")


def cfbd():
    key = os.environ.get("CFBD_KEY", "").strip()
    if not key:
        print("  cfbd: no CFBD_KEY, skipping"); return
    yr = NOW.year if NOW.month >= 8 else NOW.year - 1
    for st in ("regular", "postseason"):
        r = requests.get("https://api.collegefootballdata.com/lines", params=dict(year=yr, seasonType=st),
                         headers={"Authorization": f"Bearer {key}"}, timeout=120)
        if r.status_code != 200:
            print(f"  cfbd {st}: HTTP {r.status_code}"); continue
        d = os.path.join(HERE, "cfbd"); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"lines_{yr}_{st}.json"); json.dump(r.json(), open(p, "w"))
        print(f"  {os.path.relpath(p, HERE)} ({len(r.json())} games)")


if __name__ == "__main__":
    print("ESPN"); espn()
    print("DailyFaceoff"); dailyfaceoff()
    print("CFBD"); cfbd()
