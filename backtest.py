"""
backtest.py: one harness for every board. It never trains anything. A board writes a
predictions file; this scores it once against pre-registered bars and writes a report.

    python backtest.py predictions.csv --bars bars.json --out report.json

predictions.csv, one row per game (or per bet side if you prefer, keep it consistent):
    date, season, y, p_model                       required. y is 1/0 for the modelled side.
    p_incumbent                                    optional. the frozen model you are trying to beat
    p_elo                                          optional. the rating floor
    p_market                                       optional. de-vigged closing probability, same side
    price_home, price_away                         optional. decimal closing prices for the SAME market
                                                   as p_model (a DNB probability needs DNB prices; 1X2
                                                   prices need draw-inclusive probabilities)
    group                                          optional. league / conference / division
    holdout                                        optional. 1 marks rows the bars are judged on;
                                                   if absent, every row is judged

bars.json (write it BEFORE you look at the holdout, commit it, never edit it after):
    {"min_gain_vs_incumbent": 0.005,     model must beat incumbent by this much log loss
     "ci_clear_of_zero": true,           and the 95% paired bootstrap interval must exclude 0
     "max_gap_vs_market": 0.010,         model may trail the close by at most this (null = no bar)
     "blend_coef_min": 0.0,              walk-forward blend coefficient on the model, per season
     "magnitude_pass": true,             outer buckets: actual on the model's side of the market
     "calibration_2se": true}            no favoured-side band overclaims by 2 standard errors

Exit code 1 if any bar is breached. The report carries the sha256 of the input file, so
the number you publish can be tied to the file that produced it.
"""
import argparse
import hashlib
import json
import math
import sys

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260901)


def clip(p):
    return np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)


def ll(y, p):
    p = clip(p)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def per_game_ll(y, p):
    p = clip(p)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_bootstrap(d, n=4000):
    """d = per-game log-loss differences (a - b). Negative means a is better."""
    idx = RNG.integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def logit(p):
    p = clip(p)
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def calibration(p, y, edges=(.5, .55, .6, .65, .7, .8, .9, 1.01), min_n=25):
    """Favoured-side reliability with the 2se rule."""
    p = np.asarray(p, float); y = np.asarray(y, float)
    fav = np.where(p >= .5, p, 1 - p); hit = np.where(p >= .5, y, 1 - y)
    rows, fail = [], False
    for lo, hi in zip(edges, edges[1:]):
        m = (fav >= lo) & (fav < hi)
        if m.sum() < min_n:
            continue
        s, a = fav[m].mean(), hit[m].mean(); se = math.sqrt(s * (1 - s) / m.sum())
        over = (s - a) > 2 * se
        fail |= over
        rows.append(dict(band=f"{lo:.2f}-{min(hi, 1):.2f}", n=int(m.sum()), said=round(s, 3),
                         actual=round(a, 3), gap=round(a - s, 3), overclaim=bool(over)))
    rows.append(dict(band="pooled", n=int(len(p)), said=round(fav.mean(), 3),
                     actual=round(hit.mean(), 3), gap=round(hit.mean() - fav.mean(), 3), overclaim=False))
    return rows, fail


def magnitude(pm, pk, y, edges=(-1, -.10, -.05, -.02, .02, .05, .10, 1), min_n=30):
    """Bucket by model minus market. Outer buckets pass when actual is on the model's side
    of the market (or between them). Fail when actual sits on the market's far side."""
    d = pm - pk
    rows, outer_pass, outer_n = [], True, 0
    for lo, hi in zip(edges, edges[1:]):
        m = (d >= lo) & (d < hi)
        if m.sum() < min_n:
            continue
        mo, mk, ac = pm[m].mean(), pk[m].mean(), y[m].mean()
        toward_model = (ac - mk) * np.sign(mo - mk) >= 0
        if abs(lo) >= .05 or abs(hi) >= .10:
            if not (lo < 0 < hi):
                outer_pass &= bool(toward_model); outer_n += int(m.sum())
        rows.append(dict(bucket=f"{lo:+.2f}..{hi:+.2f}", n=int(m.sum()), model=round(mo, 3),
                         market=round(mk, 3), actual=round(ac, 3), toward_model=bool(toward_model)))
    return rows, (outer_pass if outer_n else None)


