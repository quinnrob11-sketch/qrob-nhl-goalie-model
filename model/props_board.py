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

import math

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
    """(market, player_id, date, line) -> DK row, for the market price of a DFS leg in that day's game."""
    out = {}
    for mk, key in (("sog", "dk_sog"), ("points", "dk_points"), ("saves", "dk")):
        for r in payload.get(key) or []:
            pid = r.get("player_id", r.get("goalie_id"))
            if pid is not None and r.get("line") is not None:
                out[(mk, int(pid), r.get("date"), float(r["line"]))] = r
    return out


def _books_index(payload):
    """(market, player_id, date, line) -> [(book, no-vig P(over))] from the other sportsbooks (payload["books"])."""
    out = {}
    for r in payload.get("books") or []:
        pid, nv = r.get("player_id"), pricing.novig(r.get("over"), r.get("under"))
        if pid is not None and r.get("line") is not None and nv is not None:
            out.setdefault((r["market"], int(pid), r.get("date"), float(r["line"])), []).append((r.get("book"), nv))
    return out


def market_quote(dk, books, mk, pid, line, date):
    """The market's no-vig P(over) on this exact player-line and where it came from. DraftKings first: it is
    the reference the rules were backtested on. Otherwise the mean no-vig of the other books that price the same
    line (they would otherwise leave the model alone, and model-only picks have not won)."""
    q = dk.get((mk, pid, date, line))
    if q:
        nv = pricing.novig(q.get("over"), q.get("under"))
        if nv is not None:
            return nv, "DraftKings"
    bs = books.get((mk, pid, date, line)) or []
    if bs:
        return sum(p for _, p in bs) / len(bs), (bs[0][0] if len(bs) == 1 else f"{len(bs)} books")
    return None, None


def candidate_lines(payload, pick6_rows, now=None) -> tuple[list[dict], dict]:
    """Pick6 rows, plus DK lines for (player, market) pairs Pick6 doesn't list. Started games removed."""
    games = {g["id"]: g for g in payload["slate"]}
    have = {(r["market"], r["player_id"]) for r in pick6_rows}
    out = [dict(r) for r in pick6_rows if r["game"] in games and not slate_mod.started(games[r["game"]], now)]
    drops = {}
    # a DK row without its own stamp takes the DK pull's real fetch time (never the build time)
    dk_at = ((payload.get("sources") or {}).get("dk") or {}).get("fetched_at")
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
                        "fetched_at": r.get("fetched_at") or dk_at, "over": r.get("over"), "under": r.get("under")})
    return out, drops


def _prm(payload, mk):
    blk = payload.get(mk) if mk == "points" else payload["sog"]
    if not blk or "params" not in blk:
        return None
    return sog.SogParams(**{k: tuple(v) if isinstance(v, list) else v for k, v in blk["params"].items() if k in sog.SogParams.__dataclass_fields__})


def _player_quotes(payload, books_rows=None):
    """(market, player_id, date) -> [(line, no-vig P(over), source)] for every line a book prices for the player that day:
    DraftKings first, then the other books (payload["books"])."""
    out = {}
    for mk, key in (("sog", "dk_sog"), ("points", "dk_points")):
        for r in payload.get(key) or []:
            nv = pricing.novig(r.get("over"), r.get("under"))
            if r.get("player_id") is not None and nv is not None:
                out.setdefault((mk, int(r["player_id"]), r.get("date")), []).append((float(r["line"]), nv, "DraftKings"))
    for r in payload.get("books") or []:
        nv = pricing.novig(r.get("over"), r.get("under"))
        if r.get("player_id") is not None and nv is not None and r.get("market") in ("sog", "points"):
            out.setdefault((r["market"], int(r["player_id"]), r.get("date")), []).append((float(r["line"]), nv, r.get("book") or "book"))
    return out


def sog_market_mean(quotes, prm, pos):
    """The market's view of a player's shots as a negative-binomial mean: from DraftKings' line whose no-vig is
    nearest 50% (the most informative number), else the other books' mean implied mean. (mu, source) or (None, None)."""
    if not quotes or prm is None:
        return None, None
    dk = [q for q in quotes if q[2] == "DraftKings"]
    if dk:
        line, nv, _ = min(dk, key=lambda q: abs(q[1] - 0.5))
        return sog.implied_mean(nv, line, prm, pos), "DraftKings"
    mus = [m for m in (sog.implied_mean(nv, line, prm, pos) for line, nv, _ in quotes) if m is not None]
    return (sum(mus) / len(mus), quotes[0][2] if len({q[2] for q in quotes}) == 1 else f"{len({q[2] for q in quotes})} books") if mus else (None, None)


