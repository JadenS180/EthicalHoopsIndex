"""
query_ehi.py — EHI database query utilities.

CLI usage
---------
  python3 query_ehi.py player       <name>   <season>           season averages
  python3 query_ehi.py player-game  <name>   <date YYYY-MM-DD>  single game breakdown
  python3 query_ehi.py game         <date>   <team1>  <team2>   game leaderboard
  python3 query_ehi.py season-best  <season> [n]                top N by avg EHI
  python3 query_ehi.py season-worst <season> [n]                bottom N by avg EHI
  python3 query_ehi.py summary      <season>                    full season summary

Examples:
  python3 query_ehi.py player       'Luka Doncic'  2025-26
  python3 query_ehi.py player-game  'Luka Doncic'  2026-01-26
  python3 query_ehi.py game          2026-01-26    DAL  ATL
  python3 query_ehi.py season-best   2025-26       20
  python3 query_ehi.py season-worst  2025-26
  python3 query_ehi.py summary       2025-26
"""

import sys

from database import get_connection
from config import W_SQS, W_FDS, W_FTP, W_SPS, W_DES, W_SSS

MIN_GAMES = 20   # minimum games played to appear in season rankings


# ─── SHARED HELPERS ───────────────────────────────────────────────────────────

def _bar(fraction: float, width: int = 22) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "█" * filled + "░" * (width - filled)


def _resolve_player(raw: str, conn) -> str | None:
    """
    Case-insensitive substring match on player_name in the DB.
    Returns the single matched name, or None after printing disambiguation help.
    Prefers an exact case-insensitive match when multiple substrings are found.
    """
    rows = conn.execute(
        "SELECT DISTINCT player_name FROM player_games "
        "WHERE LOWER(player_name) LIKE LOWER(?)",
        (f"%{raw}%",),
    ).fetchall()
    names = [r[0] for r in rows]

    if not names:
        print(f"  No player found matching '{raw}'.")
        return None

    if len(names) == 1:
        return names[0]

    exact = [n for n in names if n.lower() == raw.lower()]
    if len(exact) == 1:
        return exact[0]

    print(f"  Ambiguous — '{raw}' matched {len(names)} players:")
    for n in sorted(names):
        print(f"    {n}")
    print("  Use a more specific name.")
    return None


def _ehi_components(sqs, fds, ftp, sps, des, sss=None):
    comps = [
        ("SQS", W_SQS, sqs),
        ("FDS", W_FDS, fds),
        ("FTP", W_FTP, ftp),
        ("SPS", W_SPS, sps),
        ("DES", W_DES, des),
    ]
    if sss is not None:
        comps.append(("SSS", W_SSS, sss))
    return comps


# ─── 1. GET_PLAYER_GAME ───────────────────────────────────────────────────────

