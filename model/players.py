"""Player matching: a (name, team, game) from any board -> one NHL playerId, or UNMATCHED.

Boards spell players many ways ("A. Lee", "Anders Lee", "Stuetzle", "Stützle", "J.J. Peterka",
"JJ Peterka", "Mitch Marner", "Mitchell Marner"). Matching is always scoped to a team: the row's
own team when it has one, otherwise the two teams in its game. It never falls back to the whole
league, so "A. Lee UTA" can only be Utah's Lee, never the Kings' Andre Lee.

Within the team(s), a roster player matches when
  * his last name equals the row's trailing name tokens (accents, punctuation, spacing and German
    transliteration ignored: Stützle = Stutzle = Stuetzle), and
  * the leading tokens are compatible with his first name: equal, an initial of it, one a prefix of
    the other (Mitch / Mitchell, Alex / Alexander), or a known nickname (Mike / Michael); an empty
    first name (last name only) is compatible.
If exactly one player matches he is the match. If several do, an optional position (F / D / G)
narrows them. Zero or 2+ -> UNMATCHED with the reason, and the row is excluded from plays.

Rosters: api-web.nhle.com/v1/roster/{team}/current every build (full first names, live teams after
trades). A team whose roster can't be fetched falls back to the last saved roster
(model/data/rosters.json) and then to the players in its recent box scores (initials only).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAVED = os.path.join(HERE, "data", "rosters.json")
ROSTER_API = "https://api-web.nhle.com/v1/roster/{team}/current"

# board team codes that differ from the NHL's
TEAM_FIX = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "MON": "MTL", "WAS": "WSH", "CLB": "CBJ",
            "NAS": "NSH", "UTAH": "UTA", "VEG": "VGK", "CAL": "CGY", "LV": "VGK", "ARI": "UTA", "UTH": "UTA"}
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}
NICK = [{"mike", "michael", "mikey"}, {"jake", "jacob", "jakob"}, {"bill", "william", "will", "willy"},
        {"bob", "robert", "rob", "bobby"}, {"tony", "anthony"}, {"zach", "zack", "zachary", "zak"},
        {"nick", "nicholas", "nicolas", "nik", "niko", "nikolai"}, {"alex", "alexander", "alexandre", "aleksander", "sasha"},
        {"matt", "matthew", "mathew", "matthias", "mat"}, {"josh", "joshua"}, {"cam", "cameron"},
        {"tim", "timothy"}, {"tom", "thomas", "tommy"}, {"dan", "daniel", "danny"}, {"chris", "christopher"},
        {"jon", "jonathan", "john", "johnny"}, {"joe", "joseph", "joey"}, {"ben", "benjamin"},
        {"sam", "samuel"}, {"max", "maxim", "maxime", "maximilian"}, {"jt", "jt"}, {"jj", "jj"},
        {"mitch", "mitchell"}, {"pat", "patrick"}, {"greg", "gregory"}, {"fred", "frederik", "frederick"},
        {"vince", "vincent"}, {"phil", "phillip", "philip"}, {"ed", "edward", "eddie"}, {"andy", "andrew", "drew"},
        {"steve", "steven", "stephen"}, {"jeff", "jeffrey"}, {"ken", "kenneth"}, {"evgeny", "evgeni", "yevgeni"},
        {"dmitri", "dmitry"}, {"nikita", "nikita"}, {"artemi", "artemiy"}, {"ilya", "ilia"}]
_NICK = {n: i for i, grp in enumerate(NICK) for n in grp}
GERMAN = {"ü": "ue", "ö": "oe", "ä": "ae", "Ü": "Ue", "Ö": "Oe", "Ä": "Ae", "ß": "ss"}

status = "not run"


def fold(s: str) -> str:
    """Lowercase ASCII, punctuation to spaces, initials split ("J.J." -> "j j")."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’`]", " ", s)
    s = re.sub(r"[^a-z ]", " ", s.replace("-", " "))
    return " ".join(s.split())