def _skater_p(payload, pl, g, mk, line):
    team = pl["team"]; opp = g["away"] if team == g["home"] else g["home"]
    blk = payload.get(mk) if mk == "points" else payload["sog"]
    rate, toi_k = ("p60", "ptoi") if mk == "points" else ("r60", "toi")
    if rate not in pl or "params" not in blk:
        return None, None
    prm = _prm(payload, mk)
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
    books = _books_index(payload)
    pquotes = _player_quotes(payload)
    sprm = _prm(payload, "sog")
    cached = _cached_sources(payload)
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
        # DraftKings fallback lines, and PrizePicks demons / goblins (non-standard payouts), carry their own odds
        over_p, under_p = (r.get("over"), r.get("under")) if r["source"] == "DraftKings" or r.get("priced") else (None, None)
        mkt, mkt_src = market_quote(dk, books, mk, r["player_id"], float(r["line"]), g["date"])
        mu_mkt, msrc = None, None
        if mk == "sog" and pricing.SOG_MEAN_W > 0:
            # shots on goal: blend in mean space. The market's price (any line it posts) becomes an expected-shots
            # number, averaged with the model's projection, then priced at THIS line with the model's dispersion.
            # No Platt for SOG: fitted on DK main lines it distorted every other line (ladder rungs shown at 12%
            # hit 5%). Without any market price the raw model stands (and the rule then PASSes: no market support).
            pos = (sk.get(r["player_id"]) or {}).get("pos")
            mu_mkt, msrc = sog_market_mean(pquotes.get(("sog", int(r["player_id"]), g["date"])), sprm, pos)
            line = float(r["line"])
            if mu_mkt is not None:
                mu_b = (1 - pricing.SOG_MEAN_W) * proj + pricing.SOG_MEAN_W * mu_mkt
                pb = sog.p_over(mu_b, line, sog.size_for(mu_b, sprm, pos))
                pk = mkt if mkt is not None else sog.p_over(mu_mkt, line, sog.size_for(mu_mkt, sprm, pos))
                mkt_src = mkt_src if mkt is not None else f"{msrc} (other line)"
            else:
                pb, pk = po, None
            pm = po
        else:
            pb, pm, pk = pricing.final_p_over(po, cal, market_p=mkt, line=r["line"])
        # a DraftKings fallback line is priced at DraftKings' own odds: a -200 favourite needs 67%, it is not a free 1x leg
        v = pricing.verdict(mk, pb, pm, r["line"], proj, r.get("mo"), r.get("mu"), over_p, under_p,
                            matched=row["matched"], confirmed=confirmed, p_mkt_over=pk)
        v["p_model_side"] = v.pop("p_model")
        # a line or a market price reused from an earlier build (this build's pull failed) is never a TAKE: paired
        # with tonight's other numbers it can show an edge that no longer exists
        stale_src = _cached_reason(r, cached, pk is not None)
        if stale_src and (str(v.get("verdict", "")).startswith("TAKE") or v.get("tier") == "Near miss"):
            v.update(verdict="PASS", tier="", reason=stale_src)      # a reused line is not a near miss either
        # probabilities ship at full precision: the page re-decides every row from them (finishRow), and a value
        # rounded onto a bar (61.996% -> 62.00%) would turn a near miss into a TAKE there but not here
        row.update(proj=round(proj, 3), p_raw=po, p_model=pm, p_mkt=pk, p_blend=pb, w=pricing.blend_w(cal),
                   dk_over=over_p, dk_under=under_p, confirmed=confirmed,
                   mkt_src=mkt_src if pk is not None else None, mu_mkt=mu_mkt, mu_src=msrc if mu_mkt is not None else None,
                   mean_blend=mk == "sog" and pricing.SOG_MEAN_W > 0, cached=bool(stale_src), **v)
        out.append(row)
    return out


def _cached_sources(payload) -> set:
    """Sources whose lines this build reused from an earlier pull ("fallback") or could not get ("error")."""
    return {k for k, v in (payload.get("sources") or {}).items() if (v or {}).get("status") in ("fallback", "error")}