def get_player_game(player_name: str, date: str) -> dict | None:
    """
    Print and return a full EHI breakdown for player_name on date (YYYY-MM-DD).

    Returns a dict with sub-scores and game metadata, or None if not found.
    The breakdown shows weighted contribution and bar chart for each component,
    matching the style of compute_ehi.print_bam_breakdown.
    """
    with get_connection() as conn:
        resolved = _resolve_player(player_name, conn)
        if not resolved:
            return None

        rows = conn.execute(
            """
            SELECT pg.player_name, pg.team, COALESCE(pg.position, '?') AS pos,
                   pg.date, pg.minutes, pg.points,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES,
                   COALESCE(pg.SSS, 0.0) AS SSS,
                   pg.EHI,
                   g.home_team, g.away_team, g.season
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE LOWER(pg.player_name) = LOWER(?) AND pg.date = ?
            """,
            (resolved, date),
        ).fetchall()

    if not rows:
        print(f"  No data for {resolved} on {date}.")
        return None

    r      = rows[0]
    name, team, pos, date_, min_, pts, sqs, fds, ftp, sps, des, sss, ehi, home, away, season = r
    matchup    = f"{home} vs {away}"
    components = _ehi_components(sqs, fds, ftp, sps, des, sss)
    BAR_W      = 22
    W          = 80

    print("\n" + "=" * W)
    print(f"EHI — {name} ({team}, {pos})  |  {matchup}  {date_}  |  {min_:.1f} min  {pts} pts")
    print(f"  EHI = {W_SQS}×SQS + {W_FDS}×FDS + {W_FTP}×FTP + {W_SPS}×SPS + {W_DES}×DES + {W_SSS}×SSS")
    print("=" * W)
    print(
        f"  {'Component':<12}{'Weight':>7}{'Raw':>8}{'Contrib':>9}{'MaxPoss':>9}"
        f"  Bar (contrib / max)"
    )
    print("  " + "─" * (W - 2))

    total_contrib = 0.0
    for comp, weight, raw in components:
        contrib   = weight * raw
        max_poss  = weight * 100.0
        total_contrib += contrib
        bar = _bar(contrib / max_poss, BAR_W)
        print(f"  {comp:<12}{weight:>7.2f}{raw:>8.1f}{contrib:>9.2f}{max_poss:>9.2f}  {bar}")

    print("  " + "─" * (W - 2))
    print(
        f"  {'EHI':<12}{'1.00':>7}{'—':>8}{total_contrib:>9.2f}{'100.00':>9}"
        f"  {_bar(total_contrib / 100.0, BAR_W)}"
    )
    print("=" * W)

    print(f"\n  Contribution share (of EHI {total_contrib:.2f}):")
    for comp, weight, raw in components:
        contrib = weight * raw
        share   = (contrib / total_contrib * 100) if total_contrib > 0 else 0
        gap     = (weight * 100.0) - contrib
        print(
            f"    {comp}  {contrib:5.2f} pts  ({share:5.1f}% of EHI)"
            f"  [{gap:+.2f} vs max {weight * 100:.0f}]"
        )
    print()

    return {
        "player": name, "team": team, "pos": pos,
        "date": date_, "matchup": matchup, "season": season,
        "min": min_, "pts": pts,
        "SQS": sqs, "FDS": fds, "FTP": ftp, "SPS": sps, "DES": des, "SSS": sss, "EHI": ehi,
    }


# ─── 2. GET_PLAYER_SEASON ─────────────────────────────────────────────────────

def get_player_season(player_name: str, season: str) -> dict | None:
    """
    Print and return season averages for player_name in the given season.

    Returns a dict with avg_SQS, avg_FDS, avg_FTP, avg_SPS, avg_DES,
    avg_EHI, gp, avg_pts, min_EHI, max_EHI; or None if not found.
    """
    with get_connection() as conn:
        resolved = _resolve_player(player_name, conn)
        if not resolved:
            return None

        rows = conn.execute(
            """
            SELECT pg.player_name,
                   AVG(pg.SQS), AVG(pg.FDS), AVG(pg.FTP),
                   AVG(pg.SPS), AVG(pg.DES),
                   AVG(COALESCE(pg.SSS, 0.0)),
                   AVG(pg.EHI),
                   COUNT(*) AS gp, AVG(pg.points),
                   MIN(pg.EHI), MAX(pg.EHI)
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE LOWER(pg.player_name) = LOWER(?) AND g.season = ?
            GROUP BY pg.player_id, pg.player_name
            """,
            (resolved, season),
        ).fetchall()

    if not rows:
        print(f"  No data for {resolved} in {season}.")
        return None

    r = rows[0]
    name, avg_sqs, avg_fds, avg_ftp, avg_sps, avg_des, avg_sss, avg_ehi, gp, avg_pts, min_ehi, max_ehi = r
    components = _ehi_components(avg_sqs, avg_fds, avg_ftp, avg_sps, avg_des, avg_sss)
    BAR_W      = 22
    W          = 80

    print("\n" + "=" * W)
    print(f"EHI — {name}  |  {season} Season Averages  ({gp} games)")
    print(f"  Avg PTS: {avg_pts:.1f}   EHI range: {min_ehi:.2f} – {max_ehi:.2f}")
    print(f"  EHI = {W_SQS}×SQS + {W_FDS}×FDS + {W_FTP}×FTP + {W_SPS}×SPS + {W_DES}×DES + {W_SSS}×SSS")
    print("=" * W)
    print(
        f"  {'Component':<12}{'Weight':>7}{'Avg Raw':>9}{'Contrib':>9}{'MaxPoss':>9}"
        f"  Bar (contrib / max)"
    )
    print("  " + "─" * (W - 2))

    total_contrib = 0.0
    for comp, weight, avg_raw in components:
        contrib   = weight * avg_raw
        max_poss  = weight * 100.0
        total_contrib += contrib
        bar = _bar(contrib / max_poss, BAR_W)
        print(f"  {comp:<12}{weight:>7.2f}{avg_raw:>9.1f}{contrib:>9.2f}{max_poss:>9.2f}  {bar}")

    print("  " + "─" * (W - 2))
    print(
        f"  {'avg EHI':<12}{'1.00':>7}{'—':>9}{avg_ehi:>9.2f}{'100.00':>9}"
        f"  {_bar(avg_ehi / 100.0, BAR_W)}"
    )
    print("=" * W)
    print()

    return {
        "player":  name,
        "season":  season,
        "gp":      gp,
        "avg_pts": round(avg_pts, 1),
        "avg_SQS": round(avg_sqs, 2),
        "avg_FDS": round(avg_fds, 2),
        "avg_FTP": round(avg_ftp, 2),
        "avg_SPS": round(avg_sps, 2),
        "avg_DES": round(avg_des, 2),
        "avg_SSS": round(avg_sss, 2),
        "avg_EHI": round(avg_ehi, 2),
        "min_EHI": round(min_ehi, 2),
        "max_EHI": round(max_ehi, 2),
    }


