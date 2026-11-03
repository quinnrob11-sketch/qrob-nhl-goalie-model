"""Writes pick6_synthetic.html: a Pick6-style page whose board is embedded as React Router / Remix
single-fetch loader data (turbo-stream chunks passed to streamController.enqueue).

SYNTHETIC: the field names follow what pick6.py looks for, not a captured page. Save the real page
(pick6.draftkings.com/?sport=NHL, File > Save Page As, "HTML only") as model/tests/fixtures/pick6.html
and test_pick6 checks it too.

    python model/tests/fixtures/make_pick6_fixture.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def flatten(root):
    """Minimal turbo-stream encoder: objects -> {"_<key idx>": value idx}, arrays -> [idx...]."""
    vals, memo = [], {}

    def enc(v):
        if v is None:
            return -5
        key = None if isinstance(v, (dict, list)) else (type(v).__name__, json.dumps(v))
        if key and key in memo:
            return memo[key]
        i = len(vals)
        vals.append(None)
        if key:
            memo[key] = i
        if isinstance(v, dict):
            vals[i] = {f"_{enc(k)}": enc(x) for k, x in v.items()}
        elif isinstance(v, list):
            vals[i] = [enc(x) for x in v]
        else:
            vals[i] = v
        return i

    enc(root)
    return json.dumps(vals, separators=(",", ":"))


def pickable(pid, name, team, pos, market, line, mo, mu, event, start):
    p = {"pickableId": pid, "marketName": market, "lineValue": line, "eventId": event, "startTime": start,
         "pickableEntities": [{"displayName": name, "position": pos,
                               "pickableCompetitors": [{"team": {"abbreviation": team}}]}]}
    if mo is not None:
        p["moreMultiplier"] = mo
    if mu is not None:
        p["lessMultiplier"] = mu
    return p


TOR_FLA, UTA_LAK = ("ev-1", "2026-11-04T00:00:00Z"), ("ev-2", "2026-11-04T01:30:00Z")
PICKS = [
    pickable(1, "Mitch Marner", "TOR", "RW", "Shots on Goal", 2.5, 1.0, 1.0, *TOR_FLA),
    pickable(2, "Mitch Marner", "TOR", "RW", "Shots on Goal", 3.5, 1.25, 0.8, *TOR_FLA),        # alt line
    pickable(3, "Matthew Tkachuk", "FLA", "LW", "Shots on Goal", 3.5, 1.0, 1.0, *TOR_FLA),
    pickable(4, "Brady Tkachuk", "FLA", "LW", "Shots on Goal", 2.5, 0.9, 1.1, *TOR_FLA),
    pickable(5, "Anders Lee", "UTA", "LW", "Shots on Goal", 1.5, 1.0, 1.0, *UTA_LAK),
    pickable(6, "Andre Lee", "LAK", "LW", "Shots on Goal", 1.5, 1.0, 1.0, *UTA_LAK),
    pickable(7, "Mitch Marner", "TOR", "RW", "Points", 0.5, 1.0, 1.0, *TOR_FLA),
    pickable(8, "Matthew Tkachuk", "FLA", "LW", "Points", 0.5, 0.85, 1.15, *TOR_FLA),
    pickable(9, "Brady Tkachuk", "FLA", "LW", "Blocked Shots", 0.5, 1.0, 1.0, *TOR_FLA),
    pickable(10, "Joseph Woll", "TOR", "G", "Saves", 26.5, 1.0, 1.0, *TOR_FLA),
    pickable(11, "Nobody Special", "TOR", "C", "Shots on Goal", 1.5, 1.0, 1.0, *TOR_FLA),        # unmatched
    pickable(12, "Jake Trouba", "NYR", "D", "Shots on Goal", 1.5, 1.0, 1.0, "ev-9", "2026-11-04T00:00:00Z"),  # not on the slate
    pickable(13, "Anders Lee", "UTA", "LW", "Points", 0.5, None, None, *UTA_LAK),                # no multipliers
]
DATA = {"root": {"loaderData": {"routes/_homeShared": {"sport": "NHL",
                                                      "pickGroups": [{"name": "All", "pickables": PICKS}]}}}}


def page():
    stream = flatten(DATA) + "\n"
    half = len(stream) // 2
    js = "".join(f"window.__reactRouterContext.streamController.enqueue({json.dumps(c)});"
                 for c in (stream[:half], stream[half:]))
    return ("<!DOCTYPE html><html><head><title>DraftKings Pick6</title></head><body><div id=\"root\"></div>"
            "<script>window.__reactRouterContext = {\"basename\":\"/\",\"future\":{},\"isSpaMode\":false};"
            "window.__reactRouterContext.stream = new ReadableStream({start(c){window.__reactRouterContext.streamController = c;}});</script>"
            f"<script>{js}</script></body></html>")


if __name__ == "__main__":
    open(os.path.join(HERE, "pick6_synthetic.html"), "w").write(page())
    print("wrote pick6_synthetic.html")