def _cached_reason(r, cached: set, priced: bool) -> str | None:
    """Why a row's numbers are not this build's, or None: its own line came from a reused board or an earlier pull
    (`reused`), or the market price it leans on did (DraftKings and the other books arrive in one Odds API pull)."""
    import sources
    src = sources.SOURCE_KEY.get(r.get("source"), "")
    if src in cached:
        return f"cached {r.get('source')} line (this build's pull failed): not a play"
    if r.get("reused"):       # pick6.merge_day: an earlier pull's line the page did not show this build
        return f"cached {r.get('source')} line (from an earlier pull today): not a play"
    if priced and "dk" in cached:
        return "cached market price (this build's odds pull failed): not a play"
    return None


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


SRC_PREF = {"Pick6": 0, "PrizePicks": 1, "DraftKings": 2}


def _both_ways(r) -> bool:
    """A main line: More and Less both offered (not a More-only Pick6 alt, not a demon / goblin)."""
    if r.get("alt") or r.get("priced"):
        return False
    if r.get("source") == "DraftKings":
        return True
    mo, mu = r.get("mo"), r.get("mu")
    return mo not in (None, 0, 0.0) and mu not in (None, 0, 0.0)


def _ladder_dist(r) -> float:
    """How far a one-sided rung's offered multiplier is from 1x (|ln m|); 0 for lines offered both ways."""
    if _both_ways(r):
        return 0.0
    m = [float(x) for x in (r.get("mo"), r.get("mu")) if x not in (None, "") and float(x) > 0]
    return min(abs(math.log(x)) for x in m) if m else 99.0


def main_line_key(r):
    """Display order for a player's lines when none is kept: his main line (offered both ways), Pick6 first,
    then PrizePicks, then DraftKings; if every line is a one-sided ladder rung, the rung whose offered
    multiplier is closest to 1x; then the stable tie-break. Display only: it never makes or removes a call.
    (The old rule showed the highest-p line, which was often a More-only alt shown on its LESS side.)"""
    return (not _both_ways(r), SRC_PREF.get(r.get("source"), 3), _ladder_dist(r), -float(r.get("p") or 0),
            float(r.get("line") or 0))


def _main_index(rs):
    """The line to show first when nothing is a TAKE: the player's main line (main_line_key)."""
    return min(range(len(rs)), key=lambda j: main_line_key(rs[j]))


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
    match), "discount" (the side pays under 1x: hidden from both curated lists, even at a high p), "Lock" /
    "Strong" (a valid TAKE: pricing.lock_p / take_p for SOG), "Near miss" (the verdict's flag: every check met
    except p, within NEAR_BAND of the bar; never a TAKE), or None (a side not offered, no market support, a
    cached line, or failing break-even)."""
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
        return ("Lock" if p >= pricing.lock_p("sog") - 1e-9 else "Strong"), ""
    agrees = (r.get("p_model_side") or 0) > 0.5 or not pricing.SOG_MODEL_AGREE
    # near miss = the verdict's own flag: every check met except p, which is within NEAR_BAND of the bar
    if r.get("tier") == "Near miss" and agrees:
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
        main = k or min(rs, key=main_line_key)
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
    disc = [r for r in sog_rows if r["sog_tier"] == "discount" and (r.get("p") or 0) >= pricing.near_p("sog") - 1e-9]
    return {"plays": [r for r in kept if r["sog_section"] == "plays"], "near": [r for r in kept if r["sog_section"] == "near"],
            "review": [r for r in sog_rows if r["sog_section"] == "review"],
            "counts": {"rows": len(sog_rows), "lock": sum(r["sog_tier"] == "Lock" for r in kept),
                       "strong": sum(r["sog_tier"] == "Strong" for r in kept), "near_miss": sum(r["sog_section"] == "near" for r in kept),
                       "needs_review": sum(r["sog_section"] == "review" for r in sog_rows), "hidden_discounts": len(disc)}}


# ---------- one pick per player and market: which side, on which app, how sure (template.html pickFor mirrors it) ----------
APPS = ("Pick6", "PrizePicks")
PICK_RANK = {"play": 0, "lean": 1, "check": 2}


def side_offer(r, side):
    """What `side` ("OVER" / "UNDER") of this line pays: its break-even probability with the multiplier or the price
    behind it, or None when the side is not offered. A pick'em multiplier m needs dfs_break_even(m); a line that
    carries American odds (a DraftKings fallback row, a PrizePicks demon / goblin) needs the price's implied
    probability. `full` = it pays at least what a 1x pick'em leg does."""
    if r.get("source") == "DraftKings" or r.get("priced"):
        price = r.get("dk_over") if side == "OVER" else r.get("dk_under")
        if price in (None, ""):
            return None
        o = {"be": pricing.implied(price), "mult": None, "price": price}
    else:
        m = r.get("mo") if side == "OVER" else r.get("mu")
        m = 1.0 if m in (None, "") else float(m)
        if m <= 0:
            return None
        o = {"be": pricing.dfs_break_even(m), "mult": m, "price": None}
    o["full"] = o["be"] <= pricing.dfs_break_even(pricing.MIN_MULT) + 1e-9
    return o