# ─── 3. GET_GAME_LEADERBOARD ──────────────────────────────────────────────────

def get_game_leaderboard(date: str, team1: str, team2: str) -> list[dict] | None:
    """
    Print and return the full EHI leaderboard for a specific game, sorted by EHI desc.

    team1 / team2 can be in either home/away order.
    Returns a list of dicts (one per player), or None if game not found.
    """
    t1, t2 = team1.upper(), team2.upper()

    with get_connection() as conn:
        game = conn.execute(
            """
            SELECT game_id, home_team, away_team, season
            FROM games
            WHERE date = ?
              AND (
                    (home_team = ? AND away_team = ?)
                 OR (home_team = ? AND away_team = ?)
              )
            """,
            (date, t1, t2, t2, t1),
        ).fetchone()

        if not game:
            # Partial date match fallback (tolerates YYYY-MM-DD vs stored format differences)
            game = conn.execute(
                """
                SELECT game_id, home_team, away_team, season
                FROM games
                WHERE date LIKE ?
                  AND home_team IN (?, ?) AND away_team IN (?, ?)
                """,
                (f"%{date}%", t1, t2, t1, t2),
            ).fetchone()

        if not game:
            print(f"  No game found: {t1} vs {t2} on {date}.")
            return None

        gid, home, away, season = game

        rows = conn.execute(
            """
            SELECT pg.player_name, pg.team, COALESCE(pg.position, '?') AS pos,
                   pg.minutes, pg.points,
                   pg.SQS, pg.FDS, pg.FTP, pg.SPS, pg.DES,
                   COALESCE(pg.SSS, 0.0) AS SSS,
                   pg.EHI
            FROM player_games pg
            WHERE pg.game_id = ?
            ORDER BY pg.EHI DESC
            """,
            (gid,),
        ).fetchall()

    if not rows:
        print(f"  No player data in DB for game_id={gid}.")
        return None

    matchup = f"{home} vs {away}"
    W       = 122
    print("\n" + "=" * W)
    print(f"EHI Leaderboard — {matchup}  {date}  ({season})")
    print(f"  EHI = {W_SQS}×SQS + {W_FDS}×FDS + {W_FTP}×FTP + {W_SPS}×SPS + {W_DES}×DES + {W_SSS}×SSS")
    print("=" * W)
    print(
        f"  {'Rk':>3}  {'Player':<24}{'Pos':>5}{'Tm':>4}{'MIN':>6}{'PTS':>5}"
        f"{'SQS':>7}{'FDS':>7}{'FTP':>7}{'SPS':>7}{'DES':>7}{'SSS':>7}  │{'EHI':>7}"
    )
    print("  " + "─" * (W - 2))

    result: list[dict]         = []
    team_ehi: dict[str, list]  = {}

    for rank, r in enumerate(rows, 1):
        name, team, pos, min_, pts, sqs, fds, ftp, sps, des, sss, ehi = r
        print(
            f"  {rank:>3}  {name:<24}{pos:>5}{team:>4}{min_:>6.1f}{pts:>5}"
            f"{sqs:>7.1f}{fds:>7.1f}{ftp:>7.1f}{sps:>7.1f}{des:>7.1f}{sss:>7.1f}  │{ehi:>7.2f}"
        )
        team_ehi.setdefault(team, []).append(ehi)
        result.append({
            "player": name, "team": team, "pos": pos, "min": min_, "pts": pts,
            "SQS": sqs, "FDS": fds, "FTP": ftp, "SPS": sps, "DES": des, "SSS": sss, "EHI": ehi,
        })

    print("  " + "─" * (W - 2))
    for team, ehis in team_ehi.items():
        print(f"  {team} avg EHI: {sum(ehis)/len(ehis):.2f}  (n={len(ehis)})")
    all_ehis = [r["EHI"] for r in result]
    print(f"  Game avg EHI: {sum(all_ehis)/len(all_ehis):.2f}  (n={len(all_ehis)})")
    print("=" * W)
    print()

    return result


