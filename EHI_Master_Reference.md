# Ethical Hoops Index (EHI) — Master Reference Document

## Overview

The **Ethical Hoops Index (EHI)** is a composite per-game metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct, while penalizing manipulation, deception, and laziness.

Sub-scores are **unclamped** — they can exceed 100 for exceptional performances. The sole exception is SPS, which has a floor of 0. FTP is naturally bounded [0, 100] by formula construction. EHI inherits the same float-freely behaviour from the weighted sum. All players with fewer than 8 minutes are excluded from computation entirely.

---

## Master Formula

```
EHI = 0.45(SQS) + 0.20(FDS) + 0.25(FTP) + 0.05(SPS) + 0.05(DES)
```

| Sub-Score | Name | Weight |
|---|---|---|
| SQS | Shot Quality Score | 45% |
| FDS | Foul Drawing Score | 20% |
| FTP | FT Dependency Score | 25% |
| SPS | Sportsmanship Score | 5% |
| DES | Defensive Effort Score | 5% |

---

## Sub-Score 1: Shot Quality Score (SQS) — 45%

### Goal
Did this player take shots that a skilled, ethical player would take?

### Inputs (via `nba_api`)
- Shot zone / distance (ShotChartDetail — `SHOT_ZONE_BASIC`)
- Whether shot was assisted or self-created (PlayByPlayV3 assist cross-reference)
- Made / missed (ShotChartDetail — `SHOT_MADE_FLAG`)
- xeFG% by zone (empirical from `ehi.db` shots table; hardcoded fallbacks)

### xeFG% Reference Table

Zones with ≥ 50 shots in `ehi.db` use empirical values; all others fall back to hardcoded league averages. The table is rebuilt at import time from `compute_ehi._build_xefg_table()`.

| Zone | Empirical (full 2025-26 season) | Hardcoded Fallback | Active |
|---|---|---|---|
| Restricted Area | 0.6560 | 0.72 | empirical |
| In the Paint (Non-RA) | 0.4500 | 0.54 | empirical |
| Mid-Range | 0.4810 | 0.44 | empirical |
| Left Corner 3 | 0.2750 | 0.58 | empirical |
| Right Corner 3 | 0.3980 | 0.58 | empirical |
| Above the Break 3 | 0.3620 | 0.52 | empirical |
| Backcourt | — | 0.30 | hardcoded |

> **Note:** Empirical values now reflect the full 2025-26 season run (1,223 games). Corner 3 figures remain below hardcoded league averages — likely reflects genuine sample composition rather than small-sample noise.

### Per-Shot Score Logic

```python
base = xeFG% * 100

if made:
    shot_score = base * 1.0

elif xeFG% >= 0.38:   # reasonable shot, just missed
    shot_score = base * 0.85  # OPEN_MISS_MULT

else:                 # chuck: bad shot + missed
    chuck_count += 1
    shot_score = base * 0.50  # CONTESTED_MISS_MULT
    shot_score -= (chuck_count ^ 1.4) * 3  # cumulative penalty (CHUCK_PENALTY)

# Self-created bonus (unassisted make in a quality zone)
if not assisted and made and xeFG% >= 0.50:
    shot_score *= 1.25   # SELF_CREATED_MULT

# Assisted demerit (catch-and-shoot, underperforming the look)
if assisted and xeFG% < 0.45:
    shot_score *= 0.90   # ASSISTED_DEMERIT
```

### Rules
- Bad shot (xeFG% < 0.38) + **made** → no penalty; you scored
- Open shot + **missed** → no penalty; correct decision
- Chuck penalty is cumulative and escalates exponentially within a game
- No shot-clock exception — all shot attempts included

### Volume-Quality Bonus

After computing the per-shot mean, if both conditions are met, a bonus is added:

```python
avg_xefg = mean(s["xefg"] for s in all_shots)
n_shots   = len(all_shots)

# Position-adjusted xeFG threshold
xefg_threshold = {
    "center":  0.58,   # SQS_XEFG_THRESHOLD_CENTER
    "forward": 0.53,   # SQS_XEFG_THRESHOLD_FORWARD
    "guard":   0.50,   # SQS_XEFG_THRESHOLD_GUARD
}[position]

if n_shots >= 15 and avg_xefg >= xefg_threshold:
    volume_bonus = (n_shots - 14) * 0.5
    SQS += volume_bonus
```

