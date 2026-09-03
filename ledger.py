"""
ledger.py: opener ledger for the boards that do not fetch prices when they run
(WNBA, NBA, NHL, MMA). Runs daily in mbm-data after the morning odds tick.

For every archived event it takes the EARLIEST snapshot as the opener, joins the model's
probability from that board's logs/predictions.csv (read from the private repo with
MODEL_REPO_TOKEN), and logs every side where model probability x best available price
beats 1 + threshold. Rows are graded from the model log's own result column, and the
tally is the bar you set: hit rate against the implied probability of the price taken,
plus the magnitude table against the de-vigged opener consensus.

Threshold is PROVISIONAL (3%) for all four boards until a season of openers exists to
backtest it. This file is the record that makes that backtest possible.

Config in ledger.json. Set LOCAL_LOGS=<dir> to read <dir>/<board>/predictions.csv instead
of GitHub (for testing).
"""
import csv, datetime as dt, difflib, glob, io, json, math, os, sys
from collections import defaultdict
from zoneinfo import ZoneInfo

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "ledger.json")))
OUT = os.path.join(HERE, "ledger", "opener_ledger.csv")
NOW = dt.datetime.now(dt.timezone.utc)
ET = ZoneInfo("America/New_York")
TOKEN = os.environ.get("MODEL_REPO_TOKEN", "").strip()
COLS = ["board", "snap_ts", "event_id", "commence", "game_date", "home", "away", "side", "team",
        "book", "price", "implied", "p_model", "p_cons", "edge", "n_books", "result", "pnl", "graded"]


# --- model logs ----------------------------------------------------------------------

def model_log(board):
    b = CFG["boards"][board]
    local = os.environ.get("LOCAL_LOGS")
    if local:
        p = os.path.join(local, board, "predictions.csv")
        return pd.read_csv(p, low_memory=False) if os.path.exists(p) else None
    if not TOKEN:
        print("MODEL_REPO_TOKEN is empty; add the fine-grained token as a repository secret"); return None
    url = f"https://raw.githubusercontent.com/{CFG['owner']}/{b['repo']}/{CFG.get('branch', 'main')}/logs/predictions.csv"
    r = requests.get(url, headers={"Authorization": f"token {TOKEN}"}, timeout=60)
    if r.status_code != 200:
        print(f"{board}: could not read {b['repo']} predictions.csv (HTTP {r.status_code}); check the token's repository list and Contents permission")
        return None
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


def norm_date(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10]


# --- archive -------------------------------------------------------------------------

def archive(sport):
    files = sorted(glob.glob(os.path.join(HERE, "odds", sport, "*.csv")))
    if not files:
        return pd.DataFrame()
    a = pd.concat([pd.read_csv(f, low_memory=False) for f in files], ignore_index=True)
    a = a[a.market == "h2h"].copy()
    a["price"] = pd.to_numeric(a.price, errors="coerce")
    return a[a.price > 1]


def team_code(board, name):
    m = CFG["boards"][board].get("teams", {})
    if name in m:
        return m[name]
    nick = name.split()[-1]
    hits = [v for k, v in m.items() if k.split()[-1] == nick]
    return hits[0] if len(hits) == 1 else None


