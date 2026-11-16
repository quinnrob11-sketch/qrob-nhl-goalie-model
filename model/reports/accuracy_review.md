# Accuracy review (2026-11-08)

What the out-of-sample tests say about the props board, and what changed because of them. Anything fitted
was fitted only on earlier dates (walk-forward), and every DraftKings price is the last snapshot taken
**before** puck drop (`model/prices.py`). Three choices were made with this season's lines in view, and each
is marked where it appears:

* the shots projection's design;
* the 50/50 blend weight;
* the 62% / 55% play bars.

An independent audit found no look-ahead. It reproduced every number here with its own code, from the raw
price snapshots and box scores (scrambling future games leaves every earlier projection, probability, verdict
and settlement unchanged).

## The short version

* **No model beats DraftKings' own no-vig price by a reliable margin, in any market.** The best shots model
  is a little better than DK, but only by about 1.5 standard errors (below). Points and saves are not better.
* **The old "+ROI" numbers came from scoring DraftKings favourites as if they were free 1x pick'em legs.** The
  sides the old rule picked were juiced favourites, priced around 64% (SOG) and 68% (points) implied. At DK's
  real price the same picks lost: SOG -7.2% ± 2.6, points -3.4% ± 3.6 per leg.
* **DFS boards don't offer the sides the market favours.** Pick6 paid 1x or more on **0 of 295** sides DK
  priced at 52% or more (Nov 3-8). PrizePicks sets its lines where DK is 50/50.
* So the board is now strict. **Most nights it will show no shots play.** When one does appear, the market and
  the model both like the side, and a DFS board still pays at least 1x on it. That usually means a PrizePicks
  line that hasn't caught up with a DraftKings move.

## Shots on goal

**Projection.** Expected shots are now the player's **shot-attempt rate** (on goal + missed + blocked, from
play-by-play) times **his own shots-on-goal-per-attempt ratio**. Both are shrunk toward position averages.
Ice time is now **0.7 × a 3-game average + 0.3 × a 24-game average** (`sog.SogParams`: `w_att`, `toi_hl2`,
`toi_lam`; parameters in `output/sog_params.json`, fitted with `fit_props.py`).

| test | result |
|---|---|
| NB log-likelihood per player-game, 2025-26 (n=50,182) | +2.12e-3 ± 0.29 vs the old projection |
| NB log-likelihood per player-game, 2026-27 (n=9,503) | +2.05e-3 ± 0.72 |
| Months improved | 11 of 12 |
| Leak test (future rows deleted) | identical projections |
| Placebo (shots on goal treated as "attempts") | -0.06e-3 ± 0.03: the attempt data is real information |

The design and its search grid were picked with the 2025-26 and 2026-27 results, and this season's DK lines,
in view. The fitted values use no 2026-27 game: re-running the fit with 2026-27 deleted reproduces them exactly.
The 2025-26 gain alone, +2.12e-3 ± 0.29, is the cleaner out-of-sample number.

**Probability: a 50/50 blend with the market, in expected shots.** DraftKings' price on the player's line nearest
50% is turned into the expected-shots number that reproduces it (`sog.implied_mean`). That number is averaged
50/50 with the projection, and the result is priced at every line with the model's own dispersion. The Platt
calibration step is no longer used for shots. It was fitted on DK's main lines and pushed every other line
toward 50%: on Pick6 ladder rungs it showed 12-17% for outcomes that happened 5-10% of the time (ECE 0.08,
against 0.007 for the blend).

| on 3,551 graded DK lines (walk-forward weeks) | log loss | Brier |
|---|---|---|
| DraftKings no-vig | 0.68592 | 0.24641 |
| raw model | 0.68612 | 0.24649 |
| **live: 50/50 mean blend** | **0.68458** | **0.24576** |

It scores best, but not by a reliable margin. The older Platt blends are also slightly below DK (0.6849-0.6859).
On every DK quote that has a box score (4,358 lines, the independent recompute), the blend scores 0.68302
against DK's 0.68495, a difference of -1.9e-3 ± 0.8.

**The 0.5 weight was chosen on these lines.** It is the in-sample log-loss optimum, and the curve is flat from
0.4 to 0.6. A weight chosen week by week from earlier weeks only scores 0.68478, still 1.15e-3 ± 0.91 below DK.