Rewards players who sustain high shot quality across high volume. Threshold is position-adjusted: centers must maintain a higher zone quality average than guards to qualify.

### Final SQS
```python
SQS = raw_mean + volume_bonus   # unclamped; can exceed 100
```

Zero shots → `SQS = SQS_ZERO_SHOTS_BASELINE (50)`.

---

## Sub-Score 2: Foul Drawing Score (FDS) — 20%

### Goal
Did this player earn their free throws, or manufacture them?

### Philosophy
Ethical basketball = scoring through skill, not contact. Even legitimate fouls are less ideal than not needing them. Proximity to the defender and game context determine how much credit each FTA is worth.

### Foul Legitimacy Score (per foul drawn)

Each foul drawn that results in FTA gets a legitimacy score (0.0–1.0):

```python
legitimacy = 0.0

# ── Defender proximity (PlayerDashPtShots season-level bucket distribution) ──
# prox_bonus = very_tight_pct * 0.40 + tight_pct * 0.25
# Falls back to +0.25 flat if no proximity data available for this player.
if not off_ball_foul:
    legitimacy += prox_bonus

# ── Position modifier ──────────────────────────────────────────────────────
if position == "center" and location == "paint":
    legitimacy += 0.10   # FDS_CENTER_PAINT_BONUS — natural contact zone
if position == "guard" and location == "3pt":
    legitimacy -= 0.10   # FDS_GUARD_3PT_PENALTY — higher manipulation suspicion

# ── Other positive signals ─────────────────────────────────────────────────
if assisted (catch-and-shoot): legitimacy += 0.20
if and_1 (made shot + foul):   legitimacy += 0.20

# ── Repetition penalty (same foul subtype within this game) ───────────────
if 3rd foul of same subtype:  legitimacy -= 0.10   # FDS_REP_PENALTY_3RD
if 4th+ foul of same subtype: legitimacy -= 0.20   # FDS_REP_PENALTY_4TH

# ── Hard caps ─────────────────────────────────────────────────────────────
if off_ball_foul:
    legitimacy = min(legitimacy, 0.45)

# Garbage time: Q4, lead ≥ 25 pts, ≤ 5 min left
if garbage_time:
    legitimacy = min(legitimacy, 0.20)   # GARBAGE_TIME_LEG_CAP

# Global clamp
legitimacy = clamp(legitimacy, 0.0, 1.0)
```

> **Rep penalty history:** 3rd-foul penalty was softened from −0.20 → −0.10; 4th+ from −0.30 → −0.20 after 12-game validation showed over-penalisation of players who legitimately drew the same foul type repeatedly.

### FDS Formula

```python
avg_legitimacy = mean(all foul legitimacy scores)

FDS = avg_legitimacy * 100   # unclamped

# FT% modifier
if FTM / FTA < 0.60 and FTA >= 4:
    FDS *= 0.92   # FT_PCT_MODIFIER

# Zero-FTA baseline
if FTA_in_game == 0:
    FDS = 50   # ZERO_FTA_BASELINE — neutral; player neither helped nor hurt
```

> **Calibration log:** Volume penalty (`FTA^1.15 × 1.0`) was removed — it zeroed star players regardless of legitimacy quality. Aggregate clamp also removed; FDS floats freely. Zero-FTA baseline reduced from 72 → 50 to compress the bench-player advantage. Position modifiers and softened rep penalties added after 12-game validation.

---

## Sub-Score 3: FT Dependency Score (FTP) — 25%

### Goal
Reward scoring through field goals and penalize FT dependency, while recognising that high-volume FG scorers contribute more than low-volume ones at the same dependency rate.

### Formula

```python
FT_points    = FTM
FG_points    = (FGM_2pt * 2) + (FGM_3pt * 3)
total_points = FT_points + FG_points

ft_dep_ratio = FT_points / total_points   # 0.0 if total_points == 0

ratio_score  = (1 - ft_dep_ratio) * 70   # max 70  (FTP_RATIO_WEIGHT)
volume_score = min(total_points, 30)      # max 30  (FTP_VOLUME_CAP)

FTP = ratio_score + volume_score          # naturally in [0, 100], no clamp needed
```

