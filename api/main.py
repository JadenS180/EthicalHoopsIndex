import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="EthicalHoopsIndex API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent.parent / "ehi.db")))
MIN_GAMES = 20
MIN_MINUTES = 8

VALID_SORT_COLUMNS = {
    "avg_EHI", "avg_SQS", "avg_FDS", "avg_FTP", "avg_SPS", "avg_DES", "avg_SSS",
    "avg_pts", "gp", "player_name",
}

HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ─── /api/seasons ─────────────────────────────────────────────────────────────

@app.get("/api/seasons")
def get_seasons():
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT season FROM games ORDER BY season DESC"
        ).fetchall()
    return {"seasons": [r["season"] for r in rows]}


# ─── /api/season/{season}/summary ─────────────────────────────────────────────

@app.get("/api/season/{season}/summary")
def get_season_summary(season: str):
    with _db() as conn:
        league = conn.execute(
            """
            SELECT AVG(pg.EHI) AS avg_ehi, COUNT(*) AS n_rows
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            """,
            (season, MIN_MINUTES),
        ).fetchone()

        if not league or league["avg_ehi"] is None:
            raise HTTPException(status_code=404, detail=f"No data for season {season}")

        top_games = conn.execute(
            """
            SELECT pg.player_id, pg.player_name, pg.team,
                   CASE WHEN pg.team = g.home_team THEN g.away_team ELSE g.home_team END AS opponent,
                   pg.date, g.game_id, pg.points, pg.EHI,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES, COALESCE(pg.SSS, 0.0) AS SSS
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            ORDER BY pg.EHI DESC LIMIT 10
            """,
            (season, MIN_MINUTES),
        ).fetchall()

        bot_games = conn.execute(
            """
            SELECT pg.player_id, pg.player_name, pg.team,
                   CASE WHEN pg.team = g.home_team THEN g.away_team ELSE g.home_team END AS opponent,
                   pg.date, g.game_id, pg.points, pg.EHI,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES, COALESCE(pg.SSS, 0.0) AS SSS
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            ORDER BY pg.EHI ASC LIMIT 10
            """,
            (season, MIN_MINUTES),
        ).fetchall()

        team_rows = conn.execute(
            """
            SELECT pg.team,
                   AVG(pg.EHI)                    AS avg_ehi,
                   AVG(pg.SQS)                    AS avg_SQS,
                   AVG(pg.FDS)                    AS avg_FDS,
                   AVG(pg.FTP)                    AS avg_FTP,
                   AVG(pg.SPS)                    AS avg_SPS,
                   AVG(pg.DES)                    AS avg_DES,
                   AVG(COALESCE(pg.SSS, 0.0))     AS avg_SSS,
                   COUNT(DISTINCT pg.game_id)      AS gp,
                   AVG(pg.points)                 AS avg_pts
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            GROUP BY pg.team
            ORDER BY avg_ehi DESC
            """,
            (season, MIN_MINUTES),
        ).fetchall()

    def _game_row(r):
        d = _row_to_dict(r)
        d["headshot_url"] = HEADSHOT_URL.format(player_id=d["player_id"])
        return d

    return {
        "season": season,
        "league_avg_ehi": round(league["avg_ehi"], 4),
        "player_game_count": league["n_rows"],
        "top_10_games": [_game_row(r) for r in top_games],
        "bottom_10_games": [_game_row(r) for r in bot_games],
        "teams": [_row_to_dict(r) for r in team_rows],
    }


# ─── /api/season/{season}/players ─────────────────────────────────────────────

