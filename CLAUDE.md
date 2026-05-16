# EthicalHoopsIndex — CLAUDE.md

## What is EHI?

The **Ethical Hoops Index (EHI)** is a per-game, absolute metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct while penalizing manipulation, deception, and laziness.

```
EHI = 0.45(SQS) + 0.20(FDS) + 0.25(FTP) + 0.05(SPS) + 0.05(DES)
```

---

## The 5 Sub-Scores

| Code | Name | Weight | What it measures |
|------|------|--------|-----------------|
| SQS | Shot Quality Score | 45% | Did the player take shots a skilled, ethical player would take? Rewards contested makes and self-created quality looks; penalizes low-xeFG% chucks. Volume-quality bonus for 15+ shots at avg xeFG ≥ position threshold (C: 0.58, F: 0.53, G: 0.50). xeFG% sourced empirically from `ehi.db` shots table where ≥50 shots per zone; hardcoded fallbacks otherwise. |
| FDS | Foul Drawing Score | 20% | Did the player earn their free throws or manufacture them? Per-foul legitimacy scored via defender proximity, assisted/and-1 flags, and position modifiers (center in paint +0.10, guard at 3pt −0.10). `FDS = avg_legitimacy × 100` plus FT% modifier. Zero-FTA baseline = 50. |
| FTP | FT Dependency Score | 25% | Combined ratio + volume score: `(1 − FT_dep_ratio) × 70 + min(pts, 30)`. Naturally bounded 0–100; no clamping needed. |
| SPS | Sportsmanship Score | 5% | Did the player conduct themselves with integrity? Starts at 100; penalties only. Exponential stacking per violation type. Floor at 0 (only sub-score with a clamp). |
| DES | Defensive Effort Score | 5% | Did the player compete defensively? Weighted sum of contested shots, deflections, steals, blocks, defensive rebounds, charges taken; minus foul penalty. Position-adjusted normalization: C ÷ 110, F ÷ 85, G ÷ 60. Unclamped. |

All constants (weights, thresholds, multipliers) live in `config.py`.

---

## pipeline.py

Pulls all raw data for a single game from `nba_api` and returns it as a dict of pandas DataFrames. The original `pipeline.main()` is hardcoded to **Bam Adebayo's 83-point game — Heat vs Wizards, 2026-03-10**. `run_validation.py` and `run_season.py` reimplement the same API calls inline with flexible game lookup — do not call `pipeline.main()` from those scripts.

**7 API calls in order (1-second sleep between each):**

1. `LeagueGameFinder` — locates a game ID by team and date
2. `BoxScoreSummaryV3` — game-level metadata (score, officials, line score)
3. `BoxScoreTraditionalV3` — per-player stats: PTS, FGM/A, FTM/A, 3PM/A, REB, STL, BLK, PF, position. Pipeline derives `twoPointersMade` and `twoPointersAttempted` as `FGM − 3PM`.
4. `PlayByPlayV3` — full play log; `actionType`, `subType`, `description` fields carry foul classification
5. `ShotChartDetail` × 2 — one call per team with `player_id=0`; returns shot zone, made/missed, LOC_X/Y
6. `BoxScoreHustleV2` — per-player hustle stats for all players
7. `PlayerDashPtShots` × 2 — one call per team with `player_id=0`; result set `[4]` provides `CLOSE_DEF_DIST_RANGE` buckets per player (season-level; per-game date filtering returns 0 rows)

**Returns:** `{"game_id", "game_summary", "player_box", "pbp", "shots", "hustle", "proximity"}`

**Headers:** The NBA stats API silently times out on outdated User-Agents. `config.py` uses Chrome 145 and `NBAStatsHTTP.headers` is patched globally at import time — do not pass `headers=` per endpoint.

---

## compute_ehi.py

Consumes the data dict and computes EHI sub-scores for every active player. Players with fewer than `MIN_MINUTES_THRESHOLD` (8) minutes are excluded entirely from all results and DB saves.

### Position Detection

