"""Trace one bot through a simulated match: python3 trace.py <bot> <opponents> <seed> [from_t] [to_t]"""
import sim, os, sys, json, gzip, math, random
kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
bot, opps, seed = os.path.abspath(sys.argv[1]), [os.path.abspath(p) for p in sys.argv[2].split(",")], int(sys.argv[3])
t0 = float(sys.argv[4]) if len(sys.argv) > 4 else 0; t1 = float(sys.argv[5]) if len(sys.argv) > 5 else 1e9
w = sim.World(kit)
h = json.loads(gzip.open(kit + "/check/stream.jsonl.gz", "rt").readline()); h["map"]["dir"] = kit + "/arena"
rng = random.Random(seed); slot = rng.sample(range(16), 1)[0]
roster = [bot if i == slot else opps[i % len(opps)] for i in range(16)]
m = sim.Match(w, h, roster, seed); me = m.mechs[slot]
while me.alive and m.t < 480 and sum(x.alive for x in m.mechs) > 1:
    if m.tick % 2 == 0:
        m.decide()
        if m.tick % 10 == 0 and t0 <= m.t <= t1:
            cx, cy, r, dps = m.zone_live(m.t)
            lab = (me.mf.draw._d or {}).get("label", "")
            print(f"t={m.t:6.1f} hp={me.hp:6.0f} e={me.energy:4.0f} zone_d={math.hypot(me.x-cx, me.y-cy)-r:+7.1f} "
                  f"spd={math.hypot(me.vx, me.vy):4.1f} move={[round(v,2) for v in me.cmd['move']]} {lab}")
    m.physics(); m.tick += 1; m.t = m.tick * sim.DT
print("end", m.t, "alive" if me.alive else "dead", "place", m.places()[slot])
