"""
compute_ehi.py — EHI Sub-Score Calculator
Computes the Ethical Hoops Index for every active player in a game.

Implemented  : FTP — FT Dependency Score
               SPS — Sportsmanship Score
               DES — Defensive Effort Score
               FDS — Foul Drawing Score
Stubs (TODO) : SQS
"""

import re

import pandas as pd

from config import (
    # Weights (used in final EHI roll-up once all sub-scores exist)
    W_SQS, W_FDS, W_FTP, W_SPS, W_DES,
    # FTP constants
    FT_DEP_THRESHOLD,
    FT_DEP_PENALTY_MULT,
    FT_DEP_PENALTY_EXP,
    ZERO_POINTS_BASELINE,
    # SPS constants
    TECH_PENALTY,
    FLAGRANT1_PENALTY,
    FLAGRANT2_PENALTY,
    ILLEGAL_SCREEN_PEN,
    DELAY_PENALTY,
    SPS_STACK_EXP,
    # DES constants
    CONTESTED_WEIGHT,
    DEFLECTION_WEIGHT,
    STEAL_WEIGHT,
    BLOCK_WEIGHT,
    DREB_WEIGHT,
    CHARGE_WEIGHT,
    DES_NORMALIZATION,
    FOUL_PENALTY_BASE,
    FOUL_PENALTY_EXP,
    DEF_FOUL_MULT,
    OFF_FOUL_MULT,
    LOOSE_BALL_MULT,
    ZERO_DEF_BASELINE,
    # FDS constants
    VOLUME_PENALTY_BASE,
    VOLUME_PENALTY_EXP,
    FT_PCT_THRESHOLD,
    FT_PCT_MODIFIER,
    ZERO_FTA_BASELINE,
    # Garbage-time constants (shared FDS + FTP)
    GARBAGE_TIME_LEAD,
    GARBAGE_TIME_MINUTES_LEFT,
    GARBAGE_TIME_LEG_CAP,
)


# ─── UTILITIES ────────────────────────────────────────────────────────────────

def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def parse_minutes(val) -> float:
    """'MM:SS' or 'PT12M34.56S' → decimal minutes. Handles both V2 and V3 formats."""
    if not val:
        return 0.0
    s = str(val)
    try:
        if ":" in s:                            # V3 format: "34:26"
            m, sec = s.split(":")
            return float(m) + float(sec) / 60.0
        if "PT" in s:                           # ISO 8601: "PT34M26.00S"
            s = s.replace("PT", "").replace("S", "")
            m, sec = s.split("M")
            return float(m) + float(sec) / 60.0
        return float(s)                         # already numeric
    except (ValueError, AttributeError):
        return 0.0


# ─── SUB-SCORE: FTP ───────────────────────────────────────────────────────────

def compute_ftp(row: pd.Series) -> dict:
    """
    FT Dependency Score for one player (EHI ref §3).

    Returns a dict with all intermediate values so the caller can
    print a full validation table without re-computing anything.
    """
    ftm     = int(row["freeThrowsMade"])
    fgm_2   = int(row["twoPointersMade"])
    fgm_3   = int(row["threePointersMade"])
    fgm_tot = int(row["fieldGoalsMade"])   # used only for the pure-FT edge case

    ft_pts    = ftm                         # each FT = 1 point
    fg_pts    = fgm_2 * 2 + fgm_3 * 3
    total_pts = ft_pts + fg_pts

    # ── Edge case A: player scored zero points ────────────────────────────────
    if total_pts == 0:
        return dict(
            ft_pts=0, fg_pts=0, total_pts=0,
            ft_dep_ratio=0.0,
            ftp_raw=float(ZERO_POINTS_BASELINE),
            extra_penalty=0.0,
            FTP=float(ZERO_POINTS_BASELINE),
            note="zero pts → baseline",
        )

    # ── Edge case B: scored only via FTs, never made a field goal ─────────────
    if fgm_tot == 0 and ftm > 0:
        return dict(
            ft_pts=ft_pts, fg_pts=0, total_pts=total_pts,
            ft_dep_ratio=1.0,
            ftp_raw=0.0,
            extra_penalty=0.0,
            FTP=0.0,
            note="pure FT scorer → 0",
        )

    # ── Normal path ───────────────────────────────────────────────────────────
    ft_dep_ratio = ft_pts / total_pts
    ftp_raw      = (1.0 - ft_dep_ratio) * 100.0

    extra_penalty = 0.0
    note          = ""
    if ft_dep_ratio > FT_DEP_THRESHOLD:
        excess        = ft_dep_ratio - FT_DEP_THRESHOLD
        extra_penalty = (excess * 100) ** FT_DEP_PENALTY_EXP * FT_DEP_PENALTY_MULT
        note          = f"dep {ft_dep_ratio*100:.1f}% > {FT_DEP_THRESHOLD*100:.0f}% → −{extra_penalty:.2f}"

    ftp = clamp(ftp_raw - extra_penalty)

    return dict(
        ft_pts=ft_pts,
        fg_pts=fg_pts,
        total_pts=total_pts,
        ft_dep_ratio=round(ft_dep_ratio, 4),
        ftp_raw=round(ftp_raw, 2),
        extra_penalty=round(extra_penalty, 2),
        FTP=round(ftp, 2),
        note=note,
    )


# ─── SUB-SCORE: SPS ───────────────────────────────────────────────────────────

# Maps each violation type to (base_penalty, matcher).
# matcher(actionType, subType, description) → bool
# All string comparisons are case-insensitive via .lower() on both sides.
_SPS_VIOLATIONS: list[tuple[str, float, object]] = [
    (
        "flagrant2",
        FLAGRANT2_PENALTY,
        lambda at, st, desc: (
            at == "foul" and st in ("flagrant type 2", "flagrant 2", "flagrant foul type 2")
        ),
    ),
    (
        "flagrant1",
        FLAGRANT1_PENALTY,
        lambda at, st, desc: (
            at == "foul" and st in ("flagrant type 1", "flagrant 1", "flagrant foul type 1")
        ),
    ),
    (
        "technical",
        TECH_PENALTY,
        lambda at, st, desc: at == "foul" and st == "technical",
    ),
    (
        "illegal_screen",
        ILLEGAL_SCREEN_PEN,
        # Primary: dedicated subType. Fallback: description text (e.g. "Illegal Screen Foul").
        lambda at, st, desc: (
            at == "foul"
            and ("illegal screen" in st or "illegal screen" in desc)
        ),
    ),
    (
        "delay_of_game",
        DELAY_PENALTY,
        # Delay can appear as a Violation or as a Foul depending on the season/crew.
        lambda at, st, desc: (
            "delay" in st or "delay of game" in desc
        ),
    ),
]


