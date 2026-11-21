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
| BB-2B482130 | ed981aa | U + crates + seek | +0.30 ± 0.30 over U (384 each) | **3.96** (best, +0.44) |
| BB-CDBDE7C4 | b5900fa | ed981aa + lootfar: walk up to 120 m for ground weapons in the first 150 s | (sim has no loot) | 3.73 (worse, off) |
| BB-8216156A | 2e8d5c2 | ed981aa + drones (snipe NPC drones for cubes) | (sim has no NPCs) | **4.06** (best, +0.10) |
| BB-D46D4999 | 39da462 | 2e8d5c2 + cratego: walk to crates when idle, shoot them from 90 m | +0.23 ± 0.29 (sim) | 3.96 (no gain, off) |
| BB-491F2EED | eac4376 | 2e8d5c2 + terrain-aware walls + radius-aware routes | neutral, fewer zone deaths | 3.77 (worse, both off) |
| BB-6F48C004 | 2025b71 | 2e8d5c2 + steering looks only as far as the route waypoint | +0.31 ± 0.22 (sim, 768) | 3.98 (neutral; kept, correct fix) |
| BB-2D784B26 | a80dbe0 | 2025b71 + regroup: heal to 85% out of sight between fights | +0.04 ± 0.32 (sim) | 3.79 (worse than 3.98, off) |
| BB-5D0464CB | 36e24d0 | 2025b71 + hunt: walk to the last-seen enemy when healthy and idle | +0.40 ± 0.29 (sim) | 3.73 (off) |
| BB-D250913B | 45859f3 | 2025b71 + roof: climb a roof inside the next circle and fight from it | sim can't model roofs | 3.58 (worse, off) |

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

### Real-only candidates (the sim has no NPCs or weapon pickups)
- lootfar (b5900fa, scoring).
- drones (in the working copy, off): when no enemy mech is in sight, snipe NPC drones (350 HP, 2 cubes
  each, 12 per match) from 70-200 m, where their 2.5-degree-spread bullets mostly miss; keep shooting the
  current one down to 20 m; cube pickup range 130 m with it on. Unit-tested on a real observation with an
  injected drone: it targets, leads and fires once aimed.

### Round 7 (cratego): `sim/confirm_r7.txt`
- cratego = when idle in a safe zone and nobody in sight, walk toward the nearest ground crate within
  150 m (inside the next circle), and shoot crates from up to 90 m instead of 65 m.
- 384 fresh each: cratego 4.54 ± 0.21 vs base 4.31 ± 0.20 (+0.23 ± 0.29, 0.8 s.e.); no regression -> real test.

### Round 8 (zone deaths, widefield): `sim/confirm_r8.txt`
- In the sim, 20 of 96 matches end in a zone death, mostly at 138-215 s, placing 15th-16th (mean score
  0.95 vs 3.69 otherwise). Traced seed 1300016 (`sim/trace_squad.py`): the bot sat 20 m outside the zone
  for 30 s, mode "zone" with no route, until it died. Cause: the flow field only searches the live circle
  + 40 m; the pocket west of the stadium connects to the safe zone only through a detour outside that
  limit, so the field never reached it and the bot steered straight into the wall.
- widefield = flow field search area live circle + 150 m. Result (`confirm_r8.txt`): no help, zone deaths
  69 -> 67 of 384, score 4.39 -> 4.25. Off.
- Deeper trace (seeds 1300018, 1300037): the bot *spawned* inside a pocket south of the stadium that the
  grid says is sealed (flood fill from it never reaches the safe zone). The pocket is sealed by "walls"
  whose tops are below the ground there (down to 14 m under our feet): prisms buried in the terrain, such
  as the sunken stadium bowl's lower rows. Both the bot's grid and the sim marked every prism taller
  than 1.2 m as a wall regardless of terrain height. 691 of 44,509 wall cells (1.6%) are such phantoms.
- This matters for the real game too: phantom walls bend the bot's routes and block its line-of-sight
  checks (clear-shot targeting, crates, drones).
