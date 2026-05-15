"""
run_validation.py
Runs the full EHI pipeline across 12 validation games and stores
every player's results in ehi.db.

Rate limiting: 2-second sleep between API calls, 5-second sleep between games.
"""

import sys
import time
import traceback

import pandas as pd

from nba_api.stats.endpoints import (
    leaguegamefinder,
    boxscoretraditionalv3,
    playbyplayv3,
    shotchartdetail,
    boxscorehustlev2,
    playerdashptshots,
)
from nba_api.stats.library.http import NBAStatsHTTP

import compute_ehi
import database
from config import HEADERS

NBAStatsHTTP.headers = HEADERS

SLEEP_API  = 2   # seconds between API calls
SLEEP_GAME = 5   # seconds between games


# ─── 12 VALIDATION GAMES ─────────────────────────────────────────────────────
# team_id : NBA team ID used to locate the game via LeagueGameFinder.
# date    : MM/DD/YYYY  (LeagueGameFinder date_from / date_to format)

VALIDATION_GAMES = [
    {"label": "DAL vs ATL",  "team_id": 1610612742, "date": "01/26/2024"},
    {"label": "DET vs LAC",  "team_id": 1610612765, "date": "12/28/2025"},
    {"label": "MIN vs DEN",  "team_id": 1610612750, "date": "04/01/2025"},
    {"label": "IND vs OKC",  "team_id": 1610612754, "date": "10/23/2025"},
    {"label": "MIL vs PHI",  "team_id": 1610612749, "date": "11/20/2025"},
    {"label": "DET vs WAS",  "team_id": 1610612765, "date": "11/10/2025"},
    {"label": "HOU vs OKC",  "team_id": 1610612745, "date": "10/21/2025"},
    {"label": "LAL vs CLE",  "team_id": 1610612747, "date": "03/31/2026"},
    {"label": "SAS vs DAL",  "team_id": 1610612759, "date": "10/22/2025"},
    {"label": "MIL vs IND",  "team_id": 1610612749, "date": "12/23/2023"},
    {"label": "HOU vs NYK",  "team_id": 1610612745, "date": "01/23/2019"},
    {"label": "GSW vs POR",  "team_id": 1610612744, "date": "01/03/2021"},
]


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _infer_season(date_mmddyyyy: str) -> str:
    """'MM/DD/YYYY' → NBA season string, e.g. '2023-24'."""
    month, _day, year = (int(x) for x in date_mmddyyyy.split("/"))
    start = year if month >= 9 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _parse_matchup(matchup: str, searched_tricode: str) -> tuple[str, str]:
    """
    LeagueGameFinder matchup strings:
      'ABC vs. XYZ'  →  ABC is home
      'ABC @ XYZ'    →  ABC is away (XYZ is home)

    searched_tricode is the team whose ID was passed to LeagueGameFinder
    (always appears as the left side of the matchup string).
    Returns (home_tricode, away_tricode).
    """
    if " vs. " in matchup:
        parts = matchup.split(" vs. ")
        return parts[0].strip(), parts[1].strip()
    if " @ " in matchup:
        parts = matchup.split(" @ ")
        return parts[1].strip(), parts[0].strip()
    return searched_tricode, "UNK"


# ─── STEP 1: Locate the game ──────────────────────────────────────────────────

def find_game(
    team_id: int,
    date: str,
    season: str,
    label: str,
) -> dict:
    """
    Use LeagueGameFinder to locate a specific game.
    Returns {"game_id", "date", "home_team", "away_team", "season"}.
    """
    print(f"  [1/6] LeagueGameFinder — {label} on {date} …")
    resp = leaguegamefinder.LeagueGameFinder(
        team_id_nullable=team_id,
        date_from_nullable=date,
        date_to_nullable=date,
        timeout=60,
    )
    time.sleep(SLEEP_API)

    games = resp.get_data_frames()[0]
    if games.empty:
        raise ValueError(f"No game found for team_id={team_id} on {date}")

    row = games.iloc[0]
    game_id  = str(row["GAME_ID"])
    matchup  = str(row.get("MATCHUP", ""))
    raw_date = str(row.get("GAME_DATE", date))

    # Derive home/away tricodes from the matchup string
    searched_tricode = matchup.split(" vs. ")[0].split(" @ ")[0].strip()
    home_team, away_team = _parse_matchup(matchup, searched_tricode)

    print(f"       game_id={game_id}  matchup={matchup}  date={raw_date}")
    return {
        "game_id":   game_id,
        "date":      raw_date,
        "home_team": home_team,
        "away_team": away_team,
        "season":    season,
    }


# ─── STEP 2–6: Pull all raw data ─────────────────────────────────────────────