### Key Properties
- **Zero scorers:** `dep_ratio = 0 → ratio = 70, volume = 0 → FTP = 70` (neutral)
- **Max score (100):** requires 0% FT dependency AND ≥ 30 field-goal points
- **Pure FT scorers:** `dep_ratio = 1.0 → ratio = 0, volume = min(ftm, 30)`
- No exponential penalty, no edge-case overrides

### Reference Table

| Pts | FTM | FT dep% | ratio | vol | FTP |
|---|---|---|---|---|---|
| 0 | 0 | 0% | 70.0 | 0 | 70.0 |
| 14 | 0 | 0% | 70.0 | 14 | 84.0 |
| 30 | 0 | 0% | 70.0 | 30 | 100.0 |
| 20 | 4 | 20% | 56.0 | 20 | 76.0 |
| 30 | 8 | 27% | 51.3 | 30 | 81.3 |
| 55 | 12 | 22% | 54.7 | 30 | 84.7 |
| 61 | 22 | 36% | 44.8 | 30 | 74.8 |
| 10 | 6 | 60% | 28.0 | 10 | 38.0 |
| 10 | 10 | 100% | 0.0 | 10 | 10.0 |

---

## Sub-Score 4: Sportsmanship Score (SPS) — 5%

### Goal
Did this player conduct themselves with integrity, or manipulate the game through deception and aggression?

### Philosophy
Starts at 100, penalties only. Clean conduct = no deduction. Flagrant fouls are handled here (not DES).

### Violation Penalties

| Violation | Base Penalty |
|---|---|
| Flagrant 2 | −40 |
| Flagrant 1 | −25 |
| Technical foul | −18 |
| Illegal screen (called) | −10 |
| Delay of game | −8 |

- Late-game intentional fouls: **not penalized** (legitimate strategy)
- Flop violations: handled implicitly via FDS low legitimacy scores; no dedicated endpoint available

### Exponential Stacking (per violation type)

```python
for each violation_type:
    count   = occurrences in this game
    penalty = base_penalty * (count ^ 1.4)   # SPS_STACK_EXP

SPS = max(0, 100 - sum(all penalties))   # floor at 0; only sub-score with any clamp
```

### Stacking Reference (Technical Fouls, base = 18)

| Techs | Penalty |
|---|---|
| 1 | 18.0 pts |
| 2 | 48.0 pts |

---

## Sub-Score 5: Defensive Effort Score (DES) — 5%

### Goal
Did this player compete defensively, or coast and take plays off?

### Positive Signals

| Stat | Weight |
|---|---|
| Contested shots defended | × 3.5 |
| Deflections | × 4.0 |
| Steals | × 5.0 |
| Blocks | × 5.0 |
| Defensive rebounds | × 2.0 |
| Charges taken (`chargesDrawn`) | × 15.0 |

### Foul Penalty (Differentiated by Type)

```python
adjusted_fouls = (defensive_fouls  * 1.0)   # DEF_FOUL_MULT
               + (offensive_fouls  * 1.3)   # OFF_FOUL_MULT — active manipulation
               + (loose_ball_fouls * 0.5)   # LOOSE_BALL_MULT — effort play, lightest

foul_penalty = (adjusted_fouls ^ 1.3) * 5   # FOUL_PENALTY_EXP, FOUL_PENALTY_BASE
```

### DES Formula (Position-Adjusted)

```python
positive_total = (contested * 3.5) + (deflections * 4.0)
               + (steals * 5.0)   + (blocks * 5.0)
               + (drebs * 2.0)    + (charges * 15.0)

# Position-adjusted normalization
norm = {
    "center":  110,   # DES_NORM_CENTER
    "forward":  85,   # DES_NORM_FORWARD
    "guard":    60,   # DES_NORM_GUARD
}[position]

DES_raw = (positive_total / norm) * 100   # unclamped

foul_penalty = (adjusted_fouls ^ 1.3) * 5

DES = DES_raw - foul_penalty   # unclamped; can exceed 100 or go negative

# Zero-defense edge case
if all defensive stats == 0:
    DES = 25   # ZERO_DEF_BASELINE — coasting, not misconduct
```