The separate experiment at DK's own line measured -0.88e-3 ± 0.88. Away from DK's line (±1 / ±2 and
whole-number lines), the blend beats the plain market transfer by -1.46e-3 ± 0.68.

**Rule (R1).** A shots TAKE needs all of the following:
* blended p of at least **62%** (Lock at 64%);
* the market's own probability for that side at least **55%**;
* the side offered at **1x or better** on a DFS board;
* the line and the price come from this build's pulls, not a reused cached board.

There is no separate "model alone agrees" check for shots: the blend already carries the model.

| R1 on graded DK lines, as if each side were a 1x leg (bars chosen on these lines) | n | hit | ROI at DK's price |
|---|---|---|---|
| lines the tracker logged, warm weeks (`reports/audit_backtest.md` §3) | 270 | **66.3% ± 2.9** | +2.4% ± 4.5 |
| every DK quote with a box score, all weeks (independent recompute) | 446 | 67.3% ± 2.2 | +3.9% ± 3.4 |
| bars re-chosen each week from earlier weeks only | – | 65.4-67.6% | +0.9% to +3.6% |
| test-period experiment (one line per player-date, 10-07..11-06) | 246 | 63.8% ± 3.1 | -1.5% ± 4.7 |

* **Bars.** The 62% and 55% cut-offs were chosen on these same dates. The record does not hang on that choice:
  - The record rises steadily with the bar: 64.4% at 61%, 66.3% at 62%, 68.4% at 63%.
  - Bars re-chosen each week from earlier weeks only land within one standard error of the fixed ones.
  - Bars picked on the first half give 68.6% / +5.3% ± 6.1 on the second half.
