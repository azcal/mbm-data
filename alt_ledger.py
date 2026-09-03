"""
alt_ledger.py: the NFL alternate-spread paper rule. Runs in mbm-data on Sunday evening
and Tuesday morning (grading).

Rule (written 2026-09-03, do not edit mid-season):
  For every alternate spread quoted on a Sunday-morning snapshot, take the runner's
  market-anchored cover probability at that exact line (logs/alt_grid.csv in mbm-nfl,
  market line for location, model shape for the tails). Flag the best price across books
  wherever probability x price >= 1.03. Flat one unit, graded at the price flagged.
  Pass at season end if, on at least 150 graded flags, hit rate >= pooled implied
  probability + 0.02 and ROI > 0. Fail: retired.

Needs MODEL_REPO_TOKEN with read access to mbm-nfl (add it to the token's repository
list). Set LOCAL_GRID=<path> and LOCAL_LOG=<path> for testing without GitHub.
"""
import datetime as dt, glob, io, json, math, os, sys
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ledger", "alt_ledger.csv")
NOW = dt.datetime.now(dt.timezone.utc)
TOKEN = os.environ.get("MODEL_REPO_TOKEN", "").strip()
OWNER = json.load(open(os.path.join(HERE, "ledger.json"))).get("owner", "azcal")
REPO, BRANCH = "mbm-nfl", "main"
THRESHOLD, BAR_N, BAR_MARGIN = 0.03, 150, 0.02
TEAMS = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
         "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
         "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
         "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
         "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
         "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
         "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
         "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS"}
COLS = ["snap_ts", "event_id", "game_id", "date", "home", "away", "team", "side", "point", "book", "price",
        "implied", "p_cover", "mkt_line", "edge", "result", "pnl", "graded"]


def fetch(path):
    url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{path}"
    r = requests.get(url, headers={"Authorization": f"token {TOKEN}"}, timeout=60)
    if r.status_code != 200:
        sys.exit(f"could not read {REPO}/{path} (HTTP {r.status_code}); is mbm-nfl on the token's repository list?")
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


