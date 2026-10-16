---
name: top-moves
description: Pull current ESPN league data and recommend top roster moves for my team (waiver adds/drops, buy-low and sell-high trades, trade partners). Use when asked for fantasy moves, waiver targets, or trade ideas.
---

# Top moves

Separate from `metrics.py` / dashboard.

## 1. Pull data

From the repo root:

```
uv run --env-file .env moves.py
```

Writes `output/moves/`:
- `league.json`: my team, next week, weeks left, trade deadline, PPR value, roster slots, FAAB vs waiver order
- `teams.csv`: record, playoff %, waiver rank / FAAB, starter strength rank by position (1 = best)
- `players.csv`: every rostered player + top free agents (`team` = `FA`)

`players.csv` columns:
- `pts`, `proj`, `diff`: actual vs ESPN weekly projections, completed weeks only
- `diff_recent`: `diff` over the last 3 completed weeks
- `avg`: actual pts/game; `espn_avg`: ESPN's season projected pts/game (updated in-season)
- `next_proj`: ESPN projection for `next_week` (0 = on bye or expected out; check `bye` / `status`)
- `median`: median actual pts/game; `weeks`: actual pts by week as `week:pts`
- `next_games`: next 4 games as `week:OPP(rank)`; rank = opponent vs position, 1 = toughest, 32 = easiest
- `next_opp_rank`: avg of those ranks (higher = easier)
- `bye`: next bye week
- `own_pct`, `start_pct`: ESPN-wide ownership / start rates
- `waiver_clears`: date an unrostered player clears waivers; blank = free agent (immediate add)

## 2. Analyze

Use pandas or read the CSVs directly. Look for:

- **Lineup holes**: my weakest starters and slot ranks in `teams.csv`; injuries; upcoming byes with no cover
- **Waiver adds**: FAs whose `espn_avg` / recent production beats my weakest starter or bench player at a position of need; easy upcoming schedule; name the drop
- **Buy low**: players on other teams with negative `diff` / `diff_recent` but strong `espn_avg` (ESPN still believes), easier upcoming schedule, or returning from injury/bye
- **Sell high**: my players with large positive `diff` well above `espn_avg`, tougher upcoming schedule, or an upcoming bye
- **Trade partners**: teams strong where I'm weak and weak where I'm strong (`*_rank`); losing teams with low `playoff_pct` may sell, contenders may overpay for depth
- **Timing**: weeks until trade deadline and end of regular season; my `playoff_pct` (contend vs build)

Weigh carefully:
- Early-season samples are small; don't overreact to one week
- Check `median` / `weeks` before calling buy/sell high; one big week can drive `avg` and `diff`
- `diff` measures luck vs ESPN's expectation, not talent; pair it with `espn_avg`, usage, and role
- Use both projections: `next_proj` for this week's lineup and short-term fill-ins; `espn_avg` for trades, stashes, and drops
- Respect roster slots and positional needs; a trade should make my starting lineup better
- Handcuffs: keep low-projected RBs who back up elite starters (injury stashes); pick another drop or call out the tradeoff
- Trade value is capped by free agents; a player is worth little if a similar FA is available
- Waivers: free agents are guaranteed immediate adds; waiver claims depend on my `waiver_rank` (low odds when last); claims can't share the same drop; ESPN adds claims to the bench, not IR (an open IR slot doesn't free a bench spot)

## 3. Report

Concise, ranked list of the top 5-8 moves. For each:
- Move (add/drop, trade target + what to offer, sell, or hold)
- Why: key numbers (`diff`, `avg` vs `espn_avg`, schedule, team fit)
- Risk / what would change the call

Then a short watch list (players to monitor, not act on yet). Note any data gaps (e.g. injury news beyond ESPN status).