* **Price.** At DK's own price the R1 picks are about break-even. By the blend's own probabilities they should
  return about -1% there (DK's vig on these props is about 8.7%), and the realized numbers are within about one
  standard error of that. DK's favourites alone (no-vig 55%+) hit exactly their no-vig, 58.5%, and return
  -6.7% ± 1.7.
* **Payout.** These picks only make money where a DFS board pays 1x on the side, and none has done that yet:
  0 of 1,999 graded Pick6 SOG legs qualified at 1x or better. The "real DFS" column in the audit is 0 by
  construction (sides DK prices at 54%+ are taken to pay 0.8x, as measured on Nov 3-8 boards), and the leg log
  agrees.

**Expect roughly 0 shots plays on a typical night.**

**Ladders.** Pick6's More-only rungs and other high-multiplier sides lose money even with accurate
probabilities. Per-leg EV was about -17% at 1x, falling to -46% at 8x and above. Pick6 pays a median 0.59 of
the fair multiplier at 3x and above. Betting every offered side realized -21%, -17%, -28% and -49% by multiplier
bucket, matching the predictions. The board never makes a ladder rung a play. It shows each rung's probability so
you can see this for yourself.

**Never from a cached board.** When a pull fails and the build reuses the last good board, its lines and prices
are still shown, but no row that leans on them can be a TAKE. A cached PrizePicks line paired with tonight's
DraftKings price produced 3 phantom plays in testing.

## Leans (added 2026-11-10)

The play rule above leaves most nights empty, and the board still has to say which way to go on the lines the
apps do post. So each player now gets **one pick** (`props_board.picks`): the side to take, the line, and the
app or apps that offer exactly that bet at 1x or better. A pick has one of three labels.

* **Play**: a TAKE under the rules in this review. Unchanged.
* **Lean**: not a play, but the likelier side. It needs a chance of **55%+**, the market's own probability for
  the side at **52%+**, and a 1x-or-better payout on Pick6 or PrizePicks. Shots and points only.
* **No edge**: everything else. The row still shows the likelier side and what the app pays for it.

A shots lean on a player whose line changed is labelled **Check** until his spot is confirmed.

| leans on graded DK lines, each side taken as a 1x leg (`calibrate.lean_record`) | n | hit | chance said | ROI as a 1x leg |
|---|---|---|---|---|
| shots, 10-01..11-09 | 1,969 | **57.0% ± 1.1** | 58.3% | -1.3% |
| shots, MORE only | 810 | 56.3% ± 1.7 | 58.0% | -2.5% |
| shots, LESS only | 1,159 | 57.5% ± 1.5 | 58.4% | -0.5% |
| points, 11-02..11-09 | 150 | 62.7% ± 4.0 | 56.5% | +8.5% |
| shots rated 55%+ with the market under 52% (not leans) | 62 | 48.4% ± 6.3 | 56.3% | – |

* **A lean is a direction, not an edge.** A 1x pick'em leg needs 54-58% to break even, depending on the entry.
  Shots leans hit 57%, which is about break-even. The points number rests on one week of lines.
* **Both bars were read off these same lines.** The 55% and 52% cut-offs are a description of this sample, not an
  out-of-sample test. Leans are logged with every build from 2026-11-10 (`legs.csv`, column `lean`), so the
  Results tab grades them going forward.
* **Why the market has to agree.** With the market's own number under 52%, sides the board rated 55%+ hit 48%.
  The sample is small (62), but it matches the rest of this review: model-only picks have not won.
* **Saves have no leans.** Saves calls of 65%+ hit 46%.
* **On real app lines so far:** on the two slates since the current shots probability went live (Nov 8-9),
  24 lines met the lean rule on Pick6 or PrizePicks and 14 hit (58%). That is too few to mean anything yet.

## Points

* A line priced at DraftKings' own odds is never a TAKE. Walk-forward, DK-priced points TAKEs hit exactly DK's
  no-vig (59.5% ± 3.9 vs 59.8%) and lost at every blend weight (-7% to -23%). The live record was 10-10,
  -21.9% at DK prices.
* The blend weight is a fixed 0.3 until 200 walk-forward lines exist. It is never fitted in-sample: the
  in-sample fits of 0.55-1.0 overstated the walk-forward optimum, which is about 0.3.
* No unders at 1.5 points or more: rated 65.6%, they hit 50.9% (n=55).
* Points still need the market's side at 55%+ and the model alone leaning the same way.

## Saves

* No overs: they lost at every edge threshold.
* A TAKE needs a market price on the line. The DK saves market is close to a coin flip (log loss 0.692), and
  the model ties it at best. So saves TAKEs are now very rare.

## Data fixes behind these numbers

* **Prices:** every reader now uses the last DraftKings snapshot before the scheduled start
  (`prices.last_pregame`). Before, about 5% of shots lines and 11% of points lines were priced from an in-game
  snapshot.
* **Weeks:** walk-forward splits used the ISO week number, which restarts in January (October-December would
  have trained on January). They now use a running week count (`calibrate.week_key`).
* **The results panel** counts only playable legs: graded, the game's last pre-game build, offered at 1x or
  better or priced, and one row per leg across sources. It settles each leg at its real price, so it no longer
  counts sides a board didn't offer.

## Full audit (2026-11-16)

Every part of the pipeline was re-checked: the data, the three models, the lines from each app, the board's rules,
the page's copy of those rules, the grading and the records. Numbers are through the 11-14 slate.

**What held up**

* The board's numbers re-derive from the raw inputs to 13 decimals, and the page's picks match the Python on
  every line (104 of 104 on the 11-15 board).
* The shots model has no look-ahead: cutting the data off at any date, or scrambling later games, leaves every
  earlier projection unchanged.
* The 50/50 blend is still the best of the three on graded lines (log loss 0.68393, against 0.68541 for the
  model alone and 0.68545 for the market alone, n=5,115).
* The play bars hold in walk-forward weeks they were not read from: chance 62%+ with the market at 55%+ hit
  69.3% ± 4.3 (n=114).
* Whole-number lines are calibrated, pushes included (a 2.0 line lands exactly on 2 about 24% of the time).
* Pick6's ordinary multipliers price the chance in. 365 sides paying over 1x hit 37.8% against a stated 41.2%,
  and 2,116 alternate rungs returned -36%. There is no hidden value on its ordinary ladder.

**What was wrong, and is fixed**

* **The records counted only the calls still on the last board.** The leg log kept each leg's last pre-game
  snapshot, so a lean that was dropped, or whose line was taken down, was never graded as a lean. The page read
  leans 23-13 and plays "none yet". Counting every call shown, once each, at the numbers it had when first shown:

  | calls shown, 11-08..11-14 | record | hit |
  |---|---|---|
  | plays (current rules) | 2-3 | 40% |
  | leans, all | 56-40 | 58.3% |
  | leans still a lean on the game's last board | 22-13 | 63% |
  | leans whose line was taken down while still a lean | 27-7 | 79% |
  | leans the page later dropped (the market or our number moved against them) | 7-20 | 26% |
  | shots leans, MORE / LESS | 12-18 / 41-21 | 40% / 66% |

  The log now keeps the strongest call ever shown for a leg and never erases it (`tracker.log_legs`,
  `shown_legs`, `shown_split`); earlier calls were rebuilt from the repository's history
  (`model/backfill_shown.py`). All three groups are small. Two readings are safe: a lean is about a 58%
  proposition, which is near break-even for a 2-pick (57.7%) and above it for a 3-pick Power (55.0%); and a lean
  that disappears because the market moved is no longer a lean. The MORE / LESS gap is the same direction as the
  overs bias under Known gaps, on 30 and 62 legs.
* **One missed pull wiped the calls.** When PrizePicks' lines were missing from a single build, every lean went
  with them until the next build. A line pulled within the last 20 minutes now keeps its call
  (`props_board.recent_enough`).
* **Late-night false alarms.** With every game under way and the next slate most of a day off, an empty answer
  from an app read as "fallback" or "parse failed" and raised the stale-data banner for hours. Nothing to pull is
  now "fresh" with no lines (`pick6.nothing_open`, `odds.idle`); a pull that fails, or comes back empty with a
  game close, is still a failure.
* **Call-ups and trades went unmatched.** The NHL roster feed lags: P. Tomasino played three games for Ottawa
  while on no roster, and every line of his was dropped. Players who dressed in the last 10 days are now matched
  on that team (`players.add_recent`).
* **The role-change adjustment was too big.** When a player's line assignment changed, his expected ice time
  moved by up to 15%. About 30% of the stated change shows up in the next game, so the cap is now 5%
  (`linecombos.TOI_CAP`).
* **The saves model was on its fallback.** MoneyPuck's shot-attempt logs had not refreshed since 11-03 (a fresh
  CI checkout made every cached file look new), so from about 11-06 they covered under 90% of the season and the
  model used its own attempt counts. The two modes project within 0.3 saves of each other on average and their
  errors are the same to two decimals in every season, so no call was affected. The refresh now runs about once a
  day and keeps only the numbers the model needs (`moneypuck_teams.refresh`).