def _pull_shot_chart_with_retry(game_id: str, tid: int) -> tuple[pd.DataFrame, bool]:
    """
    Fetch ShotChartDetail for one team with one automatic retry on failure.

    On the first exception, sleeps 10 s then tries once more.
    Returns (DataFrame, failed) — failed=True means both attempts raised.
    The normal SLEEP_API delay is honoured on success; a best-effort sleep
    is still taken on failure so we don't hammer the API.
    """
    for attempt in (1, 2):
        try:
            resp = shotchartdetail.ShotChartDetail(
                team_id=tid,
                player_id=0,
                game_id_nullable=game_id,
                context_measure_simple="FGA",
                timeout=60,
            )
            time.sleep(SLEEP_API)
            return resp.get_data_frames()[0], False
        except Exception as exc:
            time.sleep(SLEEP_API)  # keep rate limiting even on failure
            if attempt == 1:
                print(
                    f"       attempt 1 failed ({type(exc).__name__}: {exc}). "
                    f"Retrying in 10s …"
                )
                time.sleep(10)
            else:
                print(
                    f"       attempt 2 failed ({type(exc).__name__}: {exc}). "
                    f"Giving up — shot chart will be skipped."
                )
                return pd.DataFrame(), True
    return pd.DataFrame(), True  # unreachable; satisfies type checker


