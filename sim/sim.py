"""Rough local match simulator for mechfight/1 bots. NOT the real server.

It exists to compare bot versions without spending a submission. It models what matters for
survival and placement, approximately:

- the real map walls (buildings and stadium from v2/world.json; bridges ignored), terrain height
- movement with acceleration, walk/boost speeds, energy drain and regen, wall sliding
- torso aim slewing at turn_rate / pitch_rate
- gun only (12-round mag, reload, cooldown, spread, bullet travel, wall hits, rear-armor x1.5)
- vision (45 m all around, 200 m in a 120 degree wedge, walls block, 5 s memory)
- sounds (gun, step, boost, death) with bearing noise and near/mid/far
- damaged/hit events, HP regen after 5 s out of combat, the shrinking zone with its dps
- placement by death order, ties shared, survivors at the time limit ranked by HP

Squad mode (--tiers, the practice format): the other 15 mechs are house bots in 4 tiers (4 easy, 4
medium, 4 hard, 3 expert). They never fight each other (no friendly fire, they only ever see the
candidate), share vision, and hunt weakest-first: `hunters` at the start, one more per house bot the
candidate kills, all of them after --late seconds. Hunters know where the candidate is whenever any
house bot sees it (or always, with --omniscient). Non-hunters ignore the candidate unless it shot them
in the last 10 s. House bots only take zone damage in the final circle (they play the zone well).

Cubes: death drops (victim's + 2), pickup, +HP/+damage/+size scaling. Ground crates (300 HP, 1 cube).
Prisms buried under the terrain (or overhead) are not walls.
Upgrade offers at cube thresholds (mech + gun upgrades; sensors = +25 m vision only).
Not modelled: loot, mortar/laser/lightning, NPCs, roof crates, supply drops, jumping,
jets, roofs, bridges, trees, mech-vs-mech pushing. The bots under test get `[]` for those fields.

Usage (from anywhere):
  python3 sim.py --kit ../../mechfight-kit --candidate ../example_bot.py \
      --opponents ../../mechfight-kit/python/example_bot.py --matches 48 --jobs 24
Prints the candidate's mean score (16 - place), the same number the track page shows.
"""
import argparse
import gzip
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from array import array
from multiprocessing import Pool

DT = 0.05
CELL = 2.0


def angdiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


# ------------------------------------------------------------------------------------------ world
class World:
    def __init__(self, kit):
        w = json.load(open(os.path.join(kit, "arena", "v2", "world.json")))
        b = w["bounds"]
        self.x0, self.y0, self.x1, self.y1 = b["minX"], b["minY"], b["maxX"], b["maxY"]
        self.nx = int((self.x1 - self.x0) / CELL) + 1
        self.ny = int((self.y1 - self.y0) / CELL) + 1
        self.solid = bytearray(self.nx * self.ny)
        t = w["terrain"]
        self.tx0, self.ty0, self.tstep, self.tnx, self.tny = t["minX"], t["minY"], t["step"], t["nx"], t["ny"]
        self.h = array("h")
        with open(os.path.join(kit, "arena", "v2", t.get("file", "terrain.i16")), "rb") as f:
            self.h.frombytes(f.read())
        if sys.byteorder != "little":
            self.h.byteswap()
        for p in w["prisms"]:
            if p["kind"] == "bridge" or p["top"] - p["base"] <= 1.2:
                continue
            self._fill(p)

    def _fill(self, p):
        edges, ymin, ymax = [], 1e18, -1e18
        for r in [p["ring"]] + list(p.get("holes") or []):
            n = len(r) // 2
            for i in range(n):
                ax, ay, bx, by = r[2 * i], r[2 * i + 1], r[2 * ((i + 1) % n)], r[2 * ((i + 1) % n) + 1]
                if ay != by:
                    edges.append((ax, ay, bx, by))
                ymin, ymax = min(ymin, ay), max(ymax, ay)
        for j in range(max(0, int((ymin - self.y0) / CELL)), min(self.ny - 1, int((ymax - self.y0) / CELL) + 1) + 1):
            yc = self.y0 + (j + 0.5) * CELL
            xs = sorted(ax + (yc - ay) * (bx - ax) / (by - ay) for ax, ay, bx, by in edges
                        if (ay <= yc < by) or (by <= yc < ay))
            for k in range(0, len(xs) - 1, 2):
                for i in range(max(0, int((xs[k] - self.x0) / CELL)), min(self.nx - 1, int((xs[k + 1] - self.x0) / CELL)) + 1):
                    gz = self.ground(self.x0 + (i + 0.5) * CELL, yc)
                    if p["top"] <= gz + 1.2 or p["base"] >= gz + 9:
                        continue  # buried under the terrain, or overhead: not a wall
                    self.solid[j * self.nx + i] = 1

    def blocked(self, x, y):
        if not (self.x0 + 1 < x < self.x1 - 1 and self.y0 + 1 < y < self.y1 - 1):
            return True
        return self.solid[int((y - self.y0) / CELL) * self.nx + int((x - self.x0) / CELL)] == 1

    def body_blocked(self, x, y, r):
        return (self.blocked(x, y) or self.blocked(x + r, y) or self.blocked(x - r, y)
                or self.blocked(x, y + r) or self.blocked(x, y - r))

    def los(self, ax, ay, bx, by, step=3.0):
        d = math.hypot(bx - ax, by - ay)
        n = int(d / step)
        for k in range(1, n):
            f = k / n
            if self.blocked(ax + (bx - ax) * f, ay + (by - ay) * f):
                return False
        return True

    def ground(self, x, y):
        fx, fy = (x - self.tx0) / self.tstep, (y - self.ty0) / self.tstep
        i, j = int(fx), int(fy)
        if not (0 <= i < self.tnx - 1 and 0 <= j < self.tny - 1):
            return 0.0
        u, v = fx - i, fy - j
        h, n = self.h, self.tnx
        a = h[j * n + i] * (1 - u) + h[j * n + i + 1] * u
        b = h[(j + 1) * n + i] * (1 - u) + h[(j + 1) * n + i + 1] * u
        return (a * (1 - v) + b * v) * 0.01