def openers(board, a):
    """Per event: opener snapshot (earliest), best price per side, consensus, and the last
    snapshot before kickoff for the instrument."""
    out = {}
    for eid, ev in a.groupby("event_id"):
        first = ev.snap_ts.min(); last_pre = ev[ev.snap_ts < ev.commence.iloc[0]].snap_ts.max()
        op = ev[ev.snap_ts == first]
        home, away = ev.home.iloc[0], ev.away.iloc[0]
        best, probs = {}, []
        for bk, bq in op.groupby("book"):
            q = {r.outcome: r.price for r in bq.itertuples()}
            if home in q and away in q:
                ih, ia = 1 / q[home], 1 / q[away]; probs.append(ih / (ih + ia))
                for side, nm in (("home", home), ("away", away)):
                    if side not in best or q[nm] > best[side][1]:
                        best[side] = (bk, q[nm])
        if len(probs) == 0 or len(best) < 2:
            continue
        cons = float(pd.Series(probs).median())
        close = None
        if pd.notna(last_pre):
            cl = ev[ev.snap_ts == last_pre]; cp = []
            for bk, bq in cl.groupby("book"):
                q = {r.outcome: r.price for r in bq.itertuples()}
                if home in q and away in q:
                    ih, ia = 1 / q[home], 1 / q[away]; cp.append(ih / (ih + ia))
            close = float(pd.Series(cp).median()) if cp else None
        out[eid] = dict(commence=ev.commence.iloc[0], snap_ts=first, home=home, away=away, best=best,
                        cons=cons, n_books=len(probs), close=close,
                        game_date=dt.datetime.fromisoformat(ev.commence.iloc[0].replace("Z", "+00:00")).astimezone(ET).date().isoformat())
    return out


# --- matching ------------------------------------------------------------------------

def match_rows(board, log, ops):
    """Return list of (event, log_row) pairs."""
    b = CFG["boards"][board]
    log = log.copy(); log["gdate"] = log[b.get("date_col", "date")].map(norm_date)
    pairs = []
    if board == "mma":
        for eid, ev in ops.items():
            near = log[(pd.to_datetime(log.gdate) - pd.Timestamp(ev["game_date"])).dt.days.abs() <= 2]
            best = None
            for r in near.itertuples():
                s = max(difflib.SequenceMatcher(None, ev["home"].lower(), str(r.A).lower()).ratio() + difflib.SequenceMatcher(None, ev["away"].lower(), str(r.B).lower()).ratio(),
                        difflib.SequenceMatcher(None, ev["home"].lower(), str(r.B).lower()).ratio() + difflib.SequenceMatcher(None, ev["away"].lower(), str(r.A).lower()).ratio())
                if best is None or s > best[0]:
                    flip = difflib.SequenceMatcher(None, ev["home"].lower(), str(r.B).lower()).ratio() > difflib.SequenceMatcher(None, ev["home"].lower(), str(r.A).lower()).ratio()
                    best = (s, r, flip)
            if best and best[0] > 1.5:
                pairs.append((eid, ev, best[1], best[2]))
        return pairs
    idx = {}
    for r in log.itertuples():
        idx[(r.gdate, str(r.home), str(r.away))] = r
    for eid, ev in ops.items():
        h, a = team_code(board, ev["home"]), team_code(board, ev["away"])
        if not h or not a:
            continue
        d0 = dt.date.fromisoformat(ev["game_date"])
        for dd in (0, 1, -1):
            r = idx.get(((d0 + dt.timedelta(days=dd)).isoformat(), h, a))
            if r is not None:
                pairs.append((eid, ev, r, False)); break
    return pairs


def p_home_of(board, r, flip):
    b = CFG["boards"][board]
    p = float(getattr(r, b.get("prob_col", "p_home")))
    return (1 - p) if flip else p


def result_of(board, r, flip):
    v = getattr(r, "result", None)
    if v is None or (isinstance(v, float) and math.isnan(v)) or str(v) == "":
        return None
    v = float(v)
    if board == "mma":
        return (1 - v) if flip else v
    return v


# --- ledger --------------------------------------------------------------------------

