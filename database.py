"""
database.py — SQLite persistence layer for EHI validation results.

Tables
------
  games            : one row per game (metadata)
  player_games     : one row per player per game with all sub-scores
  validation_notes : manual annotations for expected EHI direction
"""

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "ehi.db"


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create all tables if they do not already exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                game_id     TEXT PRIMARY KEY,
                date        TEXT NOT NULL,
                home_team   TEXT NOT NULL,
                away_team   TEXT NOT NULL,
                season      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS player_games (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                team        TEXT NOT NULL,
                game_id     TEXT NOT NULL,
                date        TEXT NOT NULL,
                minutes     REAL NOT NULL,
                points      INTEGER NOT NULL,
                SQS         REAL NOT NULL,
                FDS         REAL NOT NULL,
                FTP         REAL NOT NULL,
                SPS         REAL NOT NULL,
                DES         REAL NOT NULL,
                EHI         REAL NOT NULL,
                UNIQUE(player_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS validation_notes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id             TEXT NOT NULL,
                player_name         TEXT NOT NULL,
                expected_direction  TEXT NOT NULL
                    CHECK(expected_direction IN ('high', 'low', 'neutral')),
                notes               TEXT,
                FOREIGN KEY (game_id) REFERENCES games(game_id)
            );
        """)


def save_game(
    game_id: str,
    date: str,
    home_team: str,
    away_team: str,
    season: str,
) -> None:
    """Upsert a game record."""
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO games
               (game_id, date, home_team, away_team, season)
               VALUES (?, ?, ?, ?, ?)""",
            (game_id, date, home_team, away_team, season),
        )


def save_validation_note(
    game_id: str,
    player_name: str,
    expected_direction: str,
    notes: str,
) -> None:
    """Insert one row into validation_notes. expected_direction must be 'high', 'low', or 'neutral'."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO validation_notes
               (game_id, player_name, expected_direction, notes)
               VALUES (?, ?, ?, ?)""",
            (game_id, player_name, expected_direction, notes),
        )


def save_player_results(df: pd.DataFrame, game_id: str, date: str) -> int:
    """
    Upsert one row per player in df.
    Returns the number of rows written.
    """
    rows = []
    for _, r in df.iterrows():
        rows.append((
            int(r["personId"]),
            str(r["player"]),
            str(r["team"]),
            game_id,
            date,
            float(r["min"]),
            int(r["pts"]),
            float(r["SQS"]),
            float(r["FDS"]),
            float(r["FTP"]),
            float(r["SPS"]),
            float(r["DES"]),
            float(r["EHI"]),
        ))

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO player_games
               (player_id, player_name, team, game_id, date,
                minutes, points, SQS, FDS, FTP, SPS, DES, EHI)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)
