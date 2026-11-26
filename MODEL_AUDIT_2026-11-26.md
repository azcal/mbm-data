# Model audit, 2026-11-26

Scope: every winner model that can be rebuilt from its repo (NFL, NCAAF, NBA, NHL, Big 5
soccer, MMA). Bar: the one in `backtest.py`. A change is adopted only if it beats the
incumbent by 0.005 log loss out of sample and the 95% paired bootstrap interval excludes 0.

## What changed

1. **Cover claims at the market line are no longer published** (mbm-nfl, mbm-ncaaf). 779 live
   picks claimed 59.2% and hit 47.4%; log loss 0.746 against a coin's 0.693. Printing 50%
   instead, week by week, would have gained 0.045 (interval 0.022 to 0.073). Boards now show
   the model line and win probability with the market number as context. Raw picks are
   still logged, so the paper ledgers keep measuring the rule.
2. **Published holdouts restated to the engines that run live.** NBA 0.6051 / 0.5991 (was
   0.5930 / 0.5862), NHL 0.6617 / 0.6841 (was 0.6613 / 0.6821), NFL 0.6083 / 0.6467 with
   pregame-known starters (was 0.6021 / 0.6427).

## What was tested and not adopted

The same nine candidates on every board, fixed before any result was read: three
regularisation strengths, recency weighting (half-life three seasons), last four seasons
only, gradient boosting, a logit and boosting blend, and each model with every unused
numeric column added. Folds are the two frozen holdouts plus the 2026 live season where the
features can be rebuilt. Change in log loss against the incumbent, negative is better:

| Board | Games | Best candidate | Change | 95% interval |
|---|---|---|---|---|
| NFL | 732 | logit C=0.02 | -0.0002 | -0.0009 to +0.0006 |
| NCAAF | 1,606 | logit C=2.0 | -0.0002 | -0.0005 to +0.0002 |
| NBA | 2,890 | logit C=0.02 | -0.0009 | -0.0017 to -0.0001 |
| NHL | 3,191 | recency weighted | -0.0002 | -0.0010 to +0.0006 |
| Big 5 | 3,049 | logit C=0.02 | -0.0002 | -0.0004 to +0.0001 |
| MMA | 2,240 | boosting | -0.0105 | see mbm-mma README: a data leak, rejected |

Gradient boosting was worse than the incumbent on every board but MMA (+0.004 to +0.012).

Also tested: a calibration slope fitted on each holdout and applied to 2026 live (NFL
-0.0004, NCAAF +0.0003, NBA -0.0021, NHL +0.0019), and retraining the NFL model on
pregame-known starters (+0.0038, worse).

## Reading

The fits are at the ceiling of their inputs. No change of model class, regularisation,
training window or use of columns already in hand moves any board by a fifth of the bar.
Accuracy gains from here come from new information, not from refitting.