`map_position(pos)` maps `BoxScoreTraditionalV3` position strings to `'center'`, `'forward'`, or `'guard'`. Forward is the neutral default for empty or unrecognised values. Position is passed to `compute_des`, `compute_fds`, and `compute_sqs` to apply position-adjusted thresholds.

| BoxScore String | Mapped |
|---|---|
| `C` | center |
| `F-C`, `C-F` | forward |
| `F`, `PF`, `SF` | forward |
| `G`, `PG`, `SG`, `G-F`, `F-G` | guard |
| (empty / unknown) | forward |

### FTP — FT Dependency Score
- Formula: `ratio_score = (1 − ft_dep_ratio) × 70`; `volume_score = min(total_pts, 30)`; `FTP = ratio_score + volume_score`
- Naturally bounded [0, 100] — no clamping needed
- Zero scorers: `dep_ratio = 0 → FTP = 70` (neutral baseline)
- Constants: `FTP_RATIO_WEIGHT = 70`, `FTP_VOLUME_CAP = 30`

### SPS — Sportsmanship Score
- Starts at 100; `penalty = base × (count ^ SPS_STACK_EXP)` per violation type; `SPS = max(0, 100 − sum)`
- **Only sub-score with a clamp** — floor at 0
- Violation types and base penalties: Technical −18, Flagrant 1 −25, Flagrant 2 −40, Illegal Screen −10, Delay of Game −8
- `build_violation_index(pbp)` scans PBP once; returns `{personId: {vtype: count}}`

### DES — Defensive Effort Score
- Weighted sum: contested × 3.5, deflections × 4.0, steals × 5.0, blocks × 5.0, drebs × 2.0, charges × 15.0
- **Position-adjusted normalization:** `des_raw = (positive_total / norm) × 100`
  - `DES_NORM_CENTER = 110`, `DES_NORM_FORWARD = 85`, `DES_NORM_GUARD = 60`
- Foul penalty: `(adjusted_fouls ^ 1.3) × 5` where defensive × 1.0, offensive × 1.3, loose-ball × 0.5
- All defensive stats zero → `DES = ZERO_DEF_BASELINE (25)`; unclamped otherwise

### FDS — Foul Drawing Score
- Per-foul legitimacy signal (0→1); key signals:
  - Defender proximity: `very_tight_pct × 0.40 + tight_pct × 0.25` from PlayerDashPtShots; flat +0.25 fallback
  - **Position modifier:** center drawing paint foul +0.10 (`FDS_CENTER_PAINT_BONUS`); guard drawing 3pt foul −0.10 (`FDS_GUARD_3PT_PENALTY`)
  - Assisted (catch-and-shoot) +0.20; And-1 (made + fouled) +0.20
  - **Repetition penalty:** 3rd foul of same subtype −0.10 (`FDS_REP_PENALTY_3RD`); 4th+ −0.20 (`FDS_REP_PENALTY_4TH`)
  - Off-ball fouls capped at 0.45 legitimacy
  - **Garbage time cap:** Q4, lead ≥ 25 pts (`GARBAGE_TIME_LEAD`), ≤ 5 min left → legitimacy capped at 0.20
- `FDS = avg_legitimacy × 100`; FT% modifier ×0.92 if FT% < 0.60 and FTA ≥ 4; zero-FTA baseline = 50

### SQS — Shot Quality Score
- Per-shot: made → `xeFG × 100`; open miss (xeFG ≥ 0.38) → `× 0.85`; chuck miss (xeFG < 0.38) → `× 0.50 − (chuck_count ^ 1.4) × 3`
- Self-created bonus ×1.25 if unassisted, made, xeFG ≥ 0.50; assisted demerit ×0.90 if assisted, xeFG < 0.45
- **Volume-quality bonus** if `n_shots ≥ 15` and `avg_xeFG ≥ threshold`: `SQS += (n_shots − 14) × 0.5`
  - Position-adjusted threshold: C = 0.58, F = 0.53, G = 0.50
- `SQS = raw_mean + volume_bonus` — unclamped

### Empirical xeFG% Table (12-game sample, 2,216 shots)

