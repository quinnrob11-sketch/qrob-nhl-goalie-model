"""Tonight's prop board: every posted line with model / market / blended p and one verdict per player.

Lines (audit item 10): every Pick6 row the build pulled (pick6.py), then DraftKings sportsbook lines for
shots, points and saves as the fallback for players Pick6 doesn't list (priced at DK's own odds, so a juiced
favourite has to beat its implied probability). DK lines are also the market
price for a Pick6 leg on the same player and line. Every row carries playerId, team, game, market, line,
More / Less multipliers, source and fetched-at time; started games are left out.

For each line (audit items 3 and 9):
  * model p   = the calibrated model alone (no market), P(over)
  * market p  = DraftKings no-vig P(over) on the same player and line, when DK prices it
  * blended p = w x model + (1 - w) x market, w fitted by log loss per market (calibrate.fit_blend)
  * verdict   = pricing.verdict: TAKE MORE / TAKE LESS / PASS with a reason
Per player and market only the best line (highest EV among TAKEs at >= 1x) stays a TAKE; his other lines
are listed under it as alternates. Conflicts (teammates on opposite sides of the same prop, a goalie's
saves against the opposing skaters' shots) demote the lower-probability leg to PASS ("conflict") and
flag the one kept. "Today's plays" is exactly the TAKE rows.
"""
from __future__ import annotations

import pricing
import saves_dist
import slate as slate_mod
import sog
import tracker

MODELED = ("sog", "points", "saves")
LABEL = {"sog": "SOG", "points": "Points", "saves": "Saves", "blocks": "Blocks", "assists": "Assists", "goals": "Goals"}


def _skaters(payload):
    return {pl["id"]: dict(pl, team=team) for team, pls in payload["sog"]["players"].items() for pl in pls}


def _dk_index(payload):
    """(market, player_id, line) -> DK row, for the market price of a DFS leg."""
    out = {}
    for mk, key in (("sog", "dk_sog"), ("points", "dk_points"), ("saves", "dk")):
        for r in payload.get(key) or []:
            pid = r.get("player_id", r.get("goalie_id"))
            if pid is not None and r.get("line") is not None:
                out[(mk, int(pid), float(r["line"]))] = r
    return out


def candidate_lines(payload, pick6_rows, now=None) -> tuple[list[dict], dict]:
    """Pick6 rows, plus DK lines for (player, market) pairs Pick6 doesn't list. Started games removed."""
    games = {g["id"]: g for g in payload["slate"]}
    have = {(r["market"], r["player_id"]) for r in pick6_rows}
    out = [dict(r) for r in pick6_rows if r["game"] in games and not slate_mod.started(games[r["game"]], now)]
    drops = {}
    for mk, key in (("sog", "dk_sog"), ("points", "dk_points"), ("saves", "dk")):
        for r in payload.get(key) or []:
            pid = r.get("player_id", r.get("goalie_id"))
            g = next((g for g in payload["slate"] if g["date"] == r.get("date") and set(r.get("teams") or [r.get("team")]) <= {g["home"], g["away"]}), None)
            if pid is None or g is None:
                drops["DK: unmatched or no game"] = drops.get("DK: unmatched or no game", 0) + 1
                continue
            if (mk, int(pid)) in have or slate_mod.started(g, now):
                continue
            out.append({"name": r["name"], "player_id": int(pid), "team": r.get("team"), "game": g["id"], "date": g["date"],
                        "market": mk, "line": float(r["line"]), "mo": None, "mu": None, "source": "DraftKings",
                        "fetched_at": payload.get("built_iso"), "over": r.get("over"), "under": r.get("under")})
    return out, drops