**Why position-adjusted?** Centers are expected to contest more shots and grab more defensive rebounds than guards. Normalizing against a higher baseline (110) means a center must generate more activity to reach DES = 100, while a guard reaching 60 weighted points is already performing at an elite level for their role. Replaces the flat 80-point baseline used through the 12-game validation.

### Foul Penalty Reference (defensive fouls only, no type adjustment)

| Fouls | Penalty |
|---|---|
| 1 | 5.0 pts |
| 2 | 11.9 pts |
| 3 | 20.8 pts |
| 4 | 31.5 pts |
| 5 | 43.7 pts |
| 6 (fouled out) | 57.3 pts |

---

## Garbage Time Rule

### Definition
```python
if quarter == 4 and point_differential >= 25 and time_remaining_seconds <= 300:
    garbage_time = True
```

A game is considered decided once the lead reaches 25+ points with ≤ 5 minutes left. FTA drawn in this window are flagged as potential stat-padding regardless of how legitimate the foul appeared.

> **Threshold history:** Lead threshold tightened from 20 → 25 pts after 12-game validation flagged too many legitimate 4th-quarter fouls in games that remained competitive.

### Application in FDS
```python
if garbage_time and foul_drawn:
    legitimacy = min(legitimacy, 0.20)   # GARBAGE_TIME_LEG_CAP
```

### What This Does NOT Affect
- Field goal attempts in garbage time are **not penalized** — shooting in a blowout is fine
- DES, SPS, and FTP are unaffected by the garbage time flag
- Early-game legitimate play is fully preserved

---

## Data Sources

| Data | Source | Endpoint |
|---|---|---|
| Shot location, zone, made/missed | `nba_api` | `ShotChartDetail` (player_id=0, per team) |
| Assisted vs self-created | `nba_api` | `PlayByPlayV3` + assist cross-reference |
| Defender proximity (FDS legitimacy) | `nba_api` | `PlayerDashPtShots` result set [4] — `CLOSE_DEF_DIST_RANGE` buckets, season-level |
| FTA, FTM, FGM breakdown, position | `nba_api` | `BoxScoreTraditionalV3` |
| Foul type classification | `nba_api` | `PlayByPlayV3` (actionType / subType / description) |
| Technical / flagrant fouls | `nba_api` | `PlayByPlayV3` |
| Contested shots, deflections, charges | `nba_api` | `BoxScoreHustleV2` (`chargesDrawn` column) |
| Blocks, steals, rebounds | `nba_api` | `BoxScoreTraditionalV3` |
| Official flop violations | NBA.com | Published foul reports (V2 — not yet integrated) |

---

## Scripts

| Script | Purpose |
|---|---|
| `pipeline.py` | Single-game data pull hardcoded to Bam Adebayo 2026-03-10 — used for development only |
| `compute_ehi.py` | Sub-score computation for all active players; validation print helpers |
| `run_validation.py` | Runs 12 hardcoded validation games; writes to `ehi.db` |
| `run_season.py` | Full 2025-26 regular season run; resume-safe; retry/backoff; auto-calls `get_season_summary` on completion |
| `query_ehi.py` | DB query utilities: `get_player_game`, `get_player_season`, `get_game_leaderboard`, `get_season_best`, `get_season_worst`, `get_season_summary`; all callable from CLI |
| `database.py` | SQLite persistence layer (`games`, `player_games`, `shots`, `validation_notes` tables) |
| `config.py` | All tunable constants |

**`query_ehi.py` CLI examples:**
```bash
python3 query_ehi.py player       'Luka Doncic'  2025-26
python3 query_ehi.py player-game  'Luka Doncic'  2026-01-26
python3 query_ehi.py game          2026-01-26    DAL  ATL
python3 query_ehi.py season-best   2025-26       20
python3 query_ehi.py season-worst  2025-26
python3 query_ehi.py summary       2025-26
```

---

## Validation Status

Validated across **12 games** (218+ qualifying player-game rows, min ≥ 8 min, stored in `ehi.db`).

