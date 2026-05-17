---
name: 2025-26 season run complete
description: Full 2025-26 NBA season processed; key findings, positional bias issue identified
type: project
---

2025-26 full season run complete as of 2026-05-17: 1,223 games (1,197 direct + 26 retried), 23,313 player-game rows saved to ehi.db.

Key results: League avg EHI 48.27 · Season high 75.76 (Rudy Gobert, single game) · Season low 8.91 (Collin Gillespie).
Top 10 led by Mitchell Robinson (60.43), Robert Williams III (60.06), Jericho Sims (59.23).
Notable star results: Giannis (58.04, 35 GP), Dyson Daniels (57.77, 76 GP).
Bottom 10 led by Jordan Poole (39.47), Grayson Allen (40.19).
Most ethical team: New Orleans Pelicans (49.84).

**Why:** Season run was the primary deliverable after 12-game validation.
**Known issue:** Low-scoring centers dominate top rankings due to positional bias in DES normalization + neutral FTP baseline for zero-scorers. Fix planned: offensive usage floor or reduced EHI weight for very low FGA players.
**How to apply:** When discussing top-10 results, note the positional bias caveat. Next dev priority is the positional bias fix.
