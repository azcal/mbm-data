"""
props_ledger.py: the NFL receiving-props paper rule. Sunday 16:45 UTC to flag, Tuesday
16:15 UTC to grade (nflverse posts the week's player stats by Tuesday morning).

Rule (written 2026-09-03, do not edit mid-season):
  For every receiving-yards and receptions line on the Sunday snapshot, take the model's
  probability for that side from logs/props_grid.csv in mbm-nfl (yards: linear
  interpolation on the grid; receptions: P(rec >= k+1) for a k.5 line). Flag the best
  price across books wherever probability x price >= 1.05. Flat one unit.
  Pass at season end if, on at least 200 graded flags, hit rate >= pooled implied + 0.02
  and ROI > 0. Fail: retired. Voided props (player did not play) are dropped, as a book would.
Needs MODEL_REPO_TOKEN with read access to mbm-nfl.
"""
import datetime as dt, glob, io, json, math, os, re, sys
import numpy as np, pandas as pd, requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ledger", "props_ledger.csv")
NOW = dt.datetime.now(dt.timezone.utc)
TOKEN = os.environ.get("MODEL_REPO_TOKEN", "").strip()
_lj = os.path.join(HERE, "ledger.json")
OWNER = json.load(open(_lj)).get("owner", "azcal") if os.path.exists(_lj) else "azcal"
THRESHOLD, BAR_N, BAR_MARGIN = 0.05, 200, 0.02
YGRID = np.array([10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 120], float)
TEAMS = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF", "Carolina Panthers": "CAR",
         "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
         "Detroit Lions": "DET", "Green Bay Packers": "GB", "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
         "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
         "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG", "New York Jets": "NYJ",
         "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
         "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS"}
COLS = ["snap_ts", "event_id", "season", "week", "date", "team", "player", "market", "side", "line", "book", "price", "implied", "p_model",
        "median", "result", "actual", "pnl", "graded"]
norm = lambda s: re.sub(r"[^a-z]", "", str(s).lower())


def fetch_grid():
    if os.environ.get("LOCAL_GRID"):
        return pd.read_csv(os.environ["LOCAL_GRID"])
    r = requests.get(f"https://raw.githubusercontent.com/{OWNER}/mbm-nfl/main/logs/props_grid.csv", headers={"Authorization": f"token {TOKEN}"}, timeout=60)
    if r.status_code != 200:
        sys.exit(f"could not read mbm-nfl/logs/props_grid.csv (HTTP {r.status_code})")
    return pd.read_csv(io.StringIO(r.text))


def p_side(row, market, side, line):
    if market == "player_reception_yds":
        ps = np.array([row[f"p_over_{int(x)}"] for x in YGRID]); po = float(np.interp(line, YGRID, ps))
    else:
        k = int(math.floor(line)) + 1
        po = float(row.get(f"p_rec_{k}", 0.0)) if k <= 10 else 0.0
        if line == math.floor(line):          # whole-number line: push possible, approximate
            po = float(row.get(f"p_rec_{k}", 0.0))
    return po if side == "Over" else 1 - po


