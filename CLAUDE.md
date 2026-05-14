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
| FDS | Foul Drawing Score | 20% | Did the player earn their free throws or manufacture them? Scores legitimacy per foul drawn; applies volume penalty even for legitimate FTAs. |
| FTP | FT Dependency Score | 20% | What fraction of points came from free throws vs. field goals? Penalizes exponentially above 50% dependency. |
| SPS | Sportsmanship Score | 15% | Did the player conduct themselves with integrity? Starts at 100; penalties only. Exponential stacking per violation type. |
| DES | Defensive Effort Score | 10% | Did the player compete defensively? Weighted sum of contested shots, deflections, steals, blocks, defensive rebounds, charges taken; minus foul penalty. |

All constants (weights, thresholds, multipliers) live in `config.py`.

---

## pipeline.py

Pulls all raw data for a single game from `nba_api` and returns it as a dict of pandas DataFrames. Currently configured for **Bam Adebayo's 83-point game — Heat vs Wizards, 2026-03-10 (game_id `0022500938`)**.

**6 API calls in order (1-second sleep between each):**

1. `LeagueGameFinder` — locates the game ID by filtering Heat games on 03/10/2026
2. `BoxScoreSummaryV3` — game-level metadata (score, officials, line score)
3. `BoxScoreTraditionalV3` — per-player stats: PTS, FGM/A, FTM/A, 3PM/A, REB, STL, BLK, PF. Pipeline derives `twoPointersMade` and `twoPointersAttempted` as `FGM − 3PM`.
4. `PlayByPlayV3` — full play log (569 rows); `actionType`, `subType`, `description` fields carry foul classification
5. `ShotChartDetail` × 2 — one call per team with `player_id=0`; returns `SHOT_DISTANCE`, `SHOT_ZONE_*`, `EVENT_TYPE`, `ACTION_TYPE`, `LOC_X/Y`
6. `BoxScoreHustleV2` — per-player hustle stats for all players

**Returns:** `{"game_id", "game_summary", "player_box", "pbp", "shots", "hustle"}`

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

### Stubs (not yet implemented)
`compute_sqs`, `compute_fds`, `compute_des` — each raises `NotImplementedError`.

### Validation helpers
- `print_ftp_report(df)` — shows all intermediates (ft_pts, fg_pts, ft_dep%, raw, penalty, FTP); includes a spot-check that computed `total_pts` matches box-score `pts`
- `print_sps_report(df)` — shows per-violation counts and penalties; only violators are non-trivial rows

---

## Development Approach

Sub-scores are built and validated one at a time before moving to the next:

- [x] FTP — complete, validated
- [x] SPS — complete, validated (Coulibaly 1 tech → SPS 82.0 confirmed)
- [x] DES — complete, validated
- [x] FDS — complete, validated (Bam 43-FTA game → FDS 0.0 confirmed; volume_penalty 332.2 dominates)
- [ ] SQS — next; requires shot-level xeFG% lookup table; most complex

---

## Known Design Notes

**`chargesDrawn` column name:** `BoxScoreHustleV2` returns `chargesDrawn`, not `chargesTaken`. The EHI reference document uses `chargesTaken` — use `chargesDrawn` when reading the hustle DataFrame.

**Illegal screen and delay of game not tested:** This game (Heat vs Wizards 2026-03-10) contains no illegal screen calls or delay-of-game violations. The SPS matchers for those two types are written defensively but have not been exercised against real data. Validate against a game with a known illegal screen before trusting those branches.

**FDS defender distance — V2 improvement:** `build_foul_drawn_events` does not have access to defender proximity data (`DefenderDashPtShots` endpoint). The `+0.25 defender ≤4ft` signal is assumed for all shooting fouls (a foul implies contact), and the `+0.40 defender ≤2ft` bonus is silently skipped. When `DefenderDashPtShots` data is added, plug actual distance into `compute_fds` to replace the assumed signal and unlock the full legitimacy range.
