# Overnight tuning log (Mech Royale)

Times are local (Sat 21 Nov 2026). Scores are practice score = mean(16 - place) over 48 matches.
Sim = `bot/sim` practice-format simulator (squad of house bots, tiers easy/starter/v1/fighter,
passive non-hunters, late=300), calibrated against real practice scores.

## Real submissions

| Receipt | Commit | What | Sim (vs same-seed v1) | Real score |
|---|---|---|---|---|
| BB-800C2F2C | ff3653f | v1: movement + weapons first version | 2.52-2.62 | 2.96 |
| BB-B6DC4365 | 2b1e2e4 | "aggressive": cautious switches off, zone-travel fix, sticky targeting | 2.96 ± 0.26 (v1 2.52 ± 0.24) | **3.31** (best) |
| BB-DFD1BDED | 080afbf | + focus (weakest clear-shot target) + strafe2 | 3.65 ± 0.21 (pushed 2.79 ± 0.18) | 3.19 |
| BB-40E1BAD6 | 6b70f38 | A: aggressive (2b1e2e4 behaviour) + cubes | 3.33 ± 0.25 (aggr 2.61 ± 0.16) | **3.56** (best) |
| BB-DDAA8695 | 861f493 | B: A + focus + strafe2 | 4.05 ± 0.26 (cube sim) | 3.10 |
| BB-F8A4F210 | 6b70f38 | A again, unchanged: measures run-to-run noise of the real scorer | - | 3.42 |

Same commit scored 3.56 and 3.42: the real scorer is repeatable to about ±0.1 (fixed seeds), far tighter
than the ±0.4 I first assumed. So focus + strafe2 (3.19, 3.10 vs 3.31-3.56) really is worse.

| BB-FC832A13 | 379f5bf | U: A + damage-first upgrades (uppower) | about +0.40 ± 0.14 over A (1152 each) | 3.52 (A: 3.56, 3.42) |
| BB-?       | (next) | U + crates + seek | +0.30 ± 0.30 over U (384 each) | real test |

### Change of method (03:55)
Sim vs real so far: aggressive +0.44 / +0.35, cubes +0.71 / +0.25 (vs 3.31), focus+strafe2 +0.85 / -0.12 and
+0.96 / -0.46, damage-first upgrades +0.40 / ~0. The sim finds mechanics (cubes) but overrates combat and
upgrade tweaks; its house bots are gun-only copies of our own code. The real scorer repeats to about ±0.07
per run and allows 4 runs an hour, so it is the better judge. From here: the sim screens for crashes,
slow ticks and clear regressions; real submissions decide what becomes the default.

Note: the site scores one submission per team at a time; the next one is refused until it finishes.

Sim tracked the first change well: predicted +0.44, real +0.35. It missed the second: predicted
+0.85, real -0.12. One practice run is 48 matches with a per-match spread of about 2.8, so a real
score is only good to about ±0.4; the miss is about 2 s.e. Lesson: the sim overrates targeting and
strafing tweaks (its house bots are all gun-only copies of our own code), so prefer changes based on
game mechanics the sim models faithfully, and judge real results on more than one run.

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

### Round 3 (cubes, seek): `sim/confirm_r3.txt`
- Found that the bot ignores power cubes completely (+4% HP and damage each, cap 10; kills drop the
  victim's cubes + 2; upgrade offers at 1/3/6/10). Added cube drops, pickup and HP/damage/size
  scaling to the sim (`sim/sim.py`; the old version is `sim/sim_pre_cubes.py.bak`).
- cubes = walk to the nearest visible cube within 70 m when not at zone risk.
- seek = when safe, healthy (>= 70% HP) and nobody in sight, walk toward the latest fight noise.
- 192 fresh matches each on the focus+strafe2 base (`sim/confirm_r3.txt`): cubes +0.74 ± 0.32 (2.3 s.e.),
  cubes+seek +0.72 (2.4 s.e.), seek alone +0.46 (1.6 s.e.), cubes+seek+regroup +0.48. Cubes held at end 0.75 -> 4.1.
- Same on the real-best aggressive base (`sim/confirm_r3b.txt`): aggr+cubes 3.33 ± 0.25 vs aggr 2.61 ± 0.16
  = +0.71 ± 0.30 (2.4 s.e.); aggr+cubes+strafe2 +0.64 (2.3 s.e.).
- Shipped two commits so the real scorer can separate cubes from focus: A = 6b70f38 (aggressive + cubes),
  B = 861f493 (HEAD: A + focus + strafe2). Both pass check.py and the container check (max 12.0 ms).

### Verdict on focus + strafe2 (real scorer)
- Two real pairs: 3.31 -> 3.19 without/with, and 3.56 -> 3.10. Both worse (about -0.3 on average), while
  the sim said about +0.9 both times. The sim is wrong about targeting/strafing; both stay off.
  Validated for real so far: aggressive (+0.35) and cubes (+0.25).

### Round 4 (crates): `sim/confirm_r4.txt`
- crates = when nobody is in sight, shoot open a ground crate within 65 m with line of sight
  (7 shots) for its cube. Sim now has 27 ground crates per match.
- On the A base: 3.32 ± 0.23 vs 3.32 ± 0.24 (no change, though cubes held 3.8 -> 4.7). On the B base +0.35.
  Not shipped; flag kept, off by default.
- Default flags set back to A (focus, strafe2, crates off).
- Next: resubmit A's exact commit to measure how much a real score varies run to run.

### Round 5 (upgrade order): `sim/confirm_r5.txt`
- Cubes now trigger upgrade offers, and our order was movement-first (servos, jets, armor,
  capacitor, ...), with gun_damage missing entirely. Sim now models offers at cube thresholds
  (3 random eligible choices, choice 0 after 5 s) and per-mech upgrade effects (sim_pre_upgrades.py.bak = old).
- uppower = gun_damage, gun_rate, armor, plating, nanites, gun_mag, servos, ...
- uptank  = armor, plating, nanites, gun_damage, gun_rate, servos, ...
- 192 fresh (`confirm_r5.txt`): uppower 4.11 ± 0.30, uptank 3.89 ± 0.28, A 3.69 ± 0.26 (uppower +1.1 s.e.).
- 384 more (`confirm_r5b.txt`): uppower 3.55 ± 0.17 vs A 3.32 ± 0.16 (+1.0 s.e.).
- Pooled 576 each: about +0.30 ± 0.19 (1.6 s.e.).
- 576 more (`confirm_r5c.txt`): uppower 3.98 ± 0.17 vs A 3.48 ± 0.14 = +0.50 ± 0.22 (2.3 s.e.).
  Pooled 1152 each: about +0.40 ± 0.14 (2.8 s.e.) -> BETTER. Shipping A + uppower.

### Round 6 (crates, seek on the U base): `sim/confirm_r6.txt`
- Upgrades make every cube worth more, so re-testing crates and seek (both neutral/borderline before).
- 384 fresh each: U 4.12 ± 0.21, U+crates 4.16, U+seek 4.17, U+crates+seek 4.42 ± 0.21 (+0.30 ± 0.30, 1.0 s.e.).
  Cubes held 4.6 -> 5.6 with both. No regression, so U+crates+seek goes to a real test.