def _skater_p(payload, pl, g, mk, line):
    team = pl["team"]; opp = g["away"] if team == g["home"] else g["home"]
    blk = payload.get(mk) if mk == "points" else payload["sog"]
    rate, toi_k = ("p60", "ptoi") if mk == "points" else ("r60", "toi")
    if rate not in pl or "params" not in blk:
        return None, None
    prm = sog.SogParams(**{k: tuple(v) if isinstance(v, list) else v for k, v in blk["params"].items() if k in sog.SogParams.__dataclass_fields__})
    b2b, ob2b = tracker._b2b(payload, team, g["date"]), tracker._b2b(payload, opp, g["date"])
    mean = float(sog.live_proj(pl[rate], pl.get(toi_k, pl.get("toi")), blk.get("opp", {}).get(opp, 1),
                               blk.get("team", {}).get(team, 1), team == g["home"], b2b, ob2b, prm))
    return mean, sog.p_over(mean, line, sog.size_for(mean, prm, pl.get("pos")))


def _saves_p(payload, pid, team, g, line):
    """(bias-corrected projection, P(over), confirmed starter?) for this goalie in this game."""
    opp = g["away"] if team == g["home"] else g["home"]
    gid, src, _, _ = tracker.starter(payload, team, g["date"])
    sa, sv, _ = tracker.project_saves(payload, pid, team, opp, team == g["home"], tracker._b2b(payload, team, g["date"]),
                                      g.get("type") == "P", tracker._b2b(payload, opp, g["date"]))
    gl = next((x for x in payload["goalies"] if x["id"] == pid), None) or {"sv": .9, "share": payload["lg_share"]}
    pw, _ = tracker._ml(payload, g["date"], team)
    pr = saves_dist.project(sa, gl["share"], gl["sv"], pw, payload.get("dist") or saves_dist.DEFAULTS)
    proj = pr["proj"] + float(payload.get("saves_bias") or 0.0)
    confirmed = gid == pid and src in ("dk", "pp", "df", "manual")
    return proj, saves_dist.p_over(proj, pr["sd"], line), confirmed


def score_lines(payload, lines) -> list[dict]:
    calib = (payload.get("calib") or {}).get("markets", {})
    sk = _skaters(payload)
    games = {g["id"]: g for g in payload["slate"]}
    dk = _dk_index(payload)
    out = []
    for r in lines:
        g = games[r["game"]]; mk = r["market"]
        row = {**r, "label": LABEL.get(mk, mk.split(":")[-1].title()), "opp": g["away"] if r["team"] == g["home"] else g["home"],
               "start": g.get("start"), "matched": r.get("player_id") is not None, "proj": None, "p_raw": None,
               "p_model": None, "p_mkt": None, "p_blend": None}
        if not row["matched"]:
            row.update(verdict="PASS", reason="unmatched player", side=None, p=None)
            out.append(row); continue
        if mk not in MODELED:
            row.update(verdict="PASS", reason=f"no model for {row['label'].lower()}", side=None, p=None)
            out.append(row); continue
        confirmed = True
        if mk == "saves":
            proj, po, confirmed = _saves_p(payload, r["player_id"], r["team"], g, r["line"])
        else:
            pl = sk.get(r["player_id"])
            if pl is None:
                row.update(verdict="PASS", reason="not on tonight's skater list", side=None, p=None)
                out.append(row); continue
            proj, po = _skater_p(payload, pl, g, mk, r["line"])
            row["role_change"] = pl.get("role_change"); row["role"] = " · ".join(v for v in (pl.get("line"), pl.get("pp")) if v)
        if po is None:
            row.update(verdict="PASS", reason="no projection", side=None, p=None)
            out.append(row); continue
        cal = calib.get(mk, {}).get("cal")
        q = dk.get((mk, r["player_id"], float(r["line"])))
        over_p, under_p = (r.get("over"), r.get("under")) if r["source"] == "DraftKings" else (None, None)
        mkt = pricing.novig(q.get("over"), q.get("under")) if q else None
        pb, pm, pk = pricing.final_p_over(po, cal, market_p=mkt, line=r["line"])
        # a DraftKings fallback line is priced at DraftKings' own odds: a -200 favourite needs 67%, it is not a free 1x leg
        v = pricing.verdict(mk, pb, pm, r["line"], proj, r.get("mo"), r.get("mu"), over_p, under_p,
                            matched=row["matched"], confirmed=confirmed)
        v["p_model_side"] = v.pop("p_model")
        row.update(proj=round(proj, 3), p_raw=round(po, 4), p_model=round(pm, 4), p_mkt=None if pk is None else round(pk, 4),
                   p_blend=round(pb, 4), w=pricing.blend_w(cal), dk_over=over_p, dk_under=under_p, confirmed=confirmed,
                   **{k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()})
        out.append(row)
    return out


