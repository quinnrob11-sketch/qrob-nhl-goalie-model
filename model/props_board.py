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
            # the board says one team, tonight's skater list (current roster) another: a stale or wrong match
            if mk == "sog":   # SOG only, so saves and points rows stay exactly as before
                row["team_mismatch"] = bool(r.get("team") and pl.get("team") and r["team"] != pl["team"])
                row["roster_team"] = pl.get("team")
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


def legacy_choose(rows) -> list[dict]:
    """One TAKE per player and market (best EV); the rest of his lines become alternates. Saves and points
    keep this rule unchanged (finalize runs it over every row and keeps its saves / points results)."""
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


def legacy_conflicts(rows) -> list[dict]:
    """Teammates on opposite sides of the same prop, and a goalie's saves vs the opposing skaters' shots.
    Among TAKEs the lower-p leg of a conflicting pair becomes PASS ("conflict"); the kept one is flagged.
    Saves and points keep this rule unchanged; SOG uses select_sog."""
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


# ---------- SOG selection (one shared rule; template.html selectSog mirrors it) ----------
SOG_TIER_RANK = {"Lock": 0, "Strong": 1, "Near miss": 2}
_is_take = lambda r: str(r.get("verdict", "")).startswith("TAKE")
_sidetxt = lambda r: "MORE" if r.get("side") == "OVER" else "LESS"


def sog_class(r) -> tuple[str | None, str]:
    """Where one SOG line belongs before conflicts: "review" (role change, team-inconsistent or ambiguous
    match), "discount" (the side pays under 1x: hidden from both curated lists, even at 58%+), "Lock" /
    "Strong" (a valid TAKE at 62%+ / 58-62%), "Near miss" (55-58%, pays >= 1x, the model alone agrees;
    never a TAKE), or None (below 55%, a side not offered, or failing break-even / model agreement)."""
    if r.get("side") is None or r.get("p") is None:
        return (("review", "unmatched or ambiguous player") if not r.get("matched", True) else (None, r.get("reason") or "no projection"))
    if not r.get("matched", True):
        return "review", r.get("match_reason") or "unmatched or ambiguous player"
    if r.get("team_mismatch"):
        return "review", f"team mismatch: board {r.get('team')}, roster {r.get('roster_team') or 'other'}"
    if r.get("role_change"):
        return "review", f"role change {r['role_change']} (old → new line)"
    mult = r.get("mult")
    if mult is not None and float(mult) == 0:
        return None, r.get("reason") or "side not offered"
    if mult is not None and float(mult) < pricing.MIN_MULT - 1e-9:
        return "discount", f"pays {float(mult):g}x"
    # DraftKings-priced fallback (no multiplier): it "pays >= 1x" only if its break-even is no worse than a 1x leg's
    if mult is None and r.get("be") is not None and float(r["be"]) > pricing.dfs_break_even(pricing.MIN_MULT) + 1e-9:
        return "discount", f"DK price break-even {100 * float(r['be']):.1f}% (worse than 1x)"
    p = float(r["p"])
    if _is_take(r):
        return ("Lock" if p >= pricing.LOCK_P - 1e-9 else "Strong"), ""
    agrees = (r.get("p_model_side") or 0) > 0.5
    if pricing.NEAR_MISS_P - 1e-9 <= p < pricing.TAKE_P - 1e-9 and agrees:
        return "Near miss", f"{100 * p:.0f}% near miss"
    return None, r.get("reason") or ""


def sog_rank_key(r):
    """Tier, then blended p, then EV, then a stable tie-break. EV only breaks ties, so a lower-probability
    alternate never wins because it pays more."""
    return (SOG_TIER_RANK.get(r.get("sog_tier"), 9), -float(r.get("p") or 0), -float(r.get("ev") if r.get("ev") is not None else -9),
            str(r.get("player_id") or r.get("name")), float(r.get("line") or 0), str(r.get("side") or ""), str(r.get("source") or ""))


def _sog_clash(a, b) -> bool:
    """Teammates on opposite sides of SOG in the same game."""
    return a is not b and a["game"] == b["game"] and a["team"] == b["team"] and a.get("side") != b.get("side")


def _saves_clash(sv, k) -> bool:
    """A goalie's saves TAKE vs an opposing skater's SOG the other way (OVER saves wants the shooters MORE)."""
    return sv["game"] == k["game"] and k["team"] == sv.get("opp") and sv.get("side") != k.get("side")


