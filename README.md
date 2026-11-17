# QRob NHL Goalie Saves Model

Projects saves for every starting goalie and compares the projection to the book line.
It ships as a single self-contained `index.html` that Vercel serves (see `vercel.json`),
rebuilt through the day by GitHub Actions.

## The page

The first tab, **Picks**, is the one list to bet from. It has one row per player and stat (shots, points,
saves), built from the lines Pick6 and PrizePicks post:

- the side to take (**MORE** or **LESS**) and the line;
- the model's projection;
- the app or apps where that exact bet is offered at 1x or better (both are named when both post it);
- the chance, and a label: **Play** (passes every rule; rare), **Lean** (the likelier side at 55%+ with the
  market agreeing, about break-even), or **Check** (a lean on a player whose line just changed).

Lines with no edge and DraftKings-only lines are folded away under the list. The app filter (Both / PrizePicks /
Pick6) picks each player's best line on that app. The rule is `props_board.picks`, mirrored by `pickFor` in
`model/template.html`; the reasoning and the backtest are in `model/reports/accuracy_review.md`.

A Pick6 **promo card** carries its name beside the app: a *Stat Slice* (the line cut, MORE only, at 1x where the
ordinary card pays less) or a *Power Up* (both sides boosted). Pick6 allows one promo pick per entry.

Under the list, **the record** counts every play and lean the page showed at any time before the game, once
each, at the numbers it had when first shown (see Results tracking).

**Slips** combines tonight's plays and leans into entries of 2 to 6 legs on one app: how often every leg hits
together, what the app pays, what that is worth per $1, and the same with every chance trimmed 3 points. It has
a build-your-own list and editable payout tables. It is a calculator: it places nothing (see Slips below).

**All lines** keeps the saves, points and winners tables, the starters table and the paste box.

**Line moves.** Every prop keeps its **opening line** (the first line a build saw) and every move after it, per book
and app (`model/linemoves.py`, logged in `model/data/lines/<game day>.csv`):

- the **Goalies** tab opens with every saves line on the slate, one card per goalie, biggest moves first and games
  already started last: every book's open → now in one line and the books' **fair line** (the saves count they make a
  50/50 bet: each line moved by its no-vig price, so a flip between 22.5 at +100 and 21.5 at −135 is not a move), now
  and how far it has moved since the first line a build saw (linked pull by pull, so a book that opens after the move
  joins at the new level). Tap a card for each book's open and now with prices, the time of the last change and
  every change in order;
- the **Picks** tab shows the day's biggest goalie line moves above the picks ("Saves line moves"), each a tap through
  to that goalie's card;
