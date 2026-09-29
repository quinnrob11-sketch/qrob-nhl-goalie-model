# QRob NHL Goalie Saves Model

Projects saves for every starting goalie and compares the projection to the book line.
It ships as a single self-contained `index.html` that Vercel serves (see `vercel.json`),
rebuilt twice a day by GitHub Actions.

## The model

```
exp_SA          = LG × (TeamSA / LG)^a × (OppSF / LG)^b × home × playoff × b2b
Projected saves = exp_SA × time-in-net share × save%
Edge            = Projected saves − Line
```

| Piece | What it is |
|---|---|
| `LG` | League shots on goal per team-game (recency weighted) |
| `TeamSA` | Shots on goal the goalie's team allows per game, recency weighted and shrunk to `LG` |
| `OppSF` | Shots on goal the opponent generates per game, same treatment |
| `a`, `b` | Fitted weights. They replace the old fixed 60/40 goalie-SA / opponent-SF blend |
| time-in-net share | Pull and injury risk. Replaces the flat ~12% empty-net haircut |
| save% | Goalie SV% shrunk toward .900 |
| home / playoff / b2b | Multipliers measured from 2024-25 shot volume |

Every projection uses only games played **before** that date (walk-forward), so the
backtest has no lookahead. Team rates carry part of last season's weight into a new
season, which is how the model handles opening night of 2026-27.

### Bet rules (the markers)

- Edge under **1.0** save: PASS. **1.5+**: standard play. **2.5+**: HIGH confidence.
- Green = OVER, red = UNDER.
- **Confirm the starter** before locking. Each projection is for the goalie shown.
- Overtime inflates raw saves. In tight, high-event games, lean OVER on close calls.

## Backtest

`python model/backtest.py` fits parameters on **2024-25 only**, then grades **2025-26
out-of-sample**. Results are in `model/output/backtest.json` and `backtest_games.csv`,
and on the Backtest tab of the dashboard.

**Caveat:** historical sportsbook saves lines aren't in any public dataset, so each start
is graded against a **proxy line**: `floor(last-10-start average) + 0.5`. Real DK and
PrizePicks lines are sharper, so the proxy hit rate is a ceiling. The dashboard's
**Tracker** tab logs picks at real lines and grades them from box scores. That is the
number to judge the 65% target on.

## Running it

```bash
pip install -r requirements.txt
python model/backtest.py --no-fit   # re-grade with the saved params (drop --no-fit to refit)
python model/build_site.py          # writes index.html
python -m http.server 8080          # then open http://localhost:8080
```

Or just open `index.html` directly. Everything is inlined.

## Data

- Box scores and play-by-play: [`sportsdataverse/fastRhockey-nhl-data`](https://github.com/sportsdataverse/fastRhockey-nhl-data),
  rebuilt daily from the NHL API. Cached in `model/cache/` (gitignored).
- Upcoming schedule: `api-web.nhle.com/v1/schedule`, fetched at build time. If it's
  unreachable, the slate is empty and the matchup builder still works.

## Files

```
index.html               generated dashboard (served by Vercel)
model/data.py            download + shape box scores / play-by-play
model/engine.py          walk-forward ratings, projection, grading
model/backtest.py        fit on 2024-25, test on 2025-26
model/build_site.py      render index.html from template.html
model/template.html      dashboard template
model/output/            params.json, backtest.json, backtest_games.csv
.github/workflows/build.yml   rebuild at 11am and 5:30pm ET
```
