"""
odds_snapshot.py: archive prices near close so the stack has its own closing-line history.

Runs on every cron tick in odds.yml. For each sport in config.json whose weekday and UTC
hour match this tick (and whose season window contains today), it pulls one odds call and
appends one row per event / book / market / outcome to odds/<sport>/<YYYY-MM>.csv.

Days are Monday=0 .. Sunday=6. Credit cost per call is markets x ceil(books/10). The
runner reads x-requests-remaining from every response and stops spending at `reserve`.
Set FORCE_SPORT=<sport_key> to snapshot one sport regardless of the schedule.
"""
import csv, datetime as dt, json, math, os, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
API = "https://api.the-odds-api.com/v4"
KEY = os.environ.get("ODDS_API_KEY", "").strip()
NOW = dt.datetime.now(dt.timezone.utc)
USAGE = os.path.join(HERE, "odds", "usage.json")


def usage():
    if os.path.exists(USAGE):
        u = json.load(open(USAGE))
        if u.get("month") == NOW.strftime("%Y-%m"):
            return u
    return {"month": NOW.strftime("%Y-%m"), "remaining": None, "used": 0, "calls": []}


U = usage()


def remaining():
    return U["remaining"] if U["remaining"] is not None else CFG["monthly_budget"] - U["used"]


def in_season(sc):
    if "season" not in sc:
        return True
    a, b = sc["season"]; md = NOW.strftime("%m-%d")
    return (a <= md <= b) if a <= b else (md >= a or md <= b)


def due(sport, sc):
    if os.environ.get("FORCE_SPORT") == sport:
        return True
    return NOW.weekday() in sc["days"] and NOW.hour in sc["utc_hours"] and in_season(sc)


def snapshot(sport, sc):
    books = CFG["bookmakers"]
    cost = len(sc["markets"].split(",")) * math.ceil(len(books.split(",")) / 10)
    if remaining() - cost < CFG["reserve"]:
        print(f"SKIP {sport}: {remaining()} credits left, cost {cost}, reserve {CFG['reserve']}"); return
    r = requests.get(f"{API}/sports/{sport}/odds", params=dict(apiKey=KEY, bookmakers=books,
                     markets=sc["markets"], oddsFormat="decimal"), timeout=60)
    rem = r.headers.get("x-requests-remaining"); used = r.headers.get("x-requests-used")
    if rem: U["remaining"] = int(float(rem))
    if used: U["used"] = int(float(used))
    U["calls"].append(dict(ts=NOW.isoformat(timespec="seconds"), sport=sport, status=r.status_code,
                           cost=r.headers.get("x-requests-last")))
    if r.status_code != 200:
        print(f"{sport}: HTTP {r.status_code} {r.text[:120]}"); return
    events = r.json()
    path = os.path.join(HERE, "odds", sport, NOW.strftime("%Y-%m") + ".csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    n = 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["snap_ts", "event_id", "commence", "home", "away", "book", "book_update",
                        "market", "outcome", "point", "price"])
        for ev in events:
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for o in mk.get("outcomes", []):
                        w.writerow([NOW.isoformat(timespec="seconds"), ev["id"], ev["commence_time"],
                                    ev["home_team"], ev["away_team"], bk["key"], bk.get("last_update", ""),
                                    mk["key"], o.get("name"), o.get("point", ""), o.get("price")])
                        n += 1
    print(f"{sport}: {len(events)} events, {n} rows -> {os.path.relpath(path, HERE)}; {rem} credits left")


def main():
    if not KEY:
        sys.exit("ODDS_API_KEY is empty: add it under Settings > Secrets and variables > Actions, "
                 "and make sure odds.yml lists it in the step's env block")
    ran = 0
    for sport, sc in CFG["snapshots"].items():
        if due(sport, sc):
            snapshot(sport, sc); ran += 1
    os.makedirs(os.path.dirname(USAGE), exist_ok=True)
    json.dump(U, open(USAGE, "w"), indent=1)
    print(f"tick {NOW.isoformat(timespec='minutes')}: {ran} sport(s) snapshotted, {remaining()} credits left this month")


if __name__ == "__main__":
    main()
