# EthicalHoopsIndex — CLAUDE.md

## What is EHI?

The **Ethical Hoops Index (EHI)** is a per-game, absolute (0–100) metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct while penalizing manipulation, deception, and laziness.

```
EHI = 0.45(SQS) + 0.20(FDS) + 0.25(FTP) + 0.05(SPS) + 0.05(DES)
```

---

## The 5 Sub-Scores

| Code | Name | Weight | What it measures |
|------|------|--------|-----------------|
| SQS | Shot Quality Score | 45% | Did the player take shots a skilled, ethical player would take? Rewards contested makes and self-created quality looks; penalizes low-xeFG% chucks. Volume-quality bonus for 15+ shots at avg xeFG ≥ 0.52. |
| FDS | Foul Drawing Score | 20% | Did the player earn their free throws or manufacture them? Scores legitimacy per foul drawn; `FDS = avg_legitimacy × 100` plus FT% modifier. Zero-FTA baseline = 50. No volume penalty. |
| FTP | FT Dependency Score | 25% | Combined ratio + volume score: `(1 − FT_dep_ratio) × 70 + min(pts, 30)`. Naturally bounded 0–100; no separate edge-case handling needed. |
| SPS | Sportsmanship Score | 5% | Did the player conduct themselves with integrity? Starts at 100; penalties only. Exponential stacking per violation type. Floor at 0 (only sub-score with a clamp). |
| DES | Defensive Effort Score | 5% | Did the player compete defensively? Weighted sum of contested shots, deflections, steals, blocks, defensive rebounds, charges taken; minus foul penalty. Normalized against 80-point elite baseline; unclamped. |

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

Consumes the dict from `pipeline.main()` and computes EHI sub-scores for every active player. Players with fewer than `MIN_MINUTES_THRESHOLD` (8) minutes are excluded entirely from all results and DB saves.

### Implemented

**FTP — FT Dependency Score**
- Inputs: `freeThrowsMade`, `twoPointersMade`, `threePointersMade`
- Formula: `ratio_score = (1 − ft_dep_ratio) × FTP_RATIO_WEIGHT (70)`; `volume_score = min(total_pts, FTP_VOLUME_CAP (30))`; `FTP = ratio_score + volume_score`
- Naturally bounded [0, 100] by construction — no clamping needed
- Zero scorers: `dep_ratio = 0 → ratio = 70, volume = 0 → FTP = 70` (neutral baseline)
- Pure FT scorers: `dep_ratio = 1.0 → ratio = 0, volume = min(ftm, 30)`
- Constants: `FTP_RATIO_WEIGHT = 70`, `FTP_VOLUME_CAP = 30`
- Deprecated (not applied): `FT_DEP_THRESHOLD`, `FT_DEP_PENALTY_MULT`, `FT_DEP_PENALTY_EXP`, `ZERO_POINTS_BASELINE`

**SPS — Sportsmanship Score**
- Inputs: PlayByPlayV3 filtered by `personId`
- Formula: starts at 100; `penalty_type = base × (count ^ SPS_STACK_EXP)` per violation type; `SPS = max(0, 100 − sum)`
- **Only sub-score with a clamp** — floor at 0, no ceiling
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
- [x] FDS — complete, validated; volume penalty removed; aggregate clamp removed; zero-FTA baseline = 50
- [x] SQS — complete, validated (Bam 83-pt game; per-shot breakdown printed); volume-quality bonus added (15+ shots, avg xeFG ≥ 0.52)
- [x] EHI aggregation — complete; validated across 12 games (EHI range 46.29–67.77, std dev 5.37, n=17 star game-rows)

---

## Known Design Notes

**`chargesDrawn` column name:** `BoxScoreHustleV2` returns `chargesDrawn`, not `chargesTaken`. The EHI reference document uses `chargesTaken` — use `chargesDrawn` when reading the hustle DataFrame.

**Illegal screen and delay of game not tested:** This game (Heat vs Wizards 2026-03-10) contains no illegal screen calls or delay-of-game violations. The SPS matchers for those two types are written defensively but have not been exercised against real data. Validate against a game with a known illegal screen before trusting those branches.

**FDS defender proximity — implemented via `PlayerDashPtShots`:** `build_proximity_index(proximity_df)` in `compute_ehi.py` converts season-level `CLOSE_DEF_DIST_RANGE` bucket data into per-player `{very_tight_pct, tight_pct}` fractions. `compute_fds` applies `prox_bonus = very_tight_pct × 0.40 + tight_pct × 0.25` per shooting foul; falls back to `+0.25` flat if no data available. Season-level data used as game-level proxy because `PlayerDashPtShots` returns 0 rows when date-filtered to a single game.

**Sub-score clamping removed:** All sub-scores except SPS now float freely — no floor, no ceiling. SPS keeps a floor of 0 (`max(0, 100 − penalties)`). DES and SQS can exceed 100 for exceptional performances. FTP is naturally bounded [0, 100] by formula construction and needs no clamp.

**DES normalization = 80:** `DES_NORMALIZATION` was recalibrated from 30 → 80. Baseline: a player generating 80 weighted positive-defensive points (8 contested × 3.5 + 5 deflections × 4.0 + 2 steals × 5.0 + 2 blocks × 5.0 + 6 drebs × 2.0 = 80) scores `des_raw = 100` before foul penalty. After 2–3 typical fouls this lands ~80–88. Players with extraordinary games (e.g. Bam's 83-pt game) legitimately exceed 100.

**SQS volume-quality bonus:** After computing `raw_mean` across all shots, if `n_shots >= 15` and `avg_xeFG >= 0.52`, a bonus of `(n_shots − 14) × 0.5` is added to SQS. Rewards players who sustain high shot quality over high volume.

**FDS volume penalty — removed:** After 12-game validation, `VOLUME_PENALTY_BASE` and `VOLUME_PENALTY_EXP` are no longer applied. FDS = `avg_legitimacy × 100` (unclamped) plus FT% modifier. Zero-FTA baseline dropped from 72 → 50.

**FTP rework — ratio + volume:** The old purely-linear formula `(1 − dep) × 100` with an exponential kick above 50% dependency has been replaced with `(1 − dep) × 70 + min(pts, 30)`. This bakes volume directly into the base score. A player must both minimize FT dependency AND score field goals to reach 100.

**Minimum 8-minute filter:** Players below `MIN_MINUTES_THRESHOLD = 8` minutes are excluded from EHI computation, DB saves, and all leaderboards entirely.

**Next step — `run_season.py`:** Full 2025-26 season run. Script does not yet exist; needs to iterate all game IDs for the season and call the same pipeline/compute loop used in `run_validation.py`.