**Validation stats (n=17 star player-game rows, pts ≥ 20):**
EHI range: **47.62–69.45** · mean: **57.24** · std dev: **4.95**

Representative star-player results (run `python3 compute_ehi.py` for current values):

| Player | Game | MIN | Pts | SQS | FDS | FTP | DES | EHI |
|---|---|---|---|---|---|---|---|---|
| Jalen Brunson | MIL vs NYK 12/23/2023 | 37.3 | 36 | 62.8 | 34.1 | 94.2 | 83.3 | ~68 |
| Victor Wembanyama | SAS vs DAL 10/22/2025 | 29.7 | 40 | 62.9 | 12.6 | 84.2 | 83.4 | ~61 |
| Kawhi Leonard | DET vs LAC 12/28/2025 | 38.6 | 55 | 60.0 | 8.7 | 79.6 | 128.9 | ~60 |
| Stephen Curry | GSW vs POR 01/03/2021 | 36.4 | 62 | 66.1 | 3.4 | 79.7 | 37.5 | ~57 |
| LeBron James | LAL vs CLE 03/31/2026 | 30.6 | 14 | 51.8 | 8.5 | 59.0 | 30.8 | ~47 |

*Exact values shift with each calibration; use `print_validation_table()` or `query_ehi.py` for live DB figures.*

---

## 2025-26 Season Results

Full season run complete. **1,223 games** processed (1,197 direct + 26 retried), **23,313 player-game rows** saved to `ehi.db`.

| Metric | Value |
|---|---|
| League avg EHI | **48.27** |
| Season high (single game) | **75.76** — Rudy Gobert |
| Season low (single game) | **8.91** — Collin Gillespie |

**Season top 10 highlights** (avg EHI, min 20 GP):

| Rank | Player | Avg EHI | GP |
|---|---|---|---|
| 1 | Mitchell Robinson | 60.43 | — |
| 2 | Robert Williams III | 60.06 | — |
| 3 | Jericho Sims | 59.23 | — |
| — | Giannis Antetokounmpo | 58.04 | 35 |
| — | Dyson Daniels | 57.77 | 76 |

**Season bottom 10 highlights:**

| Rank | Player | Avg EHI |
|---|---|---|
| 1 (worst) | Jordan Poole | 39.47 |
| 2 | Grayson Allen | 40.19 |

**Team rankings highlight:** New Orleans Pelicans — most ethical team at **49.84** avg EHI.

> Run `python3 query_ehi.py summary 2025-26` for the full 30-team ranking and complete top/bottom 10 lists.

**Known issue — positional bias in top rankings:** Low-scoring centers dominate the top-10 because DES normalizes against center activity levels (÷110) without accounting for offensive contribution. High DES from rim protection combined with the neutral FTP baseline (70.0 for zero scorers) inflates EHI for low-usage bigs. A fix is planned.

---

## Tunable Constants

All live in `config.py`.