def tokens(name: str) -> list[str]:
    t = [w for w in fold(name).split() if w not in SUFFIX]
    # leading run of single letters is one set of initials: "j j peterka" -> "jj peterka"
    i = 0
    while i < len(t) - 1 and len(t[i]) == 1:
        i += 1
    return (["".join(t[:i])] + t[i:]) if i > 1 else t


def last_keys(last: str) -> set[str]:
    """Space-free keys for a roster last name, with and without German transliteration."""
    raw = str(last or "")
    de = "".join(GERMAN.get(c, c) for c in raw)
    return {fold(raw).replace(" ", ""), fold(de).replace(" ", "")} - {""}


def first_ok(given: str, first: str) -> bool:
    """Is the board's first-name part compatible with the roster first name?"""
    if not given:
        return True
    if not first:
        return True
    g, f = given.replace(" ", ""), fold(first).replace(" ", "")
    if g == f:
        return True
    if len(g) == 1 or len(f) == 1:              # an initial on either side
        return g[0] == f[0]
    if len(g) <= 2 and len(f) > 2:              # "jj" vs "john jason": initials of a two-part first name
        parts = fold(first).split()
        if len(parts) == len(g) and all(p[0] == c for p, c in zip(parts, g)):
            return True
    if min(len(g), len(f)) >= 3 and (g.startswith(f) or f.startswith(g)):
        return True
    return g in _NICK and _NICK.get(g) == _NICK.get(f)


def team_code(t) -> str:
    t = str(t or "").upper().strip()
    return TEAM_FIX.get(t, t)


def pos_group(p) -> str:
    p = str(p or "").upper()
    return "G" if p.startswith("G") else "D" if p.startswith("D") else "F" if p else ""


class Rosters:
    """{team: [{"id", "first", "last", "name", "pos"}]}, plus where each team's roster came from."""

    def __init__(self, teams: dict | None = None, source: dict | None = None):
        self.teams = {team_code(k): v for k, v in (teams or {}).items()}
        self.source = source or {}
        self.by_id = {p["id"]: dict(p, team=t) for t, ps in self.teams.items() for p in ps}

    def candidates(self, name: str, teams, pos=None) -> list[dict]:
        tk = tokens(name)
        if not tk:
            return []
        out = []
        for t in teams:
            for p in self.teams.get(team_code(t), []):
                keys = p.get("_keys") or last_keys(p["last"])
                for k in range(1, len(tk) + 1):
                    if "".join(tk[-k:]) in keys and first_ok(" ".join(tk[:-k]), p.get("first", "")):
                        out.append(dict(p, team=team_code(t)))
                        break
        if len(out) > 1 and pos_group(pos):
            narrowed = [p for p in out if pos_group(p.get("pos")) == pos_group(pos)]
            out = narrowed or out
        return out

    def match(self, name: str, team=None, game=None, pos=None) -> dict:
        """{"player_id", "team", "status": "MATCHED" | "UNMATCHED", "reason"}. `game` is the two team
        codes; with no team the search covers both. Never matches across the whole league."""
        teams = [team_code(team)] if team else [team_code(t) for t in (game or []) if t]
        if not teams:
            return {"player_id": None, "team": None, "status": "UNMATCHED", "reason": "no team or game"}
        c = self.candidates(name, teams, pos)
        if len(c) == 1:
            return {"player_id": int(c[0]["id"]), "team": c[0]["team"], "status": "MATCHED", "reason": "",
                    "full": c[0].get("name"), "pos": c[0].get("pos")}
        why = f"no {'/'.join(teams)} player named {name}" if not c else \
            f"{len(c)} {'/'.join(teams)} players match {name}"
        return {"player_id": None, "team": teams[0] if len(teams) == 1 else None, "status": "UNMATCHED", "reason": why}

    def to_json(self) -> dict:
        return {t: [{k: p[k] for k in ("id", "first", "last", "pos")} for p in ps] for t, ps in self.teams.items()}