# ------------------------------------------------------------------------------------------ bots
_cache = {}
_shared = {}  # per-match: one obstacle grid / flow field per bot file, shared by every copy of it


def _share(ns, tag):
    """Copies of the same bot see identical map data, so let them share the heavy pieces: the
    obstacle grid and the flow fields (built incrementally, so shared ones just finish sooner).
    Only affects the simulator: it wraps the bot module's globals after loading it."""
    if "_load_grid" in ns:
        real = ns["_load_grid"]

        def load_grid(hello, mech, _real=real):
            k = ("grid", tag)
            if k not in _shared:
                _shared[k] = _real(hello, mech)
            return _shared[k]
        ns["_load_grid"] = load_grid
    if "FlowField" in ns:
        real_ff = ns["FlowField"]

        def flow_field(grid, key, safe_c, safe_r, lim_c, lim_r, _real=real_ff):
            k = ("ff", tag, key, round(safe_r, 2), round(lim_c[0], 1), round(lim_c[1], 1), round(lim_r, 1))
            if k not in _shared:
                _shared[k] = _real(grid, key, safe_c, safe_r, lim_c, lim_r)
            return _shared[k]
        ns["FlowField"] = flow_field


def load_bot(path):
    """Load a bot file with its own copy of the mechfight wrapper; returns (BotClass, wrapper)."""
    path = os.path.abspath(path)
    if path in _cache:
        return _cache[path]
    d = os.path.dirname(path)
    tag = "%x" % (abs(hash(path)) & 0xFFFFFF)
    spec = importlib.util.spec_from_file_location("mechfight_" + tag, os.path.join(d, "mechfight.py"))
    mf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mf)
    got = []
    mf.run = lambda cls: got.append(cls)
    mf.log = lambda *a: None
    saved = sys.modules.get("mechfight")
    sys.modules["mechfight"] = mf
    try:
        ns = {"__name__": "bot_" + tag, "__file__": path}
        exec(compile(open(path).read(), path, "exec"), ns)
        _share(ns, tag)
    finally:
        if saved is None:
            sys.modules.pop("mechfight", None)
        else:
            sys.modules["mechfight"] = saved
    _cache[path] = (got[0], mf)
    return _cache[path]


class Mech:
    def __init__(self, mid, pos, cfg, bot, mf):
        m = cfg["mech"]
        self.id, self.bot, self.mf = mid, bot, mf
        self.x, self.y, self.z = pos
        self.vx = self.vy = 0.0
        self.yaw, self.pitch = random.uniform(-math.pi, math.pi), 0.0
        self.hp = self.max_hp = float(m["hp"])
        self.energy = self.max_energy = float(m["energy"])
        g = cfg["weapons"]["gun"]
        self.gun = dict(g)
        self.ammo, self.reload_t, self.cool = int(g["mag"]), 0.0, 0.0
        self.alive, self.death_tick = True, None
        self.cubes = 0
        self.base_hp = self.hp
        self.cm = dict(m)                  # this mech's numbers after upgrades
        self.armor = 0.0
        self.vision_bonus = 0.0
        self.ups = {}                      # upgrade id -> stacks
        self.offers = []                   # pending offers: [choice ids]
        self.offer_t = None                # when the current offer appeared
        self.offer_id = 0
        self.last_spend = -9.0
        self.last_combat = -9.0
        self.step_t = 0.0
        self.seen = {}
        self.events, self.sounds = [], []
        self.cmd = {"move": [0, 0], "boost": False, "aim": [self.yaw, 0.0], "fire": [False, False], "reload": False}
        self.in_zone = True
        self.act_ms = []
        self.errors = 0


