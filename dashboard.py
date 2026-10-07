"""Build docs/index.html (published via GitHub Pages) from the CSVs written by metrics.py."""

import json
from pathlib import Path

import pandas as pd

OUT = Path("output")
DOCS = Path("docs")


def best_lineup(roster: pd.DataFrame, slots: list[str], rank_by: str) -> list:
    """Row labels of the lineup that maximizes `rank_by` (greedy, narrowest slots first)."""
    used = []
    for slot in slots:
        cands = roster[roster.eligible.apply(lambda e: slot in e) & ~roster.index.isin(used)]
        if not cands.empty:
            used.append(cands[rank_by].idxmax())
    return used


def lineup_metrics(players: pd.DataFrame) -> pd.DataFrame:
    players = players.assign(eligible=players.eligible.str.split("|"))
    starters = players[players.group == "starters"]

    # League lineup = most common set of starting slots
    slots = starters.groupby(["week", "team"]).slot.apply(lambda s: tuple(sorted(s))).mode()[0]
    # Fill narrowest slots first (e.g. RB before RB/WR/TE) so greedy is optimal
    breadth = {s: players[players.eligible.apply(lambda e: s in e)].position.nunique() for s in set(slots)}
    slots = sorted(slots, key=breadth.get)

    rows = []
    for (week, team), roster in players.groupby(["week", "team"]):
        rows.append({
            "week": week,
            "team": team,
            "optimal": roster.loc[best_lineup(roster, slots, "actual"), "actual"].sum(),
            "espn_lineup": roster.loc[best_lineup(roster, slots, "projected"), "actual"].sum(),
        })
    return pd.DataFrame(rows)


def team_weeks(weekly: pd.DataFrame, matchups: pd.DataFrame, lineups: pd.DataFrame) -> pd.DataFrame:
    home = matchups.rename(columns={"home": "team", "away": "opponent", "home_score": "score", "away_score": "opp_score"})
    away = matchups.rename(columns={"away": "team", "home": "opponent", "away_score": "score", "home_score": "opp_score"})
    tw = pd.concat([home, away]).merge(weekly, on=["week", "team"]).merge(lineups, on=["week", "team"])

    tw["result"] = tw.apply(lambda r: "W" if r.score > r.opp_score else "L" if r.score < r.opp_score else "T", axis=1)
    # All-play: record if you'd played every other team that week
    n_opp = tw.groupby("week").team.transform("count") - 1
    rank = tw.groupby("week").score.rank(method="average")  # ties count as half
    tw["allplay_wins"] = rank - 1
    tw["allplay_losses"] = n_opp - tw.allplay_wins
    tw["exp_wins"] = tw.allplay_wins / n_opp
    tw["lineup_vs_espn"] = tw.starters_actual - tw.espn_lineup
    tw["bench_left"] = tw.optimal - tw.starters_actual
    return tw


def season_teams(tw: pd.DataFrame) -> pd.DataFrame:
    g = tw.groupby("team")
    s = g[[
        "score", "opp_score", "allplay_wins", "allplay_losses", "exp_wins",
        "starters_projected", "starters_actual", "starters_diff",
        "bench_projected", "bench_actual", "bench_diff",
        "total_projected", "total_actual", "total_diff",
        "optimal", "espn_lineup", "lineup_vs_espn", "bench_left",
    ]].sum()
    for res, col in (("W", "wins"), ("L", "losses"), ("T", "ties")):
        s[col] = g.result.apply(lambda r: (r == res).sum())
    s["luck"] = s.wins + 0.5 * s.ties - s.exp_wins
    s["efficiency"] = s.starters_actual / s.optimal
    return s.rename(columns={"score": "pf", "opp_score": "pa"}).reset_index()


def season_players(players: pd.DataFrame) -> pd.DataFrame:
    players = players.sort_values("week")
    started = players[players.group == "starters"]
    bench = players[players.group == "bench"]
    # One row per player per fantasy team (players can change teams mid-season)
    key = ["player", "team"]
    s = players.groupby(key).agg(
        position=("position", "last"),
        nfl=("pro_team", "last"),
        weeks=("week", "count"),
        projected=("projected", "sum"),
        actual=("actual", "sum"),
    )
    s["diff"] = s.actual - s.projected
    s["started"] = started.groupby(key).week.count()
    s["started_diff"] = (started.actual - started.projected).groupby([started.player, started.team]).sum()
    s["bench_pts"] = bench.groupby(key).actual.sum()
    return s.fillna(0).reset_index()


def main():
    players = pd.read_csv(OUT / "players.csv")
    weekly = pd.read_csv(OUT / "weekly.csv")
    matchups = pd.read_csv(OUT / "matchups.csv")
    meta = json.loads((OUT / "meta.json").read_text())

    tw = team_weeks(weekly, matchups, lineup_metrics(players))
    data = {
        "meta": meta,
        "teams": season_teams(tw).round(3).to_dict("records"),
        "weeks": tw.round(3).to_dict("records"),
        "players": season_players(players).round(2).to_dict("records"),
    }

    payload = json.dumps(data).replace("</", "<\\/")
    html = Path("dashboard_template.html").read_text().replace("__DATA__", payload)
    out = DOCS / "index.html"
    DOCS.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