def build_violation_index(pbp: pd.DataFrame) -> dict[int, dict[str, int]]:
    """
    Pre-scan the entire play-by-play once and return a per-player violation
    count dict:  {personId: {"technical": n, "flagrant1": n, ...}}

    Only rows with a valid integer personId are considered (skips team-level
    events like shot-clock violations which have no player attribution).
    """
    index: dict[int, dict[str, int]] = {}

    for _, row in pbp.iterrows():
        # Skip rows with no player attribution
        pid_raw = row.get("personId")
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue

        at   = str(row.get("actionType", "")).lower().strip()
        st   = str(row.get("subType",    "")).lower().strip()
        desc = str(row.get("description","")).lower().strip()

        for vtype, _penalty, matcher in _SPS_VIOLATIONS:
            if matcher(at, st, desc):
                counts = index.setdefault(pid, {})
                counts[vtype] = counts.get(vtype, 0) + 1

    return index


def compute_sps(row: pd.Series, violation_index: dict) -> dict:
    """
    Sportsmanship Score for one player (EHI ref §4).

    violation_index : output of build_violation_index(pbp)

    Starts at 100; applies exponential stacking per violation type:
        penalty_type = base * (count ^ SPS_STACK_EXP)
    SPS = clamp(100 - sum(all penalties), 0, 100)
    No violations → SPS = 100.

    Returns dict with per-type counts, per-type penalties, total penalty, SPS.
    """
    pid    = int(row["personId"])
    counts = violation_index.get(pid, {})

    per_type: dict[str, dict] = {}
    total_penalty = 0.0

    for vtype, base_penalty, _matcher in _SPS_VIOLATIONS:
        n = counts.get(vtype, 0)
        if n > 0:
            penalty = base_penalty * (n ** SPS_STACK_EXP)
        else:
            penalty = 0.0
        per_type[vtype] = {"count": n, "penalty": round(penalty, 2)}
        total_penalty   += penalty

    sps = clamp(100.0 - total_penalty)

    return dict(
        counts=per_type,           # {vtype: {"count": n, "penalty": p}}
        total_penalty=round(total_penalty, 2),
        SPS=round(sps, 2),
    )


# ─── SUB-SCORE: DES ───────────────────────────────────────────────────────────

# Foul subTypes that are handled in SPS and must be excluded from DES counts.
_SPS_FOUL_SUBTYPES: frozenset[str] = frozenset({
    "technical",
    "flagrant type 1", "flagrant type 2",
    "flagrant 1", "flagrant 2",
    "flagrant foul type 1", "flagrant foul type 2",
})

# Explicit DES foul-type sets.
_DEF_FOUL_SUBTYPES: frozenset[str] = frozenset({
    "personal", "shooting", "personal take",
})
_OFF_FOUL_SUBTYPES: frozenset[str] = frozenset({
    "offensive", "offensive charge",
})
_LOOSE_BALL_SUBTYPES: frozenset[str] = frozenset({
    "loose ball",
})


def build_foul_type_index(pbp: pd.DataFrame) -> dict[int, dict[str, int]]:
    """
    Scan PBP once and return per-player foul-type counts used by DES:
        {personId: {"defensive": n, "offensive": n, "loose_ball": n}}

    Technical and flagrant fouls are excluded (those are penalised in SPS).
    Any foul subType not explicitly mapped to offensive or loose-ball is
    treated as defensive — the safest default for unknown future subTypes.
    """
    index: dict[int, dict[str, int]] = {}

    for _, play in pbp.iterrows():
        if str(play.get("actionType", "")).lower().strip() != "foul":
            continue

        pid_raw = play.get("personId")
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue

        st = str(play.get("subType", "")).lower().strip()

        if st in _SPS_FOUL_SUBTYPES:
            continue                          # SPS handles these

        counts = index.setdefault(pid, {"defensive": 0, "offensive": 0, "loose_ball": 0})

        if st in _OFF_FOUL_SUBTYPES:
            counts["offensive"] += 1
        elif st in _LOOSE_BALL_SUBTYPES:
            counts["loose_ball"] += 1
        else:
            counts["defensive"] += 1          # includes personal, shooting, personal take, unknowns

    return index


