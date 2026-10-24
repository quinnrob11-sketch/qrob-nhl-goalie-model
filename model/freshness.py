"""Fail the build run when the box-score data is stale.

    python model/freshness.py

Reads the payload baked into index.html and exits 1 when `data_through` (latest game in the
fastRhockey box scores) is more than one day behind `latest_final` (latest finished game on the
NHL schedule). The page is still committed first, so the site updates and shows its stale banner,
but the red run makes the problem visible.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(payload: dict, max_days: int = 1) -> tuple[bool, str]:
    through, final = payload.get("data_through"), payload.get("latest_final")
    if not final:
        return True, f"data through {through}; latest finished game unknown (schedule unreachable)"
    lag = (dt.date.fromisoformat(final[:10]) - dt.date.fromisoformat(str(through)[:10])).days
    msg = f"data through {through}, latest finished game {final}: {lag} day(s) behind"
    return lag <= max_days, msg


def main():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    i = html.index("const D = ") + len("const D = ")
    payload, _ = json.JSONDecoder().raw_decode(html[i:])
    ok, msg = check(payload)
    print(("OK: " if ok else "STALE: ") + msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