def load_out():
    if os.path.exists(OUT):
        o = pd.read_csv(OUT, low_memory=False)
        for c in ("result", "actual", "pnl", "graded"):
            o[c] = o[c].astype(object).where(o[c].notna(), "")
        return o
    return pd.DataFrame(columns=COLS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    grid = fetch_grid(); grid["key"] = grid.name.map(norm) + "|" + grid.team
    gk = {r.key: r for r in grid.itertuples()}
    files = sorted(glob.glob(os.path.join(HERE, "odds", "props_americanfootball_nfl", "*.csv")))
    out = load_out(); have = set(zip(out.event_id.astype(str), out.player, out.market, out.side, out.line.astype(float)))
    new = []
    if files:
        q = pd.concat([pd.read_csv(f, low_memory=False) for f in files[-2:]], ignore_index=True)
        q["price"] = pd.to_numeric(q.price, errors="coerce"); q["point"] = pd.to_numeric(q.point, errors="coerce")
        q = q.dropna(subset=["price", "point", "player"]); q["start"] = pd.to_datetime(q.commence, utc=True)
        q = q[q.start > NOW]
        for (eid, player, market, side, line), grp in q.groupby(["event_id", "player", "market", "outcome", "point"]):
            if (str(eid), player, market, side, float(line)) in have:
                continue
            best = grp.loc[grp.price.idxmax()]
            hc, ac = TEAMS.get(best.home), TEAMS.get(best.away)
            row = gk.get(f"{norm(player)}|{hc}") or gk.get(f"{norm(player)}|{ac}")
            if row is None:
                continue
            p = p_side(row._asdict(), market, side, float(line))
            edge = p * float(best.price) - 1
            if edge >= THRESHOLD:
                new.append(dict(snap_ts=best.snap_ts, event_id=eid, season=row.season, week=row.week, date=str(best.start.date()), team=row.team,
                                player=player, market=market, side=side, line=float(line), book=best.book, price=round(float(best.price), 3),
                                implied=round(1 / float(best.price), 4), p_model=round(p, 4),
                                median=round(float(row.med_yds if market == "player_reception_yds" else row.med_rec), 1),
                                result="", actual="", pnl="", graded=""))
                have.add((str(eid), player, market, side, float(line)))
    if new:
        out = pd.concat([out, pd.DataFrame(new)], ignore_index=True)
    # grade from nflverse weekly stats
    graded = 0
    pend = out[out.result.astype(str) == ""]
    for season in sorted(set(pd.to_numeric(pend.season, errors="coerce").dropna().astype(int))):
        r = requests.get(f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet", timeout=120)
        if r.status_code != 200 or len(r.content) < 100:
            continue
        st = pd.read_parquet(io.BytesIO(r.content)); st = st[st.season_type == "REG"]
        st["key"] = st.player_display_name.map(norm) + "|" + st.team + "|" + st.week.astype(str)
        stat = {r_.key: (r_.receiving_yards, r_.receptions) for r_ in st.itertuples()}
        weeks_done = set(st.week.unique())
        for i, rw in pend[pd.to_numeric(pend.season, errors="coerce") == season].iterrows():
            wk = int(rw.week)
            if wk not in weeks_done:
                continue
            s = stat.get(f"{norm(rw.player)}|{rw.team}|{wk}")
            if s is None:                       # no stat line: did not play, book voids
                out.loc[i, ["result", "actual", "pnl", "graded"]] = ["void", "", 0.0, str(NOW.date())]; graded += 1; continue
            actual = float(s[0] if rw.market == "player_reception_yds" else s[1])
            line = float(rw.line); over = actual > line; push = actual == line
            won = (over if rw.side == "Over" else (not over)) and not push
            res = "push" if push else ("win" if won else "loss")
            out.loc[i, ["result", "actual", "pnl", "graded"]] = [res, actual, round(float(rw.price) - 1, 3) if res == "win" else (-1.0 if res == "loss" else 0.0), str(NOW.date())]
            graded += 1
    out = out[COLS]; out.to_csv(OUT, index=False)
    lines = [f"{len(new)} new flag(s), {graded} graded, {len(out)} rows"]
    for r in sorted(new, key=lambda r: -(r["p_model"] * r["price"]))[:15]:
        lines.append(f"  {r['team']} {r['player']} {r['side']} {r['line']:g} {r['market'].replace('player_', '')} @ {r['book']} {r['price']}  model {r['p_model']:.3f} vs implied {r['implied']:.3f} (median {r['median']})")
    d = out[out.result.isin(["win", "loss"])].copy()
    if len(d):
        d["pnl"] = pd.to_numeric(d.pnl); d["implied"] = pd.to_numeric(d.implied)
        imp, hit = d.implied.mean(), (d.result == "win").mean()
        lines.append(f"rule: {len(d)} bets, hit {hit:.3f} vs implied {imp:.3f} ({hit-imp:+.3f}), ROI {d.pnl.mean():+.3f} | bar on {BAR_N}: {'PASS so far' if (hit >= imp + BAR_MARGIN and d.pnl.mean() > 0) else 'short'}, {len(d)}/{BAR_N}")
        for mk in ("player_reception_yds", "player_receptions"):
            b = d[d.market == mk]
            if len(b) >= 10:
                lines.append(f"  {mk.replace('player_','')}: n={len(b)} hit {(b.result=='win').mean():.3f} implied {b.implied.mean():.3f} ROI {b.pnl.mean():+.3f}")
        v = (out.result == "void").sum()
        lines.append(f"  voided (did not play): {v}")
    print("\n".join(lines))
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if hook and (new or graded) and "--dry" not in sys.argv:
        requests.post(hook, json={"embeds": [{"title": "NFL receiving props (paper, 5% edge)", "description": "```\n" + "\n".join(lines)[:3800] + "\n```",
                                              "footer": {"text": "rule fixed 2026-09-03; pass = hit >= implied+0.02 and ROI>0 on 200"}}]}, timeout=30)


if __name__ == "__main__":
    main()
