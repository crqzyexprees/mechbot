"""Trace our bot in the practice (squad) format: python3 trace_squad.py <seed> [from_t] [to_t] [every_ticks]"""
import sim, sweep, os, sys, json, gzip, math, random
kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
cand = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
seed = int(sys.argv[1]); t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0
t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9; every = int(sys.argv[4]) if len(sys.argv) > 4 else 10
world = sim.World(kit); rng = random.Random(seed)
hello = json.loads(gzip.open(os.path.join(kit, "check", "stream.jsonl.gz"), "rt").readline())
hello["map"]["dir"] = os.path.join(kit, "arena")
n = hello["config"]["match"]["mechs"]; slot = rng.sample(range(n), 1)[0]
tiers = [sweep.TIERS[min(i, 3)] for i, c in enumerate(sim.TIER_COUNTS) for _ in range(c)]
others = [i for i in range(n) if i != slot]; rng.shuffle(others)
roster, house = [None] * n, {}
for rank, (i, p) in enumerate(zip(others, tiers)):
    roster[i], house[i] = p, rank
roster[slot] = cand
m = sim.Match(world, hello, roster, seed, dict(sweep.SQUAD, house=house)); me = m.mechs[slot]
while me.alive and m.t < 480 and sum(x.alive for x in m.mechs) > 1:
    if m.tick % 2 == 0:
        m.decide()
        if m.tick % every == 0 and t0 <= m.t <= t1:
            cx, cy, r, dps = m.zone_live(m.t)
            lab = (me.mf.draw._d or {}).get("label", "")
            print(f"t={m.t:6.1f} hp={me.hp:6.0f} e={me.energy:4.0f} zone_d={math.hypot(me.x-cx, me.y-cy)-r:+7.1f} r={r:5.0f} "
                  f"spd={math.hypot(me.vx, me.vy):4.1f} {lab}")
    m.physics(); m.tick += 1; m.t = m.tick * sim.DT
print("end", round(m.t, 1), "alive" if me.alive else "dead", "place", m.places()[slot])
