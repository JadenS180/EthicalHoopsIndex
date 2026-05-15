"""
EHI Data Pipeline
Pulls all raw data needed to compute the Ethical Hoops Index for every
player in Bam Adebayo's 83-point game: Heat vs Wizards, 2026-03-10.

Data collected
--------------
  BoxScoreTraditionalV3  — per-player stats (pts, FGM/A, FTM/A, 2PM/A, 3PM/A,
                           MIN, REB, STL, BLK, PF)
  PlayByPlayV3           — full play log for foul-type classification
  ShotChartDetail        — shot distance, zone, made/missed, assisted flag
                           (per team; player_id=0 returns all shots on that team)
  BoxScoreHustleV2       — contested shots defended, deflections, charges taken
  BoxScoreSummaryV3      — game-level metadata / confirmation

Rate limiting: 1-second sleep after every API call.
"""

import time
import pandas as pd

from nba_api.stats.endpoints import (
    leaguegamefinder,
    boxscoresummaryv3,
    boxscoretraditionalv3,
    playbyplayv3,
    shotchartdetail,
    boxscorehustlev2,
    playerdashptshots,
)
from nba_api.stats.library.http import NBAStatsHTTP

from config import HEADERS

# Patch the shared session headers once so every endpoint picks them up.
# Passing headers= per-endpoint only works when the endpoint's own
# NBAStatsHTTP instance hasn't already cached a session; patching the
# class-level dict is the reliable path.
NBAStatsHTTP.headers = HEADERS

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
HEAT_ID    = 1610612748
WIZARDS_ID = 1610612764

# LeagueGameFinder expects MM/DD/YYYY
GAME_DATE  = "03/10/2026"

SLEEP_SEC  = 1  # sleep between every API call


def _sleep() -> None:
    time.sleep(SLEEP_SEC)


# ─── STEP 1: Locate the game ──────────────────────────────────────────────────