def compute_des(row: pd.Series, hustle: pd.DataFrame, foul_type_index: dict) -> dict:
    """
    Defensive Effort Score for one player (EHI ref §5).

    hustle          : BoxScoreHustleV2 DataFrame (full game, both teams)
    foul_type_index : output of build_foul_type_index(pbp)

    Positive signals come from hustle stats + box score.
    Foul penalty is differentiated by type (defensive × 1.0,
    offensive × 1.3, loose-ball × 0.5).
    If every defensive stat is zero → DES = ZERO_DEF_BASELINE (25).

    Returns dict with all intermediates for validation.
    """
    pid = int(row["personId"])

    # ── Positive signals ──────────────────────────────────────────────────────
    # Hustle stats (may be absent if player didn't appear in hustle endpoint)
    h = hustle[pd.to_numeric(hustle["personId"], errors="coerce") == pid]
    if not h.empty:
        contested   = int(h.iloc[0]["contestedShots"])
        deflections = int(h.iloc[0]["deflections"])
        charges     = int(h.iloc[0]["chargesDrawn"])
    else:
        contested = deflections = charges = 0

    # Box score stats
    steals = int(row["steals"])
    blocks = int(row["blocks"])
    drebs  = int(row["reboundsDefensive"])

    # ── Zero-defense edge case (before computing anything else) ───────────────
    if contested + deflections + charges + steals + blocks + drebs == 0:
        fouls = foul_type_index.get(pid, {})
        return dict(
            contested=0, deflections=0, charges=0,
            steals=0, blocks=0, drebs=0,
            positive_total=0.0, des_raw=0.0,
            def_fouls=fouls.get("defensive", 0),
            off_fouls=fouls.get("offensive", 0),
            lb_fouls=fouls.get("loose_ball", 0),
            adjusted_fouls=0.0,
            foul_penalty=0.0,
            DES=float(ZERO_DEF_BASELINE),
            note="zero def stats → baseline",
        )

    # ── Positive total ────────────────────────────────────────────────────────
    positive_total = (
        contested   * CONTESTED_WEIGHT
        + deflections * DEFLECTION_WEIGHT
        + steals      * STEAL_WEIGHT
        + blocks      * BLOCK_WEIGHT
        + drebs       * DREB_WEIGHT
        + charges     * CHARGE_WEIGHT
    )
    des_raw = clamp((positive_total / DES_NORMALIZATION) * 100.0)

    # ── Foul penalty ──────────────────────────────────────────────────────────
    fouls         = foul_type_index.get(pid, {})
    def_fouls     = fouls.get("defensive",  0)
    off_fouls     = fouls.get("offensive",  0)
    lb_fouls      = fouls.get("loose_ball", 0)

    adjusted_fouls = (
        def_fouls  * DEF_FOUL_MULT
        + off_fouls  * OFF_FOUL_MULT
        + lb_fouls   * LOOSE_BALL_MULT
    )
    foul_penalty = (adjusted_fouls ** FOUL_PENALTY_EXP) * FOUL_PENALTY_BASE if adjusted_fouls > 0 else 0.0

    des = clamp(des_raw - foul_penalty)

    return dict(
        contested=contested,
        deflections=deflections,
        charges=charges,
        steals=steals,
        blocks=blocks,
        drebs=drebs,
        positive_total=round(positive_total, 2),
        des_raw=round(des_raw, 2),
        def_fouls=def_fouls,
        off_fouls=off_fouls,
        lb_fouls=lb_fouls,
        adjusted_fouls=round(adjusted_fouls, 2),
        foul_penalty=round(foul_penalty, 2),
        DES=round(des, 2),
        note="",
    )


# ─── SUB-SCORE: FDS (Part 1 — classification) ────────────────────────────────

_DRAWN_BY_RE     = re.compile(r'\(drawn by ([^)]+)\)', re.IGNORECASE)
_3PT_DESC_TOKENS = ("3pt", "3-pt", "3 pt", "three point", "3-point")


def _desc_is_3pt(desc: str) -> bool:
    d = desc.lower()
    return any(tok in d for tok in _3PT_DESC_TOKENS)


def _shot_zone_to_location(zone: str) -> str:
    z = str(zone).lower()
    if "restricted" in z or "non-ra" in z or "paint" in z:
        return "paint"
    if "mid" in z:
        return "mid_range"
    if "corner 3" in z or "above the break" in z or "backcourt" in z or "back court" in z:
        return "3pt"
    return "unknown"


def _build_shot_time_lookup(shots: pd.DataFrame) -> tuple[dict, dict]:
    """
    Return (shot_lookup, name_to_pid) from the shots DataFrame.

    shot_lookup  : (period, player_id, min_remaining, sec_remaining) → zone str
    name_to_pid  : player_name.lower() → player_id int
    """
    shot_lookup: dict[tuple, str] = {}
    name_to_pid: dict[str, int]   = {}

    for _, s in shots.iterrows():
        try:
            pid    = int(s["PLAYER_ID"])
            period = int(s["PERIOD"])
            mins   = int(s["MINUTES_REMAINING"])
            secs   = int(s["SECONDS_REMAINING"])
        except (KeyError, TypeError, ValueError):
            continue

        key = (period, pid, mins, secs)
        if key not in shot_lookup:
            shot_lookup[key] = _shot_zone_to_location(s.get("SHOT_ZONE_BASIC", ""))

        name = str(s.get("PLAYER_NAME", "")).strip()
        if name:
            name_to_pid[name.lower()] = pid

    return shot_lookup, name_to_pid


def _parse_pbp_clock(clock_str) -> tuple[int, int]:
    """PBP clock string → (minutes_remaining, seconds_remaining). Returns (-1, -1) on failure."""
    s = str(clock_str)
    try:
        if "PT" in s:
            s = s.replace("PT", "").replace("S", "")
            m, sec = s.split("M")
            return int(float(m)), int(float(sec))
        if ":" in s:
            m, sec = s.split(":")
            return int(float(m)), int(float(sec))
    except (ValueError, AttributeError):
        pass
    return -1, -1


def _coords_to_location(x: float, y: float) -> str:
    """
    Convert PBP xLegacy/yLegacy (tenths of a foot, basket at origin) to a zone string.
    3-point line: corners at 22 ft, above-break arc at ~23.75 ft.
    """
    dist = (x ** 2 + y ** 2) ** 0.5 / 10.0
    if dist < 14.0:
        return "paint"
    if dist < 22.0:
        return "mid_range"
    return "3pt"


