"""Rebuild the leg log's "check" and "cached" columns for the legs logged before the log kept them (2026-11-18).

From 2026-11-18 tracker.log_legs writes both with every leg: "check" when the board row was the player's pick as a
check (props_board.picks, pick_tier "check": a lean held until his spot is confirmed) and "cached" when its line or
price was one that build could not refresh (props_board._cached_reason). Legs logged before then carry neither, so
tracker.shown_split would still file a lean that became a check, or a call on a line its build could not refresh, as
dropped ("erased"), which the page's "Dropped since earlier" list never does.

Each leg row is its LAST pre-game snapshot, written by the build whose D.built_iso equals the row's `built`, and that
build's index.html carries the same board rows (D.board.rows: pick_tier from 2026-11-10 19:29 UTC, cached from
2026-11-08 14:47 UTC). This reads them once and writes model/data/legs_flags.json, which tracker._read_legs applies to
a row whose snapshot is the one recorded (same `built`); from then on log_legs keeps the flags itself.

    python model/backfill_flags.py [git ref, default origin/main]

Kept: "check" for any leg (a check on one app keeps the bet standing for every app), "cached" only for legs the page
showed as a call (shown_split reads it only on an app that showed the call). Needs the full history (the build's own
checkout is shallow and never runs this).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "data", "legs_flags.json")
BUILT = re.compile(r'"built_iso":\s*"([^"]+)"')


def _git(*args) -> str:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=True).stdout


def leg_key(date, player_id, market, line, source) -> str:
    """tracker._leg_key as legs_shown.json writes it: date|player|market|line|source."""
    return "|".join((str(date), str(player_id), str(market), str(float(line)), str(source)))


def _blobs(ref: str, path: str):
    """(sha, text of `path` at that commit) for every commit on `ref` that changed it, oldest first."""
    shas = _git("log", "--format=%H", "--reverse", ref, "--", path).split()
    p = subprocess.Popen(["git", "-C", ROOT, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha in shas:
            p.stdin.write(f"{sha}:{path}\n".encode())
            p.stdin.flush()
            head = p.stdout.readline().decode().split()
            if len(head) < 3 or head[1] != "blob":
                continue
            data = p.stdout.read(int(head[2]))
            p.stdout.read(1)                                  # the newline after each object
            yield sha, data.decode("utf-8", "replace")
    finally:
        p.stdin.close()
        p.wait()


def _data(page: str) -> dict | None:
    """The page's D object (the `const D = {...};` line)."""
    for line in page.split("\n"):
        if line.startswith("const D = "):
            try:
                return json.loads(line[len("const D = "):].rstrip().rstrip(";"))
            except ValueError:
                return None
    return None


def flags_of(legs: list[dict], pages) -> dict:
    """{leg key: {"built", "check"?, "cached"?}} for the legs whose last snapshot a page in `pages` (an iterable of
    page texts) built and flagged."""
    want = {}
    for r in legs:
        try:
            k = leg_key(r["date"], r["player_id"], r["market"], r["line"], r["source"])
        except (KeyError, ValueError, TypeError):
            continue
        want.setdefault(str(r.get("built") or ""), {})[k] = (r.get("shown") or "") in ("play", "lean")
    out = {}
    for page in pages:
        m = BUILT.search(page)
        if not m or m.group(1) not in want:
            continue
        D = _data(page)
        if not D or D.get("built_iso") != m.group(1):
            continue
        need = want[m.group(1)]
        for b in (D.get("board") or {}).get("rows") or []:
            if b.get("player_id") is None or b.get("side") is None or b.get("line") is None:
                continue
            try:
                k = leg_key(b["date"], b["player_id"], b["market"], b["line"], b["source"])
            except (KeyError, ValueError, TypeError):
                continue
            if k not in need:
                continue
            f = {}
            if b.get("pick_tier") == "check":
                f["check"] = 1
            if b.get("cached") and need[k]:
                f["cached"] = 1
            if f:
                out[k] = {"built": m.group(1), **f}
    return out


def main(ref: str = "origin/main"):
    sys.path.insert(0, HERE)
    import tracker
    legs = tracker._fill_shown(list(csv.DictReader(io.StringIO(_git("show", f"{ref}:model/data/legs.csv")))))
    legs = [r for r in legs if not (str(r.get("check") or "").strip() or str(r.get("cached") or "").strip())]
    n = 0

    def pages():
        nonlocal n
        for i, (sha, text) in enumerate(_blobs(ref, "index.html")):
            n = i + 1
            if i % 100 == 0:
                print(f"  {i} builds read", file=sys.stderr, flush=True)
            yield text

    out = flags_of(legs, pages())
    with open(OUT, "w") as f:
        json.dump(dict(sorted(out.items())), f, indent=0, separators=(",", ":"))
        f.write("\n")
    print(f"{len(legs)} legs without flags, {n} builds read: {sum('check' in v for v in out.values())} checks, "
          f"{sum('cached' in v for v in out.values())} cached calls -> {OUT}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