def choose(rows) -> list[dict]:
    """One TAKE per player and market (best EV); the rest of his lines become alternates."""
    groups = {}
    for r in rows:
        groups.setdefault((r.get("player_id") or r["name"], r["market"], r["game"]), []).append(r)
    for (pid, mk, _), rs in groups.items():
        i = pricing.best_line(rs)
        for j, r in enumerate(rs):
            r["primary"] = i == j if i is not None else j == _main_index(rs)
            if i is not None and j != i and str(r.get("verdict", "")).startswith("TAKE"):
                r.update(verdict="PASS", reason=f"alt line (best is {rs[i]['line']:g} {rs[i]['side'].lower()})", tier="")
    # no player ever shows two TAKEs: across markets keep both, they are different props; within a
    # market best_line already left one.
    return rows


def _main_index(rs):
    """The line to show first when nothing is a TAKE: the one with p closest to the decision (highest p)."""
    return max(range(len(rs)), key=lambda j: (rs[j].get("p") or 0, rs[j]["source"] == "Pick6"))


def conflicts(rows) -> list[dict]:
    """Teammates on opposite sides of the same prop, and a goalie's saves vs the opposing skaters' shots.
    Among TAKEs the lower-p leg of a conflicting pair becomes PASS ("conflict"); the kept one is flagged."""
    takes = [r for r in rows if str(r.get("verdict", "")).startswith("TAKE")]

    def clash(a, b):
        if a["game"] != b["game"] or a is b:
            return False
        if a["market"] == b["market"] != "saves" and a["team"] == b["team"] and a["side"] != b["side"]:
            return True
        for x, y in ((a, b), (b, a)):
            # goalie OVER saves wants the opposing skaters to shoot (MORE); UNDER saves wants LESS
            if x["market"] == "saves" and y["market"] == "sog" and y["team"] == x["opp"] and x["side"] != y["side"]:
                return True
        return False

    for a in sorted(takes, key=lambda r: -(r.get("p") or 0)):
        if not str(a.get("verdict", "")).startswith("TAKE"):
            continue
        for b in takes:
            if b is a or not str(b.get("verdict", "")).startswith("TAKE") or not clash(a, b):
                continue
            if (b.get("p") or 0) <= (a.get("p") or 0):
                b.update(verdict="PASS", reason=f"conflict: {a['name']} {a['label']} {'MORE' if a['side'] == 'OVER' else 'LESS'}", tier="")
                a.setdefault("conflicts", []).append(f"{b['name']} {b['label']} {'MORE' if b['side'] == 'OVER' else 'LESS'}")
    return rows


def build(payload, pick6_rows, now=None) -> dict:
    lines, dk_drops = candidate_lines(payload, pick6_rows, now)
    rows = conflicts(choose(score_lines(payload, lines)))
    rows.sort(key=lambda r: (not str(r.get("verdict", "")).startswith("TAKE"), -(r.get("p") or 0)))
    plays = [r for r in rows if str(r.get("verdict", "")).startswith("TAKE")]
    modeled = [r for r in rows if r["market"] in MODELED]
    with_p = [r for r in modeled if r.get("p_blend") is not None]
    return {"rows": rows, "plays": [{k: r.get(k) for k in ("name", "player_id", "team", "market", "label", "line", "side",
                                                          "verdict", "tier", "p", "p_model", "p_mkt", "mult", "source",
                                                          "start", "game", "conflicts")} for r in plays],
            "counts": {"lines": len(rows), "modeled": len(modeled), "with_p": len(with_p),
                       "match_rate": round(len(with_p) / len(modeled), 4) if modeled else None,
                       "dk_dropped": dk_drops, "takes": len(plays)}}