- terrain = the bot loads the terrain heights and only marks a cell as a wall where a prism rises above the
  ground and isn't overhead. The sim's world now uses the same rule (old: `sim/sim_pre_terrain.py.bak`).

### Round 9 (terrain): `sim/confirm_r9.txt`
- terrain 4.42 ± 0.20 vs base 4.32 ± 0.20 (+0.4 s.e.); zone deaths 83 vs 77 of 384: phantom walls are not the
  main cause of zone deaths.
- Retrace of seed 1300018 with terrain on: the bot now has a route but oscillates in place around a
  waypoint 5-8 m away for 35 s. The route goes through a gap one cell (2 m) wide: the flow field treats
  the mech as a point, but it is 5 m wide, so it cannot fit (in the sim or the real game).
- inflate = the flow field searches a wall mask grown by one cell (gaps under about 6 m are closed, paths keep
  off walls). Mask built at hello (0.13 s total init). On seed 1300018 it leaves the pocket but dies
  outside the zone at about 160 s instead: one seed, so running the full comparison.

### Round 10 (terrain x inflate): `sim/confirm_r10.txt`
- 384 fresh each: inflate 4.70, base 4.62, terrain+inflate 4.57, terrain 4.52 (all within ±0.1 of base, ±0.3 s.e.).
  Zone deaths: base 81, terrain 81, inflate 69, terrain+inflate 67 of 384.
- Both fixes are physically right for the real map (no buried walls; no 2 m squeezes for a 5 m mech) and
  the sim can't judge line-of-sight effects, so terrain+inflate goes to a real test on top of 2e8d5c2.

- Real: eac4376 (terrain+inflate) scored 3.77 vs best 4.06: -0.29, about 3x scorer noise. Both off again.
  The sim's zone-death gain did not carry over; likely the real game's collision lets a mech through gaps
  the inflated mask closes, so inflate forces long detours. The sim cannot judge this.

### Round 11 (steerwp): `sim/confirm_r11.txt`
- Remaining zone deaths with the default bot: 10/72 (seeds 1700000+). Trace of seed 1700046: stuck 20+ s
  in *flat open ground* in "path" mode, swinging left/right. Cause: `_steer` checks 9-14 m ahead along the
  heading to a waypoint only 2-3 m away; the route turns at the waypoint, so the wall past it makes the
  steering swerve off the route every tick. The same code runs in the real game.
- steerwp = when following the flow field, steering looks only as far as the waypoint (+1 m).
  Seed 1700046: zone death 16th -> killed in a fight 11th.
- r11 (seeds 1800000+): steerwp 4.89 vs base 4.32, +0.57 ± 0.31 (+1.8 s.e.); zone deaths 61 -> 53.
- r11b (seeds 1900000+, `sim/confirm_r11b.txt`): 4.57 vs 4.52, +0.05 ± 0.30; zone deaths 63 -> 57.
- Pooled 768: +0.31 ± 0.22 (+1.4 s.e.), zone deaths 124 -> 110. Under the bar, but a narrow bug fix that only
  touches route-following, and slots are free, so it goes to a real test (terrain, inflate off).
- Real: 2025b71 (steerwp) 3.98: within noise of 4.06 (the 39da462/ed981aa family also scored 3.96).
  steerwp stays on as a correct bug fix.

## Where we stand (06:10)
- Leaderboard: 222 teams, top 5.96, about 5.2 needed for the top 32 (qualifying). We are at 4.06, around rank 100.
- Rules recap: house bots never fight each other and hunt us, so score ~ how many die before us ~ our kills.
  Small tweaks are inside scorer noise; we need about +1, so the next changes target duels and survival
  between hunters (HP regen 45/s after 5 s undamaged: full heal in ~31 s).

### Round 12 (disengage flags): `sim/confirm_r12.txt`
- regroup (heal to 85% out of sight between fights), hide, outnumbered: each alone on the current base.
- 384 fresh each: regroup 5.01, base 4.97 (+0.1 s.e.), outnumbered 3.65 (-4.4 s.e.), hide 2.40 (-9.5 s.e.).
  Zone deaths with steerwp on are down to 46/384. Hiding costs kills, and kills are the score.
