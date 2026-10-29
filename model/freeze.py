"""Model freeze: params.json carries `frozen_at` and `frozen_hash`, a hash of every fitted model
setting (params.json, saves_dist.json, sog_params.json, points_params.json, winners_params.json) plus the decision /
calibration settings in pricing.config(). calibration.json itself is not hashed: it is refit from
graded lines on every build by design.

    python model/freeze.py --check [--base <git sha>]   # CI: fail on an unannounced change
    python model/freeze.py --update                     # re-freeze after an intended change

--check fails when the stored hash doesn't match the files, or when the model settings differ from
<base> and no commit message in <base>..HEAD contains "--unfreeze" (messages are read from git, or
from the COMMIT_MESSAGES environment variable when set).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
FILES = ("params.json", "saves_dist.json", "sog_params.json", "points_params.json", "winners_params.json")
SKIP = {"frozen_at", "frozen_hash", "fit"}       # bookkeeping, not model settings
TOKEN = "--unfreeze"


def settings(read=lambda name: json.load(open(os.path.join(OUT, name)))) -> dict:
    sys.path.insert(0, HERE)
    import pricing
    out = {name: {k: v for k, v in read(name).items() if k not in SKIP} for name in FILES}
    out["pricing"] = pricing.config()
    return out


def digest(s: dict) -> str:
    return hashlib.sha256(json.dumps(s, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _short(sha: str) -> str:
    return sha[:10] if len(sha) == 40 else sha


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout


def base_settings(base: str) -> dict | None:
    """Model settings at another commit (pricing.config read from that commit's pricing.py)."""
    try:
        def read(name):
            try:
                return json.loads(_git("show", f"{base}:model/output/{name}"))
            except subprocess.CalledProcessError:   # a file the base didn't have yet counts as a change
                return {}
        files = {name: {k: v for k, v in read(name).items() if k not in SKIP} for name in FILES}
        ns = {}
        exec(_git("show", f"{base}:model/pricing.py"), ns)
        files["pricing"] = ns["config"]()
        return files
    except Exception as e:  # base too old to have these files
        print(f"  [freeze] can't read model settings at {base}: {e}")
        return None


def check(base: str | None) -> tuple[bool, str]:
    stored = json.load(open(os.path.join(OUT, "params.json"))).get("frozen_hash")
    now = digest(settings())
    if stored != now:
        return False, (f"params.json frozen_hash {stored} doesn't match the model settings ({now}). "
                       f"If the change is intended, run `python model/freeze.py --update` and say {TOKEN} in the commit message.")
    if base:
        prev = base_settings(base)
        if prev is not None and digest(prev) != now:
            msgs = os.environ.get("COMMIT_MESSAGES")
            if msgs is None:
                msgs = _git("log", "--format=%B", f"{base}..HEAD")
            if TOKEN not in msgs:
                changed = sorted(k for k in prev if prev[k] != settings()[k])
                return False, f"model settings changed since {_short(base)} ({', '.join(changed)}) without {TOKEN} in a commit message"
            return True, f"model settings changed since {_short(base)}, unfrozen by commit message"
    return True, f"model settings frozen (hash {now})"


def update():
    path = os.path.join(OUT, "params.json")
    p = json.load(open(path))
    p["frozen_at"] = dt.date.today().isoformat()
    p["frozen_hash"] = digest(settings())
    json.dump(p, open(path, "w"), indent=2)
    print(f"frozen_at {p['frozen_at']}, frozen_hash {p['frozen_hash']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--base")
    a = ap.parse_args()
    if a.update:
        update()
        return
    ok, msg = check(a.base)
    print(("OK: " if ok else "FAIL: ") + msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
