"""
alt_snapshot.py: Sunday-morning pull of ALTERNATE spreads for that day's NFL games.

Alternate markets are only served per event, one call per game, so this reads the
event ids and kickoff times from the regular NFL snapshot the archive already took at
16:05 UTC, keeps the games starting in the next 40 hours (Sunday and Monday night), and
pulls alternate_spreads for each with the same ten-book list. About 15 credits a week.
Rows land in odds/alt_americanfootball_nfl/<YYYY-MM>.csv in the archive's column layout
with market = alternate_spreads. Set FORCE=1 to run regardless of the day.
"""
import csv, datetime as dt, glob, json, math, os, sys
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
API = "https://api.the-odds-api.com/v4"
KEY = os.environ.get("ODDS_API_KEY", "").strip()
NOW = dt.datetime.now(dt.timezone.utc)
SPORT = "americanfootball_nfl"
USAGE = os.path.join(HERE, "odds", "usage.json")

if not KEY:
    sys.exit("ODDS_API_KEY is empty")
if NOW.weekday() != 6 and os.environ.get("FORCE") != "1":
    print("not Sunday, nothing to do"); sys.exit(0)

files = sorted(glob.glob(os.path.join(HERE, "odds", SPORT, "*.csv")))
if not files:
    sys.exit("no NFL snapshot in the archive yet")
snap = pd.concat([pd.read_csv(f, low_memory=False) for f in files[-2:]], ignore_index=True)
ev = snap.drop_duplicates("event_id")[["event_id", "commence", "home", "away"]].copy()
ev["start"] = pd.to_datetime(ev.commence, utc=True)
ev = ev[(ev.start > NOW) & (ev.start <= NOW + dt.timedelta(hours=40))]
print(f"{len(ev)} NFL games in the next 40 hours")

u = json.load(open(USAGE)) if os.path.exists(USAGE) else {"month": NOW.strftime("%Y-%m"), "remaining": None, "used": 0, "calls": []}
remaining = u.get("remaining") if u.get("remaining") is not None else CFG["monthly_budget"] - u.get("used", 0)
books = CFG["bookmakers"]; cost_each = math.ceil(len(books.split(",")) / 10)
if remaining - cost_each * len(ev) < CFG["reserve"]:
    sys.exit(f"SKIP: {remaining} credits left, this needs {cost_each * len(ev)}, reserve {CFG['reserve']}")

path = os.path.join(HERE, "odds", f"alt_{SPORT}", NOW.strftime("%Y-%m") + ".csv")
os.makedirs(os.path.dirname(path), exist_ok=True)
new = not os.path.exists(path)
n = 0
with open(path, "a", newline="") as f:
    w = csv.writer(f)
    if new:
        w.writerow(["snap_ts", "event_id", "commence", "home", "away", "book", "book_update", "market", "outcome", "point", "price"])
    for r in ev.itertuples():
        resp = requests.get(f"{API}/sports/{SPORT}/events/{r.event_id}/odds",
                            params=dict(apiKey=KEY, bookmakers=books, markets="alternate_spreads", oddsFormat="decimal"), timeout=60)
        rem = resp.headers.get("x-requests-remaining")
        if rem:
            u["remaining"] = int(float(rem))
        u.setdefault("calls", []).append(dict(ts=NOW.isoformat(timespec="seconds"), sport=f"alt_{SPORT}", status=resp.status_code, cost=resp.headers.get("x-requests-last")))
        if resp.status_code != 200:
            print(f"  {r.away} @ {r.home}: HTTP {resp.status_code} {resp.text[:80]}"); continue
        e = resp.json(); k = 0
        for bk in e.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    w.writerow([NOW.isoformat(timespec="seconds"), e["id"], e["commence_time"], e["home_team"], e["away_team"],
                                bk["key"], bk.get("last_update", ""), mk["key"], o.get("name"), o.get("point", ""), o.get("price")])
                    k += 1
        n += k
        print(f"  {r.away} @ {r.home}: {k} alternate quotes")
json.dump(u, open(USAGE, "w"), indent=1)
print(f"{n} rows -> {os.path.relpath(path, HERE)}; {u.get('remaining')} credits left")
