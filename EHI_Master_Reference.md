# Ethical Hoops Index (EHI) — Master Reference Document

## Overview

The **Ethical Hoops Index (EHI)** is a composite per-game metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct, while penalizing manipulation, deception, and laziness.

Sub-scores are **unclamped** — they can exceed 100 for exceptional performances. The sole exception is SPS which has a floor of 0. FTP is naturally bounded [0, 100] by formula construction. EHI inherits the same range and floats freely with the weighted sum. All players with fewer than 8 minutes are excluded from computation entirely.

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

## Sub-Score 1: Shot Quality Score (SQS) — 35%

### Goal
Did this player take shots that a skilled, ethical player would take?

### Inputs (via `nba_api`)
- Shot distance / zone
- Defender distance at shot (open / lightly / tightly / very tightly contested)
- Shot type (layup, mid-range, corner 3, above-break 3, pull-up, etc.)
- Whether shot was assisted or self-created
- Made / missed
- xeFG% lookup table (historical make rate by location + contest level)

### xeFG% Reference Table (approximate)

| Shot Type | Defender Distance | xeFG% |
|---|---|---|
| At rim | Open | ~0.72 |
| At rim | Tightly contested | ~0.54 |
| Corner 3 | Open | ~0.58 |
| Above-break 3 | Open | ~0.52 |
| Long mid-range | Tightly contested | ~0.34 |
| Pull-up 3 | Very tightly contested | ~0.28 |

### Per-Shot Score Logic

```python
# Open shot (defender_dist > 4ft)
if made:
    shot_score = xeFG% * 100 * 1.0
if missed:
    shot_score = xeFG% * 100 * 0.85   # slight haircut, right decision

# Contested shot (defender_dist <= 4ft)
if made:
    shot_score = xeFG% * 100 * 1.40   # contested make multiplier
if missed:
    shot_score = xeFG% * 100 * 0.50   # bad shot + missed

# Chuck penalty (bad shot + missed only)
if xeFG% < 0.38 and missed:
    chuck_penalty = (game_chuck_count ^ 1.4) * penalty_constant
    shot_score -= chuck_penalty

# Self-created bonus
if self_created and xeFG% >= 0.50 and made:
    shot_score *= 1.25    # 25% bonus for skilled shot creation

# Assisted demerit
if assisted and xeFG% < 0.45:
    shot_score *= 0.90    # slight demerit for underperforming easy look
```

### Rules
- Bad shot (xeFG% < 0.38) + **made** → no penalty, you scored
- Open shot + **missed** → no penalty, correct decision
- Chuck penalty is exponential and compounds per game
- No shot clock exception — all shots included

### Volume-Quality Bonus
After computing the per-shot mean:
```python
avg_xefg = mean(shot["xefg"] for all shots)
if n_shots >= 15 and avg_xefg >= 0.52:
    volume_bonus = (n_shots - 14) * 0.5
    SQS += volume_bonus
```
Rewards players who sustain high shot quality (avg xeFG ≥ 0.52) across high volume (15+ attempts).

### Final SQS
```python
SQS = raw_mean + volume_bonus   # unclamped; can exceed 100
```

---

## Sub-Score 2: Foul Drawing Score (FDS) — 20%

### Goal
Did this player earn their free throws, or manufacture them?

### Philosophy
Ethical basketball = scoring through skill, not contact. Even legitimate fouls are less ideal than not needing them at all.

### Foul Legitimacy Score (per foul drawn)

Each foul drawn that results in FTA gets a legitimacy score (0.0–1.0):

```python
legitimacy = 0.0

# Defender proximity (from PlayerDashPtShots season-level bucket distribution)
# prox_bonus = very_tight_pct * 0.40 + tight_pct * 0.25
# Fallback: +0.25 flat if no proximity data available for the player
if not off_ball_foul:
    legitimacy += prox_bonus   # ranges ~0.08–0.40 depending on player's shot profile

# Other positive signals
if assisted (catch-and-shoot): legitimacy += 0.20
if and_1 (made + fouled):      legitimacy += 0.20

# Repetition penalties (same foul subtype within the game)
if 3rd foul of same type this game:  legitimacy -= 0.20
if 4th+ foul of same type this game: legitimacy -= 0.30

# Hard cap for off-ball fouls (personal / loose-ball in bonus)
if off_ball_foul:
    legitimacy = min(legitimacy, 0.45)

# Garbage time cap (Q4, lead ≥ 20, ≤ 5 min left)
if garbage_time:
    legitimacy = min(legitimacy, 0.20)

# Global clamp
legitimacy = clamp(legitimacy, 0.0, 1.0)
```