# ------------------------------------------------------------------------------------------ match
class Match:
    def __init__(self, world, hello, roster, seed, squad=None):
        """squad: None (free-for-all) or {"house": {slot: rank}, "late": s, "hunters": n, "omniscient": b}"""
        self.squad = squad
        self.w, self.rng = world, random.Random(seed)
        _shared.clear()
        random.seed(seed)
        self.cfg = hello["config"]
        self.hello = hello
        cm = self.cfg["mech"]
        self.radius, self.height = cm["radius"], cm["height"]
        self.zone_plan()
        self.mechs = []
        spawns = self.spawns(len(roster))
        for i, (path, pos) in enumerate(zip(roster, spawns)):
            cls, mf = load_bot(path)
            h = json.loads(json.dumps(hello))
            h["slot"], h["seed"] = i, self.rng.randrange(1 << 31)
            mf.draw.caps = h["config"].get("debug", {})
            try:
                bot = cls(h)
            except Exception:
                bot = None
            self.mechs.append(Mech(i, pos, self.cfg, bot, mf))
        self.bullets = []
        self.cube_list = []   # {"id", "x", "y", "z"}
        self.cube_id = 5000
        cc = self.cfg.get("cubes", {})
        self.cube_cfg = {"pickup_radius": cc.get("pickup_radius", 3.5), "hp": cc.get("hp_per_cube", 0.04),
                         "dmg": cc.get("damage_per_cube", 0.04), "cap": cc.get("stat_cap", 10),
                         "extra": cc.get("death_drop_extra", 2), "size": cc.get("size_per_cube", 0.05)}
        self.crates = self.spawn_crates(seed)
        self.tick = 0
        self.t = 0.0
        self.house = (squad or {}).get("house", {})
        self.cand_kills = 0
        self.provoked = {}  # house slot -> last time a candidate hit it
        self.final_shrink = self.phases[-1][4]

    def is_house(self, m):
        return m.id in self.house

    def hunters(self):
        sq = self.squad
        alive = sorted((m for m in self.mechs if m.alive and self.is_house(m)), key=lambda m: self.house[m.id])
        if self.t >= sq.get("late", 300):
            return {m.id for m in alive}
        k = sq.get("hunters", 1) + self.cand_kills
        return {m.id for m in alive[:k]}

    def squad_sees(self, target):
        return any(self.t - h.seen.get(target.id, -99) <= self.cfg["vision"].get("memory_s", 5)
                   for h in self.mechs if h.alive and self.is_house(h))

    # -------------------------------------------------------------------- zone
    def zone_plan(self):
        z = self.cfg["zone"]
        cx, cy = z["start_center"]
        r = z["start_radius"]
        t = 0.0
        self.phases = []
        for ph in z["phases"]:
            nr = ph["radius"]
            a, d = self.rng.uniform(-math.pi, math.pi), math.sqrt(self.rng.random()) * max(0.0, r - nr)
            nx_, ny_ = cx + math.cos(a) * d, cy + math.sin(a) * d
            # keep the next circle's center on open, in-bounds ground (like the real zone, roughly)
            for _ in range(50):
                if not self.w.blocked(nx_, ny_):
                    break
                a, d = self.rng.uniform(-math.pi, math.pi), math.sqrt(self.rng.random()) * max(0.0, r - nr)
                nx_, ny_ = cx + math.cos(a) * d, cy + math.sin(a) * d
            s, e = t + ph["hold_s"], t + ph["hold_s"] + ph["shrink_s"]
            self.phases.append(((cx, cy), r, (nx_, ny_), nr, s, e, ph["dps"]))
            cx, cy, r, t = nx_, ny_, nr, e

    def zone_obs(self, t):
        for c, r, nc, nr, s, e, dps in self.phases:
            if t < e:
                return {"center": list(c), "radius": r, "next_center": list(nc), "next_radius": nr,
                        "shrink_start": s, "shrink_end": e, "dps": dps}
        c, r, nc, nr, s, e, dps = self.phases[-1]
        return {"center": list(nc), "radius": nr, "next_center": list(nc), "next_radius": nr,
                "shrink_start": s, "shrink_end": e, "dps": dps}

    def zone_live(self, t):
        z = self.zone_obs(t)
        f = 0.0 if t <= z["shrink_start"] else min(1.0, (t - z["shrink_start"]) / max(1e-6, z["shrink_end"] - z["shrink_start"]))
        c, nc = z["center"], z["next_center"]
        return c[0] + (nc[0] - c[0]) * f, c[1] + (nc[1] - c[1]) * f, z["radius"] + (z["next_radius"] - z["radius"]) * f, z["dps"]

    def spawns(self, n):
        mc = self.cfg["match"]
        cx, cy = self.cfg["zone"]["start_center"]
        R = self.cfg["zone"]["start_radius"] * mc.get("spawn_zone_fraction", 0.8)
        sep = mc.get("spawn_min_separation", 130)
        margin = mc.get("arena_margin", 30)
        out = []
        for _ in range(n):
            for attempt in range(4000):
                a, d = self.rng.uniform(-math.pi, math.pi), math.sqrt(self.rng.random()) * R
                x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
                if not (self.w.x0 + margin < x < self.w.x1 - margin and self.w.y0 + margin < y < self.w.y1 - margin):
                    continue
                if self.w.body_blocked(x, y, self.radius + 1):
                    continue
                s = sep if attempt < 3000 else sep * 0.5
                if all(math.hypot(x - p[0], y - p[1]) >= s for p in out):
                    break
            out.append((x, y, self.w.ground(x, y)))
        return out

    # -------------------------------------------------------------------- senses
    def emit(self, kind, x, y, src):
        rng_ = self.cfg["sound"]["range"].get(kind, 0)
        noise = math.radians(self.cfg["sound"]["bearing_noise_deg"])
        for m in self.mechs:
            if not m.alive or m is src:
                continue
            d = math.hypot(x - m.x, y - m.y)
            if d <= rng_:
                b = math.atan2(y - m.y, x - m.x) + self.rng.gauss(0, noise)
                dist = "near" if d < self.cfg["sound"]["near"] else "mid" if d < self.cfg["sound"]["mid"] else "far"
                m.sounds.append({"kind": kind, "bearing": round(angdiff(b, 0), 3), "dist": dist, "age": 0.05})

    def spawn_crates(self, seed):
        """Ground crates only (the real game puts about a quarter on roofs, which a walker can't loot)."""
        cc = self.cfg.get("crates", {})
        n = int(round(cc.get("count", 36) * (1 - cc.get("roof_fraction", 0.25))))
        rng = random.Random(seed * 7 + 13)
        cx, cy = self.cfg["zone"]["start_center"]
        R = self.cfg["zone"]["start_radius"]
        out = []
        for k in range(n):
            for _ in range(500):
                a, d = rng.uniform(-math.pi, math.pi), math.sqrt(rng.random()) * R
                x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
                if self.w.x0 + 20 < x < self.w.x1 - 20 and self.w.y0 + 20 < y < self.w.y1 - 20 \
                        and not self.w.body_blocked(x, y, 2.0):
                    break
            out.append({"id": 1000 + k, "x": x, "y": y, "z": self.w.ground(x, y), "hp": float(cc.get("hp", 300)),
                        "r": cc.get("radius", 1.4), "h": cc.get("height", 2.4)})
        return out

    def queue_offer(self, m):
        ok = [u for u in self.cfg.get("upgrades", [])
              if u.get("requires") in (None, "gun") and m.ups.get(u["id"], 0) < u.get("max", 1)]
        if len(ok) >= 1:
            m.offers.append([u["id"] for u in self.rng.sample(ok, min(3, len(ok)))])

    def offer_obs(self, m):
        if not m.offers:
            return None
        if m.offer_t is None:
            m.offer_t, m.offer_id = self.t, m.offer_id + 1
        return {"id": m.offer_id, "expires": round(m.offer_t + 5.0, 2),
                "choices": [{"id": c, "name": c, "desc": ""} for c in m.offers[0]]}

    def resolve_offer(self, m, pick):
        if not m.offers:
            return
        if pick is None and (m.offer_t is None or self.t < m.offer_t + 5.0):
            return
        ch = m.offers.pop(0)
        m.offer_t = None
        uid = ch[pick] if isinstance(pick, int) and 0 <= pick < len(ch) else ch[0]
        u = next(u for u in self.cfg["upgrades"] if u["id"] == uid)
        m.ups[uid] = m.ups.get(uid, 0) + 1
        m.events.append({"type": "upgrade", "id": uid})
        for e in u["effects"]:
            grp, key = e["path"].split(".", 1)
            if grp == "mech":
                if key == "hp":
                    f = e.get("mul", 1.0)
                    m.base_hp *= f
                    m.max_hp *= f
                    m.hp *= f
                elif key == "armor":
                    m.armor += e.get("add", 0.0)
                elif key == "vision_bonus":
                    m.vision_bonus += e.get("add", 0.0)
                elif key == "energy":
                    m.max_energy += e.get("add", 0.0)
                elif key in m.cm:
                    m.cm[key] = m.cm[key] * e.get("mul", 1.0) + e.get("add", 0.0)
            elif e["path"].startswith("weapons.gun."):
                k = e["path"].split(".")[-1]
                if k in m.gun:
                    m.gun[k] = m.gun[k] * e.get("mul", 1.0) + e.get("add", 0.0)

    def rad(self, m):
        return self.radius * (1 + self.cube_cfg["size"] * m.cubes)

    def hgt(self, m):
        return self.height * (1 + self.cube_cfg["size"] * m.cubes)

    def drop_cubes(self, m):
        n = m.cubes + self.cube_cfg["extra"]
        for k in range(n):
            a = self.rng.uniform(-math.pi, math.pi)
            rr = self.rng.uniform(0.5, 3.0)
            x, y = m.x + rr * math.cos(a), m.y + rr * math.sin(a)
            if self.w.blocked(x, y):
                x, y = m.x, m.y
            self.cube_id += 1
            self.cube_list.append({"id": self.cube_id, "x": x, "y": y, "z": self.w.ground(x, y)})

    def collect_cubes(self):
        pr = self.cube_cfg["pickup_radius"]
        keep = []
        for c in self.cube_list:
            best, bd = None, 1e9
            for m in self.mechs:
                if m.alive:
                    d = math.hypot(m.x - c["x"], m.y - c["y"])
                    if d <= pr and abs(m.z - c["z"]) <= 4 and d < bd:
                        best, bd = m, d
            if best is None:
                keep.append(c)
                continue
            best.cubes += 1
            mult = 1 + self.cube_cfg["hp"] * min(best.cubes, self.cube_cfg["cap"])
            new_max = best.base_hp * mult
            best.hp += new_max - best.max_hp
            best.max_hp = new_max
            best.events.append({"type": "pickup", "cubes": best.cubes})
            if best.cubes in self.cfg.get("cubes", {}).get("upgrade_thresholds", ()):
                self.queue_offer(best)
        self.cube_list = keep

    def sees(self, o, x, y):
        v = self.cfg["vision"]
        d = math.hypot(x - o.x, y - o.y)
        if d > v["range"] + o.vision_bonus:
            return False
        if d > v["near_range"] and abs(angdiff(math.atan2(y - o.y, x - o.x), o.yaw)) > math.radians(v["fov_deg"]) / 2:
            return False
        return self.w.los(o.x, o.y, x, y)

    def obs_for(self, o, alive_n, zone, hunters=None):
        mechs = []
        house_o = self.squad is not None and self.is_house(o)
        for m in self.mechs:
            if m is o or not m.alive:
                continue
            if house_o and self.is_house(m):
                continue  # the squad never targets its own
            if self.sees(o, m.x, m.y):
                o.seen[m.id] = self.t
            if house_o:
                if o.id in hunters:
                    known = self.squad.get("omniscient") or self.squad_sees(m)
                elif self.squad.get("passive"):
                    known = False  # non-hunters never engage
                else:
                    known = self.t - self.provoked.get(o.id, -99) < 10 and self.t - o.seen.get(m.id, -99) <= 5
                if known:
                    mechs.append({"id": m.id, "kind": "mech", "pos": [m.x, m.y, m.z], "vel": [m.vx, m.vy, 0.0],
                                  "aim": [m.yaw, m.pitch], "hp": m.hp, "max_hp": m.max_hp, "cubes": m.cubes,
                                  "weapons": ["gun"], "charging": False})
                continue
            if self.t - o.seen.get(m.id, -99) <= self.cfg["vision"].get("memory_s", 5):
                mechs.append({"id": m.id, "kind": "mech", "pos": [m.x, m.y, m.z], "vel": [m.vx, m.vy, 0.0],
                              "aim": [m.yaw, m.pitch], "hp": m.hp, "max_hp": m.max_hp, "cubes": m.cubes,
                              "weapons": ["gun"], "charging": False})
        projs = []
        for b in self.bullets:
            if b["owner"] is o or (house_o and self.is_house(b["owner"])):
                continue
            if self.sees(o, b["x"], b["y"]):
                projs.append({"id": b["id"], "kind": "gun", "pos": [b["x"], b["y"], b["z"]], "vel": [b["vx"], b["vy"], b["vz"]]})
        cx, cy, r, _ = self.zone_live(self.t)
        st = dict(o.cm)
        obs = {
            "type": "obs", "tick": self.tick, "t": round(self.t, 2), "alive": alive_n,
            "self": {"id": o.id, "pos": [o.x, o.y, o.z], "vel": [o.vx, o.vy, 0.0], "aim": [o.yaw, o.pitch],
                     "hp": o.hp, "max_hp": o.max_hp, "energy": o.energy, "max_energy": o.max_energy,
                     "grounded": True, "cubes": o.cubes, "upgrades": [k for k, n in o.ups.items() for _ in range(n)], "in_zone": o.in_zone,
                     "weapons": [{"kind": "gun", "cooldown": max(0.0, o.cool), "ammo": o.ammo,
                                  "reload": max(0.0, o.reload_t), "stats": dict(o.gun)}, None],
                     "stats": st},
            "mechs": mechs, "projectiles": projs, "crates": [{"id": c["id"], "pos": [c["x"], c["y"], c["z"]], "hp": c["hp"]} for c in self.crates
                                                  if self.sees(o, c["x"], c["y"])],
            "cubes": [{"id": c["id"], "pos": [c["x"], c["y"], c["z"]]} for c in self.cube_list
                                                 if self.sees(o, c["x"], c["y"])], "pickups": [],
            "sounds": o.sounds, "beams": [], "events": o.events, "drops": [], "zone": zone, "offer": self.offer_obs(o),
        }
        o.sounds, o.events = [], []
        return obs

    # -------------------------------------------------------------------- step
    def decide(self):
        alive_n = sum(m.alive for m in self.mechs)
        zone = self.zone_obs(self.t)
        hunters = self.hunters() if self.squad is not None else None
        if self.squad is not None:  # shared vision: update every house bot's sightings first
            for h in self.mechs:
                if h.alive and self.is_house(h):
                    for m in self.mechs:
                        if m.alive and not self.is_house(m) and self.sees(h, m.x, m.y):
                            h.seen[m.id] = self.t
        for m in self.mechs:
            if not m.alive or m.bot is None:
                continue
            obs = self.obs_for(m, alive_n, json.loads(json.dumps(zone)), hunters)
            m.mf.draw.clear()
            s = time.perf_counter()
            try:
                a = m.bot.act(obs) or {}
            except Exception:
                m.errors += 1
                a = {k: m.cmd[k] for k in ("move", "boost", "aim")}
            m.act_ms.append((time.perf_counter() - s) * 1000)
            mv = a.get("move", [0, 0])
            self.resolve_offer(m, a.get("pick"))
            m.cmd = {"move": [float(mv[0]), float(mv[1])], "boost": bool(a.get("boost", False)),
                     "aim": a.get("aim", m.cmd["aim"]), "fire": list(a.get("fire", [False, False])),
                     "reload": bool(a.get("reload", False))}

    def damage(self, victim, amount, by, bearing, weapon, rear=False):
        if not victim.alive:
            return
        if self.squad is not None and by is not None:
            if self.is_house(by) and self.is_house(victim):
                return  # no friendly fire in the squad
            if self.is_house(victim):
                self.provoked[victim.id] = self.t
        if weapon != "zone":
            amount *= max(0.0, 1.0 - victim.armor)
        victim.hp -= amount
        victim.last_combat = self.t
        if by is not None:
            victim.hit_log = getattr(victim, "hit_log", []) + [(self.t, by.id)]
        ev = {"type": "damaged", "amount": round(amount, 1), "weapon": weapon, "bearing": bearing,
              "by": by.id if by else None}
        if rear:
            ev["rear"] = True
        victim.events.append(ev)
        if by is not None:
            by.last_combat = self.t
            by.events.append({"type": "hit", "target": victim.id, "amount": round(amount, 1), "weapon": weapon})
        if victim.hp <= 0:
            victim.alive, victim.death_tick = False, self.tick
            self.emit("death", victim.x, victim.y, victim)
            self.drop_cubes(victim)
            if by is not None:
                by.events.append({"type": "kill", "target": victim.id})
                by.kill_ts = getattr(by, "kill_ts", []) + [round(self.t, 1)]
                if self.squad is not None and not self.is_house(by) and self.is_house(victim):
                    self.cand_kills += 1

    def physics(self):
        for m in self.mechs:
            if not m.alive:
                continue
            cm = m.cm
            # aim slew
            ty, tp = float(m.cmd["aim"][0]), max(cm["min_pitch"], min(cm["max_pitch"], float(m.cmd["aim"][1])))
            dy = angdiff(ty, m.yaw)
            m.yaw = angdiff(m.yaw + max(-cm["turn_rate"] * DT, min(cm["turn_rate"] * DT, dy)), 0)
            m.pitch += max(-cm["pitch_rate"] * DT, min(cm["pitch_rate"] * DT, tp - m.pitch))
            # legs
            mx, my = m.cmd["move"]
            L = math.hypot(mx, my)
            if L > 1:
                mx, my, L = mx / L, my / L, 1.0
            boosting = m.cmd["boost"] and L > 0.05 and m.energy > 0
            speed = cm["boost_speed"] if boosting else cm["walk_speed"]
            if boosting:
                m.energy = max(0.0, m.energy - cm["boost_drain"] * DT)
                m.last_spend = self.t
            elif self.t - m.last_spend >= cm["energy_regen_delay"]:
                m.energy = min(m.max_energy, m.energy + cm["energy_regen"] * DT)
            tvx, tvy = mx * speed, my * speed
            ddx, ddy = tvx - m.vx, tvy - m.vy
            dd = math.hypot(ddx, ddy)
            acc = cm["ground_accel"] * DT
            if dd > acc:
                ddx, ddy = ddx / dd * acc, ddy / dd * acc
            m.vx += ddx
            m.vy += ddy
            nx_, ny_ = m.x + m.vx * DT, m.y + m.vy * DT
            r = self.rad(m)
            if not self.w.body_blocked(nx_, ny_, r):
                m.x, m.y = nx_, ny_
            elif not self.w.body_blocked(nx_, m.y, r):
                m.x, m.vy = nx_, 0.0
            elif not self.w.body_blocked(m.x, ny_, r):
                m.y, m.vx = ny_, 0.0
            else:
                m.vx = m.vy = 0.0
            m.z = self.w.ground(m.x, m.y)
            # footsteps
            sp = math.hypot(m.vx, m.vy)
            if sp > self.cfg["sound"]["step_speed"]:
                m.step_t += DT
                if m.step_t >= self.cfg["sound"]["step_every"]:
                    m.step_t = 0.0
                    self.emit("boost" if boosting else "step", m.x, m.y, m)
            # gun
            g = m.gun
            m.cool -= DT
            if m.reload_t > 0:
                m.reload_t -= DT
                if m.reload_t <= 0:
                    m.ammo = int(g["mag"])
            elif m.cmd["reload"] and m.ammo < g["mag"]:
                m.reload_t = g["reload"]
                self.emit("reload", m.x, m.y, m)
            if m.cmd["fire"] and m.cmd["fire"][0] and m.cool <= 0 and m.reload_t <= 0 and m.ammo > 0:
                sp_ = math.radians(g["spread_deg"])
                yaw, pit = m.yaw + self.rng.gauss(0, sp_), m.pitch + self.rng.gauss(0, sp_)
                dx, dy_, dz = math.cos(pit) * math.cos(yaw), math.cos(pit) * math.sin(yaw), math.sin(pit)
                ox, oy, oz = m.x + dx * (r + 0.5), m.y + dy_ * (r + 0.5), m.z + cm["muzzle_height"] + dz * (r + 0.5)
                # aim stats: band by distance to the nearest live opponent (4 = none within gun range)
                opp_ = [(math.hypot(o.x - m.x, o.y - m.y), o) for o in self.mechs if o.alive and o is not m
                        and not (self.squad is not None and self.is_house(m) and self.is_house(o))]
                dn, tgt_ = min(opp_, key=lambda q: q[0], default=(1e9, None))
                band = 0 if dn < 50 else 1 if dn < 100 else 2 if dn < 150 else 3 if dn < 230 else 4
                st_ = m.__dict__.setdefault("aimst", {"shots": [0] * 5, "hits": [0] * 5, "walls": [0] * 5, "crates": [0] * 5, "blocked": [0] * 5})
                st_["shots"][band] += 1
                self.bullets.append({"id": self.tick * 100 + m.id, "owner": m, "x": ox, "y": oy, "z": oz, "band": band, "dn": dn, "trav": 0.0, "tgt": tgt_, "best": (1e9, 0.0, 0.0), "tv0": ((tgt_.vx, tgt_.vy) if tgt_ is not None else (0.0, 0.0)),
                                     "vx": dx * g["speed"], "vy": dy_ * g["speed"], "vz": dz * g["speed"], "left": g["range"]})
                m.ammo -= 1
                m.cool = g["cooldown"]
                if m.ammo == 0:
                    m.reload_t = g["reload"]
                self.emit("gun", m.x, m.y, m)
        # bullets
        keep = []
        for b in self.bullets:
            sx, sy, sz = b["x"], b["y"], b["z"]
            ex, ey, ez = sx + b["vx"] * DT, sy + b["vy"] * DT, sz + b["vz"] * DT
            seg = math.hypot(ex - sx, ey - sy)
            hit = None
            best = 1e9
            for m in self.mechs:
                if not m.alive or m is b["owner"]:
                    continue
                if self.squad is not None and self.is_house(b["owner"]) and self.is_house(m):
                    continue
                px, py = m.x - sx, m.y - sy
                L2 = (ex - sx) ** 2 + (ey - sy) ** 2
                f = max(0.0, min(1.0, (px * (ex - sx) + py * (ey - sy)) / L2)) if L2 > 0 else 0.0
                cx, cy, cz = sx + (ex - sx) * f, sy + (ey - sy) * f, sz + (ez - sz) * f
                if math.hypot(m.x - cx, m.y - cy) < self.rad(m) + 0.3 and m.z - 0.3 <= cz <= m.z + self.hgt(m) + 0.3 and f < best:
                    hit, best = m, f
            tg = b.get("tgt")
            if tg is not None and tg.alive:
                px, py = tg.x - sx, tg.y - sy
                L2 = (ex - sx) ** 2 + (ey - sy) ** 2
                f = max(0.0, min(1.0, (px * (ex - sx) + py * (ey - sy)) / L2)) if L2 > 0 else 0.0
                cx, cy, cz = sx + (ex - sx) * f, sy + (ey - sy) * f, sz + (ez - sz) * f
                dd = math.hypot(cx - tg.x, cy - tg.y)
                if dd < b["best"][0]:
                    v0x, v0y = b["tv0"]  # the target's velocity when we fired
                    sp = math.hypot(v0x, v0y)
                    along = ((cx - tg.x) * v0x + (cy - tg.y) * v0y) / sp if sp > 1.0 else 0.0
                    rev = (v0x * tg.vx + v0y * tg.vy) < 0  # it turned back since
                    b["best"] = (dd, along, cz - (tg.z + self.hgt(tg) / 2), rev, sp)
            crate_hit = None
            for c in self.crates:
                px, py = c["x"] - sx, c["y"] - sy
                L2 = (ex - sx) ** 2 + (ey - sy) ** 2
                f = max(0.0, min(1.0, (px * (ex - sx) + py * (ey - sy)) / L2)) if L2 > 0 else 0.0
                cx, cy, cz = sx + (ex - sx) * f, sy + (ey - sy) * f, sz + (ez - sz) * f
                if math.hypot(c["x"] - cx, c["y"] - cy) < c["r"] and c["z"] - 0.2 <= cz <= c["z"] + c["h"] and f < best:
                    hit, best, crate_hit = None, f, c
            # walls: sample the segment up to the hit point
            stop = best if (hit or crate_hit) else 1.0
            wall = False
            n = max(1, int(seg * stop / 2.0))
            for k in range(1, n + 1):
                f = stop * k / n
                if self.w.blocked(sx + (ex - sx) * f, sy + (ey - sy) * f):
                    wall = True
                    break
            ast_ = b["owner"].__dict__.get("aimst")
            def _rec_miss(b=b, ast_=ast_):
                if ast_ is not None and b["band"] == 1 and b["best"][0] < 12.0:
                    ast_.setdefault("miss_along", []).append(round(b["best"][1], 1))
                    ast_.setdefault("miss_z", []).append(round(b["best"][2], 1))
                    ast_.setdefault("miss_rev", []).append(bool(b["best"][3]) if len(b["best"]) > 3 else False)
                    ast_.setdefault("miss_sp", []).append(round(b["best"][4], 1) if len(b["best"]) > 4 else 0.0)
            if wall:
                _rec_miss()
                if ast_:
                    ast_["walls"][b["band"]] += 1
                    if b["trav"] + seg * f < b["dn"] - 4.0:  # stopped short of the target: fired into cover
                        ast_["blocked"][b["band"]] += 1
                continue
            if crate_hit is not None:
                if ast_: ast_["crates"][b["band"]] += 1
                dmg = b["owner"].gun["damage"] * (1 + self.cube_cfg["dmg"] * min(b["owner"].cubes, self.cube_cfg["cap"]))
                crate_hit["hp"] -= dmg
                b["owner"].events.append({"type": "hit", "target": crate_hit["id"], "amount": round(dmg, 1), "weapon": "gun"})
                if crate_hit["hp"] <= 0:
                    self.crates.remove(crate_hit)
                    self.cube_id += 1
                    self.cube_list.append({"id": self.cube_id, "x": crate_hit["x"], "y": crate_hit["y"], "z": crate_hit["z"]})
                continue
            if hit is not None:
                if ast_: ast_["hits"][b["band"]] += 1
                src = math.atan2(-b["vy"], -b["vx"])  # direction the bullet came from
                rear = abs(angdiff(src, hit.yaw)) > math.radians(self.cfg["mech"]["front_arc_deg"]) / 2
                dmg = b["owner"].gun["damage"] * (self.cfg["mech"]["rear_mult"] if rear else 1.0)
                dmg *= 1 + self.cube_cfg["dmg"] * min(b["owner"].cubes, self.cube_cfg["cap"])
                self.damage(hit, dmg, b["owner"], round(src, 3), "gun", rear)
                continue
            b["left"] -= seg
            b["trav"] = b.get("trav", 0.0) + seg
            if b["left"] <= 0 or ez < self.w.ground(ex, ey) - 0.5:
                _rec_miss()
                continue
            b["x"], b["y"], b["z"] = ex, ey, ez
            keep.append(b)
        self.bullets = keep
        self.collect_cubes()
        # zone and regen
        cx, cy, r, dps = self.zone_live(self.t)
        for m in self.mechs:
            if not m.alive:
                continue
            m.in_zone = math.hypot(m.x - cx, m.y - cy) <= r
            if not m.in_zone and self.squad is not None and self.is_house(m) and self.t < self.final_shrink:
                continue
            if not m.in_zone:
                self.damage(m, dps * DT, None, None, "zone")
            elif self.t - m.last_combat >= m.cm["regen_delay"]:
                m.hp = min(m.max_hp, m.hp + m.cm["regen_per_s"] * DT)

    def run(self):
        dur = self.cfg["match"]["duration_s"]
        every = self.cfg["match"].get("decide_every", 2)
        while True:
            alive = [m for m in self.mechs if m.alive]
            if len(alive) <= 1 or self.t >= dur:
                break
            if self.tick % every == 0:
                self.decide()
            self.physics()
            self.tick += 1
            self.t = self.tick * DT
        return self.places()

    def places(self):
        n = len(self.mechs)
        place = {}
        survivors = sorted((m for m in self.mechs if m.alive), key=lambda m: -m.hp)
        for i, m in enumerate(survivors):
            place[m.id] = i + 1
        dead = sorted((m for m in self.mechs if not m.alive), key=lambda m: -m.death_tick)
        alive_before = len(survivors)
        i = 0
        while i < len(dead):
            j = i
            while j < len(dead) and dead[j].death_tick == dead[i].death_tick:
                j += 1
            group = dead[i:j]
            alive_before += len(group)
            for m in group:
                place[m.id] = alive_before
            i = j
        return place


