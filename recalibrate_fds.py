"""
recalibrate_fds.py — FDS Volume Penalty Recalibration Test

Pulls BoxScoreTraditionalV3, PlayByPlayV3, and ShotChartDetail (both teams)
for each of the 12 validation games (game_ids from ehi.db), then:

  1. Runs compute_fds once to extract config-independent intermediates:
       fta, avg_legitimacy, fds_raw, ft_mod
  2. Re-applies the volume penalty formula under each config:
       vol_pen = FTA ^ EXP * BASE
       FDS     = clamp(fds_raw - vol_pen) * ft_mod
  3. Recomputes EHI using stored SQS/FTP/SPS/DES from ehi.db.

API calls: 4 per game × 12 games = 48 total (~100 s with 2 s sleeps).

Configs
-------
  A (current) : BASE=2.5, EXP=1.30
  B (softer)  : BASE=1.5, EXP=1.20
  C (softer²) : BASE=1.0, EXP=1.15
"""

import sqlite3
import statistics
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import (
    boxscoretraditionalv3,
    playbyplayv3,
    shotchartdetail,
)
from nba_api.stats.library.http import NBAStatsHTTP

from config import HEADERS, W_SQS, W_FDS, W_FTP, W_SPS, W_DES, ZERO_FTA_BASELINE
import compute_ehi

NBAStatsHTTP.headers = HEADERS

DB_PATH  = Path(__file__).parent / "ehi.db"
SLEEP    = 2   # seconds between API calls

# ─── CONFIGS ─────────────────────────────────────────────────────────────────

CONFIGS = [
    ("A (current)", 2.5, 1.30),
    ("B (softer)",  1.5, 1.20),
    ("C (softer²)", 1.0, 1.15),
]

# ─── STAR PLAYERS ─────────────────────────────────────────────────────────────
# (full_name_as_in_db, date, short_label, game_label)

STARS = [
    ("Luka Dončić",            "2024-01-26", "Luka",   "DAL vs ATL"),
    ("Kawhi Leonard",           "2025-12-28", "Kawhi",  "DET vs LAC"),
    ("Nikola Jokić",            "2025-04-01", "Jokic",  "MIN vs DEN"),
    ("Shai Gilgeous-Alexander", "2025-10-23", "SGA",    "IND vs OKC"),
    ("Tyrese Maxey",            "2025-11-20", "Maxey",  "MIL vs PHI"),
    ("Cade Cunningham",         "2025-11-10", "Cade",   "DET vs WAS"),
    ("Kevin Durant",            "2025-10-21", "KD",     "HOU vs OKC"),
    ("Donovan Mitchell",        "2026-03-31", "D-Mitch","LAL vs CLE"),
    ("Victor Wembanyama",       "2025-10-22", "Wemby",  "SAS vs DAL"),
    ("Giannis Antetokounmpo",   "2023-12-23", "Giannis","MIL vs IND"),
    ("James Harden",            "2019-01-23", "Harden", "HOU vs NYK"),
    ("Stephen Curry",           "2021-01-03", "Curry",  "GSW vs POR"),
]


# ─── DB QUERY ─────────────────────────────────────────────────────────────────

def _get_stored(player_name: str, date: str) -> dict:
    """Return game_id, player_id, and stored non-FDS sub-scores from ehi.db."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT game_id, player_id, SQS, FTP, SPS, DES
            FROM player_games
            WHERE player_name = ? AND date = ?
        """, (player_name, date))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"No DB row for '{player_name}' on {date}")
    return {"game_id": row[0], "player_id": row[1],
            "SQS": row[2], "FTP": row[3], "SPS": row[4], "DES": row[5]}


# ─── API PULLS ────────────────────────────────────────────────────────────────