### FDS Formula

```python
avg_legitimacy = mean(all foul legitimacy scores)

FDS = avg_legitimacy * 100   # unclamped

# FT% modifier
if FTM / FTA < 0.60 and FTA >= 4:
    FDS *= 0.92

# Zero-FTA baseline
if FTA_in_game == 0:
    FDS = 50   # neutral; player neither helped nor hurt by foul drawing
```

> **Note (calibration 2025-05):** Volume penalty (`FTA^1.3 × 2.5`) was removed — it zeroed out all high-FTA star players regardless of legitimacy quality. Aggregate clamp also removed; FDS floats freely. Zero-FTA baseline reduced from 72 → 50 to compress the bench-player advantage.

---

## Sub-Score 3: FT Dependency Score (FTP) — 25%

### Goal
Reward scoring through field goals and penalize FT dependency, while also recognizing that high-volume FG scorers contribute more than low-volume ones at the same dependency rate.

### Formula

```python
FT_points    = FTM
FG_points    = (FGM_2pt * 2) + (FGM_3pt * 3)
total_points = FT_points + FG_points

ft_dep_ratio = FT_points / total_points   # 0.0 if total_points == 0

ratio_score  = (1 - ft_dep_ratio) * 70   # max 70
volume_score = min(total_points, 30)      # max 30

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

## Sub-Score 4: Sportsmanship Score (SPS) — 15%

### Goal
Did this player conduct themselves with integrity, or manipulate the game through deception and aggression?

### Philosophy
Starts at 100, penalties only. Clean conduct = no deduction. Flagrant fouls committed on defense are handled here (not DES).

### Violation Penalties

| Violation | Base Penalty |
|---|---|
| Flagrant 2 | -40 |
| Flagrant 1 | -25 |
| Technical foul | -18 |
| Illegal screen (called) | -10 |
| Delay of game | -8 |

- Technical fouls: **Option A** — all techs treated equally at -18 (V2 upgrade: split by reason)
- Late game intentional fouls: **not penalized** (legitimate strategy)
- Flop violations: handled implicitly via FDS low legitimacy scores — no dedicated endpoint available in nba_api

### Exponential Stacking (per violation type)

```python
for each violation_type:
    count = occurrences in this game
    penalty = base_penalty * (count ^ 1.4)

SPS = max(0, 100 - sum(all penalties))   # floor at 0; only sub-score with any clamp
```

### Stacking Reference (Technical Fouls)

| Techs | Penalty |
|---|---|
| 1 | 18 pts |
| 2 | 48 pts |

---

## Sub-Score 5: Defensive Effort Score (DES) — 5%

### Goal
Did this player compete defensively, or coast and take plays off?

### Positive Signals

| Stat | Weight |
|---|---|
| Contested shots defended | × 3.5 |
| Deflections | × 4.0 |
| Steals | × 5.0 (linear, no cap) |
| Blocks | × 5.0 |
| Defensive rebounds | × 2.0 |
| Charges taken | × 15.0 (flat bonus) |

### Foul Penalty (Differentiated by Type)

```python
adjusted_fouls = (defensive_fouls * 1.0)
               + (offensive_fouls * 1.3)   # active manipulation, penalized harder
               + (loose_ball_fouls * 0.5)  # effort play, lightest penalty

