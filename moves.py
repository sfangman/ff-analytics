"""Pull rosters, free agents, and schedules for the /top-moves skill; writes output/moves/.

Env vars: same as metrics.py, plus
- ESPN_TEAM_ID (optional; defaults to the team owned by ESPN_SWID)
"""

import json
import os
from datetime import datetime

import pandas as pd
from espn_api.football.constant import PRO_TEAM_MAP

from metrics import load_league

FREE_AGENTS = {"QB": 10, "RB": 30, "WR": 30, "TE": 15, "D/ST": 8, "K": 5}  # pulled per position
POSITION_IDS = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5, "D/ST": 16}  # ESPN defaultPositionId
RECENT_WEEKS = 3
UPCOMING_GAMES = 4
OUT = "output/moves"


def find_my_team(league):
    if team_id := os.environ.get("ESPN_TEAM_ID"):
        return league.get_team_data(int(team_id))
    swid = os.environ.get("ESPN_SWID", "").upper()
    return next(t for t in league.teams if any(o.get("id", "").upper() == swid for o in t.owners))


def weekly_points(league, ids, weeks) -> pd.DataFrame:
    """Actual and ESPN-projected points per player per week."""
    rows = []
    for w in weeks:
        f = {"players": {"filterIds": {"value": ids}}}
        data = league.espn_request.league_get(
            params={"view": "kona_player_info", "scoringPeriodId": w},
            headers={"x-fantasy-filter": json.dumps(f)},
        )
        for p in data["players"]:
            pts = {
                s["statSourceId"]: s.get("appliedTotal", 0)
                for s in p["player"].get("stats", [])
                if s.get("scoringPeriodId") == w and s.get("seasonId") == league.year
            }
            if 1 in pts:  # no projection = bye
                rows.append({"id": p["id"], "week": w, "actual": pts.get(0, 0), "projected": pts[1]})
    return pd.DataFrame(rows)


def upcoming(player, schedule, ratings, next_week, last_week) -> dict:
    """Next opponents with ESPN opponent rank vs position (1 = toughest, 32 = easiest) and next bye."""
    team_id = next((k for k, v in PRO_TEAM_MAP.items() if v == player.proTeam), None)
    games = schedule.get(team_id, {})
    pos_ratings = ratings.get(str(POSITION_IDS.get(player.position)), {})
    opps, bye = [], None
    for w in range(next_week, last_week + 1):
        game = (games.get(str(w)) or [None])[0]
        if game is None:
            bye = bye or w
        elif len(opps) < UPCOMING_GAMES:
            opp = game["awayProTeamId"] if game["homeProTeamId"] == team_id else game["homeProTeamId"]
            opps.append((w, PRO_TEAM_MAP[opp], pos_ratings.get(str(opp))))
    ranks = [r for _, _, r in opps if r]
    return {
        "next_opp_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
        "next_games": " ".join(f"{w}:{o}({r or '-'})" for w, o, r in opps),
        "bye": bye,
    }


def team_strength(players: pd.DataFrame, slots: dict) -> pd.DataFrame:
    """League rank (1 = best) of each team's starters by ESPN projected avg, per position."""
    ranks = {}
    for pos in ("QB", "RB", "WR", "TE"):
        top = (
            players[(players.pos == pos) & (players.team != "FA")]
            .sort_values("espn_avg", ascending=False)
            .groupby("team").head(slots.get(pos, 1))
            .groupby("team").espn_avg.sum()
        )
        ranks[f"{pos.lower()}_rank"] = top.rank(ascending=False, method="min").astype(int)
    return pd.DataFrame(ranks)


def main():
    league = load_league()
    me = find_my_team(league)
    s = league.settings
    completed = range(1, league.current_week)
    last_week = s.reg_season_count

    pool = [(t.team_name, p) for t in league.teams for p in t.roster]
    pool += [("FA", p) for pos, n in FREE_AGENTS.items() for p in league.free_agents(size=n, position=pos)]
    ids = [p.playerId for _, p in pool]

    weekly = weekly_points(league, ids, completed)
    weekly["diff"] = weekly.actual - weekly.projected
    recent = weekly[weekly.week > league.current_week - 1 - RECENT_WEEKS]
    totals = weekly.groupby("id")[["actual", "projected", "diff"]].sum().rename(
        columns={"actual": "pts", "projected": "proj"})
    totals["gp"] = weekly[weekly.projected > 0].groupby("id").size()
    totals["diff_recent"] = recent.groupby("id")["diff"].sum()

    schedule = league._get_all_pro_schedule()
    now = datetime.now().timestamp() * 1000
    games = pd.DataFrame([
        {"week": int(w), "future": g[0]["date"] > now}
        for team_games in schedule.values() for w, g in team_games.items() if g
    ])
    future_share = games.groupby("week").future.mean()
    next_week = int(future_share[future_share > 0.5].index.min())  # first week mostly unplayed
    ratings = league._get_positional_ratings(league.current_week)

    rows = []
    for team, p in pool:
        rows.append({
            "id": p.playerId,
            "team": team,
            "mine": team == me.team_name,
            "player": p.name,
            "pos": p.position,
            "nfl": p.proTeam,
            "slot": p.lineupSlot or "FA",
            "status": p.injuryStatus,
            "own_pct": p.percent_owned,
            "start_pct": p.percent_started,
            "avg": p.avg_points,
            "espn_avg": p.projected_avg_points,
            **upcoming(p, schedule, ratings, next_week, last_week),
        })
    players = pd.DataFrame(rows).join(totals, on="id").drop(columns="id").round(2)
    players["gp"] = players.gp.fillna(0).astype(int)

    teams = pd.DataFrame([{
        "team": t.team_name,
        "mine": t.team_id == me.team_id,
        "wins": t.wins,
        "losses": t.losses,
        "pf": round(t.points_for, 2),
        "pa": t.points_against,
        "standing": t.standing,
        "playoff_pct": round(t.playoff_pct, 1),
        "waiver_rank": t.waiver_rank,
        "faab_left": s.acquisition_budget - t.acquisition_budget_spent if s.faab else None,
    } for t in league.teams]).set_index("team")
    teams = teams.join(team_strength(players, s.position_slot_counts)).sort_values("standing")

    os.makedirs(OUT, exist_ok=True)
    players.to_csv(f"{OUT}/players.csv", index=False)
    teams.to_csv(f"{OUT}/teams.csv")
    with open(f"{OUT}/league.json", "w") as f:
        json.dump({
            "league": s.name,
            "my_team": me.team_name,
            "last_completed_week": league.current_week - 1,
            "next_week": next_week,
            "reg_season_weeks": last_week,
            "playoff_teams": s.playoff_team_count,
            "trade_deadline": datetime.fromtimestamp(s.trade_deadline / 1000).date().isoformat()
            if s.trade_deadline else None,
            "faab": s.faab,
            "points_per_reception": next((x["points"] for x in s.scoring_format if x["abbr"] == "REC"), 0),
            "roster_slots": {k: v for k, v in s.position_slot_counts.items() if v},
        }, f, indent=2)

    print(f"{me.team_name} ({me.wins}-{me.losses}); weeks 1-{league.current_week - 1}; "
          f"{len(players)} players -> {OUT}/")


if __name__ == "__main__":
    main()