**What is new**

* **Pick6 promo cards.** Pick6 serves a Stat Slice (the line cut, MORE only, at 1x where the ordinary card pays
  0.7x) and a Power Up (both sides at 1.3x) as separate cards. They were being dropped as duplicates. They are now
  read, shown with their name, and judged for what they pay: a Stat Slice is an ordinary side at its multiplier; a
  boosted side is a lean when it is the likelier side and chance x multiplier is at least 0.58 on our number and
  on the market's (`pricing.promo_lean`). Pick6 allows one promo pick per entry.
* **Slips** (`model/slips.py`, the Slips tab): entries of 2 to 6 legs, valued with same-game correlation, the
  app's payout table, pushes and a stress test. The correlations come from three full seasons of box scores,
  which agree closely:

  | pair in one game | 2023-24 | 2024-25 | 2025-26 | in use |
  |---|---|---|---|---|
  | a shooter's shots and the opposing goalie's saves | +0.222 | +0.229 | +0.226 | +0.23 |
  | ... for a shooter averaging 2.5+ shots | +0.308 | +0.342 | +0.317 | +0.32 |
  | teammates' points | +0.222 | +0.249 | +0.212 | +0.23 |
  | ... for two scorers at 0.8+ points a game | +0.323 | +0.391 | +0.317 | +0.34 |
  | a skater's points and the opposing goalie's saves | -0.059 | -0.061 | -0.054 | -0.06 |
  | the two goalies' saves | -0.030 | -0.130 | -0.146 | -0.10 |
  | a skater's shots and his own goalie's saves | -0.028 | -0.044 | -0.044 | -0.04 |
  | teammates' shots; opponents' shots or points; shots with points | within ±0.04 | | | ±0.03 |

  This season alone (325 games) reads +0.18 for the first row, which is within its noise: pairs in one game share
  that game's pace, so the games behind a number say how firm it is, not the pairs. The table in use moves toward
  the current season by games played (about a fifth of the way after six weeks).

  What that is worth, for two 58% legs (unrelated: both hit 33.6%):

  | pair, both legs the same way | both hit | PrizePicks 2-pick | Pick6 after its cut |
  |---|---|---|---|
  | shooter's shots + opposing goalie's saves | 37.2% | +11.6% | -8.5% (cut 0.82) |
  | ... a high-volume shooter | 38.6% | +15.9% | -4.9% |
  | teammates' points | 37.2% | +11.6% | +0.4% (cut 0.90) |
  | ... two high scorers | 39.0% | +16.9% | +5.2% |
  | teammates' shots | 34.1% | +2.3% | -2.8% (cut 0.95) |
  | a skater's shots + a teammate's points | 34.0% | +1.8% | -10.4% (cut 0.88) |

  Pick6's cut is bigger than the correlation it charges for on every pair except two high-scoring teammates'
  points. PrizePicks applies no cut. One leg MORE and the other LESS flips the sign: a shooter's MORE with the
  opposing goalie's LESS hits together 30.1%, 10% less often than unrelated legs.
