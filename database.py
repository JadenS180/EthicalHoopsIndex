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
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parent / "ehi.db"


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create all tables if they do not already exist, then run any pending migrations."""
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
                SSS         REAL,
                EHI         REAL NOT NULL,
                UNIQUE(player_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS shots (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id   TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                shot_zone TEXT NOT NULL,
                made      INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_shots_game ON shots(game_id);
            CREATE INDEX IF NOT EXISTS idx_shots_zone ON shots(shot_zone);

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
        _migrate_db(conn)


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema without dropping existing data."""
    for col_def in [
        "ALTER TABLE player_games ADD COLUMN position TEXT",
        "ALTER TABLE player_games ADD COLUMN SSS REAL",
    ]:
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass  # column already exists


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


def save_shots(shots_df: pd.DataFrame, game_id: str) -> int:
    """
    Save shot-chart rows for one game to the shots table.
    Clears any existing shots for this game first (idempotent).
    Returns the number of rows written.
    """
    if shots_df.empty:
        return 0

    rows = []
    for _, s in shots_df.iterrows():
        try:
            pid  = int(s["PLAYER_ID"])
            zone = str(s.get("SHOT_ZONE_BASIC", "")).lower().strip()
            made = int(s.get("SHOT_MADE_FLAG", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if zone:
            rows.append((game_id, pid, zone, made))

    if not rows:
        return 0

    with get_connection() as conn:
        conn.execute("DELETE FROM shots WHERE game_id = ?", (game_id,))
        conn.executemany(
            "INSERT INTO shots (game_id, player_id, shot_zone, made) VALUES (?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def save_player_results(df: pd.DataFrame, game_id: str, date: str) -> int:
    """
    Upsert one row per player in df.
    Returns the number of rows written.
    """
    rows = []
    for _, r in df.iterrows():
        sss_val = r.get("SSS")
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
            float(sss_val) if sss_val is not None else None,
            float(r["EHI"]),
            str(r.get("position", "forward")),
        ))

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO player_games
               (player_id, player_name, team, game_id, date,
                minutes, points, SQS, FDS, FTP, SPS, DES, SSS, EHI, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)