def blend_walk_forward(df):
    """Per season: logistic blend of logit(market) and logit(model) fit on the OTHER seasons,
    coefficient on the model reported for the held-out season."""
    from sklearn.linear_model import LogisticRegression
    out = []
    X = np.column_stack([logit(df.p_market), logit(df.p_model)]); y = df.y.values
    for s in sorted(df.season.unique()):
        te = df.season.values == s; tr = ~te
        if te.sum() < 50 or tr.sum() < 100:
            continue
        m = LogisticRegression(C=1e6, max_iter=2000).fit(X[tr], y[tr])
        pb = m.predict_proba(X[te])[:, 1]
        out.append(dict(season=str(s), n=int(te.sum()), coef_market=round(float(m.coef_[0][0]), 3),
                        coef_model=round(float(m.coef_[0][1]), 3),
                        ll_blend=round(ll(y[te], pb), 4), ll_market=round(ll(y[te], df.p_market.values[te]), 4)))
    return out


def ledger(df):
    """Bet the modelled side whenever p_model x price > 1, and the other side likewise.
    Hit rate against implied probability by bucket, flat stakes."""
    rows = []
    for i, r in df.iterrows():
        for side, p, price, won in (("home", r.p_model, r.price_home, r.y == 1),
                                    ("away", 1 - r.p_model, r.price_away, r.y == 0)):
            if pd.isna(price) or price <= 1:
                continue
            if p * price > 1:
                rows.append(dict(implied=1 / price, edge=p * price - 1, won=bool(won),
                                 pnl=(price - 1) if won else -1.0))
    if not rows:
        return None
    b = pd.DataFrame(rows)
    out = []
    for lo, hi in ((0, .02), (.02, .05), (.05, .10), (.10, 9)):
        m = (b.edge >= lo) & (b.edge < hi)
        if m.sum() < 20:
            continue
        imp, hit = b.implied[m].mean(), b.won[m].mean()
        se = math.sqrt(imp * (1 - imp) / m.sum())
        out.append(dict(claimed_edge=f"{lo:.2f}-{hi:.2f}", n=int(m.sum()), implied=round(imp, 3),
                        hit=round(hit, 3), roi=round(b.pnl[m].mean(), 3), short=bool(imp - hit > 2 * se)))
    out.append(dict(claimed_edge="all", n=int(len(b)), implied=round(b.implied.mean(), 3),
                    hit=round(b.won.mean(), 3), roi=round(b.pnl.mean(), 3), short=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--bars", default=None)
    ap.add_argument("--out", default="backtest_report.json")
    a = ap.parse_args()
    raw = open(a.predictions, "rb").read()
    df = pd.read_csv(a.predictions)
    for c in ("date", "season", "y", "p_model"):
        if c not in df.columns:
            sys.exit(f"predictions file needs a {c} column")
    df = df.dropna(subset=["y", "p_model"]).copy()
    df["y"] = df.y.astype(int)
    if "holdout" in df.columns:
        H = df[df.holdout == 1].copy()
    else:
        H = df.copy()
    bars = json.load(open(a.bars)) if a.bars else {}
    rep = dict(input_sha256=hashlib.sha256(raw).hexdigest(), n_rows=int(len(df)), n_holdout=int(len(H)),
               seasons={}, bars=bars, breaches=[])
    y = H.y.values

    # per-season table
    for s in sorted(H.season.unique()):
        d = H[H.season == s]; row = dict(n=int(len(d)), model=round(ll(d.y, d.p_model), 4),
                                         hit=round(float(np.mean((d.p_model > .5) == (d.y == 1))), 3))
        base = df[df.season < s].y.mean() if (df.season < s).any() else d.y.mean()
        row["base_rate"] = round(ll(d.y, np.full(len(d), base)), 4)
        for c in ("p_incumbent", "p_elo", "p_market"):
            if c in d.columns and d[c].notna().all():
                row[c.replace("p_", "")] = round(ll(d.y, d[c]), 4)
        rep["seasons"][str(s)] = row

    # paired tests
    if "p_incumbent" in H.columns and H.p_incumbent.notna().all():
        d = per_game_ll(y, H.p_model) - per_game_ll(y, H.p_incumbent)
        mean, lo, hi = paired_bootstrap(d)
        rep["vs_incumbent"] = dict(gain=round(-mean, 4), ci95=[round(-hi, 4), round(-lo, 4)])
        if bars.get("min_gain_vs_incumbent") is not None and -mean < bars["min_gain_vs_incumbent"]:
            rep["breaches"].append(f"gain vs incumbent {-mean:.4f} < {bars['min_gain_vs_incumbent']}")
        if bars.get("ci_clear_of_zero") and not (hi < 0):
            rep["breaches"].append("95% interval vs incumbent includes zero")
    if "p_market" in H.columns and H.p_market.notna().all():
        d = per_game_ll(y, H.p_model) - per_game_ll(y, H.p_market)
        mean, lo, hi = paired_bootstrap(d)
        rep["vs_market"] = dict(gap=round(mean, 4), ci95=[round(lo, 4), round(hi, 4)])
        if bars.get("max_gap_vs_market") is not None and mean > bars["max_gap_vs_market"]:
            rep["breaches"].append(f"gap vs market {mean:.4f} > {bars['max_gap_vs_market']}")
        rows, ok = magnitude(H.p_model.values, H.p_market.values, y)
        rep["magnitude"] = dict(pass_outer=ok, table=rows)
        if bars.get("magnitude_pass") and ok is False:
            rep["breaches"].append("magnitude test: outcomes on the market's far side in outer buckets")
        if H.season.nunique() >= 2:
            bl = blend_walk_forward(H)
            rep["blend_walk_forward"] = bl
            if bars.get("blend_coef_min") is not None and bl and min(b["coef_model"] for b in bl) < bars["blend_coef_min"]:
                rep["breaches"].append(f"blend coefficient below {bars['blend_coef_min']} in at least one season")
    cal, fail = calibration(H.p_model.values, y)
    rep["calibration"] = cal
    if bars.get("calibration_2se") and fail:
        rep["breaches"].append("a favoured-side band overclaims by 2se")
    if {"price_home", "price_away"} <= set(H.columns):
        rep["ledger"] = ledger(H)

    json.dump(rep, open(a.out, "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k in ("seasons", "vs_incumbent", "vs_market")}, indent=1))
    if "magnitude" in rep:
        print("magnitude outer pass:", rep["magnitude"]["pass_outer"])
        for r in rep["magnitude"]["table"]:
            print(f"  {r['bucket']:>14} n={r['n']:>5} model {r['model']:.3f} market {r['market']:.3f} actual {r['actual']:.3f}")
    if "blend_walk_forward" in rep:
        for b in rep["blend_walk_forward"]:
            print(f"  blend {b['season']}: market {b['coef_market']:+.2f} model {b['coef_model']:+.2f}")
    if rep.get("ledger"):
        for r in rep["ledger"]:
            print(f"  ledger {r['claimed_edge']:>9} n={r['n']:>5} implied {r['implied']:.3f} hit {r['hit']:.3f} roi {r['roi']:+.3f}{'  SHORT' if r['short'] else ''}")
    print("BREACHES:", rep["breaches"] or "none")
    print("report:", a.out, "sha256:", rep["input_sha256"][:12])
    sys.exit(1 if rep["breaches"] else 0)


if __name__ == "__main__":
    main()
