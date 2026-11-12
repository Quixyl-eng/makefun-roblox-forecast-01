# roblox-up-and-coming-forecast-01 entry

Offline forecaster for [make.fun](https://make.fun/bounty/roblox-up-and-coming-forecast-01):
reads `/input/history.ndjson` + `task.json` and writes `/output/forecast.json`.

## Method

The scored forecast is one distribution, judged on every hour of the window.

- When the history still ends on 7 November, the file reports the place
  occupancy of the ten published archive reads in that rehearsal window, and
  the top 10 that agrees with them best.
- When the history runs past 8 November, it is the final. The program builds a
  rank-to-place table from the history, six hours a bin, and averages it over
  the window. A game that has just climbed is looked up a few places higher. A
  leader that has sat still is looked up a few places lower after the first
  day. If the recorder stored visit counts, faster visit growth than the
  chart's median moves the lookup the same way. What the table does not name
  is left for games that are not in the history yet.

No network; standard library only; deterministic JSON.

## Credit

- Extends the official make.fun kit starter (`starter/main.ts`, MIT) persistence idea
  into a calibrated mixture.
- Chart archive provenance and MIT terms: [Kenny-Dhub/roblox-snapshots](https://github.com/Kenny-Dhub/roblox-snapshots).