def select_sog(sog_rows, saves_takes=()) -> dict:
    """The one deterministic SOG selection.
    1. Pool: every main and alternate line, classified by sog_class.
    2. Greedy in sog_rank_key order: a line is kept when its player has no kept line yet and it doesn't
       clash with a kept teammate on the other side or with a saves TAKE (saves decide first and never
       change). A line that loses a conflict is skipped, so that player's next-best eligible line that
       doesn't conflict is promoted. The kept line carries the conflict warning.
    3. At most one SOG line per player per game. Today's plays = kept Lock / Strong; Near miss = kept 55-58%.
    Rows are updated in place (verdict / reason / sog_tier / sog_section / primary / conflicts)."""
    for r in sog_rows:
        r["sog_tier"], r["sog_note"] = sog_class(r)
        r["sog_section"] = None
    pool = sorted([r for r in sog_rows if r["sog_tier"] in SOG_TIER_RANK], key=sog_rank_key)
    kept, have = [], set()
    for r in pool:
        who = (r.get("player_id") or r["name"], r["game"])
        if who in have:
            continue
        foe = next((k for k in kept if _sog_clash(k, r)), None)
        foe_sv = None if foe else next((s for s in saves_takes if _saves_clash(s, r)), None)
        if foe or foe_sv:
            w = foe or foe_sv
            r["sog_note"] = f"conflict: {w['name']} {w.get('label', 'SOG')} {_sidetxt(w)}"
            if foe:
                foe.setdefault("conflicts", []).append(f"{r['name']} SOG {_sidetxt(r)}")
            continue
        kept.append(r); have.add(who)
        r["sog_section"] = "plays" if r["sog_tier"] in ("Lock", "Strong") else "near"
    kept_ids = {id(r) for r in kept}
    groups = {}
    for r in sog_rows:
        groups.setdefault((r.get("player_id") or r["name"], r["game"]), []).append(r)
    for rs in groups.values():
        k = next((r for r in rs if id(r) in kept_ids), None)
        main = k or max(rs, key=lambda r: (r.get("p") or 0, r.get("source") == "Pick6", -float(r.get("line") or 0)))
        for r in rs:
            r["primary"] = r is main
            if id(r) in kept_ids:
                if r["sog_section"] == "plays":
                    r.update(verdict=f"TAKE {_sidetxt(r)}", tier=r["sog_tier"], reason="")
                else:
                    r.update(verdict="PASS", tier="Near miss", reason=r["sog_note"])
                continue
            if r["sog_tier"] == "review":
                r["sog_section"] = "review"
            note = r["sog_note"]
            if k is not None and r["sog_tier"] in SOG_TIER_RANK and not note.startswith("conflict"):
                note = f"alt line (best is {k['line']:g} {_sidetxt(k).lower()})"
            r.update(verdict="PASS", tier="", reason=("needs review: " + note) if r["sog_tier"] == "review" else (note or r.get("reason") or ""))
    disc = [r for r in sog_rows if r["sog_tier"] == "discount" and (r.get("p") or 0) >= pricing.NEAR_MISS_P - 1e-9]
    return {"plays": [r for r in kept if r["sog_section"] == "plays"], "near": [r for r in kept if r["sog_section"] == "near"],
            "review": [r for r in sog_rows if r["sog_section"] == "review"],
            "counts": {"rows": len(sog_rows), "lock": sum(r["sog_tier"] == "Lock" for r in kept),
                       "strong": sum(r["sog_tier"] == "Strong" for r in kept), "near_miss": sum(r["sog_section"] == "near" for r in kept),
                       "needs_review": sum(r["sog_section"] == "review" for r in sog_rows), "hidden_discounts": len(disc)}}


def finalize(rows) -> tuple[list[dict], dict]:
    """Saves and points: the legacy rule, run over every row exactly as before, so their verdicts,
    reasons, tiers and conflict flags are unchanged. SOG: select_sog."""
    import copy
    legacy = legacy_conflicts(legacy_choose(copy.deepcopy(rows)))
    out = []
    for r, lg in zip(rows, legacy):
        out.append(lg if r["market"] != "sog" else r)
    sog_rows = [r for r in out if r["market"] == "sog"]
    saves_takes = [r for r in out if r["market"] == "saves" and _is_take(r)]
    return out, select_sog(sog_rows, saves_takes)


PLAY_KEYS = ("name", "player_id", "team", "market", "label", "line", "side", "verdict", "tier", "p", "p_model", "p_mkt",
             "mult", "source", "start", "game", "conflicts", "role_change", "role", "reason")


def build(payload, pick6_rows, now=None, review=None) -> dict:
    lines, dk_drops = candidate_lines(payload, pick6_rows, now)
    rows, sel = finalize(score_lines(payload, lines))
    rows.sort(key=lambda r: (not _is_take(r), -(r.get("p") or 0)))
    plays = [r for r in rows if _is_take(r)]
    modeled = [r for r in rows if r["market"] in MODELED]
    with_p = [r for r in modeled if r.get("p_blend") is not None]
    # ambiguous / unmatched board rows the Pick6 pull dropped: listed for review, never in a play list
    ambiguous = [{"name": r.get("name"), "team": r.get("team"), "market": r.get("market"), "line": r.get("line"),
                  "reason": r.get("reason")} for r in (review or [])]
    pick = lambda xs: [{k: r.get(k) for k in PLAY_KEYS} for x in [xs] for r in x]
    return {"rows": rows, "plays": pick(plays), "near_miss": pick(sel["near"]),
            "review": pick(sel["review"]) + ambiguous,
            "counts": {"lines": len(rows), "modeled": len(modeled), "with_p": len(with_p),
                       "match_rate": round(len(with_p) / len(modeled), 4) if modeled else None,
                       "dk_dropped": dk_drops, "takes": len(plays),
                       "sog": {**sel["counts"], "needs_review": sel["counts"]["needs_review"] + sum(r["market"] == "sog" for r in ambiguous)}}}


# old names, kept for callers and tests
choose, conflicts = legacy_choose, legacy_conflicts