def _pull_proximity_with_retry(player_box: pd.DataFrame, season: str) -> pd.DataFrame:
    """
    Fetch PlayerDashPtShots proximity data (result set [4]) for all teams.
    One call per team; player_id=0 returns all players on the team.
    Uses season-level data (per-game date filtering returns 0 rows).
    On any failure, returns an empty DataFrame so FDS falls back to +0.25 flat.
    """
    team_ids = player_box["teamId"].dropna().unique().tolist()
    frames: list[pd.DataFrame] = []
    for tid in team_ids:
        for attempt in (1, 2):
            try:
                resp = playerdashptshots.PlayerDashPtShots(
                    player_id=0,
                    team_id=int(tid),
                    season=season,
                    per_mode_simple="Totals",
                    timeout=60,
                )
                time.sleep(SLEEP_API)
                df = resp.get_data_frames()[4]
                frames.append(df)
                print(f"       proximity: {len(df)} rows for team {int(tid)}")
                break
            except Exception as exc:
                time.sleep(SLEEP_API)
                if attempt == 1:
                    print(f"       proximity attempt 1 failed ({type(exc).__name__}). Retrying in 10s …")
                    time.sleep(10)
                else:
                    print(f"       proximity attempt 2 failed — skipping team {int(tid)}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def pull_game_data(game_id: str, season: str) -> tuple[dict, bool]:
    """
    Pull BoxScoreTraditionalV3, PlayByPlayV3, ShotChartDetail (both teams),
    BoxScoreHustleV2, and PlayerDashPtShots proximity for the given game.

    Returns (data_dict, shots_failed).
      data_dict    : compatible with compute_ehi.compute_all()
      shots_failed : True if ShotChartDetail could not be fetched after retry;
                     in that case shots is an empty DataFrame and SQS will
                     fall back to the neutral baseline (50) for all players.
    """
    # ── Player box ───────────────────────────────────────────────────────────
    print(f"  [2/6] BoxScoreTraditionalV3 …")
    resp = boxscoretraditionalv3.BoxScoreTraditionalV3(
        game_id=game_id,
        timeout=60,
    )
    time.sleep(SLEEP_API)

    players = resp.get_data_frames()[0].copy()

    if {"fieldGoalsMade", "threePointersMade"}.issubset(players.columns):
        players["twoPointersMade"] = (
            players["fieldGoalsMade"] - players["threePointersMade"]
        )
    if {"fieldGoalsAttempted", "threePointersAttempted"}.issubset(players.columns):
        players["twoPointersAttempted"] = (
            players["fieldGoalsAttempted"] - players["threePointersAttempted"]
        )

    desired = [
        "personId", "firstName", "familyName", "nameI",
        "teamId", "teamTricode", "position",
        "minutes", "points",
        "fieldGoalsMade", "fieldGoalsAttempted",
        "freeThrowsMade", "freeThrowsAttempted",
        "twoPointersMade", "twoPointersAttempted",
        "threePointersMade", "threePointersAttempted",
        "reboundsOffensive", "reboundsDefensive", "reboundsTotal",
        "assists", "steals", "blocks",
        "turnovers", "foulsPersonal",
        "plusMinusPoints",
    ]
    available = [c for c in desired if c in players.columns]
    players   = players[available]
    print(f"       {len(players)} player rows, {len(available)} columns")

    # ── Play-by-play ──────────────────────────────────────────────────────────
    print(f"  [3/6] PlayByPlayV3 …")
    resp = playbyplayv3.PlayByPlayV3(
        game_id=game_id,
        timeout=60,
    )
    time.sleep(SLEEP_API)
    pbp = resp.get_data_frames()[0]
    print(f"       {len(pbp)} play-by-play rows")

    # ── Shot charts (one per team, with retry on failure) ────────────────────
    team_ids = players["teamId"].dropna().unique().tolist()
    shots_list: list[pd.DataFrame] = []
    shots_failed = False
    for call_num, tid in enumerate(team_ids, 4):
        print(f"  [{call_num}/6] ShotChartDetail (team {int(tid)}) …")
        df_shots, failed = _pull_shot_chart_with_retry(game_id, int(tid))
        if failed:
            shots_failed = True
            shots_list = []   # discard any partial data; SQS will use baseline
            print("       shot chart unavailable — SQS will use neutral baseline (50)")
            break
        shots_list.append(df_shots)
        print(f"       {len(df_shots)} shot rows")

    shots = pd.concat(shots_list, ignore_index=True) if shots_list else pd.DataFrame()

    # ── Hustle ────────────────────────────────────────────────────────────────
    hustle_step = len(team_ids) + 4   # 6 if 2 teams
    print(f"  [{hustle_step}/7] BoxScoreHustleV2 …")
    resp = boxscorehustlev2.BoxScoreHustleV2(
        game_id=game_id,
        timeout=60,
    )
    time.sleep(SLEEP_API)
    hustle = resp.get_data_frames()[0]
    print(f"       {len(hustle)} hustle rows")

    # ── Proximity (PlayerDashPtShots, per team) ───────────────────────────────
    print(f"  [7/7] PlayerDashPtShots proximity (season={season}) …")
    proximity = _pull_proximity_with_retry(players, season)
    if proximity.empty:
        print("       proximity unavailable — FDS will use flat +0.25 fallback")
    else:
        print(f"       {len(proximity)} proximity rows")

    data = {
        "game_id":      game_id,
        "game_summary": {},   # not consumed by compute_ehi.compute_all
        "player_box":   players,
        "pbp":          pbp,
        "shots":        shots,
        "hustle":       hustle,
        "proximity":    proximity,
    }
    return data, shots_failed


# ─── GAME RUNNER ──────────────────────────────────────────────────────────────

def run_game(spec: dict, game_num: int, total: int) -> None:
    """
    Full pipeline for one validation game: find → pull → compute → save.
    Errors are caught and logged; the loop continues to the next game.
    """
    label = spec["label"]
    date  = spec["date"]
    season = _infer_season(date)

    print()
    print(f"{'='*65}")
    print(f"Game {game_num}/{total}: {label}  ({date})  season={season}")
    print(f"{'='*65}")

    try:
        # Locate game
        meta = find_game(spec["team_id"], date, season, label)
        game_id = meta["game_id"]

        # Pull raw data
        data, shots_failed = pull_game_data(game_id, season)

        # Compute EHI — empty shots DataFrame causes SQS to fall back to 50
        print("  Computing EHI …")
        results, _detail = compute_ehi.compute_all(data)
        active_players = len(results)
        print(f"  {active_players} active players computed")

        # Save to database
        database.save_game(
            game_id   = game_id,
            date      = meta["date"],
            home_team = meta["home_team"],
            away_team = meta["away_team"],
            season    = season,
        )
        saved = database.save_player_results(results, game_id, meta["date"])

        if shots_failed:
            database.save_validation_note(
                game_id            = game_id,
                player_name        = "ALL",
                expected_direction = "neutral",
                notes              = "SQS unavailable - shot chart data missing for this game",
            )
            print("  Validation note saved: SQS unavailable for this game")

        print(f"  Saved {saved} player rows to ehi.db")
        print(f"  Done: {label} — {saved} players saved  (game_id={game_id})")

    except Exception:
        print(f"  ERROR processing {label}:")
        traceback.print_exc()


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main() -> None:
    # Optional: pass 1-indexed game numbers as CLI args to run a subset.
    # e.g.  python3 run_validation.py 12        → game 12 only
    #        python3 run_validation.py 11 12     → games 11 and 12
    #        python3 run_validation.py            → all 12 games
    selected = {int(a) for a in sys.argv[1:]} if len(sys.argv) > 1 else None
    games_to_run = [
        (i, spec)
        for i, spec in enumerate(VALIDATION_GAMES, 1)
        if selected is None or i in selected
    ]

    print("EHI Validation Run")
    print(f"Processing {len(games_to_run)} game(s) → ehi.db")

    database.init_db()
    print("Database initialised.")

    for run_idx, (i, spec) in enumerate(games_to_run):
        run_game(spec, i, len(VALIDATION_GAMES))
        if run_idx < len(games_to_run) - 1:
            print(f"\n  Sleeping {SLEEP_GAME}s before next game …")
            time.sleep(SLEEP_GAME)

    print()
    print("=" * 65)
    print("Validation run complete.")
    print("=" * 65)


if __name__ == "__main__":
    main()