foul_penalty = (adjusted_fouls ^ 1.3) * 5
```

### Foul Penalty Reference (defensive fouls only)

| Fouls | Penalty |
|---|---|
| 1 | 5 pts |
| 2 | 12 pts |
| 3 | 21 pts |
| 4 | 32 pts |
| 5 | 44 pts |
| 6 (fouled out) | 57 pts |

### DES Formula

```python
positive_total = (contested_shots * 3.5) + (deflections * 4.0)
               + (steals * 5.0) + (blocks * 5.0)
               + (defensive_rebounds * 2.0) + (charges_taken * 15.0)

DES_raw = (positive_total / 80) * 100   # unclamped; elite game ≈ 100 before penalty

foul_penalty = (adjusted_fouls ^ 1.3) * 5

DES = DES_raw - foul_penalty            # unclamped; can exceed 100 or go negative

# Zero defense edge case
if all defensive stats == 0:
    DES = 25    # coasting penalty, not misconduct
```

**Normalization baseline (80):** A player generating 8 contested shots × 3.5 + 5 deflections × 4.0 + 2 steals × 5.0 + 2 blocks × 5.0 + 6 drebs × 2.0 = 80 weighted points scores `DES_raw = 100`. After 2–3 typical defensive fouls this produces DES ≈ 80–88, the intended elite-game range. Extraordinary performances legitimately exceed 100.

---

## Garbage Time Rule

### Definition
```python
if quarter == 4 and point_differential >= 20 and time_remaining <= 5:
    garbage_time = True
```

A game is considered decided — any FTA drawn in this window are flagged as potential padding regardless of how legitimate the foul looked.

### Application in FDS
```python
if garbage_time and foul_drawn:
    legitimacy = min(legitimacy, 0.20)
```

### Application in FTP
```python
garbage_FTA_ratio = garbage_time_FTA / total_FTA

if garbage_FTA_ratio > 0.30:
    extra_penalty = (garbage_FTA_ratio * 100) ^ 1.3 * 0.20
    FTP -= extra_penalty
```

### What This Does NOT Affect
- Field goal attempts in garbage time are **not penalized** — taking shots even in a blowout is fine
- Only FTA drawn in garbage time are flagged
- Early game legitimate play is fully preserved in the score

---



## Data Sources

| Data | Source | Endpoint |
|---|---|---|
| Shot location, zone, made/missed | `nba_api` | `ShotChartDetail` (player_id=0, per team) |
| Defender proximity (FDS legitimacy) | `nba_api` | `PlayerDashPtShots` result set [4] — `CLOSE_DEF_DIST_RANGE` buckets, season-level |
| Assisted vs self-created | `nba_api` | `PlayByPlayV3` + assist cross-reference |
| FTA, FTM, FGM breakdown | `nba_api` | `BoxScoreTraditionalV3` |
| Foul type classification | `nba_api` | `PlayByPlayV3` (actionType / subType / description) |
| Technical / flagrant fouls | `nba_api` | `PlayByPlayV3` |
| Official flop violations | NBA.com | Published foul reports (V2 — not yet integrated) |
| Contested shots, deflections, charges | `nba_api` | `BoxScoreHustleV2` |
| Blocks, steals, rebounds | `nba_api` | `BoxScoreTraditionalV3` |

---

## Validation Status

Validation complete across **12 games** (218 qualifying player-game rows, min ≥ 8 min, stored in `ehi.db`). Star player results with current formula:

| Player | Game | MIN | Pts | SQS | FDS | FTP | DES | EHI |
|---|---|---|---|---|---|---|---|---|
| Jalen Brunson | MIL vs NYK 12/23/2023 | 37.3 | 36 | 62.8 | 34.1 | 94.2 | 83.3 | **67.77** |
| James Harden | HOU vs NYK 01/23/2019 | 40.0 | 61 | 73.4 | 6.8 | 74.8 | 90.4 | 62.60 |
| Giannis Antetokounmpo | MIL vs NYK 12/23/2023 | 32.4 | 28 | 64.7 | 21.4 | 83.0 | 41.7 | 61.24 |
| Victor Wembanyama | SAS vs DAL 10/22/2025 | 29.7 | 40 | 62.9 | 12.6 | 84.2 | 83.4 | 61.05 |
| Kawhi Leonard | DET vs LAC 12/28/2025 | 38.6 | 55 | 60.0 | 8.7 | 79.6 | 128.9 | 60.06 |
| Stephen Curry | GSW vs POR 01/03/2021 | 36.4 | 62 | 66.1 | 3.4 | 79.7 | 37.5 | 57.22 |
| Nikola Jokić | MIN vs DEN 04/01/2025 | 52.6 | 61 | 61.2 | 13.9 | 78.2 | 37.6 | 56.73 |
| Anthony Edwards | MIN vs DEN 04/01/2025 | 50.5 | 34 | 57.9 | 10.6 | 89.7 | 8.6 | 56.04 |
| LeBron James | LAL vs CLE 03/31/2026 | 30.6 | 14 | 51.8 | 8.5 | 59.0 | 30.8 | 46.29 |
| James Harden (LAC) | DET vs LAC 12/28/2025 | 40.0 | 28 | 54.0 | 8.2 | 70.5 | −9.0 | 45.68 |

**Star EHI range: 46.29–67.77 · std dev: 5.37 · mean: 56.18 · n=17 game-rows**
**Global range (218 rows): 26.33–75.76 · mean: 55.69 · std: 7.81**

Next step: **`run_season.py`** — full 2025-26 season run across all game IDs.

---

## Tunable Constants (centralize these in code)

```python
# Weights
W_SQS = 0.45
W_FDS = 0.20
W_FTP = 0.25
W_SPS = 0.05
W_DES = 0.05

