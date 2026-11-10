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

## Known gaps

* **Saves calibration:** saves are calibrated on a probability without the rolling bias correction, while the page
  applies one. With no saves overs and a market requirement, this changes no call today.
* **One line per player and date:** the tracker log keeps one DK line per player and date: the line in the last
  pre-game call. When DK moved a line during the day, the earlier one is not in the record. The full set of quotes
  gives the same record within one standard error (table above).
* **Name joins:** a few names join on initials and last name (e.g. two "E. Pettersson" on Vancouver resolve by row
  order), and some spellings miss (Yegor / Egor Chinakhov, "J.Kulich"): 17 of 4,358 quotes.
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
* **All lines** keeps the saves, points and winners tables, the starters table and the paste box.
* The Backtest tab's rule record replays the play rule and the lean rule on graded DK lines.