def build_foul_drawn_events(pbp: pd.DataFrame, shots: pd.DataFrame) -> dict[int, list[dict]]:
    """
    Scan PBP for foul events and classify each by who drew it and where.

    Drawer identification: scan forward from the foul row to the next
    non-technical Free Throw — that FT shooter is the drawer.
    The scan stops at any subsequent foul event to prevent bleed-through.

    Location (shooting fouls only):
      1. Backward scan for an isFieldGoal=1 row by the drawer at/before same
         clock; derive zone from xLegacy/yLegacy or '3PT' in description.
         A Made Shot here also sets and_1=True; an "(N AST)" suffix sets
         assisted=True.
      2. Shot-chart lookup by (period, playerId, min, sec) ± 2 seconds.
      3. Fallback: 'mid_range' (neutral 2pt assumption per design spec).

    Non-shooting fouls → 'off_ball'.
    Technical, flagrant, and offensive fouls excluded.

    Returns {drawer_personId: [event_dict, ...]}
    Each event_dict: period, clock, subtype, location, fouler, drawer_name,
                     description, and_1, assisted, score_diff
    """
    shot_lookup, _name_to_pid = _build_shot_time_lookup(shots)

    pbp_r = pbp.reset_index(drop=True)
    n     = len(pbp_r)
    result: dict[int, list[dict]] = {}

    # Running score — updated on every Made Shot / Free Throw with a valid score field
    last_score_home = 0
    last_score_away = 0

    for i in range(n):
        play = pbp_r.iloc[i]

        # Keep running score current (scoreHome/Away populate on scoring events)
        try:
            sh = play.get("scoreHome")
            sa = play.get("scoreAway")
            if sh is not None and str(sh).strip() not in ("", "nan"):
                last_score_home = int(sh)
                last_score_away = int(sa)
        except (TypeError, ValueError):
            pass

        if str(play.get("actionType", "")).lower().strip() != "foul":
            continue

        st   = str(play.get("subType",     "")).lower().strip()
        desc = str(play.get("description", "")).strip()

        if st in _SPS_FOUL_SUBTYPES:
            continue
        if st in _OFF_FOUL_SUBTYPES:       # offensive / offensive charge → never FT-eligible
            continue

        foul_period = int(play.get("period", 0))
        foul_clock  = str(play.get("clock",  ""))
        fouler_name = str(play.get("playerNameI", play.get("playerName", "?"))).strip()
        try:
            fouler_pid = int(play.get("personId", 0))
        except (TypeError, ValueError):
            fouler_pid = 0

        score_diff = abs(last_score_home - last_score_away)

        # ── Step 1: find drawer via next non-technical Free Throw ─────────────
        drawer_pid  = None
        drawer_name = None
        for j in range(i + 1, min(i + 20, n)):
            nrow = pbp_r.iloc[j]
            nat  = str(nrow.get("actionType", "")).lower().strip()
            nst  = str(nrow.get("subType",    "")).lower().strip()
            if nat == "period":
                break
            if nat == "foul":
                break                   # stop before the next foul's FTs
            if nat == "free throw" and "technical" not in nst:
                try:
                    drawer_pid = int(nrow.get("personId", 0))
                except (TypeError, ValueError):
                    break
                drawer_name = str(nrow.get("playerNameI", nrow.get("playerName", "?"))).strip()
                break

        if not drawer_pid or drawer_pid <= 0:
            continue
        if drawer_pid == fouler_pid:
            continue

        # ── Step 2: classify location + detect and-1 / assisted ──────────────
        and_1    = False
        assisted = False
        location = None

        if st == "shooting":
            for k in range(i, max(i - 8, -1), -1):
                brow = pbp_r.iloc[k]
                if int(brow.get("isFieldGoal", 0)) != 1:
                    continue
                try:
                    bpid = int(brow.get("personId", 0))
                except (TypeError, ValueError):
                    continue
                if bpid != drawer_pid:
                    if str(brow.get("clock", "")) == foul_clock:
                        break           # different player at same clock — stop
                    continue
                # Found a shot by the drawer
                bdesc  = str(brow.get("description", ""))
                and_1  = str(brow.get("actionType", "")).lower().strip() == "made shot"
                assisted = and_1 and bool(re.search(r'\d+ AST\)', bdesc))
                x = float(brow.get("xLegacy", 0) or 0)
                y = float(brow.get("yLegacy", 0) or 0)
                if "3PT" in bdesc.upper():
                    location = "3pt"
                elif x != 0 or y != 0:
                    location = _coords_to_location(x, y)
                break

            if location is None:
                mins, secs = _parse_pbp_clock(foul_clock)
                if mins >= 0:
                    for s_off in (0, 1, -1, 2, -2):
                        adj = secs + s_off
                        if adj < 0:
                            continue
                        key = (foul_period, drawer_pid, mins, adj)
                        if key in shot_lookup:
                            location = shot_lookup[key]
                            break

            # Neutral 2pt fallback per spec
            if location is None or location == "2pt_unknown":
                location = "mid_range"
        else:
            location = "off_ball"

        result.setdefault(drawer_pid, []).append({
            "period":      foul_period,
            "clock":       foul_clock,
            "subtype":     st,
            "location":    location,
            "fouler":      fouler_name,
            "drawer_name": drawer_name,
            "description": desc,
            "and_1":       and_1,
            "assisted":    assisted,
            "score_diff":  score_diff,
        })

    return result


# ─── SUB-SCORE: FDS (Part 2 — scoring) ───────────────────────────────────────

