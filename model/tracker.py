"""Daily results tracking: freeze each night's calls, grade them from box scores.

Every build calls `snapshot(payload)`. For each slate game that hasn't started, it
writes the model's calls to model/data/calls/<date>.json: projected starters and
saves, every skater's SOG projection, and the game-winner probability, plus any
DraftKings / PrizePicks line the build saw. Started games are frozen.

`grade()` then runs on every build. Once a game is in the box scores it grades:
  * model accuracy, which needs no book line (winner picks, starter calls, saves
    and SOG error), and
  * every real line in model/data/real_line_log.csv. Rows logged from screenshots
    get their actual and HIT/MISS filled in, and lines the build pulled from DK or
    PrizePicks are appended automatically.
Each line is graded at the price and line it had at pick time; units and ROI use that price.
The summary goes to model/output/tracking.json for the Results tab.
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import math
import os

import pandas as pd

import data
import pricing
import prizepicks
import saves_dist
import winners

HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "data", "calls")
LOG = os.path.join(HERE, "data", "real_line_log.csv")
PRICES = os.path.join(HERE, "data", "dk_prices.csv")
OUT = os.path.join(HERE, "output", "tracking.json")
FIELDS = ["date", "market", "player", "team", "opp", "book", "line", "mult", "price", "side", "model_proj",
          "model_p", "p_cal", "ev", "tier", "actual", "result", "note"]
DFS_BOOKS = ("Pick6", "PrizePicks")


# ---------- model, mirroring template.html ----------
def _b2b(payload, team, date):
    last = payload["last_played"].get(team)
    return bool(last) and (dt.date.fromisoformat(date) - dt.date.fromisoformat(last[:10])).days == 1


def starter(payload, team, date):
    """Same priority as the page: DraftKings, PrizePicks, back-to-back backup, depth chart."""
    for src, rows in (("dk", payload.get("dk") or []), ("pp", payload.get("pp") or [])):
        for r in rows:
            if r.get("date") == date and r.get("team") == team and r.get("goalie_id") is not None:
                return int(r["goalie_id"]), src, r["line"]
    dep = payload["depth"].get(team) or []
    if len(dep) > 1 and _b2b(payload, team, date) and payload.get("last_starter", {}).get(team) == dep[0]:
        return dep[1], "b2b", None
    return (dep[0] if dep else None), "depth", None


def project_saves(payload, gid, team, opp, home, b2b, playoff, opp_b2b=False):
    P, lg = payload["params"], payload["league"]
    t, o = payload["teams"].get(team, {}), payload["teams"].get(opp, {})
    sa = lg * (t.get("rate_def", lg) / lg) ** P["a"] * (o.get("rate_off", lg) / lg) ** P["b"]
    sa *= P["home"] if home else 1 / P["home"]
    if playoff:
        sa *= P["playoff"]
    if b2b:
        sa *= P["b2b"]
    if opp_b2b:
        sa *= P.get("opp_b2b", 1.0)
    g = next((x for x in payload["goalies"] if x["id"] == gid), None) or {"sv": .9, "share": payload["lg_share"]}
    return sa, g["sv"], sa * g["share"] * g["sv"]


def p_over_saves(proj, line, sd):
    return saves_dist.p_over(proj, sd, line)


def _ml(payload, date, team):
    """No-vig DraftKings win probability for `team` on `date`, and its American price."""
    for r in payload.get("ml") or []:
        if r.get("date") == date and team in (r.get("home"), r.get("away")) and r.get("home_ml") and r.get("away_ml"):
            ph, pa = saves_dist.devig(r["home_ml"], r["away_ml"])
            return (ph, r["home_ml"]) if team == r["home"] else (pa, r["away_ml"])
    return None, None


def _dk_prices(rows, date, team, name, line):
    key = prizepicks.name_key(name)
    for r in rows or []:
        if r.get("date") == date and team in (r.get("teams") or [r.get("team")]) and \
                prizepicks.name_key(r["name"]) == key and float(r["line"]) == float(line):
            return r.get("over"), r.get("under")
    return None, None


def saves_tier(edge):
    e = abs(edge)
    return "HIGH" if e >= 2.5 else "MED" if e >= 1.5 else "LOW" if e >= 1.0 else "PASS"


def sog_tier(p):
    return "HIGH" if p >= .62 else "MED" if p >= .58 else "LOW" if p >= .55 else "PASS"


def sog_p_over(mean, line, size):
    mean = max(mean, .05)
    p = size / (size + mean)
    cdf, term = [], p ** size
    for i in range(int(math.floor(line)) + 1):
        if i:
            term *= (i - 1 + size) / i * (1 - p)
        cdf.append(term)
    over = 1 - min(sum(cdf), 1)
    if line != math.floor(line):
        return over
    under = min(sum(cdf[:-1]), 1)
    return over / (over + under) if over + under > 0 else .5


# ---------- snapshot ----------
def calls_for_game(payload, g):
    date, playoff = g["date"], g.get("type") == "P"
    W, lgg = payload["win"]["params"], payload["win"]["lg_goals"]
    dist = payload.get("dist") or saves_dist.DEFAULTS
    calib = (payload.get("calib") or {}).get("markets", {})
    out = {"id": g["id"], "date": date, "start": g.get("start"), "home": g["home"], "away": g["away"],
           "saves": [], "sog": []}
    side = {}
    for team, opp, home in ((g["away"], g["home"], False), (g["home"], g["away"], True)):
        gid, src, line = starter(payload, team, date)
        b2b = _b2b(payload, team, date)
        sa, sv, proj = project_saves(payload, gid, team, opp, home, b2b, playoff, _b2b(payload, opp, date))
        side[team] = dict(sa=sa, sv=sv, gid=gid, src=src, line=line, b2b=b2b, opp=opp, home=home)
    # win probability: DraftKings moneyline (no-vig) when posted, otherwise the game-winner model
    th, ta = payload["teams"].get(g["home"], {}), payload["teams"].get(g["away"], {})
    h, a = side[g["home"]], side[g["away"]]
    shot_h, shot_a = a["sa"] * (1 - a["sv"]), h["sa"] * (1 - h["sv"])
    r = lambda f, a_: lgg * ((f if f is not None else lgg) / lgg) * ((a_ if a_ is not None else lgg) / lgg)
    rate_h = (1 - W["x"]) * r(th.get("gf"), ta.get("ga")) + W["x"] * r(th.get("xgf"), ta.get("xga"))
    rate_a = (1 - W["x"]) * r(ta.get("gf"), th.get("ga")) + W["x"] * r(ta.get("xgf"), th.get("xga"))
    lh = (W["w"] * shot_h + (1 - W["w"]) * rate_h) * W["home"]
    la = (W["w"] * shot_a + (1 - W["w"]) * rate_a) / W["home"]
    out["p_home"] = round(winners.win_prob(lh, la, W["ot_home"]), 4)
    mkt_home, ml_home = _ml(payload, date, g["home"])
    _, ml_away = _ml(payload, date, g["away"])
    out["ml_home"], out["ml_away"] = ml_home, ml_away
    out["p_home_mkt"] = round(mkt_home, 4) if mkt_home is not None else None
    p_home = mkt_home if mkt_home is not None else out["p_home"]
    for team in (g["away"], g["home"]):
        x = side[team]
        g_ = next((q for q in payload["goalies"] if q["id"] == x["gid"]), None) or {"sv": .9, "share": payload["lg_share"], "name": str(x["gid"])}
        p_win = p_home if team == g["home"] else 1 - p_home
        pr = saves_dist.project(x["sa"], g_["share"], g_["sv"], p_win, dist)
        row = {"team": team, "opp": x["opp"], "goalie_id": x["gid"], "goalie": g_.get("name", str(x["gid"])), "src": x["src"],
               "confirmed": x["src"] in ("dk", "pp", "manual"), "b2b": x["b2b"], "p_win": round(p_win, 4),
               "exp_sa": round(pr["exp_sa"], 2), "proj": round(pr["proj"], 2), "sd": round(pr["sd"], 2),
               "line": x["line"], "book": {"dk": "DraftKings", "pp": "PrizePicks"}.get(x["src"])}
        if x["line"] is not None:
            po = saves_dist.p_over(pr["proj"], pr["sd"], x["line"])
            over, under = _dk_prices(payload.get("dk"), date, team, row["goalie"], x["line"]) if x["src"] == "dk" else (None, None)
            dfs = {"mult_over": 1, "mult_under": 1} if x["src"] == "pp" else {}
            d = pricing.decide(po, calib.get("saves", {}).get("cal"), over, under, cap=calib.get("saves", {}).get("tier_cap"), **dfs)
            if not row["confirmed"]:
                d.update(play=False, tier="PASS")
            row.update(p_over=round(po, 4), over=over, under=under, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
        out["saves"].append(row)
        players = payload["sog"]["players"].get(team, [])
        sp = payload["sog"]["params"]
        for pl in players:
            mean = pl["r60"] / 60 * pl["toi"] * payload["sog"]["opp"].get(x["opp"], 1) * (sp["home"] if x["home"] else 1 / sp["home"])
            key = prizepicks.name_key(pl["name"])
            dk = next((q for q in payload.get("dk_sog") or [] if q["date"] == date and team in q["teams"]
                       and prizepicks.name_key(q["name"]) == key), None)
            srow = {"id": pl["id"], "name": pl["name"], "team": team, "opp": x["opp"], "proj": round(mean, 3), "toi": pl["toi"],
                    "line": dk["line"] if dk else None, "book": "DraftKings" if dk else None}
            if dk:
                po = sog_p_over(mean, dk["line"], sp["disp"])
                d = pricing.decide(po, calib.get("sog", {}).get("cal"), dk.get("over"), dk.get("under"), cap=calib.get("sog", {}).get("tier_cap"))
                srow.update(p_over=round(po, 4), over=dk.get("over"), under=dk.get("under"),
                            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
            out["sog"].append(srow)
    return out


def snapshot(payload, now: dt.datetime | None = None):
    """Write calls for games starting in the next 30 hours; leave started games frozen."""
    now = now or dt.datetime.now(dt.timezone.utc)
    os.makedirs(CALLS, exist_ok=True)
    by_date = {}
    for g in payload["slate"]:
        start = dt.datetime.fromisoformat(g["start"].replace("Z", "+00:00")) if g.get("start") else None
        if start is None or start <= now or start > now + dt.timedelta(hours=30):
            continue
        by_date.setdefault(g["date"], []).append(g)
    for date, games in by_date.items():
        path = os.path.join(CALLS, f"{date}.json")
        cur = json.load(open(path)) if os.path.exists(path) else {"date": date, "games": {}}
        for g in games:
            cur["games"][str(g["id"])] = calls_for_game(payload, g)
        cur["built"] = payload["built"]
        cur["sd"] = payload["sd"]
        cur["sog_disp"] = payload["sog"]["params"]["disp"]
        with open(path, "w") as f:
            json.dump(cur, f, separators=(",", ":"))
    return sorted(by_date)


# ---------- grading ----------
def _minutes(toi):
    try:
        m, s = str(toi).split(":")
        return int(m) + int(s) / 60
    except ValueError:
        return 0.0


def _box(years):
    gb = pd.concat([pd.read_parquet(p) for y in years if (p := data.fetch("goalie", y))])
    sb = pd.concat([pd.read_parquet(p) for y in years if (p := data.fetch("skater", y))])
    tb = pd.concat([pd.read_parquet(p) for y in years if (p := data.fetch("team", y))])
    for d in (gb, sb, tb):
        d["game_date"] = d["game_date"].astype(str).str[:10]
    return gb, sb, tb


def _read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="") as f:
        return list(csv.DictReader(f))


def _write_log(rows):
    rows.sort(key=lambda r: (r["date"], ["saves", "sog", "winner"].index(r["market"])
                             if r["market"] in ("saves", "sog", "winner") else 9))
    with open(LOG, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _result(side, actual, line):
    if actual == line:
        return "PUSH"
    over = actual > line
    return "HIT" if (over == (side.upper() in ("OVER", "MORE"))) else "MISS"


def _auto_row(date, market, name, c, sd, disp):
    """A logged line from a frozen call. New calls carry the price-aware decision made at pick time;
    older snapshots (before price-aware picks) fall back to the original rule."""
    base = {"date": date, "market": market, "player": name, "team": c["team"], "opp": c["opp"], "book": c["book"],
            "line": c["line"], "mult": 1, "model_proj": round(c["proj"], 2), "note": "auto"}
    if c.get("side"):
        price = c.get("over") if c["side"] == "OVER" else c.get("under")
        po = c.get("p_over")
        return {**base, "side": c["side"], "price": price if price is not None else "",
                "model_p": round(po if c["side"] == "OVER" else 1 - po, 4), "p_cal": c.get("p"),
                "ev": c.get("ev"), "tier": c.get("tier") or "PASS"}
    if market == "saves":
        edge = c["proj"] - c["line"]
        po = 0.5 * math.erfc((c["line"] - c["proj"]) / sd / math.sqrt(2))
        return {**base, "side": "OVER" if edge > 0 else "UNDER", "model_p": round(max(po, 1 - po), 2), "tier": saves_tier(edge)}
    po = sog_p_over(c["proj"], c["line"], disp)
    return {**base, "side": "OVER" if po >= .5 else "UNDER", "model_p": round(max(po, 1 - po), 2), "tier": sog_tier(max(po, 1 - po))}


def grade(years, today: dt.date | None = None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    gb, sb, tb = _box(years)
    final = set(tb.game_id.unique())
    log = _read_log()
    have = {(r["date"], r["market"], r["player"], r["team"], r.get("book") or "") for r in log}
    model_rows = []        # one row per graded game/side/player, for model-accuracy stats
    notes = {}             # (date, market, player, team) -> auto reason

    for path in sorted(glob.glob(os.path.join(CALLS, "*.json"))):
        day = json.load(open(path))
        sd, disp = day["sd"], day["sog_disp"]
        for gid, c in day["games"].items():
            if int(gid) not in final:
                continue
            gt, gg, gs = tb[tb.game_id == int(gid)], gb[gb.game_id == int(gid)], sb[sb.game_id == int(gid)]
            goals = dict(zip(gt.team_abbrev, gt.goals))
            shots_for = dict(zip(gt.team_abbrev, gt.shots_on_goal))
            ot = gg.toi.map(_minutes).max() > 60.5
            # winner (model pick; graded in units at the DraftKings moneyline when one was posted)
            ph = c["p_home"]
            pick, pp = (c["home"], ph) if ph >= .5 else (c["away"], 1 - ph)
            ml = c.get("ml_home") if pick == c["home"] else c.get("ml_away")
            won = c["home"] if goals[c["home"]] > goals[c["away"]] else c["away"]
            score = f"{c['away']} {goals[c['away']]}-{goals[c['home']]} {c['home']}{' OT/SO' if ot else ''}"
            model_rows.append({"date": c["date"], "market": "winner", "pick": pick, "p": pp,
                               "hit": int(pick == won), "score": score})
            key = (c["date"], "winner", pick, pick, "model")
            if key not in have:
                log.append({"date": c["date"], "market": "winner", "player": pick, "team": pick,
                            "opp": c["home"] if pick == c["away"] else c["away"], "side": pick,
                            "model_p": round(pp, 2), "tier": "65%+" if pp >= .65 else "",
                            "book": "model", "price": ml if ml is not None else "",
                            "ev": round(pricing.profit(ml) * pp - (1 - pp), 4) if ml is not None else "",
                            "actual": score, "result": "HIT" if pick == won else "MISS", "note": ""})
                have.add(key)
            # saves
            for s in c["saves"]:
                st = gg[(gg.team_abbrev == s["team"]) & (gg.starter == True)]  # noqa: E712
                if st.empty:
                    continue
                st = st.iloc[0]
                faced = int(shots_for.get(s["opp"], 0))
                right = int(st.player_id) == s["goalie_id"]
                model_rows.append({"date": c["date"], "market": "saves", "team": s["team"],
                                   "starter_ok": int(right), "err": (int(st.saves) - s["proj"]) if right else None,
                                   "sa_err": faced - s["exp_sa"]})
                why = []
                if not right:
                    why.append(f"{st.player_name} started, not {s['goalie']}")
                if abs(faced - s["exp_sa"]) >= 6:
                    why.append(f"{s['team']} faced {faced} shots vs {s['exp_sa']:.0f} expected")
                if _minutes(st.toi) < 50:
                    why.append(f"pulled after {_minutes(st.toi):.0f} min")
                if ot:
                    why.append("went to OT")
                notes[(c["date"], "saves", s["goalie"], s["team"])] = "; ".join(why)
                if s.get("line") is not None and right:
                    k = (c["date"], "saves", s["goalie"], s["team"], s["book"])
                    if k not in have:
                        log.append(_auto_row(c["date"], "saves", s["goalie"], s, sd, None))
                        have.add(k)
            # SOG
            for p in c["sog"]:
                row = gs[gs.player_id == p["id"]]
                if row.empty:
                    continue
                row = row.iloc[0]
                toi = _minutes(row.toi)
                model_rows.append({"date": c["date"], "market": "sog", "err": int(row.shots_on_goal) - p["proj"]})
                why = []
                if abs(toi - p["toi"]) >= 4:
                    why.append(f"TOI {toi:.1f} vs {p['toi']:.1f} expected")
                if ot:
                    why.append("went to OT")
                notes[(c["date"], "sog", p["name"], p["team"])] = "; ".join(why)
                if p.get("line") is not None:
                    k = (c["date"], "sog", p["name"], p["team"], p["book"])
                    if k not in have:
                        log.append(_auto_row(c["date"], "sog", p["name"], p, None, disp))
                        have.add(k)

    # DraftKings rows logged without a price (calls frozen before prices were stored): take the
    # last pre-game price for that exact line from the price history
    if os.path.exists(PRICES):
        pr = {}
        with open(PRICES, newline="") as f:
            for q in csv.DictReader(f):
                pr[(q["market"], q["date"], prizepicks.name_key(q["name"]), float(q["line"]))] = q
        for r in log:
            if r.get("book") == "DraftKings" and r["market"] in ("saves", "sog") and r.get("price") in (None, "") and r.get("line"):
                q = pr.get((r["market"], r["date"], prizepicks.name_key(r["player"]), float(r["line"])))
                if q:
                    r["price"] = q["over"] if r["side"].upper() in ("OVER", "MORE") else q["under"]
    # fill actuals for any logged line still waiting on a result
    for r in log:
        if r.get("result") or r["market"] not in ("saves", "sog"):
            continue
        box = gb if r["market"] == "saves" else sb
        stat = "saves" if r["market"] == "saves" else "shots_on_goal"
        m = box[(box.game_date == r["date"]) & (box.team_abbrev == r["team"])
                & (box.player_name.map(prizepicks.name_key) == prizepicks.name_key(r["player"]))]
        if r["market"] == "saves":
            m = m[m.starter == True]  # noqa: E712
        if m.empty:
            if r["date"] < str(today - dt.timedelta(days=1)) and any(gb.game_date == r["date"]):
                r["result"], r["note"] = "VOID", (r.get("note") or "did not play / start")
            continue
        r["actual"] = int(m.iloc[0][stat])
        r["result"] = _result(r["side"], r["actual"], float(r["line"]))
        auto = notes.get((r["date"], r["market"], r["player"], r["team"]))
        if r["result"] == "MISS" and auto and auto not in (r.get("note") or ""):
            r["note"] = "; ".join(x for x in (r.get("note"), auto) if x)
    _write_log(log)
    summary = summarize(log, model_rows)
    with open(OUT, "w") as f:
        json.dump(summary, f, separators=(",", ":"))
    return summary


# ---------- summary ----------
def _units(r):
    """Profit in units at the pick-time price; None when the row has no sportsbook price (DFS legs)."""
    if r.get("result") not in ("HIT", "MISS", "PUSH") or r.get("book") in DFS_BOOKS or r.get("price") in (None, ""):
        return None
    if r["result"] == "PUSH":
        return 0.0
    return pricing.profit(r["price"]) if r["result"] == "HIT" else -1.0


def _rec(rows):
    h = sum(r["result"] == "HIT" for r in rows)
    m = sum(r["result"] == "MISS" for r in rows)
    u = [x for x in (_units(r) for r in rows) if x is not None]
    return {"hit": h, "miss": m, "push": sum(r["result"] == "PUSH" for r in rows),
            "pct": round(h / (h + m), 4) if h + m else None,
            "priced": len(u), "units": round(sum(u), 2), "roi": round(sum(u) / len(u), 4) if u else None}


def _tier(r):
    if r["market"] == "sog" and not r.get("tier"):
        try:
            return sog_tier(float(r["model_p"]))
        except (TypeError, ValueError):
            return ""
    return r.get("tier") or ""


def is_play(r):
    """Price-aware rows (logged with EV) are plays when their tier isn't PASS. Older rows keep the rule
    they were picked under: saves at 1.5+ edge, SOG at 55%+, never a sub-1x side."""
    if str(r.get("mult") or "1") in ("0.8", "0.9"):
        return False
    if r.get("ev") not in (None, ""):
        return _tier(r) not in ("PASS", "")
    if r["market"] == "saves":
        return _tier(r) in ("MED", "HIGH")
    return r["market"] == "sog" and _tier(r) not in ("PASS", "")


BOOK_PREF = {"Pick6": 0, "PrizePicks": 1, "user quote": 2, "DraftKings": 3}


def summarize(log, model_rows):
    every = [r for r in log if r.get("result") in ("HIT", "MISS", "PUSH")]
    # the same prop can be logged from more than one book: count it once, preferring the book you
    # actually play (Pick6, then PrizePicks). Every split below uses this same de-duplicated set, so
    # tiers, sides, books and nights all add up to the market totals.
    best = {}
    for r in every:
        k = (r["date"], r["market"], r["player"], r["team"])
        if k not in best or BOOK_PREF.get(r.get("book"), 9) < BOOK_PREF.get(best[k].get("book"), 9):
            best[k] = r
    graded = list(best.values())
    plays = [r for r in graded if is_play(r)]
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "plays": _rec(plays), "markets": {}, "days": [], "misses": [], "model": {}, "dfs": {}}
    for mk in ("saves", "sog", "winner"):
        rows = [r for r in graded if r["market"] == mk]
        if mk == "winner":
            by = {"65%+ calls": [r for r in rows if r.get("tier") == "65%+"],
                  "Under 65%": [r for r in rows if r.get("tier") != "65%+"]}
        else:
            by = {t: [r for r in rows if _tier(r) == t] for t in ("HIGH", "MED", "LOW", "PASS")}
        sides = {"OVER / MORE": [r for r in rows if r["side"].upper() in ("OVER", "MORE")],
                 "UNDER / LESS": [r for r in rows if r["side"].upper() in ("UNDER", "LESS")]} if mk != "winner" else {}
        books = sorted({r.get("book") or "" for r in rows})
        out["markets"][mk] = {"all": _rec(rows), "plays": _rec([r for r in rows if is_play(r)]),
                              "by": {k: _rec(v) for k, v in by.items()},
                              "sides": {k: _rec(v) for k, v in sides.items()},
                              "plays_by_side": {k: _rec([r for r in v if is_play(r)]) for k, v in sides.items()},
                              "books": {b or "unknown": _rec([r for r in rows if (r.get("book") or "") == b]) for b in books}}
    # DFS market-basis record: graded at the board's line and multiplier, against the per-leg break-even
    for b in DFS_BOOKS:
        rows = [r for r in graded if r.get("book") == b and r["market"] in ("saves", "sog")]
        if rows:
            be = [pricing.dfs_break_even(float(r.get("mult") or 1)) for r in rows]
            rec = _rec(rows)
            out["dfs"][b] = {**rec, "avg_be": round(sum(be) / len(be), 4),
                             "plays": _rec([r for r in rows if is_play(r)])}
    for d in sorted({r["date"] for r in graded}, reverse=True):
        rows = [r for r in graded if r["date"] == d]
        out["days"].append({"date": d, "plays": _rec([r for r in plays if r["date"] == d]),
                            **{mk: _rec([r for r in rows if r["market"] == mk]) for mk in ("saves", "sog", "winner")}})
    play_ids = {id(r) for r in plays}
    out["misses"] = [{k: r.get(k) for k in ("date", "market", "player", "team", "opp", "line", "side",
                                            "model_proj", "actual", "tier", "note")}
                     for r in sorted(graded, key=lambda r: r["date"], reverse=True)
                     if r["result"] == "MISS" and (id(r) in play_ids
                                                   or r["market"] == "winner" and r.get("tier") == "65%+")][:40]
    # the page carries the last two weeks of the log; the full history stays in the CSV
    cutoff = str(dt.date.fromisoformat(max((r["date"] for r in log), default="2000-01-01")) - dt.timedelta(days=14))
    out["log"] = [{k: r.get(k) for k in FIELDS} for r in sorted(log, key=lambda r: r["date"], reverse=True)
                  if r["date"] > cutoff]
    # model accuracy, no book line needed
    mr = pd.DataFrame(model_rows)
    if not mr.empty:
        days = []
        for d, x in mr.groupby("date"):
            w, s, k = x[x.market == "winner"], x[x.market == "saves"], x[x.market == "sog"]
            days.append({"date": d, "games": len(w), "win_hit": int(w.hit.sum()),
                         "win65": int((w.p >= .65).sum()), "win65_hit": int(w[w.p >= .65].hit.sum()),
                         "starter_ok": int(s.starter_ok.sum()), "starters": len(s),
                         "saves_mae": round(s.err.dropna().abs().mean(), 2) if s.err.notna().any() else None,
                         "sa_bias": round(s.sa_err.mean(), 2),
                         "sog_mae": round(k.err.abs().mean(), 3) if len(k) else None})
        w, s, k = mr[mr.market == "winner"], mr[mr.market == "saves"], mr[mr.market == "sog"]
        out["model"] = {
            "days": sorted(days, key=lambda d: d["date"], reverse=True),
            "winner_pct": round(w.hit.mean(), 4), "winner_n": len(w),
            "win65_pct": round(w[w.p >= .65].hit.mean(), 4) if (w.p >= .65).any() else None,
            "win65_n": int((w.p >= .65).sum()),
            "starter_pct": round(s.starter_ok.mean(), 4), "starter_n": len(s),
            "saves_mae": round(s.err.dropna().abs().mean(), 2), "sa_bias": round(s.sa_err.mean(), 2),
            "sog_mae": round(k.err.abs().mean(), 3) if len(k) else None, "sog_n": len(k)}
    return out


if __name__ == "__main__":
    import sys
    yrs = [int(sys.argv[1])] if len(sys.argv) > 1 else [dt.date.today().year + (dt.date.today().month >= 7)]
    s = grade(yrs)
    print(json.dumps({k: s[k] for k in ("plays", "markets", "model")}, indent=1)[:3000])