# Activity filter
MIN_MINUTES_THRESHOLD = 8   # players below this excluded entirely

# SQS
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

# FDS
VOLUME_PENALTY_BASE = 1.0   # DEPRECATED
VOLUME_PENALTY_EXP  = 1.15  # DEPRECATED
FT_PCT_THRESHOLD    = 0.60
FT_PCT_MODIFIER     = 0.92
ZERO_FTA_BASELINE   = 50

# FTP
FTP_RATIO_WEIGHT              = 70   # (1 - dep_ratio) * 70
FTP_VOLUME_CAP                = 30   # min(total_pts, 30)
FT_DEP_THRESHOLD              = 0.50   # DEPRECATED
FT_DEP_PENALTY_MULT           = 0.15   # DEPRECATED
FT_DEP_PENALTY_EXP            = 1.3    # DEPRECATED
ZERO_POINTS_BASELINE          = 50     # DEPRECATED
FTP_SCORING_BONUS_PTS_THRESHOLD = 30   # DEPRECATED
FTP_SCORING_BONUS_DEP_CAP       = 0.35 # DEPRECATED
FTP_SCORING_BONUS_MULT          = 0.3  # DEPRECATED

# SPS
TECH_PENALTY        = 18
FLAGRANT1_PENALTY   = 25
FLAGRANT2_PENALTY   = 40
ILLEGAL_SCREEN_PEN  = 10
DELAY_PENALTY       = 8
SPS_STACK_EXP       = 1.4

# DES
CONTESTED_WEIGHT    = 3.5
DEFLECTION_WEIGHT   = 4.0
STEAL_WEIGHT        = 5.0
BLOCK_WEIGHT        = 5.0
DREB_WEIGHT         = 2.0
CHARGE_WEIGHT       = 15.0
DES_NORMALIZATION   = 80    # elite 36-min game ≈ 80 weighted pts → DES_raw=100
FOUL_PENALTY_BASE   = 5
FOUL_PENALTY_EXP    = 1.3
DEF_FOUL_MULT       = 1.0
OFF_FOUL_MULT       = 1.3
LOOSE_BALL_MULT     = 0.5
ZERO_DEF_BASELINE   = 25

# Garbage Time
GARBAGE_TIME_LEAD         = 20
GARBAGE_TIME_MINUTES_LEFT = 5
GARBAGE_TIME_LEG_CAP      = 0.20
GARBAGE_FTA_THRESHOLD     = 0.30
GARBAGE_FTP_PENALTY_MULT  = 0.20
GARBAGE_FTP_PENALTY_EXP   = 1.3
```

---

*EHI v1.1 — unclamped sub-scores, ratio+volume FTP, SQS volume-quality bonus, 12-game validation complete*
