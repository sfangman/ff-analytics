# ff-analytics

Advanced analytics for an ESPN fantasy football league: projected vs actual scoring, luck, and lineup decisions.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

1. Install dependencies: `uv sync`
2. Fill in `.env`:
   ```
   ESPN_LEAGUE_ID=   # leagueId= in your league URL
   ESPN_YEAR=2026
   ESPN_S2=          # private leagues only
   ESPN_SWID=        # private leagues only, keep the {} braces
   ```
   - Get `espn_s2` and `SWID` from browser cookies while logged into espn.com
     - Chrome: DevTools → Application → Cookies → `https://www.espn.com`
     - Firefox: DevTools → Storage → Cookies → `https://www.espn.com`
   - `.env` is gitignored; never commit it

## Usage

```
./refresh.sh   # pull data and rebuild the dashboard
```

Or run the steps individually:

```
uv run --env-file .env metrics.py   # pull data from ESPN, write CSVs
uv run dashboard.py                 # build docs/index.html from CSVs
```

- `metrics.py` pulls completed weeks only (current week is skipped)
- `dashboard.py` reads only local CSVs, so re-run it freely without hitting ESPN
- Re-run weekly to refresh

### Auto refresh

`.github/workflows/refresh.yml` rebuilds and commits `docs/index.html` every Wednesday (or on demand from the Actions tab).

Setup (Settings → Secrets and variables → Actions):
- Variables: `ESPN_LEAGUE_ID`, `ESPN_YEAR`
- Secrets: `ESPN_S2`, `ESPN_SWID`
- `espn_s2` expires periodically; if the run fails, update the secret with a fresh cookie

## Outputs

`docs/index.html`: interactive, self-contained dashboard; published via GitHub Pages

Local data in `output/` (gitignored):

| File | Contents |
|---|---|
| `players.csv` | Player × week: slot, projected, actual |
| `weekly.csv` | Team × week: projected, actual, diff for starters / bench / total |
| `season.csv` | Team season totals of `weekly.csv` |
| `matchups.csv` | Weekly matchup scores |

## Metrics

- **± vs projection**: actual minus ESPN projected points (starters, bench, total)
- **Expected wins / luck**: expected wins = wins your score would earn vs every team, every week (all-play); luck = actual wins − expected wins
- **vs ESPN lineup**: actual starter points minus what ESPN's highest-projected lineup would have scored
- **Bench left / lineup efficiency**: best possible lineup in hindsight minus actual starters; actual / best possible

Notes:
- Bench excludes IR
- Matchup scores = starter points only
- Projections are ESPN's latest pre-game projections

## Files

- `metrics.py`: ESPN data pull and base metrics
- `dashboard.py`: derived metrics (luck, lineups) and HTML build
- `dashboard_template.html`: dashboard layout, styles, and charts
- `refresh.sh`: weekly refresh (data pull + dashboard build)