def pick_options(rs) -> list[dict]:
    """Every bet a pick'em app offers on one player's lines: {row, side, p (the blended chance of that side at that
    line), be, mult / price, full}. DraftKings rows are sportsbook odds, not an app, and are left out."""
    out = []
    for r in rs:
        if r.get("source") not in APPS or r.get("p_blend") is None or not r.get("matched", True):
            continue
        for side in ("OVER", "UNDER"):
            o = side_offer(r, side)
            if o is not None:
                out.append({"row": r, "side": side, "p": r["p_blend"] if side == "OVER" else 1 - r["p_blend"], **o})
    return out


def pick_key(o):
    """Best first: the higher chance; then the better pay; then a line this build pulled itself before one from a
    reused (fallback) board; then Pick6 before PrizePicks; then the lower line and MORE (a stable tie-break only)."""
    r = o["row"]
    return (-o["p"], o["be"], bool(r.get("fallback")), SRC_PREF.get(r.get("source"), 3), float(r.get("line") or 0), o["side"])


def lean_tier(o) -> str:
    """"lean": not a play, but the side to take: offered at >= 1x, on this build's own numbers, and a lean by
    probability (pricing.lean: blended p >= LEAN_P, the market's own probability for the side >= LEAN_MKT_MIN, shots
    or points, no points unders on 1.5+). "check": the same, on a shots line with a flagged line change or team
    mismatch (confirm his spot first). "" otherwise."""
    r, side = o["row"], o["side"]
    if not o["full"] or r.get("cached"):
        return ""
    pk = r.get("p_mkt")
    if not pricing.lean(r["market"], side, o["p"], None if pk is None else (pk if side == "OVER" else 1 - pk), r["line"]):
        return ""
    if r["market"] == "sog" and (r.get("role_change") or r.get("team_mismatch")):
        return "check"
    return "lean"


def pick_for(rs) -> dict | None:
    """One player's lines in one market and game -> the one bet to show for him, or None when no app offers him.
      1. his TAKE, if he has one ("play");
      2. else the highest-chance bet paying >= 1x that is a lean or a check (lean_tier, ordered by pick_key);
      3. else there is no edge, and the row only says which way he leans: the highest-chance bet paying >= 1x when
         that is the likelier side (50%+, e.g. a PrizePicks line near a coin flip); otherwise his main line
         (main_line_key) on its likelier offered side, whatever it pays (tier "")."""
    opts = pick_options(rs)
    if not opts:
        return None
    take = next((r for r in rs if _is_take(r) and r.get("source") in APPS), None)
    if take is not None:
        o = next((o for o in opts if o["row"] is take and o["side"] == take.get("side")), None)
        if o is not None:
            return {**o, "tier": "play"}
    full = [o for o in opts if o["full"]]
    good = [o for o in full if lean_tier(o)]
    if good:
        o = min(good, key=pick_key)
        return {**o, "tier": lean_tier(o)}
    best = min(full, key=pick_key) if full else None
    if best is not None and best["p"] >= 0.5:
        return {**best, "tier": ""}
    main = min({id(o["row"]): o["row"] for o in opts}.values(), key=main_line_key)
    o = max((o for o in opts if o["row"] is main), key=lambda o: (o["p"], -o["be"]))
    return {**o, "tier": ""}


OLD_APP_MAX_MIN = 12 * 60       # an app's line from an earlier pull is named beside a pick for at most this long


def _old_app(r) -> dict:
    """{"old": True, "age_min"} for a line this build did not pull itself (a reused board, or an earlier pull the
    app's page did not show this time: sources.label_rows' `fallback`), else {}."""
    return {"old": True, "age_min": r.get("age_min")} if r.get("fallback") else {}


