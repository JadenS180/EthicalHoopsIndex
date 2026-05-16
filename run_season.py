"""
run_season.py — 2025-26 Regular Season EHI run.

Fetches every regular-season game from LeagueGameFinder, skips games already
in ehi.db, and processes the rest using the same pipeline/compute logic as
run_validation.py.

Rate limiting : 2-second sleep after every API call, 5-second sleep between games.
Retries       : up to 3 attempts per call; rate-limit errors sleep 60s, others
                use exponential backoff (10s → 20s → 40s).
Error logging : failures written to season_errors.log with timestamp + game details.
ShotChartDetail failure : SQS falls back to neutral baseline (50) for all players.
"""

import sys
import time
import traceback
import logging

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

SEASON      = "2025-26"
SEASON_TYPE = "Regular Season"
SLEEP_API   = 2    # seconds between every API call
SLEEP_GAME  = 5    # seconds between games
MAX_RETRIES = 3    # attempts per API call before giving up


# ─── ERROR LOGGING ────────────────────────────────────────────────────────────

_error_logger = logging.getLogger("season_errors")
_error_logger.setLevel(logging.ERROR)
_fh = logging.FileHandler("season_errors.log")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
_error_logger.addHandler(_fh)


def _log_error(game_id: str, matchup: str, message: str) -> None:
    _error_logger.error(f"game_id={game_id}  matchup={matchup}  {message}")


# ─── RETRY HELPERS ────────────────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many" in msg