Zones with ≥ 50 shots in `ehi.db` use empirical values; others fall back to hardcoded.

| Zone | Empirical | Hardcoded | Active |
|---|---|---|---|
| Restricted Area | 0.6560 | 0.72 | empirical |
| In the Paint (Non-RA) | 0.4500 | 0.54 | empirical |
| Mid-Range | 0.4810 | 0.44 | empirical |
| Left Corner 3 | 0.2750 | 0.58 | empirical |
| Right Corner 3 | 0.3980 | 0.58 | empirical |
| Above the Break 3 | 0.3620 | 0.52 | empirical |
| Backcourt | — | 0.30 | hardcoded |

*Current empirical values reflect a small validation sample — expect significant shifts after the full season run.*

### Validation Helpers
- `print_ftp_report(df)`, `print_sps_report(df)`, `print_des_report(df)`, `print_fds_report(df, detail)`, `print_sqs_report(df, detail)`, `print_ehi_leaderboard(df)`, `print_bam_breakdown(df)`
- `print_empirical_xefg_table()` — prints DB-derived vs hardcoded xeFG% by zone with shot counts
- `print_validation_table(pts_threshold=20)` — queries `ehi.db` and prints star-player validation rows

---

## run_validation.py

Runs the full EHI pipeline across 12 hardcoded validation games and stores results in `ehi.db`. Accepts optional CLI game number arguments to run a subset (`python3 run_validation.py 12` or `python3 run_validation.py 11 12`).

---

## run_season.py

Full 2025-26 regular season run. Fetches all game IDs dynamically via `LeagueGameFinder(season_nullable='2025-26', season_type_nullable='Regular Season')`, deduplicates by game_id (each game appears twice in the API response), sorts by date ascending, and processes each game with the same pull/compute/save loop as `run_validation.py`.

**Key behaviors:**
- **Resume-safe:** silently skips any game_id already in `ehi.db`'s `games` table
- **Retry logic:** up to 3 attempts per API call; rate-limit errors (`429`, `"too many"`) sleep 60s; other errors use exponential backoff (10s → 20s → 40s)
- **ShotChartDetail fallback:** if shot chart fails after all retries, SQS falls back to neutral baseline (50) for all players in that game; run continues
- **Error logging:** all per-game failures written to `season_errors.log` with timestamp, game details, and full traceback
- **CLI subset:** `python3 run_season.py 1 100` processes games 1–100 (1-indexed) for chunked runs
- **Progress line:** `Game X/Y — TEAM1 vs TEAM2 — N players saved` after each game
- **Completion:** prints run stats (processed / skipped / failed / players saved / EHI range + mean) then automatically calls `get_season_summary('2025-26')`

**Rate limiting:** 2s sleep between every API call, 5s sleep between games.
**Expected runtime:** ~9–10 hours for the full 2025-26 season (~1,230 games).

---

## query_ehi.py

Database query utilities callable both programmatically and from the command line. All functions print formatted tables and return data (dict or list of dicts). Player name matching uses case-insensitive substring search; disambiguates when multiple players match.

| Function | CLI command | Description |
|---|---|---|
| `get_player_game(name, date)` | `player-game 'Name' YYYY-MM-DD` | Full EHI breakdown (sub-scores + weighted bar chart) for one player on one date |
| `get_player_season(name, season)` | `player 'Name' 2025-26` | Season averages: avg SQS/FDS/FTP/SPS/DES/EHI, GP, avg PTS, EHI min/max |
| `get_game_leaderboard(date, t1, t2)` | `game YYYY-MM-DD DAL ATL` | Full leaderboard for a specific game sorted by EHI descending |
| `get_season_best(season, n=10)` | `season-best 2025-26 [n]` | Top N players by avg EHI, minimum 20 games played |
| `get_season_worst(season, n=10)` | `season-worst 2025-26 [n]` | Bottom N players by avg EHI, minimum 20 games played |
| `get_season_summary(season)` | `summary 2025-26` | League avg EHI, highest/lowest game EHI, team rankings, top/bottom 10 players |