def compute_fds(row: pd.Series, foul_drawn_index: dict) -> dict:
    """
    Foul Drawing Score for one player (EHI ref §2).

    foul_drawn_index : output of build_foul_drawn_events(pbp, shots)

    Per-foul legitimacy signals (0→1):
      +0.25  defender ≤4ft assumed for shooting fouls (foul implies contact)
      +0.20  assisted (catch-and-shoot, from PBP description)
      +0.20  and-1 (made shot + foul at same clock)
      −0.20  3rd foul of same subtype in this game
      −0.30  4th+ foul of same subtype in this game
      cap 0.45  off-ball fouls (personal/loose-ball in bonus)
      cap 0.20  garbage time (Q4, lead ≥ 20, ≤ 5 min left)

    Aggregate:
      FDS_raw        = mean(legitimacy) × 100
      volume_penalty = FTA^1.3 × 2.5
      FDS            = clamp(FDS_raw − volume_penalty)
      FT% modifier   = × 0.92 if FTM/FTA < 0.60 and FTA ≥ 4

    Returns dict with per_foul list and all intermediates.
    """
    pid = int(row["personId"])
    fta = int(row["freeThrowsAttempted"])
    ftm = int(row["freeThrowsMade"])

    # ── Edge case: zero FTAs ──────────────────────────────────────────────────
    if fta == 0:
        return dict(
            per_foul=[],
            n_fouls_drawn=0,
            avg_legitimacy=0.0,
            fds_raw=float(ZERO_FTA_BASELINE),
            volume_penalty=0.0,
            ft_pct=float("nan"),
            ft_mod=1.0,
            FDS=float(ZERO_FTA_BASELINE),
            note="zero FTA → baseline",
        )

    events = foul_drawn_index.get(pid, [])

    # Per-subtype counter for repetition penalty (incremented as we see each foul)
    type_counts: dict[str, int] = {}
    per_foul: list[dict] = []

    for ev in events:
        subtype  = ev["subtype"]
        location = ev["location"]
        and_1    = ev["and_1"]
        assisted = ev["assisted"]
        off_ball = (location == "off_ball")

        type_counts[subtype] = type_counts.get(subtype, 0) + 1
        count = type_counts[subtype]   # 1-based occurrence of this subtype

        # ── Per-foul legitimacy ───────────────────────────────────────────────
        leg     = 0.0
        signals: list[str] = []

        # Defender proximity: a foul implies contact, so ≤4ft is assumed for
        # all shooting fouls.  The ≤2ft bonus requires distance data we don't have.
        if not off_ball:
            leg += 0.25
            signals.append("+0.25 dist≤4ft")

        if assisted:
            leg += 0.20
            signals.append("+0.20 assisted")

        if and_1:
            leg += 0.20
            signals.append("+0.20 and-1")

        if count == 3:
            leg -= 0.20
            signals.append(f"-0.20 rep#{count}")
        elif count >= 4:
            leg -= 0.30
            signals.append(f"-0.30 rep#{count}")

        # Off-ball cap (applied before garbage-time cap)
        if off_ball and leg > 0.45:
            leg = 0.45
            signals.append("⊙off-ball≤0.45")

        # Garbage time: Q4, ≤5 min left, absolute lead ≥ 20 pts.
        # Compare total seconds to avoid the integer-minutes edge case where
        # e.g. PT05M46.00S would wrongly pass a "mins <= 5" check.
        mins_left, secs_left = _parse_pbp_clock(ev["clock"])
        total_secs_left = mins_left * 60 + secs_left
        garbage = (
            ev["period"] == 4
            and total_secs_left <= GARBAGE_TIME_MINUTES_LEFT * 60
            and ev["score_diff"] >= GARBAGE_TIME_LEAD
        )
        if garbage and leg > GARBAGE_TIME_LEG_CAP:
            leg = GARBAGE_TIME_LEG_CAP
            signals.append(f"⊙garbage≤{GARBAGE_TIME_LEG_CAP}")

        leg = clamp(leg, 0.0, 1.0)

        per_foul.append({
            "period":     ev["period"],
            "clock":      ev["clock"],
            "subtype":    subtype,
            "location":   location,
            "and_1":      and_1,
            "assisted":   assisted,
            "garbage":    garbage,
            "score_diff": ev["score_diff"],
            "rep_count":  count,
            "leg":        round(leg, 3),
            "signals":    "  ".join(signals) or "—",
        })

    # ── FDS aggregate ─────────────────────────────────────────────────────────
    all_legs = [f["leg"] for f in per_foul]
    avg_leg  = (sum(all_legs) / len(all_legs)) if all_legs else 0.0

    fds_raw        = avg_leg * 100.0
    volume_penalty = (fta ** VOLUME_PENALTY_EXP) * VOLUME_PENALTY_BASE
    fds            = clamp(fds_raw - volume_penalty)

    # FT% modifier
    ft_pct = ftm / fta
    ft_mod = 1.0
    if ft_pct < FT_PCT_THRESHOLD and fta >= 4:
        fds   *= FT_PCT_MODIFIER
        ft_mod = FT_PCT_MODIFIER

    return dict(
        per_foul=per_foul,
        n_fouls_drawn=len(per_foul),
        avg_legitimacy=round(avg_leg, 4),
        fds_raw=round(fds_raw, 2),
        volume_penalty=round(volume_penalty, 2),
        ft_pct=round(ft_pct, 4),
        ft_mod=ft_mod,
        FDS=round(clamp(fds), 2),
        note="",
    )


# ─── SUB-SCORE STUBS ──────────────────────────────────────────────────────────

def compute_sqs(row: pd.Series, shots: pd.DataFrame) -> float:
    """Shot Quality Score — TODO."""
    raise NotImplementedError("SQS not yet implemented")


# ─── MAIN COMPUTE ─────────────────────────────────────────────────────────────

