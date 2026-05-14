# Ethical Hoops Index (EHI) — Master Reference Document

## Overview

The **Ethical Hoops Index (EHI)** is a composite, absolute (0–100) per-game metric that measures how "ethically" an NBA player performed. It rewards skill-based scoring, disciplined defense, and clean conduct, while penalizing manipulation, deception, and laziness.

---

## Master Formula

```
EHI = 0.35(SQS) + 0.20(FDS) + 0.20(FTP) + 0.15(SPS) + 0.10(DES)
```

| Sub-Score | Name | Weight |
|---|---|---|
| SQS | Shot Quality Score | 35% |
| FDS | Foul Drawing Score | 20% |
| FTP | FT Dependency Score | 20% |
| SPS | Sportsmanship Score | 15% |
| DES | Defensive Effort Score | 10% |

All sub-scores are on an absolute 0–100 scale. EHI is also 0–100.

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

### Final SQS
```python
SQS = clamp(mean(all shot_scores), 0, 100)
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

# Positive signals
if defender_distance <= 2ft:   legitimacy += 0.40
if defender_distance <= 4ft:   legitimacy += 0.25
if assisted (catch-and-shoot): legitimacy += 0.20
if and_1 (made + fouled):      legitimacy += 0.20

# Negative signals
if defender_distance > 4ft:              legitimacy -= 0.35
if 3rd+ foul of same type this game:     legitimacy -= 0.20
if 4th+ foul of same type this game:     legitimacy -= 0.30

# Hard cap for off-ball fouls
if off_ball_foul:
    legitimacy = min(legitimacy, 0.45)

# Global clamp
legitimacy = clamp(legitimacy, 0.0, 1.0)
```

### FDS Formula

```python
avg_legitimacy = mean(all foul legitimacy scores)
FTA_in_game = total free throw attempts

# Volume penalty (even legitimate FT volume is mildly penalized)
volume_penalty = (FTA_in_game ^ 1.3) * 2.5

FDS_raw = avg_legitimacy * 100
FDS = clamp(FDS_raw - volume_penalty, 0, 100)

# FT% modifier
if FTM / FTA < 0.60 and FTA >= 4:
    FDS *= 0.92

# Zero foul baseline
if FTA_in_game == 0:
    FDS = 72
```

### Volume Penalty Reference

| FTA | Penalty |
|---|---|
| 0 | 0 (baseline 72) |
| 2 | ~7 pts |
| 4 | ~17 pts |
| 6 | ~28 pts |
| 8 | ~40 pts |
| 12 | ~63 pts |

---

## Sub-Score 3: FT Dependency Score (FTP) — 20%

### Goal
What percentage of this player's points came from free throws vs. actual field goals?

### Formula

```python
FT_points  = FTM * 1
FG_points  = (FGM_2pt * 2) + (FGM_3pt * 3)
total_points = FT_points + FG_points

FT_dependency_ratio = FT_points / total_points

FTP_raw = (1 - FT_dependency_ratio) * 100

# Exponential kick above 50% dependency
if FT_dependency_ratio > 0.50:
    excess = FT_dependency_ratio - 0.50
    extra_penalty = (excess * 100) ^ 1.3 * 0.15
    FTP = clamp(FTP_raw - extra_penalty, 0, 100)
else:
    FTP = FTP_raw

# Edge cases
if total_points == 0:
    FTP = 75    # didn't score, but didn't abuse FTs either

if FGM == 0 and FTM > 0:
    FTP = 0     # pure FT scorer, harshest penalty
```

### Reference Table

| Points | FTM | FT Dependency | FTP_raw |
|---|---|---|---|
| 20 (0 FTM) | 0 | 0% | 100 |
| 20 (4 FTM) | 4 | 20% | 80 |
| 20 (8 FTM) | 8 | 40% | 60 |
| 20 (14 FTM) | 14 | 70% | 30 |
| 20 (20 FTM) | 20 | 100% | 0 |

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

SPS = 100 - sum(all penalties)
SPS = clamp(SPS, 0, 100)
```

### Stacking Reference (Technical Fouls)

| Techs | Penalty |
|---|---|
| 1 | 18 pts |
| 2 | 48 pts |

---

## Sub-Score 5: Defensive Effort Score (DES) — 10%

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

DES_raw = clamp((positive_total / 30) * 100, 0, 100)

foul_penalty = (adjusted_fouls ^ 1.3) * 5

DES = clamp(DES_raw - foul_penalty, 0, 100)

# Zero defense edge case
if all defensive stats == 0:
    DES = 25    # coasting penalty, not misconduct
```

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
| Shot location, distance, defender distance | `nba_api` | `shotchartdetail`, `defenderdashptsshots` |
| Assisted vs self-created | `nba_api` | Play-by-play + assist tracking |
| FTA, FTM, FGM breakdown | `nba_api` | Box score |
| Foul type classification | `nba_api` | Play-by-play (text descriptions) |
| Technical / flagrant fouls | `nba_api` | Play-by-play |
| Official flop violations | NBA.com | Published foul reports (V2) |
| Contested shots, deflections, charges | `nba_api` | `hustlestats` endpoint |
| Blocks, steals, rebounds | `nba_api` | Box score |

---

## Validation Strategy

Before finalizing weights, validate against **10–15 games** with strong public consensus on player ethics:

1. Select games where a player was widely labeled "dirty" or "ethical"
2. Run EHI and check if scores agree with consensus
3. Adjust weights and penalty constants until alignment is strong
4. Run **sensitivity analysis** — vary weights ±5% and confirm rankings are stable

---

## Tunable Constants (centralize these in code)

```python
# Weights
W_SQS = 0.35
W_FDS = 0.20
W_FTP = 0.20
W_SPS = 0.15
W_DES = 0.10

# SQS
CHUCK_THRESHOLD   = 0.38
CONTESTED_MULT    = 1.40
SELF_CREATED_MULT = 1.25
ASSISTED_DEMERIT  = 0.90
OPEN_MISS_MULT    = 0.85
CONTESTED_MISS_MULT = 0.50

# FDS
VOLUME_PENALTY_BASE = 2.5
VOLUME_PENALTY_EXP  = 1.3
FT_PCT_THRESHOLD    = 0.60
FT_PCT_MODIFIER     = 0.92
ZERO_FTA_BASELINE   = 72

# FTP
FT_DEP_THRESHOLD    = 0.50
FT_DEP_PENALTY_MULT = 0.15
FT_DEP_PENALTY_EXP  = 1.3
ZERO_POINTS_BASELINE = 75

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
DES_NORMALIZATION   = 30
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

*EHI v1.0 — designed for per-game, absolute scoring across all NBA players*