**CLI examples:**
```bash
python3 query_ehi.py player       'Luka Doncic'  2025-26
python3 query_ehi.py player-game  'Luka Doncic'  2026-01-26
python3 query_ehi.py game          2026-01-26    DAL  ATL
python3 query_ehi.py season-best   2025-26       20
python3 query_ehi.py season-worst  2025-26
python3 query_ehi.py summary       2025-26
```

---

## Development Approach

All five sub-scores and season-run infrastructure are complete.

- [x] FTP — complete, validated
- [x] SPS — complete, validated (Coulibaly 1 tech → SPS 82.0 confirmed)
- [x] DES — complete, validated; position-adjusted normalization (C÷110, F÷85, G÷60)
- [x] FDS — complete, validated; position modifiers added; rep penalties softened; zero-FTA baseline = 50
- [x] SQS — complete, validated; empirical xeFG table; position-adjusted volume-quality bonus
- [x] EHI aggregation — complete; validated across 12 games
- [x] run_season.py — built; ready for overnight 2025-26 run
- [x] query_ehi.py — built; all 6 query functions with CLI support

**Current validation results (12 games, n=17 star player-game rows):**
EHI range 47.62–69.45 · mean 57.24 · std dev 4.95

---

## Known Design Notes

**`chargesDrawn` column name:** `BoxScoreHustleV2` returns `chargesDrawn`, not `chargesTaken`. The EHI reference document uses `chargesTaken` — use `chargesDrawn` when reading the hustle DataFrame.

**Illegal screen and delay of game not tested:** No illegal screen or delay-of-game violations appear in the 12 validation games. The SPS matchers for those two types are written defensively but have not been exercised against real data.

**FDS defender proximity — season-level proxy:** `build_proximity_index(proximity_df)` converts season-level `CLOSE_DEF_DIST_RANGE` bucket data into per-player `{very_tight_pct, tight_pct}` fractions. Falls back to flat +0.25 if no data. Season-level is used as a game-level proxy because `PlayerDashPtShots` returns 0 rows when date-filtered to a single game.

**Sub-score clamping removed:** All sub-scores except SPS float freely — no floor, no ceiling. SPS floor = 0. DES and SQS can exceed 100 for exceptional performances. FTP is naturally bounded [0, 100] by formula construction.

**DES position-adjusted normalization:** Replaces the flat 80-point baseline. Centers are expected to generate more defensive activity and normalize against a higher baseline (110); guards normalize against 60 so an average guard performance still scores near 100.

**Empirical xeFG% — small sample caveat:** The 12-game, 2,216-shot sample produces values that differ substantially from league averages (notably left corner 3 at 0.275 vs hardcoded 0.58). These will stabilize after the full season run. The table updates automatically at import time: any zone with ≥50 shots in `ehi.db` overrides its hardcoded fallback.

**Position detection uses roster label, not role:** `BoxScoreTraditionalV3` returns the NBA's positional label (C, F-C, G, etc.), which reflects roster designation rather than actual on-court role. A stretch big listed as C normalizes against the center baseline regardless of how he plays.

**FDS repetition penalties softened:** 3rd foul of same subtype −0.10 (was −0.20); 4th+ −0.20 (was −0.30). Prevents over-penalizing players in games where a specific foul type occurs legitimately multiple times.

**Garbage time tightened to 25-point lead:** `GARBAGE_TIME_LEAD = 25` (was 20). Reduces false-positives on large but still competitive 4th-quarter margins.

**No per-shot defender distance:** `ShotChartDetail` does not return per-shot defender distance. Defender proximity for SQS/FDS is derived from season-level `PlayerDashPtShots` bucket distributions, not from shot-specific data.

**No opponent adjustment:** EHI scores are absolute, not adjusted for opponent quality. A guard defending a bad team's shooters gets the same DES credit as one defending elite shooters.

**Next step — `run_season.py` overnight run:** Expected ~9–10 hours for the full 2025-26 season (~1,230 games). On completion, `get_season_summary('2025-26')` prints automatically. Running `python3 query_ehi.py summary 2025-26` afterward shows the first full-season EHI distribution and team rankings.