- regroup goes to a real test (the sim misjudged several fight-behaviour changes before).
- Real: a80dbe0 (regroup) 3.79 vs 3.98 without it: off again.

### Deaths analysis (`sim/deaths.py`, 192 matches)
- 158 combat deaths, 100 of them in minute 5 (the sim's all-hunt at 300 s), usually 2-7 attackers in the last
  10 s. Kills come at only 0.5-0.7 per minute before that: hunters arrive one at a time.
- So more kills before the swarm is the lever: go and find fights while healthy.

### Round 13 (hunt): `sim/confirm_r13.txt`
- hunt = with nothing in sight and HP >= 70%, walk to the most recent enemy sighting (< 30 s old) that is
  safely inside the next circle (seek only follows sounds < 8 s old).
- 384 fresh: hunt 4.68 vs base 4.28, +0.40 ± 0.29 (+1.4 s.e.); kills 3.61 -> 3.81; zone deaths 66 -> 59.
- Real test on 2025b71 (regroup off).
- Round 14 (`sim/confirm_r14.txt`, seeds 2300000+): hunt 4.44, hunt2 4.44, no hunt 4.45: no gain on fresh seeds.
- Real: 36e24d0 (hunt) 3.73. Off.

## Change of tack (07:00)
- Since 2e8d5c2 (4.06) six real tests scored 3.73-3.98 (mean ~3.88): behaviour tweaks are inside scorer noise,
  and the sim (no roofs, jumping, jets, loot, extra weapons, NPCs; house bots = our old versions) cannot rank them.
- roof = structural bet. With no enemy within 120 m and no zone risk, pick the nearest flat roof (6-48 m up,
  >= 8 m from edge to middle) safely inside the next circle; walk until the straight line to it meets that
  building first, then hop and jet up (energy check first), and hold the middle of the roof. Fight from there
  (edge clamp keeps us on it); come down for cubes, loot, drops or the zone. A climb not done in 25 s marks
  that roof bad for 90 s.
- Kinematic harness (`sim/climb_test.py`: one mech, protocol jump/jet/energy numbers, walls from the grid):
  13 of 20 random roofs reached and held, usually in 3-5 s.
- The flat sim can only show the cost (climbs always fail there): 3.75 on 96 matches. Real test decides.
- Real: 45859f3 (roof) 3.58, the worst since 2e8d5c2. Off. HEAD restored to 2025b71 behaviour (3.98).

## Stopped (07:15)
- Seven real tests since the 4.06 best: 3.98, 3.96, 3.79, 3.77, 3.73, 3.73, 3.58. None beat it; the sim's
  screening stopped predicting real results once the remaining changes were about fights and movement.
- The leaderboard keeps 4.06 (BB-8216156A, 2e8d5c2) as the final entry unless another is picked.
- To get the ~1.2 needed for the top 32, the sim needs to model what decides real fights (loot weapons,
  NPC drones, jumping/roofs, stronger house bots) before more tuning is worth real slots.

## Day session: reload, fire and loot order

- `upmag` (pick Drum magazine first: +31% sustained gun damage by the stats) and `holdfire` (no gun fire
  at a target behind a wall, reload instead), `sim/confirm_r15.txt`, 192 fresh matches each, seeds 1010000+:
  base 4.54 ± 0.29, upmag 4.50, holdfire 4.39, both 4.46. None within 1 s.e. of better: not pushed.
  Both switches are left in the code, off.
- `lootflip` (loot ranked lightning > laser > mortar, by damage per second) is in the code, on in the
  working tree, uncommitted. The sim has no loot weapons, so only a real submission can test it.
- Real: BB-A3FFDA23, e7f1836 (lootflip on top of the 3.98 version): **4.15**, new best, entered in the
  final. +0.17 over 3.98 for the loot order alone. Team rank 109 of 252 at 4.15.
- `arcsave`: in a lightning fight (target within lightning range + 10 m) no dodge boosts, and lightning
  fires down to 3 energy (15 while zone-boosting) instead of stopping at 30. Real-only (no lightning in the sim).
