# ─── NBA API HEADERS ────────────────────────────────────────────────────────
# Required to avoid being blocked by NBA.com's rate limiter.
# Keep Chrome version in sync with nba_api's default STATS_HEADERS —
# the NBA stats API rejects outdated User-Agents with a silent timeout.
HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest": "empty",
}

# ─── EHI WEIGHTS ────────────────────────────────────────────────────────────
W_SQS = 0.45
W_FDS = 0.20
W_FTP = 0.25
W_SPS = 0.05
W_DES = 0.05

# ─── ACTIVITY FILTER ────────────────────────────────────────────────────────
MIN_MINUTES_THRESHOLD = 8   # players below this are excluded from EHI entirely

# ─── SQS CONSTANTS ──────────────────────────────────────────────────────────
CHUCK_THRESHOLD     = 0.38
CONTESTED_MULT      = 1.40
SELF_CREATED_MULT   = 1.25
ASSISTED_DEMERIT    = 0.90
OPEN_MISS_MULT      = 0.85
CONTESTED_MISS_MULT = 0.50

# xeFG% by shot zone (hardcoded league averages)
XEFG_AT_RIM         = 0.72
XEFG_PAINT_NON_RIM  = 0.54
XEFG_MID_RANGE      = 0.44
XEFG_CORNER_3       = 0.58
XEFG_ABOVE_BREAK_3  = 0.52
XEFG_BACKCOURT      = 0.30

# Chuck scoring
CHUCK_PENALTY_EXP        = 1.4
CHUCK_PENALTY_MULT       = 3

# Edge cases / thresholds
SQS_ZERO_SHOTS_BASELINE  = 50
SQS_SC_XEFG_THRESHOLD    = 0.50   # min xeFG% for self-created bonus
SQS_AST_XEFG_THRESHOLD   = 0.45   # max xeFG% for assisted demerit

# Per-position volume-quality xeFG% thresholds for SQS bonus
SQS_XEFG_THRESHOLD_CENTER  = 0.58
SQS_XEFG_THRESHOLD_FORWARD = 0.53
SQS_XEFG_THRESHOLD_GUARD   = 0.50

# ─── FDS CONSTANTS ──────────────────────────────────────────────────────────
VOLUME_PENALTY_BASE = 1.0    # DEPRECATED — not applied in compute_fds
VOLUME_PENALTY_EXP  = 1.15  # DEPRECATED — not applied in compute_fds
FT_PCT_THRESHOLD    = 0.60
FT_PCT_MODIFIER     = 0.92
ZERO_FTA_BASELINE   = 50
FDS_REP_PENALTY_3RD    = 0.10   # 3rd foul of same type (softened from 0.20)
FDS_REP_PENALTY_4TH    = 0.20   # 4th+ foul of same type (softened from 0.30)
FDS_CENTER_PAINT_BONUS = 0.10   # legitimacy bonus for centers drawing paint fouls
FDS_GUARD_3PT_PENALTY  = 0.10   # legitimacy deduction for guards drawing 3pt fouls

# ─── FTP CONSTANTS ──────────────────────────────────────────────────────────
# Ratio component: (1 - FT_dep_ratio) × FTP_RATIO_WEIGHT  → max 70
FTP_RATIO_WEIGHT = 70
# Volume component: min(total_pts × 1.0, FTP_VOLUME_CAP)  → max 30
FTP_VOLUME_CAP   = 30
# Combined FTP = ratio_score + volume_score  → naturally in [0, 100]
# Zero scorers: ratio=70, volume=0 → FTP=70 (neutral, no special case needed)
FT_DEP_THRESHOLD              = 0.50   # DEPRECATED
FT_DEP_PENALTY_MULT           = 0.15   # DEPRECATED
FT_DEP_PENALTY_EXP            = 1.3    # DEPRECATED
ZERO_POINTS_BASELINE          = 50     # DEPRECATED — formula handles zero scorers naturally
FTP_SCORING_BONUS_PTS_THRESHOLD = 30   # DEPRECATED — volume now baked into base formula
FTP_SCORING_BONUS_DEP_CAP       = 0.35 # DEPRECATED
FTP_SCORING_BONUS_MULT          = 0.3  # DEPRECATED

# ─── SPS CONSTANTS ──────────────────────────────────────────────────────────
TECH_PENALTY       = 18
FLAGRANT1_PENALTY  = 25
FLAGRANT2_PENALTY  = 40
ILLEGAL_SCREEN_PEN = 10
DELAY_PENALTY      = 8
SPS_STACK_EXP      = 1.4

# ─── DES CONSTANTS ──────────────────────────────────────────────────────────
CONTESTED_WEIGHT  = 3.5
DEFLECTION_WEIGHT = 4.0
STEAL_WEIGHT      = 5.0
BLOCK_WEIGHT      = 5.0
DREB_WEIGHT       = 2.0
CHARGE_WEIGHT     = 15.0
DES_NORMALIZATION = 80        # DEPRECATED — per-position norms now used
DES_NORM_CENTER   = 110
DES_NORM_FORWARD  = 85
DES_NORM_GUARD    = 60
FOUL_PENALTY_BASE = 5
FOUL_PENALTY_EXP  = 1.3
DEF_FOUL_MULT     = 1.0
OFF_FOUL_MULT     = 1.3
LOOSE_BALL_MULT   = 0.5
ZERO_DEF_BASELINE = 25

# ─── GARBAGE TIME CONSTANTS ─────────────────────────────────────────────────
GARBAGE_TIME_LEAD         = 25
GARBAGE_TIME_MINUTES_LEFT = 5
GARBAGE_TIME_LEG_CAP      = 0.20
GARBAGE_FTA_THRESHOLD     = 0.30
GARBAGE_FTP_PENALTY_MULT  = 0.20
GARBAGE_FTP_PENALTY_EXP   = 1.3