def load_out():
    if os.path.exists(OUT):
        o = pd.read_csv(OUT, low_memory=False)
        for c in ("result", "pnl", "graded"):
            o[c] = o[c].astype(object).where(o[c].notna(), "")
        return o
    return pd.DataFrame(columns=COLS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    grid = pd.read_csv(os.environ["LOCAL_GRID"]) if os.environ.get("LOCAL_GRID") else fetch("logs/alt_grid.csv")
    log = pd.read_csv(os.environ["LOCAL_LOG"], low_memory=False) if os.environ.get("LOCAL_LOG") else fetch("logs/predictions.csv")
    files = sorted(glob.glob(os.path.join(HERE, "odds", "alt_americanfootball_nfl", "*.csv")))
    if not files:
        print("no alternate-spread snapshots yet"); return
    alt = pd.concat([pd.read_csv(f, low_memory=False) for f in files[-2:]], ignore_index=True)
    alt = alt[alt.market == "alternate_spreads"].copy()
    alt["price"] = pd.to_numeric(alt.price, errors="coerce"); alt["point"] = pd.to_numeric(alt.point, errors="coerce")
    alt["home_code"] = alt.home.map(TEAMS); alt["away_code"] = alt.away.map(TEAMS); alt["team_code"] = alt.outcome.map(TEAMS)
    alt = alt.dropna(subset=["price", "point", "home_code", "away_code", "team_code"])
    alt["start"] = pd.to_datetime(alt.commence, utc=True)
    grid = grid.copy(); grid["home_line"] = pd.to_numeric(grid.home_line); grid["away_line"] = pd.to_numeric(grid.away_line)
    gh = {(r.home, r.away, round(r.home_line, 1)): (r.p_home_cover, r.mkt_line, r.game_id, r.date) for r in grid.itertuples()}
    ga = {(r.home, r.away, round(r.away_line, 1)): (r.p_away_cover, r.mkt_line, r.game_id, r.date) for r in grid.itertuples()}
    out = load_out(); have = set(zip(out.event_id.astype(str), out.team, out.point.astype(float)))
    # best price per (event, team, point) on the snapshot, only games not yet started
    new = []
    pend = alt[alt.start > NOW]
    for (eid, team, point), q in pend.groupby(["event_id", "team_code", "point"]):
        if (str(eid), team, float(point)) in have:
            continue
        best = q.loc[q.price.idxmax()]
        side = "home" if team == best.home_code else "away"
        key = (best.home_code, best.away_code, round(float(point), 1))
        hit = gh.get(key) if side == "home" else ga.get(key)
        if hit is None:
            continue
        p, mkt_line, gid, date = hit
        edge = p * float(best.price) - 1
        if edge >= THRESHOLD:
            new.append(dict(snap_ts=best.snap_ts, event_id=eid, game_id=gid, date=date, home=best.home_code, away=best.away_code,
                            team=team, side=side, point=float(point), book=best.book, price=round(float(best.price), 3),
                            implied=round(1 / float(best.price), 4), p_cover=round(float(p), 4), mkt_line=mkt_line,
                            edge=round(edge, 4), result="", pnl="", graded=""))
            have.add((str(eid), team, float(point)))
    if new:
        out = pd.concat([out, pd.DataFrame(new)], ignore_index=True)
    # grade from the runner's log: result is the home margin
    res = {str(r.game_id): r.result for r in log.itertuples() if pd.notna(getattr(r, "result", None))}
    graded = 0
    for i, r in out[out.result.astype(str) == ""].iterrows():
        m = res.get(str(r.game_id))
        if m is None:
            continue
        m = float(m); tm = m if r.side == "home" else -m
        cov = tm + float(r.point)
        rs = "win" if cov > 0 else "loss" if cov < 0 else "push"
        out.loc[i, ["result", "pnl", "graded"]] = [rs, round(float(r.price) - 1, 3) if rs == "win" else -1.0 if rs == "loss" else 0.0, str(NOW.date())]
        graded += 1
    out = out[COLS]; out.to_csv(OUT, index=False)
    lines = [f"{len(new)} new flag(s), {graded} graded, {len(out)} rows"]
    for r in sorted(new, key=lambda r: -r["edge"])[:12]:
        lines.append(f"  {r['away']} @ {r['home']}  {r['team']} {r['point']:+g} @ {r['book']} {r['price']}  cover {r['p_cover']:.3f} vs implied {r['implied']:.3f} (market {r['mkt_line']:+g})")
    d = out[out.result.isin(["win", "loss"])].copy()
    if len(d):
        d["pnl"] = pd.to_numeric(d.pnl); d["implied"] = pd.to_numeric(d.implied)
        imp, hit = d.implied.mean(), (d.result == "win").mean()
        ok = len(d) >= BAR_N and hit >= imp + BAR_MARGIN and d.pnl.mean() > 0
        lines.append(f"rule: {len(d)} bets, hit {hit:.3f} vs implied {imp:.3f} ({hit-imp:+.3f}), ROI {d.pnl.mean():+.3f} | bar: hit >= implied+0.02 and ROI>0 on {BAR_N}: {'PASS so far' if (hit >= imp + BAR_MARGIN and d.pnl.mean() > 0) else 'short'}, {len(d)}/{BAR_N}")
        for lo, hi in ((0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)):
            b = d[(d.implied >= lo) & (d.implied < hi)]
            if len(b) >= 10:
                lines.append(f"  implied {lo:.2f}-{min(hi,1):.2f} n={len(b):>4} hit {(b.result=='win').mean():.3f} implied {b.implied.mean():.3f} ROI {b.pnl.mean():+.3f}")
    print("\n".join(lines))
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if hook and (new or graded) and "--dry" not in sys.argv:
        requests.post(hook, json={"embeds": [{"title": "NFL alt-line rule (paper, 3% edge)", "description": "```\n" + "\n".join(lines)[:3800] + "\n```",
                                              "footer": {"text": "rule fixed 2026-09-03; pass = hit >= implied+0.02 and ROI>0 on 150"}}]}, timeout=30)


if __name__ == "__main__":
    main()
