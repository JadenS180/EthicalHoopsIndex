# 🏀 Ethical Hoops Index (EHI)

A per-game NBA player ethics metric that quantifies "ethical basketball" using real tracking data. EHI scores every player on a per-game basis based on how they earned their production — rewarding skill-based scoring and disciplined defense while penalizing manipulation, deception, and laziness.

> *"Ethical hoops" has been a growing conversation in the NBA for years. EHI is the first attempt to actually put a number on it.*

---

## What is EHI?

The **Ethical Hoops Index** is a composite metric made up of 6 sub-scores:

| Sub-Score | Weight | What it measures |
|---|---|---|
| **SQS** — Shot Quality Score | 35% | Did you take good shots or force bad ones? |
| **FDS** — Foul Drawing Score | 20% | Did you earn your free throws or manufacture them? |
| **FTP** — FT Dependency Score | 20% | FT dependency ratio, scoring volume, and playmaking contribution |
| **SPS** — Sportsmanship Score | 5% | Techs, flagrants, illegal screens, dirty play |
| **DES** — Defensive Effort Score | 5% | Contested shots, deflections, charges, active hands |
| **SSS** — Scoring Skill Score | 15% | Self-created offense and assists — did you generate your own looks? |

```
EHI = 0.35(SQS) + 0.20(FDS) + 0.20(FTP) + 0.05(SPS) + 0.05(DES) + 0.15(SSS)
```

All scores are **absolute** and computed on a **per-game basis**.

---

## Motivation

The NBA has seen growing debate around "dark arts" basketball — foul hunting on 3-point attempts, off-ball contact manipulation, and late-game free throw padding. Traditional box score stats don't distinguish between a player who scored 30 points through elite shot-making and one who scored 30 through manufactured free throws.

EHI fills that gap.

---

## Key Design Decisions

- **Shot quality over efficiency** — bad shots that go in aren't penalized. Open misses aren't penalized. Only bad shots that miss are.
- **Foul legitimacy scoring** — each foul drawn gets a 0–1 legitimacy score based on defender distance, catch-and-shoot context, and repetition patterns within the game.
- **Garbage time detection** — FTA drawn in Q4 with a 25+ point lead and ≤5 minutes remaining are capped at 0.20 legitimacy regardless of context.
- **Exponential stacking** — repeated unethical acts in a single game compound (x^1.4), reflecting how fans and analysts perceive escalating bad behavior.
- **Volume awareness** — even legitimate free throw volume is penalized because ethical basketball means scoring through skill, not contact.

---

## Formula Details

### Sub-Score Formulas

**FTP — FT Dependency Score**
```
ratio_score  = (1 − ft_dependency_ratio) × 70
volume_score = min(total_pts, 30)
assist_bonus = min(assists × 2.0, 20)
FTP          = ratio_score + volume_score + assist_bonus   # can exceed 100 for elite playmakers
```

**SSS — Scoring Skill Score**
```
skill_score = (self_created_pts × 1.5) + (assists × 3.0) + Σ(xeFG% × 10 for qualifying self-created makes)
SSS         = min((skill_score / 30) × 100, 100)   # zero shots/assists baseline = 20
```

**SPS — Sportsmanship Score**
```
SPS = max(0, 100 − Σ base_penalty × (count ^ 1.4))
```
Violations: Technical −18 · Flagrant 1 −25 · Flagrant 2 −40 · Illegal Screen −10 · Delay of Game −8

**DES — Defensive Effort Score**
```
raw = contested×3.5 + deflections×4.0 + steals×5.0 + blocks×5.0 + drebs×2.0 + charges×15.0
DES = (raw / position_norm) × 100 − foul_penalty
```

**FDS — Foul Drawing Score**
```
FDS = avg_legitimacy × 100   (× 0.92 if FT% < 0.60 and FTA ≥ 4)
```
Zero-FTA baseline = 50.

**SQS — Shot Quality Score**
```
per-shot: made → xeFG×100; open miss (xeFG ≥ 0.38) → ×0.85; chuck miss → ×0.50 − (chucks^1.4)×3
SQS = mean(per-shot scores) + volume_bonus
```

### Position Adjustments

| Score | Guard | Forward | Center |
|---|---|---|---|
| DES normalization | ÷ 60 | ÷ 85 | ÷ 110 |
| SQS volume-quality threshold | xeFG ≥ 0.50 | xeFG ≥ 0.53 | xeFG ≥ 0.58 |
| FDS paint foul modifier | — | — | +0.10 |
| FDS 3pt foul modifier | −0.10 | — | — |

### Empirical xeFG% Table

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

*Empirical values reflect the full 2025-26 season run (1,223 games). Corner 3 figures remain below hardcoded league averages — likely genuine sample composition rather than noise.*

---

## Real World Stress Test: Bam Adebayo's 83-Point Game

