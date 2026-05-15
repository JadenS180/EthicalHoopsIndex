# EthicalHoopsIndex — CLAUDE.md

## What is EHI?

The **Ethical Hoops Index (EHI)** is a per-game, absolute (0–100) metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct while penalizing manipulation, deception, and laziness.

```
EHI = 0.35(SQS) + 0.20(FDS) + 0.20(FTP) + 0.15(SPS) + 0.10(DES)
```

---

## The 5 Sub-Scores

| Code | Name | Weight | What it measures |
|------|------|--------|-----------------|
| SQS | Shot Quality Score | 35% | Did the player take shots a skilled, ethical player would take? Rewards contested makes and self-created quality looks; penalizes low-xeFG% chucks. |
| FDS | Foul Drawing Score | 20% | Did the player earn their free throws or manufacture them? Scores legitimacy per foul drawn; `FDS = clamp(avg_legitimacy × 100)` plus FT% modifier. No volume penalty. |
| FTP | FT Dependency Score | 20% | What fraction of points came from free throws vs. field goals? Penalizes exponentially above 50% dependency. |
| SPS | Sportsmanship Score | 15% | Did the player conduct themselves with integrity? Starts at 100; penalties only. Exponential stacking per violation type. |
| DES | Defensive Effort Score | 10% | Did the player compete defensively? Weighted sum of contested shots, deflections, steals, blocks, defensive rebounds, charges taken; minus foul penalty. |

All constants (weights, thresholds, multipliers) live in `config.py`.

---

## pipeline.py

Pulls all raw data for a single game from `nba_api` and returns it as a dict of pandas DataFrames. Currently configured for **Bam Adebayo's 83-point game — Heat vs Wizards, 2026-03-10 (game_id `0022500938`)**.

**7 API calls in order (1-second sleep between each):**

1. `LeagueGameFinder` — locates the game ID by filtering Heat games on 03/10/2026
2. `BoxScoreSummaryV3` — game-level metadata (score, officials, line score)
3. `BoxScoreTraditionalV3` — per-player stats: PTS, FGM/A, FTM/A, 3PM/A, REB, STL, BLK, PF. Pipeline derives `twoPointersMade` and `twoPointersAttempted` as `FGM − 3PM`.
4. `PlayByPlayV3` — full play log (569 rows); `actionType`, `subType`, `description` fields carry foul classification
5. `ShotChartDetail` × 2 — one call per team with `player_id=0`; returns `SHOT_DISTANCE`, `SHOT_ZONE_*`, `EVENT_TYPE`, `ACTION_TYPE`, `LOC_X/Y`
6. `BoxScoreHustleV2` — per-player hustle stats for all players
7. `PlayerDashPtShots` × 2 — one call per team with `player_id=0`; result set `[4]` provides `CLOSE_DEF_DIST_RANGE` buckets (0-2ft, 2-4ft, 4-6ft, 6ft+) per player for the full season (per-game date filtering returns 0 rows; season-level used as proxy)

**Returns:** `{"game_id", "game_summary", "player_box", "pbp", "shots", "hustle", "proximity"}`

**Headers:** The NBA stats API silently times out on outdated User-Agents. `config.py` uses Chrome 145 and `NBAStatsHTTP.headers` is patched globally at import time — do not pass `headers=` per endpoint.

---

## compute_ehi.py

Consumes the dict from `pipeline.main()` and computes EHI sub-scores for every active player (DNPs filtered out by `minutes > 0`).

### Implemented

**FTP — FT Dependency Score**
- Inputs: `freeThrowsMade`, `twoPointersMade`, `threePointersMade`, `fieldGoalsMade`
- Formula: `FTP_raw = (1 − ft_dep_ratio) × 100`; exponential extra penalty above 50% dependency
- Edge cases: zero points → baseline 75; FGM == 0 and FTM > 0 → score 0
- Constants: `FT_DEP_THRESHOLD`, `FT_DEP_PENALTY_MULT`, `FT_DEP_PENALTY_EXP`, `ZERO_POINTS_BASELINE`

**SPS — Sportsmanship Score**
- Inputs: PlayByPlayV3 filtered by `personId`
- Formula: starts at 100; `penalty_type = base × (count ^ SPS_STACK_EXP)` per violation type; `SPS = clamp(100 − sum, 0, 100)`
- Violation types detected via `actionType`/`subType` matching (case-insensitive):
  - Technical: `actionType='Foul'`, `subType='Technical'`
  - Flagrant 1: `subType` in `('flagrant type 1', 'flagrant 1', ...)`
  - Flagrant 2: `subType` in `('flagrant type 2', 'flagrant 2', ...)`
  - Illegal screen: `subType='Offensive'` + `"illegal screen"` in description (fallback)
  - Delay of game: `"delay"` in subType or description
- `build_violation_index(pbp)` scans the PBP once and returns `{personId: {vtype: count}}`
- Constants: `TECH_PENALTY`, `FLAGRANT1_PENALTY`, `FLAGRANT2_PENALTY`, `ILLEGAL_SCREEN_PEN`, `DELAY_PENALTY`, `SPS_STACK_EXP`

### All sub-scores implemented
All five sub-scores are complete. No stubs remain.

### Validation helpers
- `print_ftp_report(df)` — shows all intermediates (ft_pts, fg_pts, ft_dep%, raw, penalty, FTP); includes a spot-check that computed `total_pts` matches box-score `pts`
- `print_sps_report(df)` — shows per-violation counts and penalties; only violators are non-trivial rows

---

## Development Approach

Sub-scores are built and validated one at a time before moving to the next:

- [x] FTP — complete, validated
- [x] SPS — complete, validated (Coulibaly 1 tech → SPS 82.0 confirmed)
- [x] DES — complete, validated
- [x] FDS — complete, validated; volume penalty removed after 12-game calibration (all stars scored FDS=0 at any config); FDS now = `clamp(avg_legitimacy × 100)` + FT% modifier
- [x] SQS — complete, validated (Bam 83-pt game; per-shot breakdown printed)
- [x] EHI aggregation — complete; validated across 12 games (EHI range 53.7–63.8, std dev 3.12)

---

## Known Design Notes

**`chargesDrawn` column name:** `BoxScoreHustleV2` returns `chargesDrawn`, not `chargesTaken`. The EHI reference document uses `chargesTaken` — use `chargesDrawn` when reading the hustle DataFrame.

**Illegal screen and delay of game not tested:** This game (Heat vs Wizards 2026-03-10) contains no illegal screen calls or delay-of-game violations. The SPS matchers for those two types are written defensively but have not been exercised against real data. Validate against a game with a known illegal screen before trusting those branches.

**FDS defender proximity — implemented via `PlayerDashPtShots`:** `build_proximity_index(proximity_df)` in `compute_ehi.py` converts season-level `CLOSE_DEF_DIST_RANGE` bucket data into per-player `{very_tight_pct, tight_pct}` fractions. `compute_fds` applies `prox_bonus = very_tight_pct × 0.40 + tight_pct × 0.25` per shooting foul; falls back to `+0.25` flat if no data available. Season-level data used as game-level proxy because `PlayerDashPtShots` returns 0 rows when date-filtered to a single game.

**FDS volume penalty — removed:** After 12-game validation, `VOLUME_PENALTY_BASE` and `VOLUME_PENALTY_EXP` are no longer applied. All high-FTA star players scored FDS=0 under every tested config (A/B/C) because legitimate avg_leg (~0.25–0.45) can never overcome the volume penalty at 40+ FTA. FDS now equals `clamp(avg_legitimacy × 100, 0, 100)` plus the FT% modifier, letting legitimacy quality fully determine the score.