# ─── 4 & 5. GET_SEASON_BEST / GET_SEASON_WORST ───────────────────────────────

def _season_ranking(
    season: str,
    n: int,
    ascending: bool,
    min_ppg: float | None = None,
    max_ppg: float | None = None,
    title: str | None = None,
) -> list[dict] | None:
    order = "ASC" if ascending else "DESC"
    label = title or ("Worst" if ascending else "Best")

    having_parts = [f"COUNT(*) >= {MIN_GAMES}"]
    if min_ppg is not None:
        having_parts.append(f"AVG(pg.points) >= {min_ppg}")
    if max_ppg is not None:
        having_parts.append(f"AVG(pg.points) < {max_ppg}")
    having_clause = " AND ".join(having_parts)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT pg.player_name,
                   (
                       SELECT pg2.team FROM player_games pg2
                       JOIN games g2 USING (game_id)
                       WHERE pg2.player_id = pg.player_id AND g2.season = ?
                       ORDER BY g2.date DESC LIMIT 1
                   ) AS latest_team,
                   AVG(pg.SQS)                    AS avg_sqs,
                   AVG(pg.FDS)                    AS avg_fds,
                   AVG(pg.FTP)                    AS avg_ftp,
                   AVG(pg.SPS)                    AS avg_sps,
                   AVG(pg.DES)                    AS avg_des,
                   AVG(COALESCE(pg.SSS, 0.0))     AS avg_sss,
                   AVG(pg.EHI)                    AS avg_ehi,
                   COUNT(*)                       AS gp,
                   AVG(pg.points)                 AS avg_pts
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ?
            GROUP BY pg.player_id, pg.player_name
            HAVING {having_clause}
            ORDER BY avg_ehi {order}
            LIMIT ?
            """,
            (season, season, n),
        ).fetchall()

    if not rows:
        ppg_note = ""
        if min_ppg is not None or max_ppg is not None:
            ppg_note = f"  PPG filter: [{min_ppg or '—'}, {max_ppg or '—'})"
        print(f"  No data for {season} with >= {MIN_GAMES} games played.{ppg_note}")
        return None

    ppg_filter = ""
    if min_ppg is not None and max_ppg is not None:
        ppg_filter = f"  {min_ppg}–{max_ppg} PPG"
    elif min_ppg is not None:
        ppg_filter = f"  {min_ppg}+ PPG"
    elif max_ppg is not None:
        ppg_filter = f"  <{max_ppg} PPG"

    W = 115
    print("\n" + "=" * W)
    print(f"EHI Season {label} {n} — {season}  (min {MIN_GAMES} games{ppg_filter})")
    print(f"  EHI = {W_SQS}×SQS + {W_FDS}×FDS + {W_FTP}×FTP + {W_SPS}×SPS + {W_DES}×DES + {W_SSS}×SSS")
    print("=" * W)
    print(
        f"  {'Rk':>3}  {'Player':<24}{'Tm':>4}{'GP':>4}{'aPTS':>6}"
        f"{'aSQS':>7}{'aFDS':>7}{'aFTP':>7}{'aSPS':>7}{'aDES':>7}{'aSSS':>7}  │{'aEHI':>7}"
    )
    print("  " + "─" * (W - 2))

    result: list[dict] = []
    for rank, r in enumerate(rows, 1):
        name, team, avg_sqs, avg_fds, avg_ftp, avg_sps, avg_des, avg_sss, avg_ehi, gp, avg_pts = r
        team = team or "—"
        print(
            f"  {rank:>3}  {name:<24}{team:>4}{gp:>4}{avg_pts:>6.1f}"
            f"{avg_sqs:>7.1f}{avg_fds:>7.1f}{avg_ftp:>7.1f}{avg_sps:>7.1f}{avg_des:>7.1f}{avg_sss:>7.1f}"
            f"  │{avg_ehi:>7.2f}"
        )
        result.append({
            "player":   name,
            "team":     team,
            "gp":       gp,
            "avg_pts":  round(avg_pts, 1),
            "avg_SQS":  round(avg_sqs, 2),
            "avg_FDS":  round(avg_fds, 2),
            "avg_FTP":  round(avg_ftp, 2),
            "avg_SPS":  round(avg_sps, 2),
            "avg_DES":  round(avg_des, 2),
            "avg_SSS":  round(avg_sss, 2),
            "avg_EHI":  round(avg_ehi, 2),
        })

    print("  " + "─" * (W - 2))
    print("=" * W)
    print()
    return result


def get_season_best(season: str, n: int = 10, min_ppg: float | None = None, max_ppg: float | None = None) -> list[dict] | None:
    """Top N players by avg EHI for the season, minimum MIN_GAMES games played."""
    return _season_ranking(season, n, ascending=False, min_ppg=min_ppg, max_ppg=max_ppg)


def get_season_worst(season: str, n: int = 10, min_ppg: float | None = None, max_ppg: float | None = None) -> list[dict] | None:
    """Bottom N players by avg EHI for the season, minimum MIN_GAMES games played."""
    return _season_ranking(season, n, ascending=True, min_ppg=min_ppg, max_ppg=max_ppg)


def get_season_best_by_role(season: str, n: int = 10) -> None:
    """
    Print three separate leaderboards by scoring role:
      Stars      — min 20 games, avg 15+ PPG
      Role players — min 20 games, avg 8–15 PPG
      Bench      — min 20 games, avg <8 PPG
    """
    _season_ranking(season, n, ascending=False, min_ppg=15.0, title="Stars (15+ PPG) Best")
    _season_ranking(season, n, ascending=False, min_ppg=8.0, max_ppg=15.0, title="Role Players (8–15 PPG) Best")
    _season_ranking(season, n, ascending=False, max_ppg=8.0, title="Bench (<8 PPG) Best")


# ─── 6. GET_SEASON_SUMMARY ────────────────────────────────────────────────────

def get_season_summary(season: str) -> None:
    """
    Print a comprehensive season summary:
      1. League-wide avg EHI and player-game count
      2. Top 10 single-game EHI performances (player, team, opponent, date, pts, EHI)
      3. Bottom 10 single-game EHI performances (same fields)
      4. All 30 teams ranked by avg EHI with GP and avg PTS
      5. Top 10 players by avg EHI (min MIN_GAMES GP)
      6. Bottom 10 players by avg EHI (min MIN_GAMES GP)
    Min 8 minutes played filter applied throughout.
    """
    with get_connection() as conn:
        league = conn.execute(
            """
            SELECT AVG(pg.EHI), COUNT(*)
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= 8
            """,
            (season,),
        ).fetchone()

        if not league or league[0] is None:
            print(f"\n  No data in ehi.db for season {season}.")
            return

        top_games = conn.execute(
            """
            SELECT pg.player_name, pg.team,
                   CASE WHEN pg.team = g.home_team THEN g.away_team
                        ELSE g.home_team END AS opp,
                   pg.date, pg.points, pg.EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= 8
            ORDER BY pg.EHI DESC LIMIT 10
            """,
            (season,),
        ).fetchall()

        bot_games = conn.execute(
            """
            SELECT pg.player_name, pg.team,
                   CASE WHEN pg.team = g.home_team THEN g.away_team
                        ELSE g.home_team END AS opp,
                   pg.date, pg.points, pg.EHI
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= 8
            ORDER BY pg.EHI ASC LIMIT 10
            """,
            (season,),
        ).fetchall()

        team_rows = conn.execute(
            """
            SELECT pg.team,
                   AVG(pg.EHI)                                        AS avg_ehi,
                   COUNT(DISTINCT pg.game_id)                         AS gp,
                   SUM(pg.points) * 1.0 / COUNT(DISTINCT pg.game_id) AS avg_pts
            FROM player_games pg
            JOIN games g USING (game_id)
            WHERE g.season = ? AND pg.minutes >= 8
            GROUP BY pg.team
            ORDER BY avg_ehi DESC
            """,
            (season,),
        ).fetchall()

    league_avg, n_rows = league
    W = 78

    print("\n" + "=" * W)
    print(f"EHI Season Summary — {season}")
    print("=" * W)
    print(f"\n  League avg EHI : {league_avg:.2f}   ({n_rows} player-game rows)")

    # ── Single-game performance tables ────────────────────────────────────
    def _print_game_table(rows: list, title: str) -> None:
        print("\n" + "=" * W)
        print(f"  {title} — {season}")
        print("=" * W)
        print(
            f"  {'Rk':>3}  {'Player':<24}{'Tm':>4}{'Opp':>5}"
            f"{'Date':>12}{'PTS':>5}{'EHI':>8}"
        )
        print("  " + "─" * (W - 2))
        for rank, (name, team, opp, date, pts, ehi) in enumerate(rows, 1):
            print(
                f"  {rank:>3}  {name:<24}{team:>4}{opp:>5}"
                f"{date:>12}{int(pts):>5}{ehi:>8.2f}"
            )
        print("  " + "─" * (W - 2))
        print("=" * W)

    if top_games:
        _print_game_table(top_games, "Top 10 Single-Game EHI Performances")
    if bot_games:
        _print_game_table(bot_games, "Bottom 10 Single-Game EHI Performances")

    # ── All teams ranked by avg EHI ───────────────────────────────────────
    if team_rows:
        W_T = 68
        print("\n" + "=" * W_T)
        print(f"  All Teams — Avg EHI Ranking  ({season})")
        print("=" * W_T)
        print(f"  {'Rk':>3}  {'Team':<6}{'GP':>4}{'aPTS':>7}{'aEHI':>7}  Bar")
        print("  " + "─" * (W_T - 2))
        for i, (team, avg_ehi, gp, avg_pts) in enumerate(team_rows, 1):
            bar = _bar(avg_ehi / 100.0, width=20)
            print(f"  {i:>3}  {team:<6}{gp:>4}{avg_pts:>7.1f}{avg_ehi:>7.2f}  {bar}")
        print("  " + "─" * (W_T - 2))
        print("=" * W_T)

    print()
    get_season_best(season, n=10)
    get_season_worst(season, n=10)


# ─── CLI DISPATCH ─────────────────────────────────────────────────────────────

_USAGE = """
EHI Query Tool

