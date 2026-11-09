"""Build output/site/index.html (deployed to GitHub Pages) from the CSVs written by metrics.py."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("output")
SITE = OUT / "site"


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


def power_scores(tw: pd.DataFrame, through: int) -> pd.Series:
    """0-100 per team through `through` week.

    - 60% season all-play win %
    - 10% all-play win % over the last 3 weeks (recent form)
    - 30% actual win %
    """
    tw = tw[tw.week <= through]

    def allplay_pct(df):
        g = df.groupby("team")[["allplay_wins", "allplay_losses"]].sum()
        return g.allplay_wins / (g.allplay_wins + g.allplay_losses)

    win_pct = tw.groupby("team").result.apply(lambda r: ((r == "W") + 0.5 * (r == "T")).mean())
    return 100 * (0.6 * allplay_pct(tw) + 0.1 * allplay_pct(tw[tw.week > through - 3]) + 0.3 * win_pct)


def power_history(tw: pd.DataFrame) -> list[dict]:
    """Per-team power score, rank, and record through each week (for browsing past recaps)."""
    out, prev_ranks = [], {}
    for through in sorted(tw.week.unique()):
        sub = tw[tw.week <= through]
        power = power_scores(tw, through)
        rank = power.rank(ascending=False, method="first")
        for team, g in sub.groupby("team"):
            out.append({
                "week": int(through),
                "team": team,
                "rank": int(rank[team]),
                "rank_prev": prev_ranks.get(team),
                "power": round(float(power[team]), 1),
                "wins": int((g.result == "W").sum()),
                "losses": int((g.result == "L").sum()),
                "ties": int((g.result == "T").sum()),
                "pf": round(float(g.score.sum()), 1),
                "allplay_wins": float(g.allplay_wins.sum()),
                "allplay_losses": float(g.allplay_losses.sum()),
                "form": "".join(g.sort_values("week").result.tail(3)),
            })
        prev_ranks = {team: int(rank[team]) for team in rank.index}
    return out


def playoff_odds(tw: pd.DataFrame, schedule: pd.DataFrame, playoff_teams: int, sims: int = 10_000) -> pd.DataFrame:
    """Monte Carlo of the remaining regular season.

    - Each sim draws a team's true mean ~ Normal(season mean, SD / sqrt(games)), so small samples aren't treated as exact
    - Weekly score ~ Normal(true mean, league-wide SD around team means)
    - Seeds by wins, then PF (league tiebreaker); top 2 seeds get a bye
    """
    teams = sorted(tw.team.unique())
    idx = {t: i for i, t in enumerate(teams)}
    g = tw.groupby("team")
    mean = g.score.mean().reindex(teams).to_numpy()
    n = g.size().reindex(teams).to_numpy()
    sd = (tw.score - g.score.transform("mean")).std() or tw.score.std()  # 1 week played: no within-team spread yet
    wins = np.tile(g.result.apply(lambda r: ((r == "W") + 0.5 * (r == "T")).sum()).reindex(teams).to_numpy(), (sims, 1))
    pf = np.tile(g.score.sum().reindex(teams).to_numpy(), (sims, 1))

    rng = np.random.default_rng(0)  # deterministic between rebuilds
    true_mean = rng.normal(mean, sd / np.sqrt(n), (sims, len(teams)))
    remaining = schedule[schedule.week > tw.week.max()]
    for _, wk in remaining.groupby("week"):
        scores = rng.normal(true_mean, sd)
        pf += scores
        for a, b in wk[wk.team < wk.opponent][["team", "opponent"]].itertuples(index=False):
            i, j = idx[a], idx[b]
            wins[:, i] += scores[:, i] > scores[:, j]
            wins[:, j] += scores[:, j] > scores[:, i]

    seed = (-(wins + pf / 1e6)).argsort(axis=1).argsort(axis=1) + 1  # 1 = top seed
    opp_mean = remaining.opponent.map(dict(zip(teams, mean)))
    return pd.DataFrame({
        "team": teams,
        "avg": mean,
        "proj_wins": wins.mean(axis=0),
        "playoff_pct": (seed <= playoff_teams).mean(axis=0),
        "bye_pct": (seed <= 2).mean(axis=0),
        "remaining": remaining.groupby("team").size().reindex(teams, fill_value=0).to_numpy(),
        # Opponents' avg score; 0 once no games remain (NaN would break the page's JSON)
        "sos": opp_mean.groupby(remaining.team).mean().reindex(teams).fillna(0).to_numpy(),
    })


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
    s["started_projected"] = started.groupby(key).projected.sum()
    s["started_actual"] = started.groupby(key).actual.sum()
    s["started_diff"] = s.started_actual - s.started_projected
    s["bench_pts"] = bench.groupby(key).actual.sum()
    return s.fillna(0).reset_index()


def top_starters(players: pd.DataFrame) -> pd.DataFrame:
    """Highest-scoring starter each week."""
    started = players[players.group == "starters"]
    top = started.loc[started.groupby("week").actual.idxmax()]
    return top[["week", "player", "position", "team", "projected", "actual"]]


def main():
    players = pd.read_csv(OUT / "players.csv")
    weekly = pd.read_csv(OUT / "weekly.csv")
    matchups = pd.read_csv(OUT / "matchups.csv")
    schedule = pd.read_csv(OUT / "schedule.csv")
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))

    tw = team_weeks(weekly, matchups, lineup_metrics(players))
    # Season stats use the regular season only; weekly recaps include the playoffs
    reg_weeks = meta["reg_season_weeks"]
    reg = tw[tw.week <= reg_weeks]
    data = {
        "meta": meta,
        "teams": season_teams(reg).round(3).to_dict("records"),
        "power_by_week": power_history(reg),
        "odds": playoff_odds(reg, schedule, meta["playoff_teams"]).round(3).to_dict("records"),
        "schedule": schedule.to_dict("records"),
        "weeks": tw.round(3).to_dict("records"),
        "players": season_players(players[players.week <= reg_weeks]).round(2).to_dict("records"),
        # Teams that played that week (excludes playoff byes, like the other recap awards)
        "top_starters": top_starters(players.merge(tw[["week", "team"]])).round(2).to_dict("records"),
    }

    payload = json.dumps(data).replace("</", "<\\/")
    html = Path("dashboard_template.html").read_text(encoding="utf-8").replace("__DATA__", payload)
    out = SITE / "index.html"
    SITE.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