@app.get("/api/season/{season}/players")
def get_season_players(
    season: str,
    role: Optional[str] = Query(None, description="star | role | bench"),
    team: Optional[str] = Query(None),
    sort_by: str = Query("avg_EHI"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    min_games: int = Query(1),
):
    if sort_by not in VALID_SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by. Choose from: {sorted(VALID_SORT_COLUMNS)}")

    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    ppg_filter = ""
    if role == "star":
        ppg_filter = "HAVING avg_pts >= 15"
    elif role == "role":
        ppg_filter = "HAVING avg_pts >= 8 AND avg_pts < 15"
    elif role == "bench":
        ppg_filter = "HAVING avg_pts < 8"
    elif role is not None:
        raise HTTPException(status_code=400, detail="role must be 'star', 'role', or 'bench'")

    with _db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                pg.player_id,
                pg.player_name,
                (
                    SELECT pg2.team FROM player_games pg2
                    JOIN games g2 USING (game_id)
                    WHERE pg2.player_id = pg.player_id AND g2.season = ?
                    ORDER BY g2.date DESC LIMIT 1
                ) AS team,
                (
                    SELECT pg3.position FROM player_games pg3
                    JOIN games g3 USING (game_id)
                    WHERE pg3.player_id = pg.player_id AND g3.season = ?
                    ORDER BY g3.date DESC LIMIT 1
                ) AS position,
                COUNT(*)                       AS gp,
                AVG(pg.points)                 AS avg_pts,
                AVG(pg.SQS)                    AS avg_SQS,
                AVG(pg.FDS)                    AS avg_FDS,
                AVG(pg.FTP)                    AS avg_FTP,
                AVG(pg.SPS)                    AS avg_SPS,
                AVG(pg.DES)                    AS avg_DES,
                AVG(COALESCE(pg.SSS, 0.0))     AS avg_SSS,
                AVG(pg.EHI)                    AS avg_EHI,
                MIN(pg.EHI)                    AS min_EHI,
                MAX(pg.EHI)                    AS max_EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ?
            GROUP BY pg.player_id, pg.player_name
            HAVING gp >= ?
            {ppg_filter}
            ORDER BY {sort_by} {order_sql}
            """,
            (season, season, season, min_games),
        ).fetchall()

    players = []
    for r in rows:
        d = _row_to_dict(r)
        if team and (d.get("team") or "").upper() != team.upper():
            continue
        d["headshot_url"] = HEADSHOT_URL.format(player_id=d["player_id"])
        for key in ("avg_pts", "avg_SQS", "avg_FDS", "avg_FTP", "avg_SPS", "avg_DES", "avg_SSS", "avg_EHI", "min_EHI", "max_EHI"):
            if d[key] is not None:
                d[key] = round(d[key], 2)
        players.append(d)

    return {"season": season, "count": len(players), "players": players}


# ─── /api/player/{player_name}/season/{season} ────────────────────────────────

@app.get("/api/player/{player_name}/season/{season}")
def get_player_season(player_name: str, season: str):
    with _db() as conn:
        names = conn.execute(
            "SELECT DISTINCT player_name FROM player_games WHERE LOWER(player_name) LIKE LOWER(?)",
            (f"%{player_name}%",),
        ).fetchall()

        matched = [r["player_name"] for r in names]
        if not matched:
            raise HTTPException(status_code=404, detail=f"No player matching '{player_name}'")

        exact = [n for n in matched if n.lower() == player_name.lower()]
        resolved = exact[0] if exact else (matched[0] if len(matched) == 1 else None)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Ambiguous name '{player_name}' matched: {matched}. Be more specific.",
            )

        row = conn.execute(
            """
            SELECT
                pg.player_id,
                pg.player_name,
                (
                    SELECT pg2.team FROM player_games pg2
                    JOIN games g2 USING (game_id)
                    WHERE pg2.player_id = pg.player_id AND g2.season = ?
                    ORDER BY g2.date DESC LIMIT 1
                ) AS team,
                (
                    SELECT pg3.position FROM player_games pg3
                    JOIN games g3 USING (game_id)
                    WHERE pg3.player_id = pg.player_id AND g3.season = ?
                    ORDER BY g3.date DESC LIMIT 1
                ) AS position,
                COUNT(*)                       AS gp,
                AVG(pg.points)                 AS avg_pts,
                AVG(pg.SQS)                    AS avg_SQS,
                AVG(pg.FDS)                    AS avg_FDS,
                AVG(pg.FTP)                    AS avg_FTP,
                AVG(pg.SPS)                    AS avg_SPS,
                AVG(pg.DES)                    AS avg_DES,
                AVG(COALESCE(pg.SSS, 0.0))     AS avg_SSS,
                AVG(pg.EHI)                    AS avg_EHI,
                MIN(pg.EHI)                    AS min_EHI,
                MAX(pg.EHI)                    AS max_EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE LOWER(pg.player_name) = LOWER(?) AND g.season = ?
            GROUP BY pg.player_id, pg.player_name
            """,
            (season, season, resolved, season),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"No data for '{resolved}' in {season}")

        game_log = conn.execute(
            """
            SELECT pg.game_id, g.date,
                   g.home_team, g.away_team,
                   pg.minutes, pg.points,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES, COALESCE(pg.SSS, 0.0) AS SSS, pg.EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE LOWER(pg.player_name) = LOWER(?) AND g.season = ?
            ORDER BY g.date ASC
            """,
            (resolved, season),
        ).fetchall()

    d = _row_to_dict(row)
    d["headshot_url"] = HEADSHOT_URL.format(player_id=d["player_id"])
    for key in ("avg_pts", "avg_SQS", "avg_FDS", "avg_FTP", "avg_SPS", "avg_DES", "avg_SSS", "avg_EHI", "min_EHI", "max_EHI"):
        if d[key] is not None:
            d[key] = round(d[key], 2)

    d["game_log"] = [_row_to_dict(r) for r in game_log]
    d["season"] = season
    return d


# ─── /api/game/{game_id}/leaderboard ──────────────────────────────────────────

@app.get("/api/game/{game_id}/leaderboard")
def get_game_leaderboard(game_id: str):
    with _db() as conn:
        game = conn.execute(
            "SELECT game_id, date, home_team, away_team, season FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()

        if not game:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        players = conn.execute(
            """
            SELECT pg.player_id, pg.player_name, pg.team,
                   COALESCE(pg.position, 'forward') AS position,
                   pg.minutes, pg.points,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES,
                   COALESCE(pg.SSS, 0.0) AS SSS,
                   pg.EHI
            FROM player_games pg
            WHERE pg.game_id = ?
            ORDER BY pg.EHI DESC
            """,
            (game_id,),
        ).fetchall()

    if not players:
        raise HTTPException(status_code=404, detail=f"No player data for game {game_id}")

    player_list = []
    for r in players:
        d = _row_to_dict(r)
        d["headshot_url"] = HEADSHOT_URL.format(player_id=d["player_id"])
        player_list.append(d)

    return {
        "game_id": game["game_id"],
        "date": game["date"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "season": game["season"],
        "players": player_list,
    }


# ─── /api/season/{season}/best-games ──────────────────────────────────────────

@app.get("/api/season/{season}/best-games")
def get_best_games(season: str, n: int = Query(50, ge=1, le=500)):
    return _top_games(season, n, ascending=False)


@app.get("/api/season/{season}/worst-games")
def get_worst_games(season: str, n: int = Query(50, ge=1, le=500)):
    return _top_games(season, n, ascending=True)


def _top_games(season: str, n: int, ascending: bool) -> dict:
    order_sql = "ASC" if ascending else "DESC"
    with _db() as conn:
        rows = conn.execute(
            f"""
            SELECT pg.player_id, pg.player_name, pg.team,
                   CASE WHEN pg.team = g.home_team THEN g.away_team ELSE g.home_team END AS opponent,
                   g.game_id, g.date, pg.minutes, pg.points,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES, COALESCE(pg.SSS, 0.0) AS SSS, pg.EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            ORDER BY pg.EHI {order_sql}
            LIMIT ?
            """,
            (season, MIN_MINUTES, n),
        ).fetchall()

    games = []
    for r in rows:
        d = _row_to_dict(r)
        d["headshot_url"] = HEADSHOT_URL.format(player_id=d["player_id"])
        games.append(d)

    return {"season": season, "count": len(games), "games": games}


# ─── /api/season/{season}/teams ───────────────────────────────────────────────

@app.get("/api/season/{season}/teams")
def get_season_teams(season: str):
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT pg.team,
                   AVG(pg.EHI)                    AS avg_EHI,
                   AVG(pg.SQS)                    AS avg_SQS,
                   AVG(pg.FDS)                    AS avg_FDS,
                   AVG(pg.FTP)                    AS avg_FTP,
                   AVG(pg.SPS)                    AS avg_SPS,
                   AVG(pg.DES)                    AS avg_DES,
                   AVG(COALESCE(pg.SSS, 0.0))     AS avg_SSS,
                   COUNT(DISTINCT pg.game_id)      AS gp,
                   AVG(pg.points)                 AS avg_pts
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= ?
            GROUP BY pg.team
            ORDER BY avg_EHI DESC
            """,
            (season, MIN_MINUTES),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No team data for season {season}")

    teams = []
    for i, r in enumerate(rows, 1):
        d = _row_to_dict(r)
        d["rank"] = i
        for key in ("avg_EHI", "avg_SQS", "avg_FDS", "avg_FTP", "avg_SPS", "avg_DES", "avg_SSS", "avg_pts"):
            if d[key] is not None:
                d[key] = round(d[key], 2)
        teams.append(d)

    return {"season": season, "count": len(teams), "teams": teams}