Usage:
  python3 query_ehi.py player        <name>   <season>           season averages
  python3 query_ehi.py player-game   <name>   <date YYYY-MM-DD>  single game breakdown
  python3 query_ehi.py game          <date>   <team1>  <team2>   game leaderboard
  python3 query_ehi.py season-best   <season> [n]                top N by avg EHI
  python3 query_ehi.py season-worst  <season> [n]                bottom N by avg EHI
  python3 query_ehi.py season-roles  <season> [n]                top N by role (Stars/Role/Bench)
  python3 query_ehi.py summary       <season>                    full season summary

Examples:
  python3 query_ehi.py player        'Luka Doncic'  2025-26
  python3 query_ehi.py player-game   'Luka Doncic'  2026-01-26
  python3 query_ehi.py game           2026-01-26    DAL  ATL
  python3 query_ehi.py season-best    2025-26       20
  python3 query_ehi.py season-worst   2025-26
  python3 query_ehi.py season-roles   2025-26       10
  python3 query_ehi.py summary        2025-26
""".strip()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(_USAGE)
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "player" and len(args) >= 3:
        get_player_season(args[1], args[2])

    elif cmd == "player-game" and len(args) >= 3:
        get_player_game(args[1], args[2])

    elif cmd == "game" and len(args) >= 4:
        get_game_leaderboard(args[1], args[2], args[3])

    elif cmd == "season-best" and len(args) >= 2:
        n = int(args[2]) if len(args) >= 3 else 10
        get_season_best(args[1], n)

    elif cmd == "season-worst" and len(args) >= 2:
        n = int(args[2]) if len(args) >= 3 else 10
        get_season_worst(args[1], n)

    elif cmd == "season-roles" and len(args) >= 2:
        n = int(args[2]) if len(args) >= 3 else 10
        get_season_best_by_role(args[1], n)

    elif cmd == "summary" and len(args) >= 2:
        get_season_summary(args[1])

    else:
        print(f"  Unknown command or missing arguments: {' '.join(args)}\n")
        print(_USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
