# roblox-up-and-coming-forecast-01 entry

Offline forecaster for [make.fun](https://make.fun/bounty/roblox-up-and-coming-forecast-01):
reads `/input/history.ndjson` + `task.json` and writes `/output/forecast.json`.

## Method

One forecast is scored on every hour of the 72-hour window, so probabilities are
horizon-averaged place occupancy:

1. Build Laplace-smoothed start-rank → place transition tables from the history
   at several horizon bins (0–6h … 60–84h).
2. Soft Gaussian rank-spread around a momentum-adjusted expected rank (recent
   rank delta, best recent rank, playing-count surge / deep-riser pull).
3. Mix the two, leave growing unnamed mass for brand-new chart entrants, and
   emit a top-10 guess from expected presence.

No network; standard library only; deterministic JSON.

## Credit

- Extends the official make.fun kit starter (`starter/main.ts`, MIT) persistence idea
  into a calibrated mixture.
- Chart archive provenance and MIT terms: [Kenny-Dhub/roblox-snapshots](https://github.com/Kenny-Dhub/roblox-snapshots).