On March 10, 2026, Bam Adebayo scored 83 points (2nd highest in NBA history) against the Washington Wizards — going 20-43 FG, 7-22 from 3, and an NBA-record 36-43 from the free throw line.

EHI breaks this game down honestly:
- Early scoring (31 pts in Q1) was legitimate and reflected in SQS
- 43 FTA triggers a massive FDS volume penalty
- FTP dependency ratio of ~43% tanks the FT Dependency score
- Garbage time free throw padding (14-16 FT in Q4 with 25+ lead) gets capped at 0.20 legitimacy

**This is exactly the kind of game EHI was designed to evaluate.**

---

## Tech Stack

| Layer | Tool |
|---|---|
| Data collection | Python + `nba_api` |
| Data processing | `pandas` |
| Storage | SQLite (`ehi.db`) |
| Version control | Git / GitHub |

---

## Project Structure

```
EthicalHoopsIndex/
├── config.py            # All tunable constants and NBA API headers
├── pipeline.py          # Data pipeline — pulls 7 endpoints from nba_api
├── compute_ehi.py       # EHI calculator — all 6 sub-scores + aggregation
├── run_validation.py    # Runs pipeline across 12 hardcoded validation games
├── run_season.py        # Full 2025-26 season run (~1,230 games, resume-safe)
├── query_ehi.py         # DB query utilities (CLI + programmatic)
├── ehi.db               # SQLite database — games, players, shots tables
├── season_errors.log    # Per-game error log from run_season.py
├── EHI_Master_Reference.md
├── CLAUDE.md
├── .gitignore
└── LICENSE
```

---

## Data Pipeline

`pipeline.py` pulls 7 endpoints from `stats.nba.com` for any given game:

1. **LeagueGameFinder** — finds game ID by team and date
2. **BoxScoreSummaryV3** — game metadata (score, officials, line score)
3. **BoxScoreTraditionalV3** — per-player box score (PTS, FGM/A, FTA, REB, STL, BLK, PF, position)
4. **PlayByPlayV3** — full play log for foul classification and sportsmanship events
5. **ShotChartDetail** × 2 — one call per team; shot zone, made/missed, LOC_X/Y
6. **BoxScoreHustleV2** — contested shots, deflections, charges drawn
7. **PlayerDashPtShots** × 2 — one call per team; season-level defender proximity bucket distributions

---

## Sub-Score Status

- [x] SQS — Shot Quality Score (empirical xeFG table; position-adjusted volume bonus)
- [x] FDS — Foul Drawing Score (proximity, assisted/and-1 flags, position modifiers, rep penalties)
- [x] FTP — FT Dependency Score (ratio + volume + assists bonus; can exceed 100)
- [x] SPS — Sportsmanship Score (exponential stacking, validated)
- [x] DES — Defensive Effort Score (position-adjusted normalization)
- [x] SSS — Scoring Skill Score (self-created pts, assists, xeFG quality bonus; clamped at 100)
- [x] Full EHI aggregation (6 sub-scores; updated weights)
- [x] Validation across 12 games (pre-SSS formula)
- [x] `run_season.py` — 2025-26 season complete (1,223 games, 23,313 player-game rows); **re-run tonight with new formula**
- [x] `query_ehi.py` — 7 query functions with CLI support; role-based leaderboards added

---

## Usage

### Running the pipeline

```bash
# Validate against 12 hardcoded games
python3 run_validation.py

# Run a subset of validation games
python3 run_validation.py 11 12

# Full 2025-26 season run (~9-10 hours, resume-safe)
python3 run_season.py

# Process games 1-100 only (chunked run)
python3 run_season.py 1 100
```

### Querying results

```bash
# Season averages for a player
python3 query_ehi.py player 'Luka Doncic' 2025-26

# Full breakdown for a single game
python3 query_ehi.py player-game 'Luka Doncic' 2026-01-26

# Full game leaderboard
python3 query_ehi.py game 2026-01-26 DAL ATL

# Top/bottom N players by season avg EHI (min 20 GP)
python3 query_ehi.py season-best 2025-26 20
python3 query_ehi.py season-worst 2025-26

# Top N by role: Stars (15+ PPG), Role Players (8–15 PPG), Bench (<8 PPG)
python3 query_ehi.py season-roles 2025-26 10

# League-wide season summary (5 sections)
python3 query_ehi.py summary 2025-26
```

---

## Validation Results

Validated across **12 games** (2,216 shots, 17 star player-game rows):

| Metric | Value |
|---|---|
| EHI range | 47.62 – 69.45 |
| EHI mean | 57.24 |
| EHI std dev | 4.95 |

Confirmed behaviors: Bam Adebayo's 83-point game scores appropriately low on FDS/FTP; Coulibaly 1 tech → SPS 82.0; high-volume elite scorers receive SQS volume-quality bonuses.

---