```python
# ─── Weights ────────────────────────────────────────────────────────────────
W_SQS = 0.45
W_FDS = 0.20
W_FTP = 0.25
W_SPS = 0.05
W_DES = 0.05

# ─── Activity filter ────────────────────────────────────────────────────────
MIN_MINUTES_THRESHOLD = 8   # players below this excluded entirely

# ─── SQS ────────────────────────────────────────────────────────────────────
CHUCK_THRESHOLD          = 0.38
SELF_CREATED_MULT        = 1.25
ASSISTED_DEMERIT         = 0.90
OPEN_MISS_MULT           = 0.85
CONTESTED_MISS_MULT      = 0.50
CHUCK_PENALTY_EXP        = 1.4
CHUCK_PENALTY_MULT       = 3
SQS_ZERO_SHOTS_BASELINE  = 50
SQS_SC_XEFG_THRESHOLD    = 0.50
SQS_AST_XEFG_THRESHOLD   = 0.45

# Position-adjusted volume-quality xeFG thresholds
SQS_XEFG_THRESHOLD_CENTER  = 0.58
SQS_XEFG_THRESHOLD_FORWARD = 0.53
SQS_XEFG_THRESHOLD_GUARD   = 0.50

# xeFG% hardcoded fallbacks (overridden by empirical data where ≥50 shots in DB)
XEFG_AT_RIM         = 0.72
XEFG_PAINT_NON_RIM  = 0.54
XEFG_MID_RANGE      = 0.44
XEFG_CORNER_3       = 0.58
XEFG_ABOVE_BREAK_3  = 0.52
XEFG_BACKCOURT      = 0.30

# ─── FDS ────────────────────────────────────────────────────────────────────
FT_PCT_THRESHOLD       = 0.60
FT_PCT_MODIFIER        = 0.92
ZERO_FTA_BASELINE      = 50
FDS_REP_PENALTY_3RD    = 0.10   # 3rd foul of same subtype  (was 0.20)
FDS_REP_PENALTY_4TH    = 0.20   # 4th+ foul of same subtype (was 0.30)
FDS_CENTER_PAINT_BONUS = 0.10
FDS_GUARD_3PT_PENALTY  = 0.10
VOLUME_PENALTY_BASE    = 1.0    # DEPRECATED — not applied
VOLUME_PENALTY_EXP     = 1.15   # DEPRECATED — not applied

# ─── FTP ────────────────────────────────────────────────────────────────────
FTP_RATIO_WEIGHT = 70   # (1 - dep_ratio) * 70
FTP_VOLUME_CAP   = 30   # min(total_pts, 30)

# ─── SPS ────────────────────────────────────────────────────────────────────
TECH_PENALTY        = 18
FLAGRANT1_PENALTY   = 25
FLAGRANT2_PENALTY   = 40
ILLEGAL_SCREEN_PEN  = 10
DELAY_PENALTY       = 8
SPS_STACK_EXP       = 1.4

# ─── DES ────────────────────────────────────────────────────────────────────
CONTESTED_WEIGHT  = 3.5
DEFLECTION_WEIGHT = 4.0
STEAL_WEIGHT      = 5.0
BLOCK_WEIGHT      = 5.0
DREB_WEIGHT       = 2.0
CHARGE_WEIGHT     = 15.0
DES_NORM_CENTER   = 110   # position-adjusted normalization baselines
DES_NORM_FORWARD  = 85
DES_NORM_GUARD    = 60
DES_NORMALIZATION = 80    # DEPRECATED — flat baseline replaced by per-position norms
FOUL_PENALTY_BASE = 5
FOUL_PENALTY_EXP  = 1.3
DEF_FOUL_MULT     = 1.0
OFF_FOUL_MULT     = 1.3
LOOSE_BALL_MULT   = 0.5
ZERO_DEF_BASELINE = 25

# ─── Garbage Time ───────────────────────────────────────────────────────────
GARBAGE_TIME_LEAD         = 25   # point differential threshold (was 20)
GARBAGE_TIME_MINUTES_LEFT = 5
GARBAGE_TIME_LEG_CAP      = 0.20
GARBAGE_FTA_THRESHOLD     = 0.30
GARBAGE_FTP_PENALTY_MULT  = 0.20
GARBAGE_FTP_PENALTY_EXP   = 1.3
```

---

## Known Limitations

| Limitation | Impact | Future fix |
|---|---|---|
| xeFG% corner 3 below league avg | Values (L: 0.275, R: 0.398) may reflect sample composition; stable after full season | Monitor vs league-published xeFG data |
| Position detection uses roster label, not role | Stretch bigs and combo guards normalise against wrong baseline | Manual override map |
| No per-shot defender distance | SQS cannot distinguish open vs contested at shot level | `ShotQualityDetail` endpoint (if available) |
| FDS proximity is season-level, not game-level | `PlayerDashPtShots` returns 0 rows per game; season average used as proxy | None available |
| No opponent adjustment | DES/SQS not adjusted for opponent quality | Separate opponent-strength factor |
| No clutch-moment bonus | Big shot in close game counts same as garbage-time make | Clutch multiplier (future) |
| Illegal screen / delay-of-game SPS matchers untested | Validation games contained no such violations | Test against a game with a known illegal screen |

---

*EHI v1.3 — 2025-26 full season complete (1,223 games, 23,313 rows); league avg 48.27; positional bias identified in top rankings (fix planned); empirical xeFG table updated to full-season values*