def find_game_id() -> str:
    """Return the GAME_ID string for Heat vs Wizards on 2026-03-10."""
    print("Step 1 — LeagueGameFinder: locating Heat vs Wizards 2026-03-10 …")
    resp = leaguegamefinder.LeagueGameFinder(
        team_id_nullable=HEAT_ID,
        date_from_nullable=GAME_DATE,
        date_to_nullable=GAME_DATE,
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    games = resp.get_data_frames()[0]
    if games.empty:
        raise ValueError(
            f"No Heat game found on {GAME_DATE}. "
            "Verify the date or check NBA schedule."
        )

    row = games.iloc[0]
    game_id = str(row["GAME_ID"])
    print(
        f"  ✓ game_id={game_id}  matchup={row['MATCHUP']}  "
        f"pts={row.get('PTS', '?')}  ({len(games)} game(s) returned)"
    )
    return game_id


# ─── STEP 2: Game summary (BoxScoreSummaryV3) ─────────────────────────────────

def pull_game_summary(game_id: str) -> dict[str, pd.DataFrame]:
    """
    BoxScoreSummaryV3 — game-level metadata.
    Returns a dict keyed by result-set name (e.g. 'GameSummary', 'LineScore').
    """
    print("Step 2 — BoxScoreSummaryV3: game metadata …")
    resp = boxscoresummaryv3.BoxScoreSummaryV3(
        game_id=game_id,
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    frames = resp.get_data_frames()
    raw    = resp.get_dict()

    # V3 uses "resultSets" (list of dicts with "name" key)
    result_sets = raw.get("resultSets", raw.get("resultSet", []))
    if isinstance(result_sets, dict):
        result_sets = [result_sets]

    result: dict[str, pd.DataFrame] = {}
    for i, rs in enumerate(result_sets):
        name = rs.get("name", f"frame_{i}")
        result[name] = frames[i]
        print(f"  ✓ {name}: {len(frames[i])} row(s)")

    return result


# ─── STEP 3: Player box score (BoxScoreTraditionalV3) ─────────────────────────

def pull_player_box(game_id: str) -> pd.DataFrame:
    """
    BoxScoreTraditionalV3 — per-player stats for every player in the game.
    Derives twoPointersMade / twoPointersAttempted from FGM - 3PM.
    """
    print("Step 3 — BoxScoreTraditionalV3: per-player stats …")
    resp = boxscoretraditionalv3.BoxScoreTraditionalV3(
        game_id=game_id,
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    frames  = resp.get_data_frames()
    players = frames[0].copy()   # frame 0 = player stats, frame 1 = team stats

    # Derive 2PM and 2PA (not directly returned by the endpoint)
    if {"fieldGoalsMade", "threePointersMade"}.issubset(players.columns):
        players["twoPointersMade"] = (
            players["fieldGoalsMade"] - players["threePointersMade"]
        )
    if {"fieldGoalsAttempted", "threePointersAttempted"}.issubset(players.columns):
        players["twoPointersAttempted"] = (
            players["fieldGoalsAttempted"] - players["threePointersAttempted"]
        )

    # Columns required by EHI sub-scores
    desired = [
        "personId", "firstName", "familyName", "nameI",
        "teamId", "teamTricode", "position",
        "minutes",
        "points",
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

    print(
        f"  ✓ player rows: {len(players)}  "
        f"columns ({len(available)}): {available}"
    )
    return players


# ─── STEP 4: Play-by-play (PlayByPlayV3) ──────────────────────────────────────

def pull_play_by_play(game_id: str) -> pd.DataFrame:
    """
    PlayByPlayV3 — full play log.
    actionType / subType / description fields are used downstream to
    classify fouls as: defensive, offensive, loose ball, technical,
    flagrant, illegal screen, delay of game.
    """
    print("Step 4 — PlayByPlayV3: full play log …")
    resp = playbyplayv3.PlayByPlayV3(
        game_id=game_id,
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    pbp = resp.get_data_frames()[0]
    print(
        f"  ✓ play-by-play rows: {len(pbp)}  "
        f"columns: {list(pbp.columns)}"
    )
    return pbp


# ─── STEP 5: Shot chart (ShotChartDetail, per team) ───────────────────────────

def pull_shot_chart(game_id: str, team_id: int, label: str) -> pd.DataFrame:
    """
    ShotChartDetail (FGA context) for one team.
    player_id=0 returns all shots for the specified team in the game.

    Provides per-shot: SHOT_DISTANCE, SHOT_ZONE_BASIC, SHOT_ZONE_AREA,
    SHOT_ZONE_RANGE, EVENT_TYPE (Made/Missed), SHOT_TYPE (2PT/3PT),
    ACTION_TYPE (layup, pull-up, etc.), LOC_X, LOC_Y, PLAYER_ID, PLAYER_NAME.

    Note: per-shot defender distance is not available in ShotChartDetail.
    Contested-shot counts come from BoxScoreHustleV2. Assisted-vs-self-created
    is derived from the PlayByPlayV3 assist records.
    """
    print(f"Step 5 — ShotChartDetail ({label}) …")
    resp = shotchartdetail.ShotChartDetail(
        team_id=team_id,
        player_id=0,
        game_id_nullable=game_id,
        context_measure_simple="FGA",
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    shots = resp.get_data_frames()[0]
    print(
        f"  ✓ {label} shots: {len(shots)} rows  "
        f"columns: {list(shots.columns)}"
    )
    return shots


# ─── STEP 6: Hustle stats (BoxScoreHustleV2) ─────────────────────────────────

def pull_hustle(game_id: str) -> pd.DataFrame:
    """
    BoxScoreHustleV2 — per-player hustle stats for every player in the game.
    Key fields for EHI DES: contestedShots (or 2pt/3pt variants),
    deflections, chargesTaken.
    """
    print("Step 6 — BoxScoreHustleV2: hustle stats …")
    resp = boxscorehustlev2.BoxScoreHustleV2(
        game_id=game_id,
        headers=HEADERS,
        timeout=60,
    )
    _sleep()

    hustle = resp.get_data_frames()[0]   # frame 0 = player hustle

    # Request all hustle columns that exist; don't hard-filter yet so the
    # caller can see the full schema and pick what they need.
    print(
        f"  ✓ hustle rows: {len(hustle)}  "
        f"columns: {list(hustle.columns)}"
    )
    return hustle


# ─── STEP 7: Defender proximity (PlayerDashPtShots, per team) ────────────────

def pull_proximity(player_box: pd.DataFrame, season: str) -> pd.DataFrame:
    """
    PlayerDashPtShots result set [4] — CLOSE_DEF_DIST_RANGE per player.

    Calls once per team with player_id=0 (returns all players on the team).
    Season-level data is used as a proxy because per-game date filtering
    returns 0 rows from this endpoint.

    Returns a concatenated DataFrame with columns including PLAYER_ID and
    CLOSE_DEF_DIST_RANGE.
    """
    team_ids = player_box["teamId"].dropna().unique().tolist()
    frames: list[pd.DataFrame] = []

    for idx, tid in enumerate(team_ids, 1):
        print(f"Step 7 — PlayerDashPtShots (team {int(tid)}, {idx}/{len(team_ids)}) …")
        try:
            resp = playerdashptshots.PlayerDashPtShots(
                player_id=0,
                team_id=int(tid),
                season=season,
                per_mode_simple="Totals",
                timeout=60,
            )
            _sleep()
            df = resp.get_data_frames()[4]
            print(f"  ✓ {len(df)} proximity rows for team {int(tid)}")
            frames.append(df)
        except Exception as exc:
            _sleep()
            print(f"  ! PlayerDashPtShots failed for team {int(tid)}: {exc}")

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> dict:
    print("=" * 65)
    print("EHI Data Pipeline — Bam Adebayo 83-pt game, 2026-03-10")
    print("=" * 65)

    # Every function sleeps 1 s after its API call internally.
    game_id = find_game_id()

    game_summary  = pull_game_summary(game_id)
    player_box    = pull_player_box(game_id)
    pbp           = pull_play_by_play(game_id)
    heat_shots    = pull_shot_chart(game_id, HEAT_ID,    "Heat")
    wizards_shots = pull_shot_chart(game_id, WIZARDS_ID, "Wizards")
    hustle        = pull_hustle(game_id)

    # Infer season for proximity lookup
    month, _day, year = (int(x) for x in GAME_DATE.split("/"))
    season_start = year if month >= 9 else year - 1
    season = f"{season_start}-{str(season_start + 1)[-2:]}"
    proximity = pull_proximity(player_box, season)

    all_shots = pd.concat([heat_shots, wizards_shots], ignore_index=True)

    print()
    print("=" * 65)
    print("ALL DATA SOURCES PULLED SUCCESSFULLY")
    print(f"  game_id               : {game_id}")
    print(f"  players in box score  : {len(player_box)}")
    print(f"  play-by-play events   : {len(pbp)}")
    print(f"  total shot attempts   : {len(all_shots)}")
    print(f"    Heat shots          : {len(heat_shots)}")
    print(f"    Wizards shots       : {len(wizards_shots)}")
    print(f"  hustle stat rows      : {len(hustle)}")
    print(f"  proximity rows        : {len(proximity)}")
    print("=" * 65)

    return {
        "game_id":      game_id,
        "game_summary": game_summary,   # dict[str, pd.DataFrame]
        "player_box":   player_box,     # pd.DataFrame — all players, both teams
        "pbp":          pbp,            # pd.DataFrame — full play log
        "shots":        all_shots,      # pd.DataFrame — all FGA, both teams
        "hustle":       hustle,         # pd.DataFrame — hustle stats, all players
        "proximity":    proximity,      # pd.DataFrame — defender distance buckets
    }


if __name__ == "__main__":
    data = main()
