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
import sog
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


def _line_for(payload, team, date, gid):
    """The posted line for this goalie: DraftKings first, then PrizePicks. (source, line) or (None, None)."""
    for src, rows in (("dk", payload.get("dk") or []), ("pp", payload.get("pp") or [])):
        for r in rows:
            if r.get("date") == date and r.get("team") == team and r.get("goalie_id") == gid:
                return src, r["line"]
    return None, None


def starter(payload, team, date):
    """Same priority as the page: a DailyFaceoff-confirmed starter, then the goalie with a DraftKings
    line, then a PrizePicks prop, back-to-back backup, depth chart.
    Returns (goalie_id, starter source, line, line source)."""
    for r in payload.get("starters") or []:
        if r.get("date") == date and r.get("team") == team and r.get("goalie_id") is not None \
                and str(r.get("status", "")).lower() == "confirmed":
            ls, line = _line_for(payload, team, date, r["goalie_id"])
            return int(r["goalie_id"]), "df", line, ls
    for src, rows in (("dk", payload.get("dk") or []), ("pp", payload.get("pp") or [])):
        for r in rows:
            if r.get("date") == date and r.get("team") == team and r.get("goalie_id") is not None:
                return int(r["goalie_id"]), src, r["line"], src
    dep = payload["depth"].get(team) or []
    if len(dep) > 1 and _b2b(payload, team, date) and payload.get("last_starter", {}).get(team) == dep[0]:
        return dep[1], "b2b", None, None
    return (dep[0] if dep else None), "depth", None, None


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
           "saves": [], "sog": [], "points": []}
    side = {}
    for team, opp, home in ((g["away"], g["home"], False), (g["home"], g["away"], True)):
        gid, src, line, lsrc = starter(payload, team, date)
        b2b = _b2b(payload, team, date)
        sa, sv, proj = project_saves(payload, gid, team, opp, home, b2b, playoff, _b2b(payload, opp, date))
        side[team] = dict(sa=sa, sv=sv, gid=gid, src=src, line=line, lsrc=lsrc, b2b=b2b, opp=opp, home=home)
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
               "confirmed": x["src"] in ("dk", "pp", "manual", "df"), "b2b": x["b2b"], "p_win": round(p_win, 4),
               "exp_sa": round(pr["exp_sa"], 2), "proj": round(pr["proj"], 2), "sd": round(pr["sd"], 2),
               "line": x["line"], "book": {"dk": "DraftKings", "pp": "PrizePicks"}.get(x["lsrc"])}
        st_row = next((r for r in payload.get("starters") or [] if r.get("date") == date and r.get("team") == team
                       and r.get("goalie_id") == x["gid"]), None)
        if st_row:
            row["starter_src"] = f"{st_row['source']} {st_row['status']}"
            row["starter_at"] = st_row.get("at")
        if x["line"] is not None:
            po = saves_dist.p_over(pr["proj"], pr["sd"], x["line"])
            over, under = _dk_prices(payload.get("dk"), date, team, row["goalie"], x["line"]) if x["lsrc"] == "dk" else (None, None)
            dfs = {"mult_over": 1, "mult_under": 1} if x["lsrc"] == "pp" else {}
            d = pricing.decide(po, calib.get("saves", {}).get("cal"), over, under, cap=calib.get("saves", {}).get("tier_cap"),
                               market="saves", proj=pr["proj"], line=x["line"], **dfs)
            if not row["confirmed"]:
                d.update(play=False, tier="PASS")
            row.update(p_over=round(po, 4), over=over, under=under, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
        out["saves"].append(row)
        players = payload["sog"]["players"].get(team, [])
        ob2b = side[x["opp"]]["b2b"]
        for market, sec, rate, toi_k, dk_key in (("sog", "sog", "r60", "toi", "dk_sog"), ("points", "points", "p60", "ptoi", "dk_points")):
            blk = payload.get(sec) or {}
            if "params" not in blk:
                continue
            prm = sog.SogParams(**{k: v for k, v in blk["params"].items() if k in sog.SogParams.__dataclass_fields__})
            for pl in players:
                if rate not in pl:
                    continue
                mean = sog.live_proj(pl[rate], pl[toi_k], blk.get("opp", {}).get(x["opp"], 1), blk.get("team", {}).get(team, 1),
                                     x["home"], x["b2b"], ob2b, prm)
                key = prizepicks.name_key(pl["name"])
                dk = next((q for q in payload.get(dk_key) or [] if q["date"] == date and team in q["teams"]
                           and prizepicks.name_key(q["name"]) == key), None)
                srow = {"id": pl["id"], "name": pl["name"], "team": team, "opp": x["opp"], "proj": round(mean, 3), "toi": pl[toi_k],
                        "line": dk["line"] if dk else None, "book": "DraftKings" if dk else None}
                if pl.get("line") or pl.get("pp"):
                    srow["role"] = " · ".join(v for v in (pl.get("line"), pl.get("pp")) if v)
                if dk:
                    po = sog_p_over(mean, dk["line"], sog.size_for(mean, prm))
                    d = pricing.decide(po, calib.get(market, {}).get("cal"), dk.get("over"), dk.get("under"),
                                       cap=calib.get(market, {}).get("tier_cap"), market=market, proj=mean, line=dk["line"])
                    srow.update(p_over=round(po, 4), over=dk.get("over"), under=dk.get("under"),
                                **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
                out.setdefault(market, []).append(srow)
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
        cur["alarm"] = night_board(cur, {str(g["id"]) for g in games})
        cur["built"] = payload["built"]
        cur["sd"] = payload["sd"]
        cur["sog_disp"] = payload["sog"]["params"]["disp"]
        with open(path, "w") as f:
            json.dump(cur, f, separators=(",", ":"))
    return sorted(by_date)


def night_board(day: dict, fresh: set | None = None) -> dict:
    """One-sided board warning per market for one night (pricing.night_alarm), counting every game on
    the night. Display only: it never changes a play. (`fresh` is kept for callers; unused.)"""
    out = {}
    for mk in ("saves", "sog", "points"):
        rows = [r for g in day["games"].values() for r in g.get(mk, []) if r.get("side")]
        out[mk] = pricing.night_alarm([{"side": r["side"], "play": r.get("play", False)} for r in rows])
    return out


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


def dedup(rows):
    """One row per date + player + market + line + book. A graded row beats an ungraded one, a priced
    row beats an unpriced one, otherwise the later row wins. Keeps the original order."""
    def rank(r):
        return (r.get("result") not in (None, ""), r.get("price") not in (None, ""), r.get("ev") not in (None, ""))
    best = {}
    for i, r in enumerate(rows):
        try:
            line = float(r.get("line")) if r.get("line") not in (None, "") else ""
        except ValueError:
            line = r.get("line")
        k = (r["date"], prizepicks.name_key(r["player"]), r["market"], line, r.get("book") or "")
        if k not in best or rank(r) >= rank(rows[best[k]]):
            best[k] = i
    keep = set(best.values())
    return [r for i, r in enumerate(rows) if i in keep]


def _write_log(rows):
    rows[:] = dedup(rows)
    rows.sort(key=lambda r: (r["date"], ["saves", "sog", "points", "winner"].index(r["market"])
                             if r["market"] in ("saves", "sog", "points", "winner") else 9))
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

    alarms = {}            # date -> market -> board split at pick time (one-sided alarm)
    for path in sorted(glob.glob(os.path.join(CALLS, "*.json"))):
        day = json.load(open(path))
        sd, disp = day["sd"], day["sog_disp"]
        if day.get("alarm"):
            alarms[day["date"]] = day["alarm"]
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
            # points (price-aware rows only: the market started after price-aware picks)
            for p in c.get("points", []):
                if p.get("line") is None or not p.get("side") or gs[gs.player_id == p["id"]].empty:
                    continue
                k = (c["date"], "points", p["name"], p["team"], p["book"])
                if k not in have:
                    log.append(_auto_row(c["date"], "points", p["name"], p, None, disp))
                    have.add(k)

    # DraftKings rows logged without a price (calls frozen before prices were stored): take the
    # last pre-game price for that exact line from the price history
    if os.path.exists(PRICES):
        pr = {}
        with open(PRICES, newline="") as f:
            for q in csv.DictReader(f):
                pr[(q["market"], q["date"], prizepicks.name_key(q["name"]), float(q["line"]))] = q
        for r in log:
            if r.get("book") == "DraftKings" and r["market"] in ("saves", "sog", "points") and r.get("price") in (None, "") and r.get("line"):
                q = pr.get((r["market"], r["date"], prizepicks.name_key(r["player"]), float(r["line"])))
                if q:
                    r["price"] = q["over"] if r["side"].upper() in ("OVER", "MORE") else q["under"]
    # fill actuals for any logged line still waiting on a result
    for r in log:
        if r.get("result") or r["market"] not in ("saves", "sog", "points"):
            continue
        box = gb if r["market"] == "saves" else sb
        stat = {"saves": "saves", "sog": "shots_on_goal", "points": "points"}[r["market"]]
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
    summary = summarize(log, model_rows, alarms)
    with open(OUT, "w") as f:
        json.dump(summary, f, separators=(",", ":"))
    return summary


# ---------- summary ----------
def dfs_leg(r):
    """A DFS leg (Pick6 / PrizePicks) priced like a bet: per-leg break-even of the default entry at the
    row's multiplier, so a win pays 1/break-even - 1 units (+0.732u at 1x on a 2-pick 3x) and a loss -1.
    Returns (break-even, EV at the model's probability or None)."""
    be = pricing.dfs_break_even(float(r.get("mult") or 1))
    p = r.get("p_cal") if r.get("p_cal") not in (None, "") else r.get("model_p")
    try:
        ev = float(p) / be - 1
    except (TypeError, ValueError):
        ev = None
    return be, ev


def _units(r):
    """Profit in units at the pick-time price. Sportsbook rows use their American price; DFS legs are
    priced at the per-leg break-even (dfs_leg). None when there is no price at all."""
    if r.get("result") not in ("HIT", "MISS", "PUSH"):
        return None
    if r.get("book") in DFS_BOOKS:
        if r["result"] == "PUSH":
            return 0.0
        return 1 / dfs_leg(r)[0] - 1 if r["result"] == "HIT" else -1.0
    if r.get("price") in (None, ""):
        return None
    if r["result"] == "PUSH":
        return 0.0
    return pricing.profit(r["price"]) if r["result"] == "HIT" else -1.0


def _rec(rows):
    h = sum(r["result"] == "HIT" for r in rows)
    m = sum(r["result"] == "MISS" for r in rows)
    u = [x for x in (_units(r) for r in rows) if x is not None]
    ub = [x for r in rows if r.get("book") not in DFS_BOOKS and (x := _units(r)) is not None]
    return {"units_book": round(sum(ub), 2), "units_dfs": round(sum(u) - sum(ub), 2),"hit": h, "miss": m, "push": sum(r["result"] == "PUSH" for r in rows),
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


PROB_BUCKETS = (("<55", 0, .55), ("55-60", .55, .60), ("60-65", .60, .65), ("65+", .65, 2))
FORWARD_GOAL = 150         # forward-graded plays a market needs before tiers above LOW (calibrate.GATE_N)


def _p_side(r) -> float:
    """Probability of the picked side at pick time: calibrated when logged, else the model's."""
    for k in ("p_cal", "model_p"):
        try:
            return float(r[k])
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


BOOK_PREF = {"Pick6": 0, "PrizePicks": 1, "user quote": 2, "DraftKings": 3}


def board_split(plays, alarms=None):
    """Per night and market: graded plays by side, and whether the one-sided alarm fired at pick time."""
    out = []
    for d in sorted({r["date"] for r in plays}, reverse=True):
        for mk in ("saves", "sog", "points"):
            x = [r for r in plays if r["date"] == d and r["market"] == mk]
            if not x:
                continue
            o = sum(r["side"].upper() in ("OVER", "MORE") for r in x)
            a = (alarms or {}).get(d, {}).get(mk) or {}
            out.append({"date": d, "market": mk, "plays": len(x), "over": o, "under": len(x) - o,
                        "share": round(max(o, len(x) - o) / len(x), 4),
                        "one_sided": len(x) >= pricing.ALARM_MIN_PLAYS and max(o, len(x) - o) / len(x) > pricing.ALARM_SHARE,
                        "alarm": a.get("alarm"), "pre_alarm": {k: a.get(k) for k in ("plays", "over", "under")} if a else None,
                        "rec": _rec(x)})
    return out


def summarize(log, model_rows, alarms=None):
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
    for mk in ("saves", "sog", "points", "winner"):
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
        # plays by the probability they had when picked, graded at the line they were picked at
        # (every winner pick counts; props count their plays)
        pl = rows if mk == "winner" else [r for r in rows if is_play(r)]
        out["markets"][mk]["prob_buckets"] = {k: _rec([r for r in pl if lo <= _p_side(r) < hi])
                                              for k, lo, hi in PROB_BUCKETS}
        if mk != "winner":
            fwd = [r for r in pl if r.get("ev") not in (None, "")]
            out["markets"][mk]["forward"] = {**_rec(fwd), "goal": FORWARD_GOAL}
    # DFS market-basis record: graded at the board's line and multiplier, against the per-leg break-even
    for b in DFS_BOOKS:
        rows = [r for r in graded if r.get("book") == b and r["market"] in ("saves", "sog", "points")]
        if rows:
            be = [pricing.dfs_break_even(float(r.get("mult") or 1)) for r in rows]
            rec = _rec(rows)
            out["dfs"][b] = {**rec, "avg_be": round(sum(be) / len(be), 4),
                             "plays": _rec([r for r in rows if is_play(r)])}
    for d in sorted({r["date"] for r in graded}, reverse=True):
        rows = [r for r in graded if r["date"] == d]
        out["days"].append({"date": d, "plays": _rec([r for r in plays if r["date"] == d]),
                            **{mk: _rec([r for r in rows if r["market"] == mk]) for mk in ("saves", "sog", "points", "winner")}})
    out["board_split"] = board_split(plays, alarms)
    play_ids = {id(r) for r in plays}
    out["misses"] = [{k: r.get(k) for k in ("date", "market", "player", "team", "opp", "line", "side",
                                            "model_proj", "actual", "tier", "note")}
                     for r in sorted(graded, key=lambda r: r["date"], reverse=True)
                     if r["result"] == "MISS" and (id(r) in play_ids
                                                   or r["market"] == "winner" and r.get("tier") == "65%+")][:40]
    # the page carries the last two weeks of the log; the full history stays in the CSV
    cutoff = str(dt.date.fromisoformat(max((r["date"] for r in log), default="2000-01-01")) - dt.timedelta(days=14))
    out["log"] = [{**{k: r.get(k) for k in FIELDS},
                   **({"ev": round(dfs_leg(r)[1], 4)} if r.get("book") in DFS_BOOKS and r.get("ev") in (None, "") and dfs_leg(r)[1] is not None else {})}
                  for r in sorted(log, key=lambda r: r["date"], reverse=True) if r["date"] > cutoff]
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
