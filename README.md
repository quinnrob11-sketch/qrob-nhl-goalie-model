# QRob NHL Goalie Saves Model

Projects saves for every starting goalie and compares the projection to the book line.
It ships as a single self-contained `index.html` that Vercel serves (see `vercel.json`),
rebuilt through the day by GitHub Actions.

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

### Starters and lines

Books only post a saves prop for the goalie they expect to start, so each build uses
posted lines as the starter feed. Priority per team: your own pick on the page, then a
**DraftKings** saves line (`model/odds.py`, via The Odds API; needs the `ODDS_API_KEY`
Actions secret), then a **PrizePicks** saves prop, then the roster default. The roster
default is the goalie on the team's current NHL roster (`api-web.nhle.com`) ranked by
recent starts, or by last season's starts before a team has played. It's marked
unconfirmed. The DraftKings pull costs one API request per game starting in the next 18
hours.

#### PrizePicks

The page also tries the PrizePicks board **live from your own browser** each time it opens
(and on "↻ Refresh PrizePicks"), because the build server gets a 403. If PrizePicks
refuses cross-site requests, the slate keeps the build's data and the note says so.



Each build pulls the PrizePicks NHL board (`model/prizepicks.py`). PrizePicks only
posts a **Goalie Saves** prop for the goalie it expects to start, so that goalie becomes
the slate's starter, and the saves line fills the Line column. If PrizePicks hasn't
posted a team's goalie yet, the starter falls back to the depth chart and is marked
unconfirmed. You can override the goalie or the line on any row.

## Game winners (`model/winners.py`)

Expected goals per side blend a **shot view** (shots the opponent's goalie faces from the
saves model x (1 - his shrunk save%), so the starting goalie matters) with a **rate view**
(team goal and expected-goal rates for and against). Win probability comes from independent
Poisson goals, with ties split for OT/shootout. The Game Winners tab turns it into fair odds
and an edge once you enter moneylines (the vig is removed when both sides are entered).

Fit on 2024-25, tested on 2025-26 (1,394 games): **55.3% accuracy** vs 51.9% for always-home,
log loss 0.683 vs 0.697. Calls at 65%+ confidence hit 71-74%. No historical moneylines are in
the public data, so this measures probability quality, not ROI.

## SOG props (`model/sog.py`)

`proj = shots/60 x expected TOI x (opponent shots allowed / league)^c x home`, with player
rates recency-weighted and shrunk to position averages. P(over) comes from a negative binomial
fitted for over-dispersion; whole-number lines treat X == line as a push.

- Stand-in lines (x.5 nearest a 50/50 over for the last-10 average), 2025-26: 64.6% at P(hit)
  of 55%+.
- **Real PrizePicks SOG lines, 2026 playoffs (475 props, `model/data/`): about 51-54%, roughly
  break-even.** Stand-in backtests badly overstate what real lines allow. That warning applies
  to the saves backtest too.

Lines come from your entry, then DraftKings (`player_shots_on_goal`, same Odds API request as
saves), then the PrizePicks board pulled live in the browser.

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
- Starters and saves lines: DraftKings via The Odds API (`ODDS_API_KEY` secret), the PrizePicks
  board (`api.prizepicks.com`, currently returns 403 to GitHub Actions), and current NHL rosters.

## Files

```
index.html               generated dashboard (served by Vercel)
model/data.py            download + shape box scores / play-by-play
model/engine.py          walk-forward ratings, projection, grading
model/backtest.py        fit on 2024-25, test on 2025-26
model/build_site.py      render index.html from template.html
model/odds.py            starting goalies + DraftKings saves/SOG lines (The Odds API)
model/winners.py         game-winner model + backtest
model/sog.py             skater SOG model + backtest (stand-in and real PrizePicks lines)
model/data/              real PrizePicks SOG lines, 2026 playoffs
model/prizepicks.py      starting goalies + saves lines from the PrizePicks board
model/template.html      dashboard template
model/output/            params.json, backtest.json, backtest_games.csv
.github/workflows/build.yml   rebuild 11am, 2pm, 4pm, 6pm, 7pm ET
```