* **The research note's best slip could not be entered.** It combined three 1x MORE cards at 2.5; those are Stat
  Slice promos, and Pick6 takes one promo pick per entry. Its correlation table is confirmed by the three seasons
  above; its 0.18 for shooter and goalie is this season's sample.

## Known gaps

* **Saves calibration:** saves are calibrated on a probability without the rolling bias correction, while the page
  applies one. With no saves overs and a market requirement, this changes no call today.
* **One line per player and date:** the tracker log keeps one DK line per player and date: the line in the last
  pre-game call. When DK moved a line during the day, the earlier one is not in the record. The full set of quotes
  gives the same record within one standard error (table above).
* **Name joins:** a few names join on initials and last name, and some spellings miss (Yegor / Egor Chinakhov,
  "J.Kulich"): 17 of 4,358 quotes. Vancouver has two players named Elias Pettersson (a forward and a defenseman);
  a line that does not say which is left unmatched instead of guessed.
* **One-build price blips.** A play needs the market's side at 55%+. A single odd DraftKings quote can put a line
  over that bar for one build and back under it on the next. The call is graded like any other once shown; it is
  rare, and it is one reason the record counts every call shown.
* **Saves on the page for a game with no moneyline.** For a game with no moneyline posted, the page's saves
  projection can differ from the build's by a fraction of a save. The audit found the difference and no saves
  call it changes; it has not been run down.
* **Slips are estimates.** The chances are the board's, the correlations are averages over many pairs, and the
  payout tables are the apps' published ones. A partial payout on Pick6's 5- and 6-pick entries is taken with
  every leg's multiplier; the app may count only the legs that hit. The entry screen is the authority.
* **Shots overs at 1.5:** the blend says 55.6% and they hit 52.2% (n=1,134). It inherits part of DraftKings' own lean
  toward overs, and no correction fitted on earlier weeks helped later weeks. R1's MORE picks did worse than its LESS
  picks (61.8% vs 68.1% at 1x; -4.8% ± 9.2 vs +5.5% ± 4.5 at DK prices).
* **Pick6 coverage:** Pick6's page serves one category per request, and the build can only read the one it is
  given. Some builds get its full Shots On Goal list (105 players on 11-10 at 10:09 AM CT) and some only its
  featured picks (7 players two hours later). The build now keeps the lines an earlier pull saw that day
  (`pick6.merge_day`), shows them with their age, and never lets one make a play or a lean. On a day the full
  list is never served, most Pick6 lines are still missing, and the Picks tab says so.
* **Stat corrections:** graded lines are now re-graded when the NHL box score changes later
  (`tracker._regrade`). 23 logged lines had stale results (12 shots, 11 saves). No shots play was affected.

## How to read the board

* **Picks** is the one list: one row per player and stat, from the lines Pick6 and PrizePicks post. Each row
  shows MORE or LESS and the line, the projection, the app or apps where that exact bet is offered, and the
  chance. Plays come first, then leans; lines with no edge and sportsbook-only lines are folded away.
* **Chance** is the blended probability for the side shown. **Proj** is the model's projection, and the signed
  number is projection minus line.
* Tap a row for the reason in one sentence, the numbers behind it, his last 10 games and his other lines on
  both apps.
* The app filter (Both / PrizePicks / Pick6) picks each player's best line on that app only.
* **Slips** combines the night's plays and leans into entries on one app, with how often they all hit, what the
  app pays and what that is worth. The record under the picks counts every call the page showed, once each.
* **All lines** keeps the saves, points and winners tables, the starters table and the paste box.
* The Backtest tab's rule record replays the play rule and the lean rule on graded DK lines.
