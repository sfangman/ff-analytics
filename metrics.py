"""Pull ESPN league data and write player, weekly, and season metrics to output/.

Env vars:
- ESPN_LEAGUE_ID (required)
- ESPN_YEAR (default: 2026)
- ESPN_S2, ESPN_SWID (required for private leagues; browser cookies from espn.com)
"""

import json
import os

import pandas as pd
from espn_api.football import League

EXCLUDED_SLOTS = {"IR"}  # not counted as starters or bench


def load_league() -> League:
    return League(
        league_id=int(os.environ["ESPN_LEAGUE_ID"]),
        year=int(os.environ.get("ESPN_YEAR", 2026)),
        espn_s2=os.environ.get("ESPN_S2"),
        swid=os.environ.get("ESPN_SWID"),
    )


def weekly_rows(league: League, week: int) -> tuple[list[dict], list[dict]]:
    rows, matchups = [], []
    for box in league.box_scores(week):
        if box.home_team and box.away_team:
            matchups.append({
                "week": week,
                "home": box.home_team.team_name,
                "away": box.away_team.team_name,
                "home_score": box.home_score,
                "away_score": box.away_score,
            })
        for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
            if not team:  # bye
                continue
            for p in lineup:
                if p.slot_position in EXCLUDED_SLOTS:
                    continue
                rows.append({
                    "week": week,
                    "team": team.team_name,
                    "player": p.name,
                    "position": p.position,
                    "pro_team": p.proTeam,
                    "eligible": "|".join(p.eligibleSlots),
                    "slot": p.slot_position,
                    "group": "bench" if p.slot_position == "BE" else "starters",
                    "projected": p.projected_points,
                    "actual": p.points,
                })
    return rows, matchups


def main():
    league = load_league()
    # current_week is in progress; only include completed weeks
    weeks = range(1, league.current_week)
    results = [weekly_rows(league, w) for w in weeks]
    players = pd.DataFrame([r for rows, _ in results for r in rows])
    matchups = pd.DataFrame([m for _, ms in results for m in ms])

    weekly = players.pivot_table(
        index=["week", "team"], columns="group", values=["projected", "actual"], aggfunc="sum",
        fill_value=0,  # e.g. a team with an empty bench
    )
    weekly.columns = [f"{grp}_{val}" for val, grp in weekly.columns]
    for grp in ("starters", "bench"):
        weekly[f"{grp}_diff"] = weekly[f"{grp}_actual"] - weekly[f"{grp}_projected"]
    weekly["total_projected"] = weekly["starters_projected"] + weekly["bench_projected"]
    weekly["total_actual"] = weekly["starters_actual"] + weekly["bench_actual"]
    weekly["total_diff"] = weekly["total_actual"] - weekly["total_projected"]
    weekly = weekly.round(2).reset_index()

    season = (
        weekly.drop(columns="week").groupby("team").sum().round(2)
        .sort_values("starters_diff", ascending=False)
    )

    os.makedirs("output", exist_ok=True)
    players.to_csv("output/players.csv", index=False)
    weekly.to_csv("output/weekly.csv", index=False)
    season.to_csv("output/season.csv")
    matchups.to_csv("output/matchups.csv", index=False)
    with open("output/meta.json", "w", encoding="utf-8") as f:
        json.dump({"league": league.settings.name, "year": league.year,
                   "weeks": league.current_week - 1}, f)

    pd.set_option("display.width", 200, "display.max_columns", None)
    print(f"Weeks 1-{league.current_week - 1}\n")
    print(season[["starters_projected", "starters_actual", "starters_diff",
                  "bench_diff", "total_diff"]])


if __name__ == "__main__":
    main()