def compute_all(data: dict) -> tuple[pd.DataFrame, dict]:
    """
    Compute all implemented EHI sub-scores for every active player.

    data : dict returned by pipeline.main()

    Returns
    -------
    df      : DataFrame with one row per player and all sub-score columns.
    detail  : {"fds": {personId: compute_fds_result_dict}} for validation reports.
    """
    box    = data["player_box"].copy()
    pbp    = data["pbp"]
    shots  = data["shots"]
    hustle = data["hustle"]

    box["minutes_dec"] = box["minutes"].apply(parse_minutes)
    active = box[box["minutes_dec"] > 0].copy().reset_index(drop=True)

    # Build PBP indices once — O(n_plays) each, not O(n_players × n_plays)
    violation_index  = build_violation_index(pbp)
    foul_type_index  = build_foul_type_index(pbp)
    foul_drawn_index = build_foul_drawn_events(pbp, shots)

    records    = []
    fds_detail = {}         # {personId: compute_fds result dict}

    for _, row in active.iterrows():
        ftp = compute_ftp(row)
        sps = compute_sps(row, violation_index)
        des = compute_des(row, hustle, foul_type_index)
        fds = compute_fds(row, foul_drawn_index)

        pid = int(row["personId"])
        fds_detail[pid] = fds

        records.append({
            # ── Identity ──────────────────────────────────────────────────
            "personId": pid,
            "player":   f"{row['firstName']} {row['familyName']}",
            "team":     row["teamTricode"],
            "min":      round(row["minutes_dec"], 1),
            # ── Box score inputs ──────────────────────────────────────────
            "pts":      int(row["points"]),
            "ftm":      int(row["freeThrowsMade"]),
            "fta":      int(row["freeThrowsAttempted"]),
            "fgm":      int(row["fieldGoalsMade"]),
            "fga":      int(row["fieldGoalsAttempted"]),
            "2pm":      int(row["twoPointersMade"]),
            "3pm":      int(row["threePointersMade"]),
            # ── FTP intermediates ─────────────────────────────────────────
            "ft_pts":       ftp["ft_pts"],
            "fg_pts":       ftp["fg_pts"],
            "total_pts":    ftp["total_pts"],
            "ft_dep%":      round(ftp["ft_dep_ratio"] * 100, 1),
            "ftp_raw":      ftp["ftp_raw"],
            "ftp_pen":      ftp["extra_penalty"],
            "FTP":          ftp["FTP"],
            "ftp_note":     ftp["note"],
            # ── SPS intermediates ─────────────────────────────────────────
            "sps_tech":     sps["counts"]["technical"]["count"],
            "sps_flag1":    sps["counts"]["flagrant1"]["count"],
            "sps_flag2":    sps["counts"]["flagrant2"]["count"],
            "sps_screen":   sps["counts"]["illegal_screen"]["count"],
            "sps_delay":    sps["counts"]["delay_of_game"]["count"],
            "sps_pen":      sps["total_penalty"],
            "SPS":          sps["SPS"],
            # ── DES intermediates ─────────────────────────────────────────
            "des_cst":      des["contested"],
            "des_dfl":      des["deflections"],
            "des_chg":      des["charges"],
            "des_stl":      des["steals"],
            "des_blk":      des["blocks"],
            "des_dreb":     des["drebs"],
            "des_pos":      des["positive_total"],
            "des_raw":      des["des_raw"],
            "des_def_f":    des["def_fouls"],
            "des_off_f":    des["off_fouls"],
            "des_lb_f":     des["lb_fouls"],
            "des_adj_f":    des["adjusted_fouls"],
            "des_pen":      des["foul_penalty"],
            "DES":          des["DES"],
            "des_note":     des["note"],
            # ── FDS intermediates ─────────────────────────────────────────
            "fds_n":        fds["n_fouls_drawn"],
            "fds_avg_leg":  fds["avg_legitimacy"],
            "fds_raw":      fds["fds_raw"],
            "fds_vol_pen":  fds["volume_penalty"],
            "fds_ft_pct":   fds["ft_pct"],
            "fds_ft_mod":   fds["ft_mod"],
            "FDS":          fds["FDS"],
            "fds_note":     fds["note"],
            # ── SQS stub ──────────────────────────────────────────────────
            "SQS": float("nan"),
            "EHI": float("nan"),
        })

    return pd.DataFrame(records), {"fds": fds_detail}


# ─── VALIDATION DISPLAY ───────────────────────────────────────────────────────

def print_ftp_report(df: pd.DataFrame) -> None:
    """
    Print a validation table for FTP.
    Shows enough intermediate values to hand-check any row against
    the reference table in EHI_Master_Reference.md §3.
    """
    # Sort: MIA first, then visitor; within each team descending FTP
    df = df.copy()
    df["_order"] = (df["team"] != "MIA").astype(int)
    df = df.sort_values(["_order", "FTP"], ascending=[True, False]).drop(columns="_order")

    W = 100
    print("\n" + "=" * W)
    print("FTP — FT Dependency Score  (validate before proceeding to SQS/FDS/SPS/DES)")
    print("=" * W)

    # Header
    print(
        f"{'Player':<22}{'Tm':>4}{'MIN':>6}{'PTS':>5}"
        f"{'FTM':>5}{'FTA':>5}{'FGM':>5}{'2PM':>5}{'3PM':>5}"
        f"  │"
        f"{'ft_pts':>7}{'fg_pts':>7}{'tot':>5}"
        f"{'FT_dep%':>9}{'raw':>7}{'pen':>7}{'FTP':>7}"
        f"  Note"
    )
    print("─" * W)

    for _, r in df.iterrows():
        print(
            f"{r['player']:<22}{r['team']:>4}{r['min']:>6.1f}{r['pts']:>5}"
            f"{r['ftm']:>5}{r['fta']:>5}{r['fgm']:>5}{r['2pm']:>5}{r['3pm']:>5}"
            f"  │"
            f"{r['ft_pts']:>7}{r['fg_pts']:>7}{r['total_pts']:>5}"
            f"{r['ft_dep%']:>8.1f}%{r['ftp_raw']:>7.1f}{r['ftp_pen']:>7.2f}{r['FTP']:>7.1f}"
            f"  {r['ftp_note']}"
        )

    print("─" * W)

    for team, grp in df.groupby("team", sort=False):
        print(f"  {team} avg FTP: {grp['FTP'].mean():.1f}   (n={len(grp)})")
    print(f"  Game avg FTP : {df['FTP'].mean():.1f}")

    # Spot-check: verify total_pts == pts (catches any 2PM derivation errors)
    mismatch = df[df["total_pts"] != df["pts"]]
    if not mismatch.empty:
        print("\n  ⚠  total_pts ≠ box-score pts for:")
        for _, r in mismatch.iterrows():
            print(f"     {r['player']}: computed {r['total_pts']} vs box {r['pts']}")
    else:
        print("\n  ✓  total_pts matches box-score pts for all players")

    print("=" * W)


