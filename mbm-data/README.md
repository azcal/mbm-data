# mbm-data

Point-in-time archive for the MustBeMoose stack, plus the one backtest harness every board
scores against. Read GUIDE.md for the step-by-step build.

| file | runs where | what it does |
|---|---|---|
| odds_snapshot.py + odds.yml | GitHub Actions, several ticks a day | closing-line archive from The Odds API, ~180 credits/month |
| states_snapshot.py + states.yml | GitHub Actions, daily | injuries, slates, NHL projected goalies, CFBD lines |
| cfbd_backfill.py + cfbd_backfill.yml | GitHub Actions, once | college football lines and games 2015-2025 |
| xg_pull_local.py | your own computer | Big 5 xG history from Understat or FBref |
| backtest.py | any model repo | scores a predictions file once against pre-registered bars |

Secrets: `ODDS_API_KEY` (required), `CFBD_KEY` (for college football).
Settings > Actions > General > Workflow permissions must be "Read and write" so the jobs can commit.