## 🏆 2025-26 Season Findings

> ⚠️ **Results below are based on the pre-SSS formula (5 sub-scores, old weights). A full season re-run with the updated 6-sub-score formula is scheduled tonight. Figures will be updated after completion.**

The full 2025-26 regular season run is complete. **1,223 games** processed (1,197 direct + 26 retried), **23,313 player-game rows** saved to `ehi.db`.

### 📊 League-Wide Stats

| Metric | Value |
|:---|:---|
| 🎮 Games processed | 1,223 |
| 👤 Player-game rows | 23,313 |
| 📈 League avg EHI | **48.27** |
| ⬆️ Season high (single game) | **75.76** — Rudy Gobert |
| ⬇️ Season low (single game) | **8.91** — Collin Gillespie |

---

### 🥇 Most Ethical Players

> Min. 20 games played · Season avg EHI

| Rank | Player | Avg EHI | GP | Highlight |
|:---:|:---|:---:|:---:|:---|
| 1 | Mitchell Robinson | **60.43** | — | Elite rim protection, near-zero FT dependency |
| 2 | Robert Williams III | **60.06** | — | High DES, clean offense |
| 3 | Jericho Sims | **59.23** | — | — |
| — | Giannis Antetokounmpo | **58.04** | 35 | ⭐ Top star result — high-usage, high-EHI |
| — | Dyson Daniels | **57.77** | 76 | ⭐ Most ethical high-volume guard/wing |

> ⚠️ **Positional bias note:** Centers dominate the top rankings — see Known Limitations below. A fix is planned.

> Full list: `python3 query_ehi.py season-best 2025-26`

---

### 🚨 Least Ethical Players

> Min. 20 games played · Season avg EHI

| Rank | Player | Avg EHI | Highlight |
|:---:|:---|:---:|:---|
| 1 (worst) | Jordan Poole | **39.47** | Lowest season avg in the league |
| 2 | Grayson Allen | **40.19** | — |

> Full list: `python3 query_ehi.py season-worst 2025-26`

---

### 🏟️ Team Rankings

| Rank | Team | Avg EHI |
|:---:|:---|:---:|
| 🥇 1 | New Orleans Pelicans | **49.84** |

> Full 30-team ranking: `python3 query_ehi.py summary 2025-26`

---

### ⚠️ Known Issue: Positional Bias in Top Rankings

Low-scoring centers (Robinson, Williams III, Sims) dominate the top-10 for two compounding reasons:

1. **DES normalization** — Centers divide against a baseline of 110, but elite rim protectors generate enormous raw DES without meaningful offensive contribution. Their DES scores are legitimately high, but they represent a narrow slice of basketball value.
2. **FTP neutral baseline** — Zero-scorers default to FTP = 70.0 (neutral). Low-usage bigs who score rarely aren't penalized, giving them an edge over offensive players who draw any FT dependency at all.

**Partial fix applied:** Role-based leaderboards (`python3 query_ehi.py season-roles 2025-26`) split players into Stars (15+ PPG), Role Players (8–15 PPG), and Bench (<8 PPG) tiers, so low-usage bigs and high-usage stars are compared within their role. An absolute formula fix (offensive usage floor or FGA-based reweighting) remains planned.

---

## Known Limitations

- **Positional bias in top rankings** *(partially addressed)* — Low-scoring centers accumulate high DES + neutral FTP without meaningful offensive contribution, inflating their EHI. Role-based leaderboards (`season-roles`) mitigate this in per-tier comparisons. An absolute formula fix remains planned.
- **xeFG corner 3 values** — Season-run empirical values (Left: 0.275, Right: 0.398) remain below hardcoded league averages. Likely reflects sample composition; monitors against league-published xeFG data.
- **Position label vs. role** — position is read from the NBA's roster designation in `BoxScoreTraditionalV3`, not derived from on-court role. A stretch big listed as C normalizes against the center baseline regardless of how he actually plays.
- **No per-shot defender distance** — `ShotChartDetail` does not return per-shot defender proximity. FDS and SQS use season-level `PlayerDashPtShots` bucket distributions as a proxy, applied uniformly across all shots in a game.
- **No opponent adjustment** — EHI scores are absolute. A guard defending a weak team's shooters receives the same DES credit as one guarding elite shooters.
- **No clutch bonus** — EHI does not reward or penalize performance in close late-game situations. Clutch scoring and defensive stops are treated identically to any other possession.

---

## Background

Built as a resume project by Jaden Smiles, a 2nd year Computer Engineering student at UGA, combining data engineering, sports analytics, and novel metric design. The project demonstrates a full data pipeline from API ingestion to composite metric calculation using real NBA tracking data.

---

## Disclaimer

This project is not affiliated with or endorsed by the NBA. Data is pulled from publicly available endpoints on `stats.nba.com` for educational and research purposes.