def print_sps_report(df: pd.DataFrame) -> None:
    """
    Print a validation table for SPS.
    Shows per-player violation counts and how the stacking penalty was applied.
    Players with no violations (SPS = 100) are listed at the bottom.
    """
    df = df.copy()
    df["_order"] = (df["team"] != "MIA").astype(int)
    # Within each team: violators first (ascending SPS), then clean players
    df = df.sort_values(["_order", "SPS"], ascending=[True, True]).drop(columns="_order")

    W = 95
    print("\n" + "=" * W)
    print("SPS — Sportsmanship Score  (starts at 100, penalties only)")
    print("=" * W)
    print(
        f"{'Player':<22}{'Tm':>4}{'MIN':>6}"
        f"  │{'Tech':>6}{'Flag1':>6}{'Flag2':>6}{'Scrn':>6}{'Dlay':>6}"
        f"  │{'TotPen':>8}{'SPS':>7}"
        f"  Violations"
    )
    print("─" * W)

    vtype_labels = [
        ("sps_tech",   "T"),
        ("sps_flag1",  "F1"),
        ("sps_flag2",  "F2"),
        ("sps_screen", "IS"),
        ("sps_delay",  "DOG"),
    ]
    vtype_penalties = {
        "sps_tech":   TECH_PENALTY,
        "sps_flag1":  FLAGRANT1_PENALTY,
        "sps_flag2":  FLAGRANT2_PENALTY,
        "sps_screen": ILLEGAL_SCREEN_PEN,
        "sps_delay":  DELAY_PENALTY,
    }

    for _, r in df.iterrows():
        # Build a compact human-readable violation summary
        parts = []
        for col, label in vtype_labels:
            n = int(r[col])
            if n > 0:
                pen = vtype_penalties[col] * (n ** SPS_STACK_EXP)
                parts.append(f"{n}×{label}(−{pen:.1f})")
        violation_str = "  ".join(parts) if parts else "—"

        print(
            f"{r['player']:<22}{r['team']:>4}{r['min']:>6.1f}"
            f"  │{int(r['sps_tech']):>6}{int(r['sps_flag1']):>6}"
            f"{int(r['sps_flag2']):>6}{int(r['sps_screen']):>6}{int(r['sps_delay']):>6}"
            f"  │{r['sps_pen']:>8.2f}{r['SPS']:>7.1f}"
            f"  {violation_str}"
        )

    print("─" * W)
    violators = df[df["SPS"] < 100]
    clean     = df[df["SPS"] == 100]
    print(f"  Players with violations : {len(violators)}")
    print(f"  Clean (SPS = 100)       : {len(clean)}")
    for team, grp in df.groupby("team", sort=False):
        print(f"  {team} avg SPS: {grp['SPS'].mean():.1f}   (n={len(grp)})")
    print(f"  Game avg SPS : {df['SPS'].mean():.1f}")
    print("=" * W)


def print_des_report(df: pd.DataFrame) -> None:
    """
    Print a validation table for DES.

    Left block : hustle + box-score inputs
    Right block: positive_total, des_raw, foul breakdown, penalty, DES
    """
    df = df.copy()
    df["_order"] = (df["team"] != "MIA").astype(int)
    df = df.sort_values(["_order", "DES"], ascending=[True, False]).drop(columns="_order")

    W = 115
    print("\n" + "=" * W)
    print("DES — Defensive Effort Score")
    print(f"  Weights: CST×{CONTESTED_WEIGHT}  DFL×{DEFLECTION_WEIGHT}  STL×{STEAL_WEIGHT}"
          f"  BLK×{BLOCK_WEIGHT}  DREB×{DREB_WEIGHT}  CHG×{CHARGE_WEIGHT}"
          f"  norm÷{DES_NORMALIZATION}")
    print(f"  Foul mults: def×{DEF_FOUL_MULT}  off×{OFF_FOUL_MULT}  lb×{LOOSE_BALL_MULT}"
          f"  →  penalty = (adj_fouls^{FOUL_PENALTY_EXP}) × {FOUL_PENALTY_BASE}")
    print("=" * W)
    print(
        f"{'Player':<22}{'Tm':>4}{'MIN':>6}"
        f"  │{'CST':>5}{'DFL':>5}{'STL':>5}{'BLK':>5}{'DRB':>5}{'CHG':>5}"
        f"  │{'pos':>7}{'raw':>7}"
        f"  │{'dF':>4}{'oF':>4}{'lF':>4}{'adj':>6}{'pen':>7}{'DES':>7}"
        f"  Note"
    )
    print("─" * W)

    for _, r in df.iterrows():
        print(
            f"{r['player']:<22}{r['team']:>4}{r['min']:>6.1f}"
            f"  │{int(r['des_cst']):>5}{int(r['des_dfl']):>5}"
            f"{int(r['des_stl']):>5}{int(r['des_blk']):>5}"
            f"{int(r['des_dreb']):>5}{int(r['des_chg']):>5}"
            f"  │{r['des_pos']:>7.1f}{r['des_raw']:>7.1f}"
            f"  │{int(r['des_def_f']):>4}{int(r['des_off_f']):>4}"
            f"{int(r['des_lb_f']):>4}{r['des_adj_f']:>6.1f}"
            f"{r['des_pen']:>7.2f}{r['DES']:>7.1f}"
            f"  {r['des_note']}"
        )

    print("─" * W)
    # Foul penalty reference spot-check (defensive fouls only, for quick sanity)
    print("  Foul penalty reference (def fouls only): "
          + "  ".join(f"{n}F→{(n**FOUL_PENALTY_EXP * FOUL_PENALTY_BASE):.1f}"
                      for n in range(1, 7)))
    for team, grp in df.groupby("team", sort=False):
        print(f"  {team} avg DES: {grp['DES'].mean():.1f}   (n={len(grp)})")
    print(f"  Game avg DES : {df['DES'].mean():.1f}")
    print("=" * W)


