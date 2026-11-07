"""Market-line freshness: when each source's lines were really pulled, and whether they are stale.

Reporting only. Nothing here changes a projection, probability, verdict or selection; it labels rows
and feeds the dashboard's source bar (Pick6 and DraftKings fetch times, fresh / fallback / error)."""
import datetime as dt

STALE_MIN = 20          # a source (and its rows) is STALE when its lines are older than this many minutes
SOURCE_KEY = {"Pick6": "pick6", "DraftKings": "dk", "PrizePicks": "pp"}


def _ts(x):
    if not x:
        return None
    try:
        t = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def age_min(fetched_at, now) -> float | None:
    t = _ts(fetched_at)
    return None if t is None else round((now - t).total_seconds() / 60, 1)


def info(status: str, fetched_at, now, error=None) -> dict:
    """One source's line for the dashboard: status fresh / fallback / error, the real fetch time, its age."""
    a = age_min(fetched_at, now)
    return {"status": status, "fetched_at": fetched_at, "age_min": a, "error": error or None,
            "stale": status == "error" or a is None or a > STALE_MIN}


def label_rows(rows, now, sources: dict | None = None):
    """Add fetched-at age, stale and fallback labels to board rows in place (labels only)."""
    sources = sources or {}
    for r in rows:
        src = sources.get(SOURCE_KEY.get(r.get("source"), ""), {})
        a = age_min(r.get("fetched_at"), now)
        r["age_min"] = a
        r["stale"] = a is None or a > STALE_MIN
        r["fallback"] = src.get("status") == "fallback"
    return rows
