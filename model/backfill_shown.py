"""Rebuild "the strongest call the page ever showed" for every logged leg from the repository's own history.

Until 2026-11-16 the leg log (model/data/legs.csv) kept only each leg's LAST pre-game snapshot. A leg the page showed
as a lean at noon whose flag was gone by puck drop was logged as "not a lean", so the lean record counted only the
survivors (50 of 70) and missed the ones that were dropped (7 of 27). Every build commits legs.csv, so the history
holds every snapshot: this walks it once and writes model/data/legs_shown.json, which tracker._read_legs applies to
rows that carry no "shown" call yet. From then on tracker.log_legs keeps the call itself.

    python model/backfill_shown.py [git ref, default origin/main]

For each leg (date, player, market, line, source): the first build that showed it as a play (verdict TAKE ...) and
the first that showed it as a lean (lean = 1). A play outranks a lean. Stored with that build's time, side, chance
and multiplier. Needs a full clone (the build's own checkout is shallow and never runs this).
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "data", "legs_shown.json")
RANK = {"": 0, "lean": 1, "play": 2}


def _git(*args) -> str:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=True).stdout


def main(ref: str = "origin/main"):
    shas = _git("log", "--format=%H", "--reverse", ref, "--", "model/data/legs.csv").split()
    seen_built, shown = set(), {}
    for i, sha in enumerate(shas):
        try:
            raw = _git("show", f"{sha}:model/data/legs.csv")
        except subprocess.CalledProcessError:
            continue
        rows = list(csv.DictReader(io.StringIO(raw)))
        new = {r.get("built") for r in rows} - seen_built      # this commit's own build(s): the legs shown then
        for r in rows:
            if r.get("built") not in new:
                continue
            call = "play" if str(r.get("verdict") or "").startswith("TAKE") else ("lean" if str(r.get("lean") or "").strip() in ("1", "1.0") else "")
            if not call:
                continue
            try:
                k = "|".join((r["date"], str(r["player_id"]), r["market"], str(float(r["line"])), r["source"]))
            except (KeyError, ValueError):
                continue
            if RANK[call] > RANK[shown.get(k, {}).get("shown", "")]:
                shown[k] = {"shown": call, "shown_at": r.get("built") or "", "shown_side": r.get("side") or "",
                            "shown_p": r.get("p") or "", "shown_mult": r.get("mult") or ""}
        seen_built |= new
        if i % 100 == 0:
            print(f"  {i}/{len(shas)} commits, {len(shown)} calls", file=sys.stderr, flush=True)
    with open(OUT, "w") as f:
        json.dump(dict(sorted(shown.items())), f, indent=0, separators=(",", ":"))
    n = {c: sum(v["shown"] == c for v in shown.values()) for c in ("play", "lean")}
    print(f"wrote {OUT}: {n} from {len(shas)} commits through {ref}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
