"""Squad-mode trace of candidate while outside the zone: python3 ztrace.py SEED [all]"""
import os, sys, math, json, gzip, random, sim, sweep
kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
seed = int(sys.argv[1]); allp = len(sys.argv) > 2
import builtins
cap = {}
orig = sim.Match.__init__
def init(self, *a, **k):
    orig(self, *a, **k); cap["m"] = self
sim.Match.__init__ = init
orun = sim.Match.run
def run(self):
    me = [x for x in self.mechs if x.path == bot][0] if hasattr(self.mechs[0], "path") else None
    return orun(self)
# step manually instead
world = sim.World(kit)
rng = random.Random(seed)
for c in sim._CLOCKS: c.t = 0.0
hello = json.loads(gzip.open(os.path.join(kit, "check", "stream.jsonl.gz"), "rt").readline()); hello["map"]["dir"] = os.path.join(kit, "arena")
n = 16; slots = rng.sample(range(n), 1)
opps = sweep.TIERS; so = sweep.SQUAD
tiers = [opps[min(i, len(opps) - 1)] for i, c in enumerate(sim.TIER_COUNTS) for _ in range(c)]
others = [i for i in range(n) if i not in slots]; rng.shuffle(others)
roster, house = [None] * n, {}
for rank, (i, path) in enumerate(zip(others, tiers)): roster[i], house[i] = path, rank
for i in slots: roster[i] = bot
m = sim.Match(world, hello, roster, seed, dict(so, house=house)); me = m.mechs[slots[0]]
every = m.cfg["match"].get("decide_every", 2)
while me.alive and m.t < 480 and sum(x.alive for x in m.mechs) > 1:
    if m.tick % every == 0: m.decide()
    if m.tick % 10 == 0:
        cx, cy, r, dps = m.zone_live(m.t)
        zd = math.hypot(me.x - cx, me.y - cy) - r
        if zd > 0 or allp:
            lab = (me.mf.draw._d or {}).get("label", "")
            print(f"t={m.t:6.1f} g={int(bool(getattr(me,'grounded',0)))} j={int(bool(me.cmd.get('jump')))} b={int(bool(me.cmd.get('boost')))} hp={me.hp:6.0f} pos=({me.x:6.1f},{me.y:6.1f},{me.z:5.1f}) zone_d={zd:+7.1f} spd={math.hypot(me.vx, me.vy):4.1f} move={[round(v,2) for v in me.cmd['move']]} {lab}")
    m.physics()
    if m.npcs: m.step_npcs()
    m.tick += 1; m.t = m.tick * sim.DT
print("end", m.t, "alive" if me.alive else "dead")