- a pick whose line moved says so beside the app ("opened 2.5 ↓1"), and its panel has every book's open and now;
- the saves, points and starters tables put "open 25.5 ↓1" under a line that moved (only when the row shows that
  source's latest line: a pasted, typed or alternate line has no story). A saves row whose own source has not moved
  names the biggest move elsewhere ("PP 24.5→22.5").

It is display only: a move never changes a call.

## The model

```
exp_SA          = LG × (TeamSA / LG)^a × (OppSF / LG)^b × home × playoff × b2b × opp_b2b
                  × exp(−gs × logit(win prob))                      game script
Projected saves = exp_SA × time-in-net share × save% + rolling bias
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
| game script | Win probability from the no-vig DraftKings moneyline (or the game-winner model when none is posted). Heavier underdogs face more shots. `gs` = 0.025 when the model runs on its own Corsi counts, 0.005 when MoneyPuck's attempts drive it (`gs_mp`, `python model/fit_sa.py --gs-mp`): the Fenwick terms already carry most of the strength gap (`model/saves_dist.py`, `output/saves_dist.json`) |
| spread | Shots against vary like a negative binomial (K = 30, max likelihood on 2024-25) and each shot is saved with probability sv. Heavy underdogs get a spread near 8 saves, heavy favourites near 5.6; the old fixed 6.9 was too tight for underdogs and too loose for favourites. Better log-likelihood than the fixed spread on 2025-26 and 2026-27 |

Every projection uses only games played **before** that date (walk-forward), so the
backtest has no lookahead. Team rates carry part of last season's weight into a new
season, which is how the model handles opening night of 2026-27. The rolling bias is the
recent mean of actual minus this projection (30-day half-life, shrunk by 20 starts).

MoneyPuck goalie game logs (xGoals, unblocked attempts, high-danger rates, GSAx) were
tested as a replacement for shot volume and for save% on this season's walk-forward.
They did not lower the error, so they are not in the formula. Every build still
cross-checks NHL shots, saves and time on ice against those logs and fails if they
diverge (`model/moneypuck.py`, `model/reports/goalie_backtest.md`).

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
2. **After games:** every build grades finished games from the box scores (the first ones at about 6:30 and
   7:30 AM Central, dispatched by `ticker.yml`; GitHub drops most of `build.yml`'s own morning schedules):
   - every real line, appended to `real_line_log.csv` with HIT/MISS at the pick-time line and price;
     units and ROI by market, tier, side and book; game-winner picks in units at the DraftKings
     moneyline; DFS (Pick6 / PrizePicks) lines as a market-basis record against per-leg break-even;
   - model accuracy that needs no line: winner picks, starter calls, saves and SOG error;
   - a reason for each miss: wrong starter, shots against far from expected, goalie pulled, OT,
     or a big TOI change.
3. **Pick6 boards:** send the screenshots or a screen recording and they get logged in the CSV.
   The grader fills in the results the next morning.

**The leg log** (`model/data/legs.csv`) stores every board leg on every build, and keeps the strongest call
the page ever showed for it (`shown`: a play outranks a lean) with the time, side, chance and multiplier it had
when first shown. A later snapshot never erases that call. The records on the page (`plays_shown`,
`leans_shown` in `tracker.legs_summary`) count every call shown, once each. Until 2026-11-16 the log kept only
each leg's last pre-game snapshot, and the page counted only the leans still on the game's last board: it read
23-13 when every lean shown was 56-40 (through 11-14). Of those 96, the ones still a lean on the last board
went 22-13, the ones whose line was taken down while still a lean went 27-7, and the ones the page itself
dropped later (the market or our number moved against them) went 7-20 (`tracker.shown_split`; the Results tab
shows the split). Calls from before the change are rebuilt from the repository's history
(`python model/backfill_shown.py`, a full clone only; it writes `model/data/legs_shown.json`).

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

#### Line movement (`model/linemoves.py`, `model/data/lines/`)

Each build writes a row for a prop (one game day, market, player and source) only when it changes: its first row is
the open, its last row before puck drop the close.

- **Sources**: DraftKings, FanDuel, ESPN BET, BetMGM and Pinnacle (The Odds API), PrizePicks, Pick6.
- **Fresh pulls only.** A cached (fallback) pull or a Pick6 line kept from an earlier pull is never logged again. A
  build that falls back because DraftKings has nothing yet still logs the other books' and PrizePicks' own new rows
  (`odds.pulled`): they post the next day's lines overnight, before DraftKings.
- **One line per prop**: the line priced nearest even at a sportsbook (ESPN BET lists two or three), the line Pick6
  takes both ways on, PrizePicks' standard line (never a demon or goblin).
- **What counts as a move**: saves, any change of line or price; shots and points, a change of line (their prices move
  on almost every pull; every price is still in `dk_prices.csv` / `book_prices.csv`). A sportsbook moves a skater's
  main line a rung whenever its price drifts past a threshold, and often straight back (260 of DraftKings' 506 skater
  line changes from Nov 3 to 17 were undone at the next change), while the count its prices imply moves 2–12% (17%
  covers 95% of the changes that were undone): the page shows a skater's sportsbook line as moved only when that
  count is 17% from the open's or the line was taken down at some point (`linemoves.rung_only`). The log keeps
  every row.
- **Off the board** (an empty line): written only when the same pull carries that source's lines for the same game and
  market (a failed request for one game is never read as its lines coming down), and for Pick6 only when its page
  listed the market in full. A spell off shorter than 20 minutes that comes back unchanged is hidden on the page.
- **Days before the log** were rebuilt from the git history of the committed caches (`python model/backfill_lines.py`,
  run by hand in a full clone: every distinct pull of `odds_cache.json` and `pick6_cache.json` replayed through the same
  rules, Pick6 take-downs on the proof its page listed the market in full, as that build's `index.html` says) and,
  before Nov 3, from `dk_prices.csv`. A day that already has a log keeps every row the builds wrote: the replay only
  adds what came before each prop's first logged row (its real open, if the builds started logging it late). A
  build whose pull has lines for a day with no log yet, while the price logs hold earlier pulls of it, rebuilds that
  day from them first (`linemoves.ensure`).
- **The page** gets every saves line in full and the skaters' props whose line moved (about 15–45 KB a night).

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

## Slips (`model/slips.py`, **Slips** tab)

The board grades one leg at a time; the apps pay on the whole entry. For a set of legs on one app the slip
builder works out:

- **the chance they all hit.** Legs in different games are independent. Legs in one game move together by a
  correlation that depends on the pair (a shooter's shots with the opposing goalie's saves: +0.23, and +0.32
  for a high-volume shooter; teammates' points: +0.23, +0.34 for two scorers; most other pairs are near zero).
  A MORE with a LESS flips the sign. The joint chance is a Gaussian copula computed exactly (no sampling), so
  the page and the Python agree to eight decimals.
- **what the entry pays:** the level's multiple x each leg's multiplier x Pick6's own same-game cut, capped.
  Pick6's table is read from its page on every build (2-pick 3x, 3-pick 6x, 4-pick 10x, 5-pick 12x with 4 of 5
  at 1x, 6-pick 25x with 5 of 6 at 1.5x). PrizePicks' is its published table (Power 3 / 6 / 10 / 20 / 37.5; Flex
  pays part on one or two misses). Both can differ by state: the tables are editable on the page.
- **pushes.** A whole-number line can land exactly on the number; that leg is void and the entry pays one level
  down (a 2-pick is refunded). Each leg carries its push chance.
- **what it is worth:** expected return per $1, and again with every leg's chance trimmed 3 points (the stress
  test). Entries are ranked by the stressed value.

`best_slips` values every combination of 2 to 6 of an app's best legs that the app would accept (one pick per
player, at least two teams, one promo pick). The correlations start from the average of three full seasons of
box scores, which agree closely, and move toward the current season as its games add up (`measure_rho`,
`blend_rho`). `template.html` mirrors the module, and `tests/test_slips.py` runs the page's own code against
the Python on every push.

Nothing here places, submits or automates an entry. The app's entry screen is the authority on what an entry
pays.

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
model/props_board.py     the board: every line scored, one pick per player, the legs for slips
model/slips.py           entries of 2-6 legs: joint chance, payout, value, stress test, search
model/pick6.py           Pick6 board: lines, promo cards, its payout table and lineup rules
model/players.py         (name, team, game) -> NHL player id; rosters, call-ups from recent box scores
model/backfill_shown.py  rebuilds "every call ever shown" from the repository's history (run by hand)
model/linemoves.py       opening lines and line movement: the per-day line log, and the page's movement data
model/backfill_lines.py  rebuilds the line log's earlier days from the repository's history (run by hand)
model/moneypuck_teams.py MoneyPuck shot attempts for the saves model: full logs as of 11-03 plus a small daily
                         refresh (model/data/moneypuck/attempts_recent.csv)
model/calibrate.py       per-market calibration + real-line backtest, refit every build
model/tracker.py         freezes each night's calls and grades them at pick-time line and price
model/winners.py         game-winner model + backtest
model/sog.py             skater SOG model + backtest (stand-in and real PrizePicks lines)
model/data/              real-line log, DraftKings price history, nightly calls, 2026 playoff PP SOG lines,
                         lines/<game day>.csv (every prop's open and moves)
model/prizepicks.py      starting goalies + saves lines from the PrizePicks board
model/template.html      dashboard template
model/output/            params.json, saves_dist.json, calibration.json, tracking.json, backtests
.github/workflows/build.yml   rebuild, grade and publish (dispatched by ticker.yml: every 15 minutes 9 AM-1:45 AM CT,
                              and at about 6:30 and 7:30 AM to grade last night's games)
.github/workflows/tests.yml   unit tests and the model-settings freeze, on every push
```