def load_out():
    if os.path.exists(OUT):
        o = pd.read_csv(OUT, low_memory=False)
        for c in ("result", "pnl", "graded"):
            o[c] = o[c].astype(object).where(o[c].notna(), "")
        return o
    return pd.DataFrame(columns=COLS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = load_out(); have = set(zip(out.board, out.event_id.astype(str), out.side))
    new_rows, graded, post = [], 0, []
    for board, b in CFG["boards"].items():
        a = archive(b["sport"])
        if a.empty:
            print(f"{board}: no archived odds yet for {b['sport']}"); continue
        log = model_log(board)
        if log is None:
            continue
        ops = openers(board, a); pairs = match_rows(board, log, ops)
        print(f"{board}: {len(ops)} archived events, {len(pairs)} matched to the model log")
        if ops and not pairs:
            dcol = b.get("date_col", "date")
            dates = log[dcol].map(norm_date)
            print(f"  diagnosis: model log has {len(log)} rows, dates {dates.min()} to {dates.max()}")
            for eid, ev in list(ops.items())[:8]:
                h, aw = ev["home"], ev["away"]
                hc, ac = (team_code(board, h), team_code(board, aw)) if board != "mma" else (h, aw)
                near = log[(pd.to_datetime(dates) - pd.Timestamp(ev["game_date"])).dt.days.abs() <= 1]
                shown = ", ".join(f"{r.home}@{r.away}" if board != "mma" else f"{r.A} v {r.B}" for r in near.head(6).itertuples()) or "none"
                print(f"  archive {ev['game_date']}: {h} -> {hc} vs {aw} -> {ac}; model rows within a day: {shown}")
        thr = b.get("threshold", CFG.get("threshold", 0.03))
        for eid, ev, r, flip in pairs:
            ph = p_home_of(board, r, flip)
            for side in ("home", "away"):
                key = (board, str(eid), side)
                p = ph if side == "home" else 1 - ph
                bk, price = ev["best"][side]
                edge = p * price - 1
                if key in have:
                    continue
                if edge >= thr and result_of(board, r, flip) is None:
                    new_rows.append(dict(board=board, snap_ts=ev["snap_ts"], event_id=eid, commence=ev["commence"],
                                         game_date=ev["game_date"], home=ev["home"], away=ev["away"], side=side,
                                         team=ev["home"] if side == "home" else ev["away"], book=bk, price=round(price, 3),
                                         implied=round(1 / price, 4), p_model=round(p, 4), p_cons=round(ev["cons"] if side == "home" else 1 - ev["cons"], 4),
                                         edge=round(edge, 4), n_books=ev["n_books"], result="", pnl="", graded=""))
                    have.add(key)
        # grade
        res_by_event = {}
        for eid, ev, r, flip in pairs:
            res_by_event[str(eid)] = result_of(board, r, flip)
        for i, row in out[(out.board == board) & (out.result.astype(str) == "")].iterrows():
            y = res_by_event.get(str(row.event_id))
            if y is None:
                continue
            won = (y == 1) if row.side == "home" else (y == 0)
            out.loc[i, ["result", "pnl", "graded"]] = ["win" if won else "loss", round(float(row.price) - 1, 3) if won else -1.0, str(NOW.date())]
            graded += 1
    if new_rows:
        out = pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)
    out = out[COLS]; out.to_csv(OUT, index=False)
    print(f"{len(new_rows)} new flag(s), {graded} graded, {len(out)} rows in ledger/opener_ledger.csv")
    # tally
    for board in CFG["boards"]:
        d = out[(out.board == board) & out.result.isin(["win", "loss"])].copy()
        if len(d) == 0:
            continue
        d["pnl"] = pd.to_numeric(d.pnl); d["implied"] = pd.to_numeric(d.implied)
        imp, hit = d.implied.mean(), (d.result == "win").mean(); se = math.sqrt(imp * (1 - imp) / len(d))
        post.append(f"{board}: {len(d)} bets, hit {hit:.3f} vs implied {imp:.3f} ({'ok' if hit >= imp else 'SHORT' if imp - hit > 2 * se else 'under, within noise'}), ROI {d.pnl.mean():+.3f}")
    for r in new_rows:
        post.append(f"  flag {r['board']} {r['game_date']} {r['team']} @ {r['book']} {r['price']} (implied {r['implied']:.3f}, model {r['p_model']:.3f}, cons {r['p_cons']:.3f})")
    print("\n".join(post) if post else "nothing to report")
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if hook and post and "--dry" not in sys.argv:
        body = "\n".join(post)[:3800]
        requests.post(hook, json={"embeds": [{"title": "Opener ledger (WNBA/NBA/NHL/MMA), paper, provisional 3% threshold",
                                              "description": f"```\n{body}\n```"}]}, timeout=30)


if __name__ == "__main__":
    main()