def _player(pid, first, last, pos) -> dict:
    first, last = (first or "").strip(), (last or "").strip()
    name = f"{first} {last}".strip()
    return {"id": int(pid), "first": first, "last": last, "name": name, "pos": pos, "_keys": last_keys(last)}


def parse_roster(js: dict) -> list[dict]:
    out = []
    for grp, pos in (("forwards", "F"), ("defensemen", "D"), ("goalies", "G")):
        for p in js.get(grp, []) or []:
            out.append(_player(p["id"], (p.get("firstName") or {}).get("default", ""),
                               (p.get("lastName") or {}).get("default", ""), pos))
    return out


def from_box(skaters, goalies=None, season=None) -> dict:
    """Fallback rosters from box scores: each player on the team of his latest game ("A. Lee" names)."""
    import pandas as pd
    frames = []
    for d, pos_col in ((skaters, "position"), (goalies, None)):
        if d is None or not len(d):
            continue
        x = d if season is None or "season" not in d else d[d.season == season]
        x = x.sort_values("game_date").drop_duplicates("player_id", keep="last")
        frames.append(pd.DataFrame({"id": x.player_id.astype(int), "name": x.player_name, "team": x.team_abbrev,
                                    "pos": [pos_group(v) for v in x[pos_col]] if pos_col else "G"}))
    out = {}
    if not frames:
        return out
    for r in pd.concat(frames).drop_duplicates("id", keep="last").itertuples():
        parts = str(r.name).split(" ", 1)
        first, last = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
        out.setdefault(team_code(r.team), []).append(_player(r.id, first.rstrip("."), last, r.pos))
    return out


def fetch(teams, box_fallback: dict | None = None, timeout: int = 30) -> Rosters:
    """Live rosters for `teams`; per team, a failed fetch falls back to the saved roster, then to box
    scores. Writes the live ones back to model/data/rosters.json."""
    global status
    saved = json.load(open(SAVED)) if os.path.exists(SAVED) else {"teams": {}, "at": {}}
    teams_out, source, live = {}, {}, 0
    for t in sorted({team_code(x) for x in teams}):
        try:
            req = urllib.request.Request(ROSTER_API.format(team=t), headers={"User-Agent": "qrob-goalie-model"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ps = parse_roster(json.load(r))
            if not ps:
                raise ValueError("empty roster")
            teams_out[t], source[t], live = ps, "live", live + 1
            saved["teams"][t] = [{k: p[k] for k in ("id", "first", "last", "pos")} for p in ps]
            saved["at"][t] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        except Exception as e:
            if t in saved["teams"]:
                teams_out[t] = [_player(p["id"], p["first"], p["last"], p["pos"]) for p in saved["teams"][t]]
                source[t] = f"saved {saved['at'].get(t, '')[:10]}"
            elif box_fallback and t in box_fallback:
                teams_out[t], source[t] = box_fallback[t], "box scores"
            else:
                source[t] = f"missing ({e})"
    if live:
        os.makedirs(os.path.dirname(SAVED), exist_ok=True)
        with open(SAVED, "w") as f:
            json.dump(saved, f, separators=(",", ":"), sort_keys=True)
    status = f"{live} live, {len(teams_out) - live} fallback" if teams_out else "unavailable"
    print(f"  [rosters] {status}")
    return Rosters(teams_out, source)


def match_rows(rows: list[dict], R: Rosters, team_key="team", game_key="teams", pos_key="pos") -> dict:
    """Attach player_id / match status to every row in place. Returns {"matched", "unmatched", "reasons"}."""
    n_ok, bad = 0, []
    for r in rows:
        m = R.match(r.get("name", ""), r.get(team_key), r.get(game_key), r.get(pos_key))
        r["player_id"], r["match"] = m["player_id"], m["status"]
        if m["status"] == "MATCHED":
            r["team"] = m["team"]
            n_ok += 1
        else:
            r["match_reason"] = m["reason"]
            bad.append(f"{r.get('name')} ({r.get(team_key) or '/'.join(r.get(game_key) or [])}): {m['reason']}")
    return {"matched": n_ok, "unmatched": len(bad), "reasons": bad[:50]}