def print_fds_report(df: pd.DataFrame, fds_detail: dict) -> None:
    """
    Print FDS summary table for all players, then a per-foul legitimacy
    breakdown for every player who drew at least one foul.

    fds_detail : {"fds": {personId: compute_fds_result}} from compute_all
    """
    detail = fds_detail.get("fds", fds_detail)   # accept either the outer or inner dict

    df = df.copy()
    df["_order"] = (df["team"] != "MIA").astype(int)
    df = df.sort_values(["_order", "FDS"], ascending=[True, False]).drop(columns="_order")

    W = 110
    print("\n" + "=" * W)
    print("FDS — Foul Drawing Score")
    print(f"  Volume penalty: FTA^{VOLUME_PENALTY_EXP} × {VOLUME_PENALTY_BASE}"
          f"   FT% modifier: ×{FT_PCT_MODIFIER} if FT%<{FT_PCT_THRESHOLD*100:.0f}% and FTA≥4"
          f"   Zero-FTA baseline: {ZERO_FTA_BASELINE}")
    print("=" * W)
    print(
        f"{'Player':<22}{'Tm':>4}{'MIN':>6}{'FTA':>5}{'FTM':>5}"
        f"  │{'fouls':>6}{'avg_leg':>8}{'FDS_raw':>8}{'vol_pen':>8}{'FT%':>6}{'mod':>5}"
        f"  │{'FDS':>7}  Note"
    )
    print("─" * W)

    for _, r in df.iterrows():
        ft_pct_str = (f"{r['fds_ft_pct']*100:5.0f}%" if r["fta"] > 0
                      else "   n/a")
        print(
            f"{r['player']:<22}{r['team']:>4}{r['min']:>6.1f}"
            f"{r['fta']:>5}{r['ftm']:>5}"
            f"  │{int(r['fds_n']):>6}{r['fds_avg_leg']:>8.3f}"
            f"{r['fds_raw']:>8.1f}{r['fds_vol_pen']:>8.1f}"
            f"{ft_pct_str:>6}{r['fds_ft_mod']:>5.2f}"
            f"  │{r['FDS']:>7.1f}  {r['fds_note']}"
        )

    print("─" * W)
    for team, grp in df.groupby("team", sort=False):
        print(f"  {team} avg FDS: {grp['FDS'].mean():.1f}   (n={len(grp)})")
    print(f"  Game avg FDS : {df['FDS'].mean():.1f}")
    print("=" * W)

    # ── Per-foul detail for every player who drew fouls ───────────────────────
    players_with_fouls = df[df["fds_n"] > 0].copy()
    if players_with_fouls.empty:
        return

    print()
    print("=" * W)
    print("FDS — Per-Foul Legitimacy Detail  (players with drawn fouls)")
    print("=" * W)

    for _, r in players_with_fouls.iterrows():
        pid    = int(r["personId"])
        result = detail.get(pid, {})
        fouls  = result.get("per_foul", [])
        if not fouls:
            continue

        print(f"\n  {r['player']} ({r['team']})  FTA={int(r['fta'])}  FDS={r['FDS']:.1f}"
              f"  avg_leg={r['fds_avg_leg']:.3f}"
              f"  vol_pen={r['fds_vol_pen']:.1f}"
              + (f"  ft_mod×{r['fds_ft_mod']:.2f}" if r["fds_ft_mod"] < 1.0 else ""))
        print(f"  {'#':>3}  {'Per':>3}  {'Clock':>12}  {'SubType':<14}  {'Loc':<11}"
              f"  {'A1':>3}  {'Ast':>4}  {'Grb':>4}  {'Diff':>5}  {'Rep':>4}  {'Leg':>6}  Signals")
        print("  " + "─" * (W - 2))

        for k, f in enumerate(fouls, 1):
            print(
                f"  {k:>3}  {f['period']:>3}  {f['clock']:>12}  "
                f"{f['subtype']:<14}  {f['location']:<11}"
                f"  {'Y' if f['and_1'] else '-':>3}"
                f"  {'Y' if f['assisted'] else '-':>4}"
                f"  {'Y' if f['garbage'] else '-':>4}"
                f"  {f['score_diff']:>5}"
                f"  {f['rep_count']:>4}"
                f"  {f['leg']:>6.3f}  {f['signals']}"
            )

        print("  " + "─" * (W - 2))

    print("=" * W)


def print_fds_classification_report(
    pbp: pd.DataFrame,
    shots: pd.DataFrame,
    player_box: pd.DataFrame,
    target_name: str = "Bam Adebayo",
) -> None:
    """
    Print all fouls drawn by target_name with their location classification.
    Used to verify the classification before implementing FDS scoring in Part 2.

    player_box  : player_box DataFrame from pipeline (needed to resolve personId → name).
    target_name : case-insensitive partial match on firstName + familyName.
    """
    # Resolve target_name → personId
    target_lower = target_name.lower()
    target_pid   = None
    for _, r in player_box.iterrows():
        full = f"{r['firstName']} {r['familyName']}".lower()
        if target_lower in full or all(part in full for part in target_lower.split()):
            target_pid = int(r["personId"])
            target_full_name = f"{r['firstName']} {r['familyName']}"
            break

    events_by_player = build_foul_drawn_events(pbp, shots)

    W = 120
    print("\n" + "=" * W)
    print(f"FDS — Foul Drawing Classification  (target: {target_name})")
    print("=" * W)

    if target_pid is None:
        print(f"  Could not resolve '{target_name}' in player_box.")
        print("=" * W)
        return

    events = events_by_player.get(target_pid, [])
    if not events:
        all_drawers = sorted(events_by_player.keys())
        print(f"  No drawn fouls found for '{target_name}' (personId={target_pid}).")
        print(f"  personIds with drawn fouls: {all_drawers}")
        print("=" * W)
        return

    drawer_display = events[0].get("drawer_name", "?")
    print(f"  Resolved: '{target_full_name}'  personId={target_pid}  "
          f"drawer_name in PBP='{drawer_display}'   Total drawn fouls: {len(events)}")
    print()
    print(f"  {'#':>3}  {'Per':>3}  {'Clock':>12}  {'SubType':<16}  {'Location':<14}  {'Fouler':<22}  Description")
    print("  " + "─" * (W - 2))

    loc_counts: dict[str, int] = {}
    for i, ev in enumerate(events, 1):
        loc = ev["location"]
        loc_counts[loc] = loc_counts.get(loc, 0) + 1
        print(
            f"  {i:>3}  {ev['period']:>3}  {ev['clock']:>12}  "
            f"{ev['subtype']:<16}  {loc:<14}  {ev['fouler']:<22}  {ev['description']}"
        )

    print("  " + "─" * (W - 2))
    print(f"\n  Location summary:")
    for loc, count in sorted(loc_counts.items()):
        print(f"    {loc:<16} : {count}")
    print("=" * W)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pipeline import main as pull_data

    data             = pull_data()
    results, detail  = compute_all(data)
    print_ftp_report(results)
    print_sps_report(results)
    print_des_report(results)
    print_fds_report(results, detail["fds"])