# ------------------------------------------------------------------------------------------ driver
TIER_COUNTS = (4, 4, 4, 3)


def one_match(args):
    kit, cand, opps, seed, copies = args[:5]
    squad_opts = args[5] if len(args) > 5 else None
    world = World(kit)
    rng = random.Random(seed)
    hello = json.loads(gzip.open(os.path.join(kit, "check", "stream.jsonl.gz"), "rt").readline())
    hello["map"]["dir"] = os.path.join(kit, "arena")
    n = hello["config"]["match"]["mechs"]
    slots = rng.sample(range(n), copies)
    squad = None
    if squad_opts:
        # opps = one bot file per tier (easy, medium, hard, expert); house rank = weakness order
        tiers = [opps[min(i, len(opps) - 1)] for i, c in enumerate(TIER_COUNTS) for _ in range(c)]
        others = [i for i in range(n) if i not in slots]
        rng.shuffle(others)
        roster, house = [None] * n, {}
        for rank, (i, path) in enumerate(zip(others, tiers)):
            roster[i], house[i] = path, rank
        for i in slots:
            roster[i] = cand
        squad = dict(squad_opts, house=house)
    else:
        roster = [cand if i in slots else opps[i % len(opps)] for i in range(n)]
    m = Match(world, hello, roster, seed, squad)
    places = m.run()
    out = []
    for i in slots:
        me = m.mechs[i]
        out.append({"place": places[i], "kills": m.cand_kills, "cubes": me.cubes, "ups": dict(me.ups), "death_t": None if me.alive else round(me.death_tick * DT, 1),
                    "zone_death": (not me.alive) and me.events[-1:] and me.events[-1].get("weapon") == "zone",
                    "max_ms": max(me.act_ms) if me.act_ms else 0, "errors": me.errors,
                    "kill_ts": getattr(me, "kill_ts", []),
                    "attackers10": len({b for (tt, b) in getattr(me, "hit_log", []) if me.death_tick is not None and me.death_tick * DT - tt < 10}),
                    "hunters_alive": sum(1 for x in m.mechs if x.alive and x.id != me.id),
                    "aimst": me.__dict__.get("aimst"),
                    "house_aimst": [x.__dict__.get("aimst") for x in m.mechs if x is not me]})
    return out


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--kit", default=os.path.join(here, "..", "..", "mechfight-kit"))
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--opponents", default="", help="comma-separated bot files, cycled over the other slots")
    ap.add_argument("--matches", type=int, default=48)
    ap.add_argument("--copies", type=int, default=1, help="candidate copies per match")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--tiers", help="squad mode: comma-separated bot files for easy,medium,hard,expert house bots")
    ap.add_argument("--late", type=float, default=300, help="squad: time after which every house bot hunts")
    ap.add_argument("--hunters", type=int, default=1, help="squad: hunters at the start")
    ap.add_argument("--omniscient", action="store_true", help="squad: hunters always know where you are")
    ap.add_argument("--passive", action="store_true", help="squad: non-hunters never fight back")
    a = ap.parse_args()
    kit = os.path.abspath(a.kit)
    sq = None
    if a.tiers:
        opps = [os.path.abspath(p) for p in a.tiers.split(",")]
        sq = {"late": a.late, "hunters": a.hunters, "omniscient": a.omniscient, "passive": a.passive}
    else:
        opps = [os.path.abspath(p) for p in a.opponents.split(",")]
    jobs = [(kit, os.path.abspath(a.candidate), opps, a.seed * 100003 + i, a.copies, sq) for i in range(a.matches)]
    t0 = time.time()
    with Pool(min(a.jobs, len(jobs))) as pool:
        res = [r for rs in pool.map(one_match, jobs) for r in rs]
    places = [r["place"] for r in res]
    scores = [16 - p for p in places]
    deaths = [r["death_t"] for r in res if r["death_t"] is not None]
    print(f"candidate: {a.candidate}")
    print(f"samples: {len(res)}  mean score: {statistics.mean(scores):.2f}  (+/- {statistics.stdev(scores) / math.sqrt(len(scores)):.2f} s.e.)")
    print(f"mean place: {statistics.mean(places):.1f}  wins: {sum(p == 1 for p in places)}  top-4: {sum(p <= 4 for p in places)}"
          + (f"  mean kills: {statistics.mean(r['kills'] for r in res):.2f}" if a.tiers else ""))
    if deaths:
        print(f"died in {len(deaths)}/{len(res)}  median death time: {statistics.median(deaths):.0f} s  "
              f"zone deaths: {sum(bool(r['zone_death']) for r in res)}")
    print(f"worst act() time: {max(r['max_ms'] for r in res):.1f} ms  errors: {sum(r['errors'] for r in res)}  "
          f"wall time: {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