def _with_retry(fn, label: str = ""):
    """
    Call fn() with up to MAX_RETRIES attempts.
    Rate limit errors → sleep 60s then retry.
    Other errors → exponential backoff: 10s, 20s, 40s.
    Sleeps SLEEP_API after every attempt to keep rate limiting.
    Returns the result, or raises on the final attempt.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = fn()
            time.sleep(SLEEP_API)
            return result
        except Exception as exc:
            time.sleep(SLEEP_API)
            if attempt == MAX_RETRIES:
                raise
            if _is_rate_limit(exc):
                wait = 60
                print(f"       [{label}] rate limit — sleeping {wait}s (attempt {attempt}/{MAX_RETRIES}) …")
            else:
                wait = 10 * (2 ** (attempt - 1))   # 10s, 20s
                print(f"       [{label}] {type(exc).__name__} attempt {attempt} — sleeping {wait}s …")
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ─── SEASON GAME INDEX ────────────────────────────────────────────────────────

def fetch_season_games() -> list[dict]:
    """
    Return a deduplicated, date-sorted list of all regular-season games.
    Each entry: {game_id, date, home_team, away_team}.

    LeagueGameFinder returns one row per team per game.  We deduplicate by
    game_id, preferring the "vs." row (home perspective) to derive home/away.
    """
    print(f"Fetching {SEASON} {SEASON_TYPE} game list from LeagueGameFinder …")

    def _fetch():
        return leaguegamefinder.LeagueGameFinder(
            season_nullable=SEASON,
            season_type_nullable=SEASON_TYPE,
            timeout=90,
        ).get_data_frames()[0]

    df = _with_retry(_fetch, label="LeagueGameFinder(season)")

    if df.empty:
        raise ValueError(f"LeagueGameFinder returned no games for {SEASON} {SEASON_TYPE}")

    home_rows: dict[str, dict] = {}   # game_id → from home (vs.) perspective
    fallback:  dict[str, dict] = {}   # game_id → from away (@) perspective

    for _, row in df.iterrows():
        gid     = str(row["GAME_ID"])
        matchup = str(row.get("MATCHUP", ""))
        date    = str(row.get("GAME_DATE", ""))

        if " vs. " in matchup:
            parts = matchup.split(" vs. ")
            home, away = parts[0].strip(), parts[1].strip()
            home_rows[gid] = {"game_id": gid, "date": date, "home_team": home, "away_team": away}
        elif gid not in fallback:
            if " @ " in matchup:
                parts = matchup.split(" @ ")
                away, home = parts[0].strip(), parts[1].strip()
            else:
                home, away = "UNK", "UNK"
            fallback[gid] = {"game_id": gid, "date": date, "home_team": home, "away_team": away}

    # Prefer home-perspective rows; fill any gaps with fallback
    merged = {**fallback, **home_rows}
    games  = sorted(merged.values(), key=lambda g: g["date"])
    print(f"  Found {len(games)} unique {SEASON} {SEASON_TYPE} games.")
    return games


def _already_in_db(game_id: str) -> bool:
    with database.get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM games WHERE game_id = ?", (game_id,)
        ).fetchone() is not None


# ─── GAME DATA PULLING ────────────────────────────────────────────────────────

def _pull_box(game_id: str) -> pd.DataFrame:
    def _fetch():
        return boxscoretraditionalv3.BoxScoreTraditionalV3(
            game_id=game_id, timeout=60
        ).get_data_frames()[0]

    players = _with_retry(_fetch, label="BoxScoreTraditionalV3").copy()

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
    return players[available]


def _pull_pbp(game_id: str) -> pd.DataFrame:
    def _fetch():
        return playbyplayv3.PlayByPlayV3(
            game_id=game_id, timeout=60
        ).get_data_frames()[0]
    return _with_retry(_fetch, label="PlayByPlayV3")


def _pull_shot_chart(game_id: str, team_id: int) -> tuple[pd.DataFrame, bool]:
    """Returns (shots_df, failed). failed=True → all retries exhausted."""
    tid = team_id

    def _fetch():
        return shotchartdetail.ShotChartDetail(
            team_id=tid,
            player_id=0,
            game_id_nullable=game_id,
            context_measure_simple="FGA",
            timeout=60,
        ).get_data_frames()[0]

    try:
        return _with_retry(_fetch, label=f"ShotChartDetail(team={tid})"), False
    except Exception as exc:
        print(
            f"       ShotChartDetail failed for team {tid} after {MAX_RETRIES} attempts"
            f" ({type(exc).__name__}) — SQS will use neutral baseline (50)"
        )
        return pd.DataFrame(), True


def _pull_hustle(game_id: str) -> pd.DataFrame:
    def _fetch():
        return boxscorehustlev2.BoxScoreHustleV2(
            game_id=game_id, timeout=60
        ).get_data_frames()[0]
    return _with_retry(_fetch, label="BoxScoreHustleV2")


def _pull_proximity(player_box: pd.DataFrame) -> pd.DataFrame:
    team_ids = player_box["teamId"].dropna().unique().tolist()
    frames: list[pd.DataFrame] = []

    for tid in team_ids:
        def _fetch(tid=tid):
            return playerdashptshots.PlayerDashPtShots(
                player_id=0,
                team_id=int(tid),
                season=SEASON,
                per_mode_simple="Totals",
                timeout=60,
            ).get_data_frames()[4]

        try:
            df = _with_retry(_fetch, label=f"PlayerDashPtShots(team={int(tid)})")
            print(f"       proximity: {len(df)} rows for team {int(tid)}")
            frames.append(df)
        except Exception as exc:
            print(
                f"       proximity failed for team {int(tid)}"
                f" ({type(exc).__name__}) — FDS will use flat +0.25"
            )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def pull_game_data(game_id: str) -> tuple[dict, bool]:
    """
    Pull BoxScoreTraditionalV3, PlayByPlayV3, ShotChartDetail (both teams),
    BoxScoreHustleV2, and PlayerDashPtShots proximity for one game.

    Returns (data_dict, shots_failed).
    shots_failed=True means ShotChartDetail failed after retries; SQS will
    fall back to the neutral baseline (50) for all players.
    """
    print("  [1/6] BoxScoreTraditionalV3 …")
    player_box = _pull_box(game_id)
    print(f"       {len(player_box)} player rows")

    print("  [2/6] PlayByPlayV3 …")
    pbp = _pull_pbp(game_id)
    print(f"       {len(pbp)} play-by-play rows")

    team_ids = player_box["teamId"].dropna().unique().tolist()
    shots_list: list[pd.DataFrame] = []
    shots_failed = False

    for step, tid in enumerate(team_ids, 3):
        print(f"  [{step}/6] ShotChartDetail (team {int(tid)}) …")
        df_shots, failed = _pull_shot_chart(game_id, int(tid))
        if failed:
            shots_failed = True
            shots_list   = []
            break
        shots_list.append(df_shots)
        print(f"       {len(df_shots)} shots")

    shots = pd.concat(shots_list, ignore_index=True) if shots_list else pd.DataFrame()

    hustle_step = len(team_ids) + 3   # 5 if 2 teams, 6 if only 1
    print(f"  [{hustle_step}/7] BoxScoreHustleV2 …")
    hustle = _pull_hustle(game_id)
    print(f"       {len(hustle)} hustle rows")

    print("  [7/7] PlayerDashPtShots (proximity) …")
    proximity = _pull_proximity(player_box)
    if proximity.empty:
        print("       proximity unavailable — FDS using flat +0.25")
    else:
        print(f"       {len(proximity)} proximity rows total")

    return {
        "game_id":      game_id,
        "game_summary": {},
        "player_box":   player_box,
        "pbp":          pbp,
        "shots":        shots,
        "hustle":       hustle,
        "proximity":    proximity,
    }, shots_failed


# ─── GAME RUNNER ──────────────────────────────────────────────────────────────

def run_game(meta: dict, game_num: int, total: int, stats: dict) -> None:
    """
    Full pipeline for one game: pull → compute → save.
    Updates stats dict in place.
    Any unhandled exception is logged to season_errors.log; the loop continues.
    """
    game_id = meta["game_id"]
    matchup = f"{meta['home_team']} vs {meta['away_team']}"
    date    = meta["date"]

    print()
    print("=" * 65)
    print(f"Game {game_num}/{total} — {matchup}  ({date})  game_id={game_id}")
    print("=" * 65)

    if _already_in_db(game_id):
        print("  Already in ehi.db — skipping.")
        stats["skipped"] += 1
        return

    try:
        data, shots_failed = pull_game_data(game_id)

        print("  Computing EHI …")
        results, _detail = compute_ehi.compute_all(data)
        n_active = len(results)
        print(f"  {n_active} active players computed")

        database.save_game(
            game_id   = game_id,
            date      = date,
            home_team = meta["home_team"],
            away_team = meta["away_team"],
            season    = SEASON,
        )
        shots_saved = database.save_shots(data["shots"], game_id)
        saved       = database.save_player_results(results, game_id, date) if not results.empty else 0

        if shots_failed:
            database.save_validation_note(
                game_id            = game_id,
                player_name        = "ALL",
                expected_direction = "neutral",
                notes              = "SQS unavailable — ShotChartDetail failed after retries",
            )

        stats["games_processed"] += 1
        stats["players_saved"]   += saved
        stats["ehi_values"].extend(results["EHI"].tolist())

        print(f"  Saved {saved} player rows, {shots_saved} shot rows to ehi.db.")
        print(f"  Game {game_num}/{total} — {matchup} — {saved} players saved")

    except Exception as exc:
        tb  = traceback.format_exc()
        msg = f"{type(exc).__name__}: {exc}"
        print(f"  ERROR: {msg}")
        _log_error(game_id, matchup, f"{msg}\n{tb}")
        stats["failed"].append(f"{matchup}  {date}  game_id={game_id}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print(f"EHI Season Run — {SEASON} {SEASON_TYPE}")
    print("=" * 65)

    database.init_db()
    print("Database initialised.")
    compute_ehi.print_empirical_xefg_table()

    games = fetch_season_games()
    total = len(games)

    # Optional CLI subset: python3 run_season.py START END  (1-indexed, inclusive)
    # e.g.  python3 run_season.py 1 50   → process games 1–50
    if len(sys.argv) == 3:
        try:
            lo = int(sys.argv[1]) - 1
            hi = int(sys.argv[2])
            games = games[lo:hi]
            print(f"  Running subset: games {sys.argv[1]}–{sys.argv[2]} ({len(games)} games)")
        except ValueError:
            print("  Usage: python3 run_season.py [START END]  (1-indexed)")
            sys.exit(1)

    total = len(games)
    stats: dict = {
        "games_processed": 0,
        "players_saved":   0,
        "skipped":         0,
        "failed":          [],
        "ehi_values":      [],
    }

    for idx, meta in enumerate(games, 1):
        run_game(meta, idx, total, stats)
        if idx < total:
            print(f"\n  Sleeping {SLEEP_GAME}s before next game …")
            time.sleep(SLEEP_GAME)

    # ── Completion summary ────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print(f"Season Run Complete — {SEASON} {SEASON_TYPE}")
    print("=" * 65)
    print(f"  Games processed  : {stats['games_processed']}")
    print(f"  Games skipped    : {stats['skipped']}  (already in DB)")
    print(f"  Games failed     : {len(stats['failed'])}")
    print(f"  Players saved    : {stats['players_saved']}")

    ehis = stats["ehi_values"]
    if ehis:
        print(f"  EHI range        : {min(ehis):.2f} – {max(ehis):.2f}")
        print(f"  EHI mean         : {sum(ehis) / len(ehis):.2f}")

    if stats["failed"]:
        print()
        print(f"  Failed games ({len(stats['failed'])}):")
        for f in stats["failed"]:
            print(f"    {f}")
        print("  See season_errors.log for full tracebacks.")

    print("=" * 65)

    # Print season summary from DB once the overnight run finishes.
    print()
    try:
        from query_ehi import get_season_summary
        get_season_summary(SEASON)
    except Exception as exc:
        print(f"  (Season summary skipped: {exc})")


if __name__ == "__main__":
    main()