def _pull_fds_data(game_id: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Pull the three endpoints needed to recompute FDS.
    Returns (player_box, pbp, shots).
    Sleeps SLEEP seconds after every call; retries shot charts once on failure.
    """
    resp = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=60)
    time.sleep(SLEEP)
    players = resp.get_data_frames()[0].copy()
    if {"fieldGoalsMade", "threePointersMade"}.issubset(players.columns):
        players["twoPointersMade"] = (
            players["fieldGoalsMade"] - players["threePointersMade"]
        )
    if {"fieldGoalsAttempted", "threePointersAttempted"}.issubset(players.columns):
        players["twoPointersAttempted"] = (
            players["fieldGoalsAttempted"] - players["threePointersAttempted"]
        )

    resp = playbyplayv3.PlayByPlayV3(game_id=game_id, timeout=60)
    time.sleep(SLEEP)
    pbp = resp.get_data_frames()[0]

    team_ids = players["teamId"].dropna().unique().tolist()
    shots_list: list[pd.DataFrame] = []
    for tid in team_ids:
        for attempt in (1, 2):
            try:
                resp = shotchartdetail.ShotChartDetail(
                    team_id=int(tid), player_id=0,
                    game_id_nullable=game_id,
                    context_measure_simple="FGA",
                    timeout=60,
                )
                time.sleep(SLEEP)
                shots_list.append(resp.get_data_frames()[0])
                break
            except Exception as exc:
                time.sleep(SLEEP)
                if attempt == 1:
                    print(f"    shot chart retry (team {int(tid)}): {exc}")
                    time.sleep(10)
                else:
                    print(f"    shot chart failed both attempts — omitting team {int(tid)}")

    shots = pd.concat(shots_list, ignore_index=True) if shots_list else pd.DataFrame()
    return players, pbp, shots


# ─── FDS MULTI-CONFIG ─────────────────────────────────────────────────────────

def _fds_all_configs(row: pd.Series, foul_drawn_index: dict) -> dict:
    """
    Call compute_ehi.compute_fds once to get config-independent intermediates,
    then reapply the volume penalty under each config.

    Returns dict with keys:
      fta, avg_leg, fds_raw, ft_mod, n_fouls,
      vol_pen_A/B/C, FDS_A/B/C
    """
    base = compute_ehi.compute_fds(row, foul_drawn_index)

    fta     = int(row["freeThrowsAttempted"])
    fds_raw = base["fds_raw"]      # avg_leg × 100, before any volume penalty
    ft_mod  = base["ft_mod"]       # 0.92 if poor FT shooter, else 1.0
    avg_leg = base["avg_legitimacy"]
    n_fouls = base["n_fouls_drawn"]

    out = {
        "fta":     fta,
        "avg_leg": avg_leg,
        "fds_raw": fds_raw,
        "ft_mod":  ft_mod,
        "n_fouls": n_fouls,
    }

    for label, vol_base, vol_exp in CONFIGS:
        key = label[0]   # "A", "B", "C"
        if fta == 0:
            vol_pen = 0.0
            fds_val = float(ZERO_FTA_BASELINE)
        else:
            vol_pen = (fta ** vol_exp) * vol_base
            fds_val = compute_ehi.clamp(fds_raw - vol_pen)
            if ft_mod < 1.0:
                fds_val = compute_ehi.clamp(fds_val * ft_mod)
        out[f"vol_pen_{key}"] = round(vol_pen, 1)
        out[f"FDS_{key}"]     = round(fds_val, 2)

    return out


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def _print_table(rows: list[dict]) -> None:
    W = 124
    print()
    print("=" * W)
    print("FDS VOLUME PENALTY RECALIBRATION — 12 Star Players")
    print(f"  vol_pen = FTA ^ EXP × BASE   │   FDS = clamp(fds_raw − vol_pen) × ft_mod")
    print(f"  {'Config A':20s} BASE=2.50 EXP=1.30   (current)")
    print(f"  {'Config B':20s} BASE=1.50 EXP=1.20   (softer)")
    print(f"  {'Config C':20s} BASE=1.00 EXP=1.15   (softer²)")
    print("=" * W)

    hdr1 = (
        f"  {'Star':<9}{'Game':<14}{'FTA':>4}{'avg_leg':>8}{'fds_raw':>8}"
        f"  │{'vol_pen':>8}{'FDS':>6}{'EHI':>7}"
        f"  │{'vol_pen':>8}{'FDS':>6}{'EHI':>7}"
        f"  │{'vol_pen':>8}{'FDS':>6}{'EHI':>7}"
    )
    hdr2 = (
        f"  {'':9}{'':14}{'':4}{'':8}{'':8}"
        f"  │{'── A ──':>14}{'':>7}"
        f"  │{'── B ──':>14}{'':>7}"
        f"  │{'── C ──':>14}{'':>7}"
    )
    print(hdr1)
    print("  " + "─" * (W - 2))

    ehi = {k: [] for k in ("A", "B", "C")}

    for r in rows:
        ehi["A"].append(r["EHI_A"])
        ehi["B"].append(r["EHI_B"])
        ehi["C"].append(r["EHI_C"])

        change_b = f"{'↑' if r['EHI_B'] > r['EHI_A'] else '='}{abs(r['EHI_B']-r['EHI_A']):.2f}" if r["EHI_B"] != r["EHI_A"] else "  ─  "
        change_c = f"{'↑' if r['EHI_C'] > r['EHI_A'] else '='}{abs(r['EHI_C']-r['EHI_A']):.2f}" if r["EHI_C"] != r["EHI_A"] else "  ─  "

        print(
            f"  {r['label']:<9}{r['game']:<14}{r['fta']:>4}"
            f"{r['avg_leg']:>8.3f}{r['fds_raw']:>8.1f}"
            f"  │{r['vol_pen_A']:>8.1f}{r['FDS_A']:>6.1f}{r['EHI_A']:>7.2f}"
            f"  │{r['vol_pen_B']:>8.1f}{r['FDS_B']:>6.1f}{r['EHI_B']:>7.2f}"
            f"  │{r['vol_pen_C']:>8.1f}{r['FDS_C']:>6.1f}{r['EHI_C']:>7.2f}"
        )

    print("  " + "─" * (W - 2))

    # Stats per config
    for key, label in (("A", "Config A"), ("B", "Config B"), ("C", "Config C")):
        vals = ehi[key]
        lo, hi = min(vals), max(vals)
        mean  = statistics.mean(vals)
        stdev = statistics.stdev(vals)
        fds_nonzero = sum(1 for r in rows if r[f"FDS_{key}"] > 0)
        print(
            f"  {label:<14}  EHI range {lo:.2f}–{hi:.2f}  "
            f"span={hi-lo:.2f}  mean={mean:.2f}  σ={stdev:.2f}  "
            f"FDS>0: {fds_nonzero}/{len(rows)}"
        )

    print("=" * W)


def _print_sensitivity() -> None:
    """
    Show FDS at representative (FTA, avg_leg) pairs under all 3 configs.
    Answers: does legitimacy quality survive the volume penalty?
    """
    W = 90
    print()
    print("=" * W)
    print("LEGITIMACY SURVIVAL — FDS at representative (FTA, avg_leg) pairs")
    print(f"  Legitimate foul drawer : avg_leg = 0.45  (shooting foul, contested, some and-1s)")
    print(f"  Manufactured foul drawer: avg_leg = 0.05  (mostly off-ball bonus / garbage time)")
    print("=" * W)

    fta_levels = [5, 8, 12, 16, 20, 25]
    leg_legit  = 0.45
    leg_fake   = 0.05

    print(
        f"  {'FTA':>4}  "
        f"{'─── Config A ───':^20}  "
        f"{'─── Config B ───':^20}  "
        f"{'─── Config C ───':^20}"
    )
    print(
        f"  {'':>4}  "
        f"{'legit':>6}{'manuf':>6}{'gap':>6}  "
        f"{'legit':>6}{'manuf':>6}{'gap':>6}  "
        f"{'legit':>6}{'manuf':>6}{'gap':>6}"
        f"  {'Note'}"
    )
    print("  " + "─" * (W - 2))

    for fta in fta_levels:
        row_parts = [f"  {fta:>4}"]
        notes = []
        for label, vol_base, vol_exp in CONFIGS:
            vol_pen = (fta ** vol_exp) * vol_base
            fds_l = max(0.0, leg_legit * 100 - vol_pen)
            fds_f = max(0.0, leg_fake  * 100 - vol_pen)
            gap   = fds_l - fds_f
            row_parts.append(f"  {fds_l:>6.1f}{fds_f:>6.1f}{gap:>6.1f}")
            if fds_l == 0:
                notes.append(f"{label[0]}:crushed")
        note_str = "  " + ", ".join(notes) if notes else ""
        print("".join(row_parts) + note_str)

    print("  " + "─" * (W - 2))
    print(
        f"  Interpretation: 'legit' vs 'manuf' gap = how much quality survives.\n"
        f"  A gap of 0 means the volume penalty eats legitimacy signal entirely.\n"
        f"  Target: at 8 FTA, legit should score meaningfully more than manuf."
    )
    print("=" * W)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("FDS Recalibration — pulling raw data for 12 games …")
    print(f"(4 API calls per game × 12 games = 48 calls, ~100 s)")
    print()

    rows = []

    for i, (full_name, date, label, game) in enumerate(STARS, 1):
        print(f"[{i:>2}/12] {label:<8} {game}  ({date})")

        stored  = _get_stored(full_name, date)
        game_id = stored["game_id"]

        players, pbp, shots = _pull_fds_data(game_id)

        # Locate the star player's row in the box score
        pid = stored["player_id"]
        mask = pd.to_numeric(players["personId"], errors="coerce") == pid
        if not mask.any():
            print(f"  WARNING: {full_name} not found in player_box for {game_id}")
            continue
        player_row = players[mask].iloc[0]

        foul_drawn_index = compute_ehi.build_foul_drawn_events(pbp, shots)
        fds_data = _fds_all_configs(player_row, foul_drawn_index)

        # Recompute EHI under each config (SQS/FTP/SPS/DES unchanged)
        for cfg_label, _, _ in CONFIGS:
            key = cfg_label[0]
            fds = fds_data[f"FDS_{key}"]
            fds_data[f"EHI_{key}"] = round(
                W_SQS * stored["SQS"]
                + W_FDS * fds
                + W_FTP * stored["FTP"]
                + W_SPS * stored["SPS"]
                + W_DES * stored["DES"],
                2,
            )

        rows.append({
            "label":   label,
            "game":    game,
            **fds_data,
            "SQS":     stored["SQS"],
            "FTP":     stored["FTP"],
            "SPS":     stored["SPS"],
            "DES":     stored["DES"],
        })

        fta     = fds_data["fta"]
        avg_leg = fds_data["avg_leg"]
        print(
            f"         FTA={fta}  avg_leg={avg_leg:.3f}  fds_raw={fds_data['fds_raw']:.1f}"
            f"  A→FDS={fds_data['FDS_A']:.1f}/EHI={fds_data['EHI_A']:.2f}"
            f"  B→FDS={fds_data['FDS_B']:.1f}/EHI={fds_data['EHI_B']:.2f}"
            f"  C→FDS={fds_data['FDS_C']:.1f}/EHI={fds_data['EHI_C']:.2f}"
        )
        print()

    # Sort by Config A EHI desc (matches existing validation table order)
    rows.sort(key=lambda r: r["EHI_A"], reverse=True)

    _print_table(rows)
    _print_sensitivity()


if __name__ == "__main__":
    main()
