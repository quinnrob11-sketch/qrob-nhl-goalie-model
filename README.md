# QRob NHL Goalie Saves Model

Projects saves for every starting goalie and compares the projection to the book line.
It ships as a single self-contained `index.html` that Vercel serves (see `vercel.json`),
rebuilt through the day by GitHub Actions.

## The model

```
exp_SA          = LG × (TeamSA / LG)^a × (OppSF / LG)^b × home × playoff × b2b × opp_b2b
                  × exp(−gs × logit(win prob))                      game script
Projected saves = exp_SA × time-in-net share × save%
Spread (sd)     = sqrt(sv²(μ + μ²/K) + μ·sv(1−sv)),  μ = exp_SA × share,  floor 6.0
P(over line)    = Normal(projected saves, spread), then calibrated on graded real lines
Play            = calibrated P(side) > break-even of the price + 2%
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
| opp_b2b | The opponent played last night: tired teams generate about 3% fewer shots (0.968, fit on 2024-25; holds in every season since) |
| game script | Win probability from the no-vig DraftKings moneyline (or the game-winner model when none is posted). Heavier underdogs face more shots. `gs` = 0.015, fitted on 2024-25 and 2025-26 (`model/saves_dist.py`, `output/saves_dist.json`) |
| spread | Shots against vary like a negative binomial (K = 30, max likelihood on 2024-25) and each shot is saved with probability sv. Heavy underdogs get a spread near 8 saves, heavy favourites near 5.6; the old fixed 6.9 was too tight for underdogs and too loose for favourites. Better log-likelihood than the fixed spread on 2025-26 and 2026-27 |

Every projection uses only games played **before** that date (walk-forward), so the
backtest has no lookahead. Team rates carry part of last season's weight into a new
season, which is how the model handles opening night of 2026-27.

### Bet rules (price-aware, from 10/23)

Saves edge alone did not win on real lines (old HIGH tier: 46% and −15% ROI this season; PASS
was the best tier), so plays are now decided by price (`model/pricing.py`):

- **Calibrate first.** Each market's raw P(over) is recalibrated on every graded real line
  (`model/calibrate.py`, refit on every build). The model was overconfident: the fitted slope is
  about 0.33 for saves and 0.67 for SOG (1.0 would mean no change).
- **Play only when calibrated P > break-even + 2%.** Sportsbook break-even is the implied
  probability of that side's price, so a −170 under needs about 63% + 2%. DFS (Pick6 /
  PrizePicks) break-even is per leg: payout^(−1/legs) ÷ the side's multiplier. The default entry
  is 2 legs at 3x (57.7% per leg; change it in the page header), and sub-1x sides never qualify
  unless you allow them.
- **EV% decides the tier**: LOW 2–5%, MED 5–8%, HIGH 8%+. Tiers are shown only while graded
  history has HIGH > MED > LOW on both hit % and ROI with 30+ plays each; otherwise every play is
  capped at LOW. Both markets are capped right now.
- **Confirmed starters only.** A goalie counts as confirmed when a DraftKings line or PrizePicks
  prop is posted for him or you pick him on the page. Roster defaults are never plays.
- Green = OVER, red = UNDER. Rows sort by EV.

### Results tracking (`model/tracker.py`, **Results** tab)

Fully automatic once it's merged:

1. **Before games:** every build freezes the model's calls for games in the next 30 hours into
   `model/data/calls/<date>.json`: projected starters and saves, every skater's SOG projection, and
   each game's win probability, plus any DraftKings or PrizePicks line the build saw with its price
   and moneyline, and the price-aware decision (calibrated P, EV, tier). A game that has started is
   never changed.
2. **After games:** every build (first one 8:30am ET) grades finished games from the box scores:
   - every real line, appended to `real_line_log.csv` with HIT/MISS at the pick-time line and price;
     units and ROI by market, tier, side and book; game-winner picks in units at the DraftKings
     moneyline; DFS (Pick6 / PrizePicks) lines as a market-basis record against per-leg break-even;
   - model accuracy that needs no line: winner picks, starter calls, saves and SOG error;
   - a reason for each miss: wrong starter, shots against far from expected, goalie pulled, OT,
     or a big TOI change.
3. **Pick6 boards:** send the screenshots or a screen recording and they get logged in the CSV.
   The grader fills in the results the next morning.

A **play** from 10/23 on is price-aware (see Bet rules); earlier rows keep the rule they were
picked under (saves 1.5+ edge, SOG 55%+, never a side under 1x). Every table uses one de-duplicated
set of lines, so tiers, sides, books and nights add up to each market's total.
When a prop is on more than one book it counts once (Pick6 first, then PrizePicks, then DraftKings). The 10/13 board logged as "Players" was the PrizePicks app (its "Players" toggle) and is relabeled PrizePicks.

### Real-line record (`model/data/real_line_log.csv`)

Every call is logged with the actual book line and graded from box scores. This is the
number the 65% target is judged on, not the stand-in backtests. Through 9/30:

| Market | Record | Note |
|---|---|---|
| Saves plays (edge 1.0+) | 4-3 | MED 3-0, LOW 1-2, HIGH 0-1 |
| Saves leans under 1.0 (PASS) | 4-5 | about a coin flip, which is why they're passes |
| SOG, Pick6 top-5 at 1x+ | 8-2 | boosted side (MacKinnon 1.1x) missed |
| Game winners, 65%+ calls | 2-2 | backtest says 71-74% long run |

Two days is far too small to retune on. The misses came from game-script outliers (CAR held
to 15 shots in a 1-0 OT game, PIT 38 shots in a 7-0 win), not a broken model: average error
over these 16 starts was 4.2 saves, better than the model's usual 5.3.

**Current rules:** play saves only at 1.5+ (MED/HIGH); don't pair two LESS legs from the same
game; skip Pick6's boosted sides; on a back-to-back, assume the backup starts until confirmed.

### October review (real lines, 9/29–10/20)

- **Shot projections are as accurate as they were on opening week:** about 5.0 saves average miss
  this season, compared with 5.3 historically. The slide in hit rate came from the betting side, not
  from team data the model is missing.
- **Books shade saves lines high.** Goalies finish about 0.9 saves under the line, so blind unders
  hit 56%. Model unders hit 57–60%; saves overs at 1.5+ are 6-6 and 7-12 lifetime. Treat saves
  overs with caution.
- **Overtime hurts unders.** Plays in games that reached OT went 6-8; regulation games went 33-23.
- **Opponent back-to-backs were missing.** Tired opponents shoot about 3% less in every season
  checked (2023-24 through now). This is now in the model, and on this season's real lines it moves
  saves plays from 39-31 to 43-31.
- **Checked and not changed** (no consistent gain out of sample): shot attempts (Corsi), arena
  scorer bias, faster league averaging, team-rate recency and carry-over, and a retuned SOG model.
  The SOG retune fixed the under-projection of star shooters but did not win more real lines.
- **SOG 3.5 lines are 49% (n=129), the worst line size;** 1.5 and 2.5 lines are about 57%.

### Starters and lines

Books only post a saves prop for the goalie they expect to start, so each build uses
posted lines as the starter feed. Priority per team: your own pick on the page, then a
**DraftKings** saves line (`model/odds.py`, via The Odds API; needs the `ODDS_API_KEY`
Actions secret), then a **PrizePicks** saves prop, then the roster default. The roster
default is the goalie on the team's current NHL roster (`api-web.nhle.com`) ranked by
recent starts, or by last season's starts before a team has played. It's marked
unconfirmed. On a back-to-back, the default switches to the goalie who didn't start the night
before. The DraftKings pull costs one API request per game starting in the next 18
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

**Real lines (the one that counts).** Every DraftKings saves and SOG line since 10/1 is stored
with both sides' pre-game prices (`model/data/dk_prices.csv`, recovered from the build history and
appended on every build). `calibrate.py` replays them week by week, calibrating each week on
earlier weeks only, and grades the old rule and the new price-aware rule at the real price.
Through 10/22:

| Market | Old rule | New rule (calibrated P > break-even + 2%) |
|---|---|---|
| Saves (257 lines) | 81 plays, 49.4%, −7.1u, ROI −8.8% | 158 plays, 55.7%, +6.2u, ROI +3.9% |
| SOG (2,506 lines) | 1,649 plays, 57.4%, −58.5u, ROI −3.5% | 445 plays, 54.4%, +20.1u, ROI +4.5% |

These are small samples (a saves ROI of +3.9% on 158 plays is well within noise of zero), and
both refresh nightly on the Backtest tab with calibration buckets.

**Proxy lines.** `python model/backtest.py` fits on **2024-25 only** and tests **2025-26**
against `floor(last-10-start average) + 0.5`, because no public dataset has historical saves
lines. Proxy lines are much softer than real ones, so the dashboard hides proxy tier hit rates
and shows only projection accuracy (MAE, bias, correlation).

**Tested and not shipped** (no out-of-sample gain): power-play TOI and shot rates from the
play-by-play in the SOG projection (log-likelihood 1.5358 vs 1.5359 on 2025-26, worse on
2026-27); a Poisson instead of the negative binomial for SOG (worse in every season:
1.5385 vs 1.5359 on 2025-26); opponent power-play rate and own penalty minutes for shots against
(correlation with the shot residual under 0.02); the exact negative-binomial × binomial saves
distribution (fits worse than the normal form above, because pulls and save% swings fatten the
tails).

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
- Starters, lines and prices: DraftKings via The Odds API (`ODDS_API_KEY` secret): saves and SOG
  props for games in the next 18 hours, plus moneylines for the whole slate (1 credit). The
  PrizePicks board (`api.prizepicks.com`) refuses requests from cloud servers (HTTP 403), so the
  build retries transient errors, marks the source unavailable on a 403, and the page pulls the
  board live from your own browser instead.

## Files

```
index.html               generated dashboard (served by Vercel)
model/data.py            download + shape box scores / play-by-play
model/engine.py          walk-forward ratings, projection, grading
model/backtest.py        fit on 2024-25, test on 2025-26
model/build_site.py      render index.html from template.html
model/odds.py            starting goalies + DraftKings saves/SOG lines and moneylines (The Odds API)
model/saves_dist.py      saves distribution: game script, spread, P(over)
model/pricing.py         break-even, EV, calibration, tiers, DFS legs (mirrored in template.html)
model/calibrate.py       per-market calibration + real-line backtest, refit every build
model/tracker.py         freezes each night's calls and grades them at pick-time line and price
model/winners.py         game-winner model + backtest
model/sog.py             skater SOG model + backtest (stand-in and real PrizePicks lines)
model/data/              real-line log, DraftKings price history, nightly calls, 2026 playoff PP SOG lines
model/prizepicks.py      starting goalies + saves lines from the PrizePicks board
model/template.html      dashboard template
model/output/            params.json, saves_dist.json, calibration.json, tracking.json, backtests
.github/workflows/build.yml   rebuild 11am, 2pm, 4pm, 6pm, 7pm ET
```
