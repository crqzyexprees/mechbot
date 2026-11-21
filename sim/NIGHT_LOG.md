# Overnight tuning log (Mech Royale)

Times are local (Sat 21 Nov 2026). Scores are practice score = mean(16 - place) over 48 matches.
Sim = `bot/sim` practice-format simulator (squad of house bots, tiers easy/starter/v1/fighter,
passive non-hunters, late=300), calibrated against real practice scores.

## Real submissions

| Receipt | Commit | What | Sim (vs same-seed v1) | Real score |
|---|---|---|---|---|
| BB-800C2F2C | ff3653f | v1: movement + weapons first version | 2.52-2.62 | 2.96 |
| BB-B6DC4365 | 2b1e2e4 | "aggressive": cautious switches off, zone-travel fix, sticky targeting | 2.96 ± 0.26 (v1 2.52 ± 0.24) | **3.31** (best) |

Sim tracked the real change well: predicted +0.44, real +0.35.

## Rounds

### Round 1 (switch ablation): `sim/sweep_round1_results.txt`
- Every cautious behaviour (hold fire, never chase, hide, cover, flee when outnumbered) cost kills.
- "aggressive" (all five off) was the best variant; pushed as 2b1e2e4.

### Round 2 (fight switches: focus, regroup, strafe2): `sim/sweep_results.txt`
- focus = shoot the lowest-HP clear-shot enemy within 200 m; regroup = heal to 85% out of sight after a
  kill or when below 45% and not under fire; strafe2 = stronger, faster-flipping duel strafe.
- Stage 2 (120 matches): "pushed + focus" 3.67 ± 0.24, "focus + strafe2" 3.77 ± 0.28,
  "focus + regroup" 3.67 ± 0.28, pushed 3.04 ± 0.22, v1 2.42 ± 0.16.
  Every leader has `focus`; regroup and strafe2 alone did nothing (2.92, 2.75 vs pushed 2.79 in stage 1).
- Stage 3 (96 fresh): focus + strafe2 3.41 ± 0.29 vs pushed 2.89 ± 0.25 = +0.52 ± 0.38, below the 2 s.e. bar.
- Confirmation, 192 fresh matches each (`sim/confirm_r2.txt`):
  focus + strafe2 3.65 ± 0.21, pushed + focus 3.55 ± 0.19, pushed 2.79 ± 0.18.
  focus + strafe2 - pushed = **+0.85 ± 0.28 (3.1 s.e.) -> BETTER**; focus alone +0.76 (2.8 s.e.).
- Shipped focus + strafe2 (regroup off). check.py PASS (max 11.0 ms), container check PASS (max 11.4 ms).
  Baked default in the sim: 96 fresh matches, mean place 12.2 = score 3.8, 0 errors.