def picks(rows) -> list[dict]:
    """The board as a person bets it: one pick per player, market and game, from his Pick6 / PrizePicks lines.
    Marks each pick's row in place and returns those rows, plays first, then leans, then by chance:
      pick_side / pick_p   the side to take and its blended chance at that line
      pick_tier            "play" (a TAKE), "lean", "check" (lean_tier) or "" (no edge)
      pick_apps            every app that offers exactly this bet (side and line) at >= 1x: [{app, mult, price}],
                           the pick's own app first. An app whose line this build did not pull itself carries
                           old=True and its age, and is dropped after OLD_APP_MAX_MIN
      lean                 True for a lean (logged with the leg, so leans get a graded record)
    Every verdict, tier and probability on the rows is unchanged."""
    groups = {}
    for r in rows:
        r["pick"], r["lean"] = False, False
        groups.setdefault((r.get("player_id") or r["name"], r["market"], r["game"]), []).append(r)
    out = []
    for rs in groups.values():
        o = pick_for(rs)
        if o is None:
            continue
        r = o["row"]
        apps = [{"app": r["source"], "mult": o["mult"], "price": o["price"], **_old_app(r)}]
        for x in rs:
            if x is r or x.get("source") not in APPS or x.get("p_blend") is None \
                    or float(x["line"]) != float(r["line"]) or any(a["app"] == x["source"] for a in apps):
                continue
            # a line this build did not pull itself is named only while it is recent, and with its age
            if x.get("fallback") and not (x.get("age_min") is not None and x["age_min"] <= OLD_APP_MAX_MIN):
                continue
            ox = side_offer(x, o["side"])
            if ox is not None and ox["full"]:
                apps.append({"app": x["source"], "mult": ox["mult"], "price": ox["price"], **_old_app(x)})
        apps[1:] = sorted(apps[1:], key=lambda a: (bool(a.get("old")), SRC_PREF.get(a["app"], 3)))
        r.update(pick=True, pick_side=o["side"], pick_p=o["p"], pick_tier=o["tier"], pick_apps=apps, lean=o["tier"] == "lean")
        out.append(r)
    out.sort(key=lambda r: (PICK_RANK.get(r["pick_tier"], 9), -r["pick_p"], str(r.get("player_id") or r["name"]), r["market"]))
    return out


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
             "mult", "source", "start", "game", "conflicts", "role_change", "role", "reason", "fetched_at", "stale", "fallback")


PICK_KEYS = ("name", "player_id", "team", "opp", "market", "label", "line", "game", "date", "start", "source", "proj",
             "pick_side", "pick_p", "pick_tier", "pick_apps", "p_mkt", "verdict", "tier", "role_change", "fetched_at")


def build(payload, pick6_rows, now=None, review=None) -> dict:
    import datetime as _dt
    import sources
    lines, dk_drops = candidate_lines(payload, pick6_rows, now)
    rows, sel = finalize(score_lines(payload, lines))
    # freshness labels only, after every call is made: they never change a verdict, p or selection
    at = sources._ts(payload.get("sources_at")) or now or _dt.datetime.now(_dt.timezone.utc)
    sources.label_rows(rows, at, payload.get("sources"))
    rows.sort(key=lambda r: (not _is_take(r), -(r.get("p") or 0)))
    plays = [r for r in rows if _is_take(r)]
    # one pick per player and market from his pick'em lines (side, line, apps, tier): display and the leg log only
    pk = picks(rows)
    modeled = [r for r in rows if r["market"] in MODELED]
    with_p = [r for r in modeled if r.get("p_blend") is not None]
    # ambiguous / unmatched board rows the Pick6 pull dropped: listed for review, never in a play list
    ambiguous = [{"name": r.get("name"), "team": r.get("team"), "market": r.get("market"), "line": r.get("line"),
                  "reason": r.get("reason")} for r in (review or [])]
    pick = lambda xs: [{k: r.get(k) for k in PLAY_KEYS} for x in [xs] for r in x]
    return {"rows": rows, "plays": pick(plays), "near_miss": pick(sel["near"]),
            "review": pick(sel["review"]) + ambiguous,
            "picks": [{k: r.get(k) for k in PICK_KEYS} for r in pk if r["pick_tier"]],
            "counts": {"lines": len(rows), "modeled": len(modeled), "with_p": len(with_p),
                       "match_rate": round(len(with_p) / len(modeled), 4) if modeled else None,
                       "dk_dropped": dk_drops, "takes": len(plays),
                       "picks": len(pk), "leans": sum(r["pick_tier"] == "lean" for r in pk),
                       "checks": sum(r["pick_tier"] == "check" for r in pk),
                       "sog": {**sel["counts"], "needs_review": sel["counts"]["needs_review"] + sum(r["market"] == "sog" for r in ambiguous)}}}


# old names, kept for callers and tests
choose, conflicts = legacy_choose, legacy_conflicts
