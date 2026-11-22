"""Speed-first bot built on the kit's example (protocol.md mechfight/1).

Movement:
- Zone: interpolates the live circle and heads early for the nearest safe spot in the next circle.
- Routing: 2 m obstacle grid from the map's prisms + flow fields (multi-source BFS, ~10 ms/tick)
  for the shortest walkable route to the zone's safe disk and to supply drops.
- Steering + stuck detours as a local safety net; hops and jets when it keeps getting stuck.
- Dodge: bullets on a collision course, mortar landing points, charging lasers (seen or heard),
  lightning carriers, NPC drones; unpredictable strafing against seen or heard shooters.
- Range control per weapon, backing off when low on HP; turns to face unseen attackers.
- Boost when the zone would catch us, for urgent dodges, and to win supply-drop races.

Weapons: gun with aim-ahead, mortar lobbed by ballistic pitch (high arc over buildings), laser
charged only when it's safe to slow down, lightning fired whenever the cone holds a target.
Loot ranked lightning > laser > mortar with swaps (lootflip; mortar first without it); speed/energy upgrades first; early reloads.

Standard library only; uses the kit's mechfight.py wrapper.
"""
import json
import math
import os
import sys
import random
import time
from array import array
from collections import deque

import mechfight as mf

CELL = 2.0  # obstacle grid resolution, meters
FIELD_SLICE_S = 0.010  # wall time per tick spent building the zone flow field
NB8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

# Behaviour switches. In a real match nothing sets SPEEDY_OFF, so the tuned default below applies:
# the cautious behaviours (hold fire, never chase, hide, cover, flee when outnumbered) cost kills in
# the practice format, where placement is decided by how many house bots you take down. The local
# simulator (sim/) sets SPEEDY_OFF to measure each switch on its own.
_OFF = set(os.environ.get("SPEEDY_OFF", "").split(","))
if "SPEEDY_OFF" not in os.environ:
    _OFF = {"discipline", "nochase", "cover", "outnumbered", "hide", "regroup", "focus", "strafe2", "uptank", "lootfar", "widefield", "terrain", "inflate", "hunt2", "roof", "arcsave", "lootfar2", "aimlat", "aimavg", "lead50", "lead70", "lead85", "peekreload", "tol2", "tol4", "tol28", "farhold", "aimsize", "upservo", "dodge25", "holdlead", "topup", "tol36", "tol6", "tol5", "gatehv", "gatehv2", "laserblend", "reloadduck", "dronego2", "lead110", "close3", "sw12", "sw05", "hunt", "rc30", "laser160", "laser60", "retreat20", "retreat45", "late5", "light22", "light40", "explore2", "nodrop"}


def flag(name):
    return name not in _OFF


def _clip_back(vx, vy, gx, gy):
    """Remove the part of (vx, vy) that points against the unit goal direction (gx, gy)."""
    d = vx * gx + vy * gy
    return (vx - d * gx, vy - d * gy) if d < 0 else (vx, vy)


# --------------------------------------------------------------------------------------------
# small vector helpers (2D unless stated)
def _norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-9 else (0.0, 0.0)


def _rot(x, y, a):
    c, s = math.cos(a), math.sin(a)
    return (x * c - y * s, x * s + y * c)


def _angdiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


# --------------------------------------------------------------------------------------------
# weapons helpers (protocol.md §5, §7)
LOOT_RANK = {"mortar": 3, "lightning": 2, "laser": 1, "gun": 0}  # laser last: charging halves speed
# lootflip: by damage per second lightning (240, no aim) > laser (131, hitscan) > mortar (~77 on a direct hit)
LOOT_FLIP = {"lightning": 3, "laser": 2, "mortar": 1, "gun": 0}
# laserfirst: the laser is hitscan with no spread out to 280 m and 315 damage a shot (seven gun hits)
LOOT_LASER = {"laser": 3, "lightning": 2, "mortar": 1, "gun": 0}
UPGRADE_PREF = ["servos", "jets", "armor", "capacitor", "nanites", "reactor", "gyros",
                "gun_velocity", "gun_rate", "mortar_velocity", "lightning_range", "plating"]
_WEAPON_UPS = ["mortar_reload", "mortar_velocity", "mortar_splash", "lightning_efficiency", "lightning_range",
               "lightning_chain", "laser_charge", "laser_damage", "laser_pierce"]
UP_POWER = ["gun_damage", "gun_rate", "armor", "plating", "nanites", "gun_mag", "servos", "gun_velocity",
            "gyros", "jets", "capacitor", "reactor", "sensors"] + _WEAPON_UPS
UP_TANK = ["armor", "plating", "nanites", "gun_damage", "gun_rate", "servos", "gun_mag", "gun_velocity",
           "gyros", "jets", "capacitor", "reactor", "sensors"] + _WEAPON_UPS


def _lead(me, tgt, speed):
    """[yaw, pitch, dist] from our muzzle to where tgt's body centre will be when the shot arrives."""
    mx, my, mz = me["pos"]
    mz += me.get("stats", {}).get("muzzle_height", 7)
    tx, ty, tz = tgt["pos"]
    tz += 4.5 * (1.0 + 0.05 * tgt.get("cubes", 0) if flag("aimsize") else 1.0)
    vx, vy, vz = tgt["vel"]
    t = 0.0
    px, py, pz = tx, ty, tz
    d = 0.0
    for _ in range(3):
        px, py, pz = tx + vx * t, ty + vy * t, tz + vz * t
        d = math.dist((mx, my, mz), (px, py, pz))
        t = d / speed
    return math.atan2(py - my, px - mx), math.atan2(pz - mz, math.hypot(px - mx, py - my)), d


def _aimed(me, yaw, pitch, dist, tol_m):
    """Is our *actual* (slewed) torso aim within tol_m metres of the wanted line at that range?"""
    err = max(abs(_angdiff(me["aim"][0], yaw)), abs(me["aim"][1] - pitch))
    return err * max(dist, 1.0) < tol_m


def _aimed_hv(me, yaw, pitch, dist, tol_h, tol_v):
    """Like _aimed, with separate side-to-side and up-down tolerances: a mech is a 9 m tall,
    5 m wide cylinder, so the shot can be off further vertically and still hit."""
    d = max(dist, 1.0)
    return abs(_angdiff(me["aim"][0], yaw)) * d < tol_h and abs(me["aim"][1] - pitch) * d < tol_v


def _mortar_pitch(R, h, v, g, high):
    """Launch pitch that lands a shell at horizontal range R, height difference h (None = can't)."""
    disc = v ** 4 - g * (g * R * R + 2 * h * v * v)
    if disc < 0 or R < 1e-6:
        return None
    r = math.sqrt(disc)
    return math.atan((v * v + (r if high else -r)) / (g * R))


# --------------------------------------------------------------------------------------------
class ObstacleGrid:
    """Coarse occupancy grid of the map's solid prisms. Each cell keeps the (base, top) height
    spans that cover it, so the same cell can be a wall at street level and floor on a roof."""

    def __init__(self, world, step_up, height, terrain=None):
        b = world["bounds"]
        self.terrain = terrain  # (x0, y0, step, nx, ny, heights in cm) or None
        self.x0, self.y0 = b["minX"], b["minY"]
        self.x1, self.y1 = b["maxX"], b["maxY"]
        self.nx = int((self.x1 - self.x0) / CELL) + 1
        self.ny = int((self.y1 - self.y0) / CELL) + 1
        self.step_up, self.height = step_up, height
        self.cells = {}
        # street-level planning mask: buildings and stadium are walls, bridges are walkable
        self.solid = bytearray(self.nx * self.ny)
        for p in world.get("prisms", []):
            self._fill(p)
        for i in range(self.nx):
            self.solid[i] = self.solid[(self.ny - 1) * self.nx + i] = 1
        for j in range(self.ny):
            self.solid[j * self.nx] = self.solid[j * self.nx + self.nx - 1] = 1

    def cell(self, x, y):
        i, j = int((x - self.x0) / CELL), int((y - self.y0) / CELL)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return j * self.nx + i
        return None

    def center(self, k):
        j, i = divmod(k, self.nx)
        return self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL

    def walk_mask(self):
        """Solid mask grown by one cell, so paths keep our 2.5 m radius off walls and never squeeze
        through gaps narrower than about 6 m (we're 5 m wide). Built once, on first use."""
        m = getattr(self, "_walk", None)
        if m is None:
            nx, src = self.nx, self.solid
            m = bytearray(src)
            for k in range(nx + 1, len(src) - nx - 1):
                if src[k]:
                    for d in (-nx - 1, -nx, -nx + 1, -1, 1, nx - 1, nx, nx + 1):
                        m[k + d] = 1
            self._walk = m
        return m

    def ground(self, x, y):
        """Terrain height at (x, y), bilinear; 0 without terrain data."""
        if self.terrain is None:
            return 0.0
        tx0, ty0, st, tnx, tny, h = self.terrain
        fx, fy = (x - tx0) / st, (y - ty0) / st
        i, j = int(fx), int(fy)
        if not (0 <= i < tnx - 1 and 0 <= j < tny - 1):
            return 0.0
        u, v = fx - i, fy - j
        a = h[j * tnx + i] * (1 - u) + h[j * tnx + i + 1] * u
        c = h[(j + 1) * tnx + i] * (1 - u) + h[(j + 1) * tnx + i + 1] * u
        return (a * (1 - v) + c * v) * 0.01

    def _fill(self, p):
        span = (float(p["base"]), float(p["top"]))
        solid = p.get("kind") != "bridge" and span[1] - span[0] > self.step_up
        rings = [p["ring"]] + list(p.get("holes") or [])
        edges = []
        ymin, ymax = 1e18, -1e18
        for r in rings:
            n = len(r) // 2
            for i in range(n):
                ax, ay = r[2 * i], r[2 * i + 1]
                bx, by = r[2 * ((i + 1) % n)], r[2 * ((i + 1) % n) + 1]
                if ay != by:
                    edges.append((ax, ay, bx, by))
                ymin, ymax = min(ymin, ay), max(ymax, ay)
        if not edges:
            return
        j0 = max(0, int((ymin - self.y0) / CELL))
        j1 = min(self.ny - 1, int((ymax - self.y0) / CELL) + 1)
        for j in range(j0, j1 + 1):
            yc = self.y0 + (j + 0.5) * CELL
            xs = []
            for ax, ay, bx, by in edges:  # even-odd scanline: holes cancel out automatically
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                # cells whose center is inside, plus the boundary cells (walls are thin)
                i0 = max(0, int((xs[k] - self.x0) / CELL))
                i1 = min(self.nx - 1, int((xs[k + 1] - self.x0) / CELL))
                for i in range(i0, i1 + 1):
                    self.cells.setdefault(j * self.nx + i, []).append(span)
                    if solid:
                        if self.terrain is not None:  # buried under the ground or overhead: not a wall
                            gz = self.ground(self.x0 + (i + 0.5) * CELL, yc)
                            if span[1] <= gz + self.step_up or span[0] >= gz + self.height:
                                continue
                        self.solid[j * self.nx + i] = 1

    def shot_clear(self, x, y, zb, yaw, pitch, reach):
        """Does a bullet leaving (x, y) at height zb along (yaw, pitch) get `reach` metres without
        meeting a building? Checks every metre against each cell's solid height spans."""
        ca, sa, tp = math.cos(yaw), math.sin(yaw), math.tan(pitch)
        d = 1.0
        while d <= reach:
            px, py = x + ca * d, y + sa * d
            if not (self.x0 + 1 < px < self.x1 - 1 and self.y0 + 1 < py < self.y1 - 1):
                return False
            spans = self.cells.get(int((py - self.y0) / CELL) * self.nx + int((px - self.x0) / CELL))
            if spans:
                h = zb + tp * d
                for base, top in spans:
                    if base < h < top:
                        return False
            d += 1.0
        return True

    def blocked(self, x, y, z):
        """Would a mech with feet at height z be unable to stand at (x, y)?"""
        if not (self.x0 + 1 < x < self.x1 - 1 and self.y0 + 1 < y < self.y1 - 1):
            return True  # map edge is a wall
        spans = self.cells.get(int((y - self.y0) / CELL) * self.nx + int((x - self.x0) / CELL))
        if not spans:
            return False
        for base, top in spans:
            if top > z + self.step_up and base < z + self.height:
                return True
        return False

    def los(self, ax, ay, bx, by, step=2.0):
        """Street-level line of sight: no solid cell between (ax, ay) and (bx, by). Walks from b
        toward a, since a spot hidden behind a wall usually has that wall right next to it."""
        dx, dy = ax - bx, ay - by
        n = int(math.hypot(dx, dy) / step)
        sol, nx_, x0, y0 = self.solid, self.nx, self.x0, self.y0
        for k in range(1, n):
            f = k / n
            px, py = bx + dx * f, by + dy * f
            i, j = int((px - x0) / CELL), int((py - y0) / CELL)
            if 0 <= i < self.nx and 0 <= j < self.ny and sol[j * nx_ + i]:
                return False
        return True

    def clear_dist(self, x, y, z, dx, dy, reach, radius):
        """How far (up to `reach`) the body can travel along unit (dx, dy) before hitting a cell."""
        px, py = -dy * radius, dx * radius
        d = CELL * 0.75
        while d <= reach:
            cx, cy = x + dx * d, y + dy * d
            if self.blocked(cx, cy, z) or self.blocked(cx + px, cy + py, z) or self.blocked(cx - px, cy - py, z):
                return d - CELL * 0.75
            d += CELL * 0.75
        return reach


def _pip(px, py, ring):
    """Point in polygon (flat [x0, y0, x1, y1, ...] ring), even-odd rule."""
    n, inside = len(ring) // 2, False
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _find_roofs(world, g):
    """Flat building roofs we can jet onto: (cx, cy, top, ring, inner) with (cx, cy) a point well inside
    the roof and `inner` its distance to the nearest edge."""
    roofs = []
    for p in world.get("prisms", []):
        if p.get("kind") != "building" or p.get("holes"):
            continue
        ring = p["ring"]
        n = len(ring) // 2
        if n < 3:
            continue
        a = cx = cy = 0.0
        for i in range(n):
            x0, y0, x1, y1 = ring[2 * i], ring[2 * i + 1], ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
            c = x0 * y1 - x1 * y0
            a += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a) < 1e-6:
            continue
        cx, cy, area = cx / (3 * a), cy / (3 * a), abs(a) / 2
        if area < 400 or not _pip(cx, cy, ring):
            continue
        ground = min(g.ground(ring[2 * i], ring[2 * i + 1]) for i in range(n))
        h = p["top"] - max(ground, p["base"])
        if not 6.0 <= h <= 48.0:
            continue
        inner = 1e9  # distance from the centroid to the nearest edge
        for i in range(n):
            x0, y0, x1, y1 = ring[2 * i], ring[2 * i + 1], ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
            dx, dy = x1 - x0, y1 - y0
            L2 = dx * dx + dy * dy or 1e-9
            u = max(0.0, min(1.0, ((cx - x0) * dx + (cy - y0) * dy) / L2))
            inner = min(inner, math.hypot(cx - x0 - u * dx, cy - y0 - u * dy))
        if inner >= 8.0:
            roofs.append((cx, cy, float(p["top"]), ring, inner))
    return roofs


def _load_grid(hello, mech):
    try:
        d = hello["map"]["dir"]
        with open(os.path.join(d, "v2", "world.json")) as f:
            world = json.load(f)
        terrain = None
        if True:
            try:
                t = world["terrain"]
                h = array("h")
                with open(os.path.join(d, "v2", t.get("file", "terrain.i16")), "rb") as f:
                    h.frombytes(f.read())
                if sys.byteorder != "little":
                    h.byteswap()
                terrain = (t["minX"], t["minY"], t["step"], t["nx"], t["ny"], h)
            except Exception as e:
                mf.log(f"no terrain ({e!r})")
        g = ObstacleGrid(world, mech.get("step_up", 1.2), mech.get("height", 9), terrain if flag("terrain") else None)
        g.terrain = terrain  # ground heights for roofs even when walls ignore them
        g.roofs = _find_roofs(world, g)
        if flag("inflate"):
            g.walk_mask()  # build it now, inside the hello budget, not on a 50 ms tick
        mf.log(f"obstacle grid: {len(g.cells)} cells")
        return g
    except Exception as e:  # no map: everything still works, steering just sees open ground
        mf.log(f"no obstacle grid ({e!r}); steering blind")
        return None


class FlowField:
    """Steps-to-safety for every street-level cell: a multi-source BFS outward from the safe disk
    of the next circle, so following it downhill takes the shortest walkable route to the nearest
    safe spot (it decides "left or right round that building" for us). Built a time slice per tick;
    cells outside the current circle (plus slack) are skipped because nobody should path there."""

    def __init__(self, grid, key, safe_c, safe_r, lim_c, lim_r):
        self.g, self.key = grid, key
        self.safe_c, self.safe_r = safe_c, safe_r
        self.dist = array("i", [-1]) * (grid.nx * grid.ny)
        self.q = deque()
        self.done = False
        nx, ny = grid.nx, grid.ny
        # per-row column ranges: lo/hi = allowed region, ilo/ihi = interior of the safe disk (dist 0,
        # never expanded), the ring between interior and safe_r is the BFS source set
        self.lo, self.hi = [1] * ny, [0] * ny
        self.ilo, self.ihi = [1] * ny, [0] * ny
        inner = safe_r - 2 * CELL
        for j in range(1, ny - 1):
            yc = grid.y0 + (j + 0.5) * CELL
            self.lo[j], self.hi[j] = self._span(lim_c, lim_r, yc, 1, nx - 2)
            if inner > 0:
                self.ilo[j], self.ihi[j] = self._span(safe_c, inner, yc, 1, nx - 2)
            a, b = self._span(safe_c, max(safe_r, CELL), yc, 1, nx - 2)
            for i in range(a, b + 1):
                if self.ilo[j] <= i <= self.ihi[j]:
                    continue
                k = j * nx + i
                if not (grid.walk_mask() if flag("inflate") else grid.solid)[k]:
                    self.dist[k] = 0
                    self.q.append(k)

    def _span(self, c, r, yc, imin, imax):
        dy = yc - c[1]
        if abs(dy) > r:
            return 1, 0
        h = math.sqrt(r * r - dy * dy)
        g = self.g
        return max(imin, int((c[0] - h - g.x0) / CELL)), min(imax, int((c[0] + h - g.x0) / CELL))

    def build(self, budget_s):
        if self.done:
            return
        g, nx, dist, q = self.g, self.g.nx, self.dist, self.q
        solid = g.walk_mask() if flag("inflate") else g.solid
        lo, hi, ilo, ihi = self.lo, self.hi, self.ilo, self.ihi
        end = time.perf_counter() + budget_s
        n = 0
        while q:
            k = q.popleft()
            d = dist[k] + 1
            j, i = divmod(k, nx)
            for di, dj in NB8:
                jj, ii = j + dj, i + di
                if ii < lo[jj] or ii > hi[jj] or ilo[jj] <= ii <= ihi[jj]:
                    continue
                nk = jj * nx + ii
                if dist[nk] != -1 or solid[nk]:
                    continue
                if di and dj and (solid[k + di] or solid[k + dj * nx]):
                    continue  # no cutting wall corners diagonally
                dist[nk] = d
                q.append(nk)
            n += 1
            if not n & 255 and time.perf_counter() > end:
                return
        self.done = True

    def _d(self, k):
        j, i = divmod(k, self.g.nx)
        if self.ilo[j] <= i <= self.ihi[j]:
            return 0
        return self.dist[k]

    def route(self, x, y, z, radius, lookahead=12):
        """(waypoint, path length in m) toward safety, or None if we're off the field."""
        g = self.g
        k = g.cell(x, y)
        if k is None:
            return None
        if self._d(k) < 0:  # on a roof, in a wall seam: hop onto the nearest reached neighbor
            best = None
            for di in (-2, -1, 0, 1, 2):
                for dj in (-2, -1, 0, 1, 2):
                    nk = k + di + dj * g.nx
                    if 0 <= nk < len(self.dist) and self._d(nk) >= 0 and (best is None or self._d(nk) < self._d(best)):
                        best = nk
            if best is None:
                return None
            k = best
        d0 = self._d(k)
        if d0 == 0:
            return None
        chain = []
        for _ in range(lookahead):
            j, i = divmod(k, g.nx)
            nxt, nd = None, self._d(k)
            for di, dj in NB8:
                ii, jj = i + di, j + dj
                if not (0 <= ii < g.nx and 0 <= jj < g.ny):
                    continue
                nk = jj * g.nx + ii
                dd = self._d(nk)
                if 0 <= dd < nd:
                    nxt, nd = nk, dd
            if nxt is None:
                break
            k = nxt
            chain.append(k)
            if nd == 0:
                break
        if not chain:
            return None
        # string-pulling: aim at the farthest chain cell we can walk to in a straight line
        wp = g.center(chain[0])
        for c in reversed(chain):
            cx, cy = g.center(c)
            dx, dy = cx - x, cy - y
            L = math.hypot(dx, dy)
            if L < 1e-6 or g.clear_dist(x, y, z, dx / L, dy / L, L, radius) >= L - 0.5:
                wp = (cx, cy)
                break
        return wp, d0 * CELL * 1.15  # BFS steps undercount diagonals


# --------------------------------------------------------------------------------------------
class Bot:
    name = "speedy-py"

    def __init__(self, hello: mf.Hello):
        cfg = hello["config"]
        self.reach = cfg["loot"]["pickup_radius"]
        mech = cfg["mech"]
        self.radius = mech.get("radius", 2.5)
        self.gravity = cfg["weapons"]["mortar"].get("gravity", mech.get("gravity", 22))
        self.splash = cfg["weapons"]["mortar"].get("splash_radius", 7)
        self.lightning_range = cfg["weapons"]["lightning"].get("range", 45)
        self.rng = random.Random(hello.get("seed", 0))
        self.grid = _load_grid(hello, mech)

        self.hist = []            # recent (t, x, y, commanded move magnitude)
        self.detour = None        # (until_t, dx, dy) while committed to a sideways detour
        self.stuck_log = []       # times we detected being stuck (for escalation)
        self.esc_hist, self.esc_until = [], -1.0  # escape: boxed-in detection
        self.explored = set()     # explore: 80 m world cells we have been near
        self.detour_side = 1
        self.steer_side = 1       # which way steering last swung, for hysteresis
        self.strafe_side = 1
        self.strafe_until = 0.0
        self.zone_boosting = False
        self.vema = {}            # enemy id -> smoothed (vx, vy, vz, t)
        self.peek = None          # (dx, dy, until): sidestep that clears our barrel line past a corner
        self.t_now = 0.0
        self.zone_live = False    # does the server already send the interpolated circle?
        self.last_zone = None
        self.field = None         # FlowField toward the next circle's safe disk
        self.drop_field = None    # FlowField toward the supply drop we're racing for
        self.face = None          # (bearing, until): turn toward an unseen attacker
        self.threat = None        # (bearing, until): heard shooting we can't see
        self.concuss_until = 0.0
        self.enemy_reload_until = 0.0
        self.attackers = {}       # mech id -> last time it damaged us
        self.cover = None         # ((x, y) or None, zone key): a quiet spot next to a wall
        self.cover_t = -99.0
        self.hide = None          # (x, y) of a spot the current threats can't see
        self.hide_t = -99.0
        self.hiding_until = 0.0
        self.tgt_id = None        # current weapons target, kept briefly while still shootable
        self.regroup = False      # healing up between fights (after a kill, or hurt with nobody on us)
        self.heard = None         # (bearing, t) of the latest fight noise, for seek
        self.last_seen = {}       # enemy id -> (x, y, t) of its last sighting, for hunt
        self.roof = None          # roof we're climbing to / standing on (from grid.roofs)
        self.roof_since = 0.0     # when we started heading for it
        self.roof_bad = {}        # roof index -> t until which we don't retry it
        self.crate_id = None      # crate we're shooting open for its cube
        self.drone_id = None      # NPC drone we're sniping for its 2 cubes
        self.drones_seen = {}     # NPC drone id -> (x, y, z, t) of its last sighting, for dronego
        self.late = False         # end game: next circle <= 70 m or 3 or fewer alive (lategrit)
        self.tgt_since = -99.0

    # ---------------------------------------------------------------------------- zone model
    def _zone_at(self, zone, t_now, tau):
        """Circle (cx, cy, r) at match time tau >= t_now."""
        c, r = zone["center"], zone["radius"]
        nc, nr = zone["next_center"], zone["next_radius"]
        s, e = zone["shrink_start"], zone["shrink_end"]
        if tau >= e:
            return (nc[0], nc[1], nr)
        if e <= s:
            return (c[0], c[1], r)
        if self.zone_live and t_now > s:  # center/radius are already the live circle at t_now
            s = t_now
        f = min(1.0, max(0.0, (tau - s) / (e - s)))
        return (c[0] + (nc[0] - c[0]) * f, c[1] + (nc[1] - c[1]) * f, r + (nr - r) * f)

    def _track_zone_mode(self, zone, t):
        key = (zone["shrink_start"], tuple(zone["next_center"]), zone["next_radius"])
        if self.last_zone and self.last_zone[0] == key and zone["shrink_start"] < t:
            if abs(self.last_zone[1] - zone["radius"]) > 1e-6:
                self.zone_live = True
        self.last_zone = (key, zone["radius"])

    def _safe_r(self, zone):
        nr = zone["next_radius"]
        return max(0.0, nr - (min(nr * 0.35, 25.0) + self.radius))

    def _update_field(self, zone, t):
        """(Re)build the flow field when the next circle changes; spend one time slice on it."""
        if self.grid is None:
            return None
        key = (tuple(zone["next_center"]), zone["next_radius"])
        if self.field is None or self.field.key != key:
            cx, cy, r = self._zone_at(zone, t, t)
            margin = 150.0 if flag("widefield") else 40.0  # room for detours around walls near the edge
            self.field = FlowField(self.grid, key, zone["next_center"], self._safe_r(zone), (cx, cy), r + margin)
            return None  # setup is this tick's work; start the search next tick
        self.field.build(FIELD_SLICE_S)
        return self.field if self.field.done else None

    def _zone_target(self, zone, x, y, z):
        """Closest reachable point inside the next circle (with margin). None if already there."""
        nc = zone["next_center"]
        safe_r = self._safe_r(zone)
        d = math.hypot(x - nc[0], y - nc[1])
        if d <= safe_r:
            return None
        k = safe_r / d if d > 1e-9 else 0.0
        tx, ty = nc[0] + (x - nc[0]) * k, nc[1] + (y - nc[1]) * k
        if self.grid:  # a point inside a building isn't reachable: slide it toward the center
            for _ in range(20):
                if not self.grid.blocked(tx, ty, z):
                    break
                tx += (nc[0] - tx) * 0.15
                ty += (nc[1] - ty) * 0.15
        return (tx, ty)

    def _zone_risk(self, zone, t, x, y, target, walk, path_len=None):
        """Would walking (with detour slack) toward target leave us outside the zone at any point?
        With a planned path length, progress along the straight line is slowed to match it."""
        if target is None:
            tx, ty = x, y
        else:
            tx, ty = target
        dist = math.hypot(tx - x, ty - y)
        speed = walk * 0.75  # paths are never straight
        if path_len and dist > 1e-6:
            speed = walk * 0.9 * min(1.0, dist / path_len)
        eta = dist / speed if speed > 0 else 0.0
        dx, dy = _norm(tx - x, ty - y)
        horizon = max(eta, min(zone["shrink_end"] - t, 30.0), 0.0)
        tau = 0.0
        while tau <= horizon + 1e-6:
            step = min(tau, eta) * speed
            qx, qy = x + dx * step, y + dy * step
            cx, cy, r = self._zone_at(zone, t, t + tau)
            if math.hypot(qx - cx, qy - cy) > r - self.radius - 2.0 - (10.0 if flag("zonefix") else 0.0):
                return True
            tau += 0.5
        return False

    # ---------------------------------------------------------------------------- threats
    def _dodge(self, obs, t, x, y, z, vx, vy, mine):
        """A dodge vector (dx, dy), its urgency (0..1+), and a short reason. `mine` = kinds we hold."""
        cz = z + 4.5
        ax = ay = 0.0
        urgency = 0.0
        why = ""
        # sounds (§8): threats we can hear but not see
        for snd in obs.get("sounds") or []:
            k, b = snd["kind"], snd["bearing"]
            if k in ("gun", "mortar", "laser", "laser_charge", "lightning") and snd["dist"] in ("near", "mid"):
                self.threat = (b, t + 2.0)
            if k == "laser_charge":  # someone within 140 m is lining up a beam: cross their line
                ax += -math.sin(b) * self.strafe_side
                ay += math.cos(b) * self.strafe_side
                urgency = max(urgency, 0.8)
                why = why or "charge?"
            elif k == "reload" and snd["dist"] == "near":
                self.enemy_reload_until = t + 2.0
        for p in obs["projectiles"]:
            px, py, pz = p["pos"]
            ux, uy, uz = p["vel"]
            if p["kind"] == "mortar":
                # solve pz + uz t - g t^2 / 2 = z for the landing time
                a, b, c = -0.5 * self.gravity, uz, pz - z
                disc = b * b - 4 * a * c
                if disc < 0:
                    continue
                tl = (-b - math.sqrt(disc)) / (2 * a)
                if tl <= 0 or tl > 4:
                    continue
                lx, ly = px + ux * tl, py + uy * tl
                d = math.hypot(x + vx * tl - lx, y + vy * tl - ly)
                if d < self.splash + self.radius + 3:
                    ex, ey = _norm(x - lx, y - ly)
                    if ex == 0 and ey == 0:
                        ex, ey = _norm(-uy, ux)
                    w = 1.5 * (1.0 - d / (self.splash + self.radius + 3)) + 0.6
                    ax += ex * w
                    ay += ey * w
                    urgency = max(urgency, 1.2 if tl < 1.5 else 0.7)
                    why = "mortar"
                continue
            # bullets fly straight: closest approach of the bullet to our (moving) center
            rx, ry, rz = px - x, py - y, pz - cz
            dvx, dvy, dvz = ux - vx, uy - vy, uz
            dv2 = dvx * dvx + dvy * dvy + dvz * dvz
            if dv2 < 1e-6:
                continue
            tc = -(rx * dvx + ry * dvy + rz * dvz) / dv2
            if tc <= 0 or tc > 1.2:
                continue
            mx, my, mz = rx + dvx * tc, ry + dvy * tc, rz + dvz * tc
            miss = math.hypot(mx, my)
            if abs(mz) > 6.0 or miss > self.radius + 2.5:
                continue
            # step perpendicular to the bullet, away from where it will pass
            nx, ny = _norm(-uy, ux)
            side = -(mx * nx + my * ny)
            if abs(side) < 0.3:  # dead center: keep going whichever way we already drift
                side = vx * nx + vy * ny or self.strafe_side
            s = 1.0 if side > 0 else -1.0
            w = (1.0 - miss / (self.radius + 2.5)) * 0.7 + 0.5 / (tc + 0.25)
            ax += nx * s * w
            ay += ny * s * w
            urgency = max(urgency, 1.0 if tc < 0.6 else 0.5)
            why = why or "bullet"
        for m in obs["mechs"]:
            mx_, my_ = m["pos"][0], m["pos"][1]
            dx, dy = x - mx_, y - my_
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                continue
            if m["kind"] == "npc":  # drones shoot any mech within 45 m of home: give them room
                if dist < 50:
                    ex, ey = _norm(dx, dy)
                    w = 0.6 * (1.0 - dist / 50) + 0.1
                    ax += ex * w
                    ay += ey * w
                    urgency = max(urgency, 0.2)
                    why = why or "npc"
                continue
            if m.get("charging"):
                # how far off its aim line are we? if it would hit, get off the line
                off = _angdiff(math.atan2(dy, dx), m["aim"][0])
                lateral = abs(math.sin(off)) * dist
                if abs(off) < math.pi / 2 and lateral < self.radius + 6:
                    nx, ny = _norm(-dy, dx)
                    s = 1.0 if off > 0 else -1.0
                    if abs(off) < 0.02:
                        s = float(self.strafe_side)
                    ax += nx * s * 1.6
                    ay += ny * s * 1.6
                    urgency = max(urgency, 1.0)
                    why = "laser"
            if "lightning" in (m.get("weapons") or []) and "lightning" not in mine and dist < self.lightning_range + 12:
                ex, ey = _norm(dx, dy)
                w = 0.8 * (1.0 - dist / (self.lightning_range + 12)) + 0.2
                ax += ex * w
                ay += ey * w
                urgency = max(urgency, 0.4)
                why = why or "arc"
        return ax, ay, urgency, why

    def _strafe(self, obs, t, x, y):
        """Unpredictable side-to-side motion relative to the nearest visible enemy mech."""
        foes = [m for m in obs["mechs"] if m["kind"] == "mech" and math.dist(m["pos"][:2], (x, y)) < 240]
        if foes:
            f = min(foes, key=lambda m: math.dist(m["pos"][:2], (x, y)))
            dx, dy = _norm(x - f["pos"][0], y - f["pos"][1])
        elif self.threat and t < self.threat[1]:  # unseen shooter: strafe across its bearing
            dx, dy = -math.cos(self.threat[0]), -math.sin(self.threat[0])
        else:
            return 0.0, 0.0
        if t >= self.strafe_until:
            if self.rng.random() < 0.75:
                self.strafe_side = -self.strafe_side
            self.strafe_until = t + (self.rng.uniform(0.3, 0.8) if flag("strafe2") else self.rng.uniform(0.45, 1.1))
        return -dy * self.strafe_side, dx * self.strafe_side

    # ---------------------------------------------------------------------------- steering
    def _steer(self, x, y, z, dx, dy, reach):
        """Swing (dx, dy) toward the nearest clear heading. Returns the new unit heading."""
        if self.grid is None or (dx == 0 and dy == 0):
            return dx, dy
        r = self.radius + 0.5
        if self.grid.clear_dist(x, y, z, dx, dy, reach, r) >= reach:
            return dx, dy
        best = None
        for k in range(1, 9):  # 15°..120° each way, preferred side first
            for side in (self.steer_side, -self.steer_side):
                hx, hy = _rot(dx, dy, side * k * math.radians(15))
                if self.grid.clear_dist(x, y, z, hx, hy, reach, r) >= reach:
                    best = (hx, hy, side)
                    break
            if best:
                break
        if best is None:
            return dx, dy  # boxed in: let the wall slide do its thing, stuck logic will kick in
        self.steer_side = best[2]
        return best[0], best[1]

    def _roof_line_clear(self, x, y, rx, ry, ring):
        """True if the first wall on the straight line from us to the roof's middle is that building's own."""
        g = self.grid
        d = math.hypot(rx - x, ry - y)
        if d < 1e-6:
            return True
        ux, uy = (rx - x) / d, (ry - y) / d
        s_ = 1.0
        while s_ < d:
            px, py = x + ux * s_, y + uy * s_
            c = g.cell(px, py)
            if c is not None and g.solid[c]:
                # wall cells straddle the outline: judge by a point just past it
                qx, qy = x + ux * min(d, s_ + 3.0), y + uy * min(d, s_ + 3.0)
                return _pip(qx, qy, ring)
            s_ += 1.0
        return True

    def _roof_plan(self, t, x, y, z, zone, risk, enemies, mode):
        """'roof' while standing on our roof, 'climb' while getting onto it, else None."""
        roofs = self.grid.roofs
        nc, nr = zone["next_center"], zone["next_radius"]
        cur = self.roof
        if cur is not None:
            rx, ry, rtop, ring, inner = roofs[cur]
            on = z > rtop - 1.0 and _pip(x, y, ring)
            if math.hypot(rx - nc[0], ry - nc[1]) + inner * 0.5 > nr - 10 or (risk and not on):
                self.roof = None  # the zone is leaving it (or we must run): drop the plan
                return None
            if mode in ("cube", "loot", "drop"):
                self.roof = None  # cubes, weapons and drops are worth coming down for
                return None
            if on:
                return "roof"
            if t - self.roof_since > 25.0:
                self.roof_bad[cur] = t + 90.0  # couldn't get up: try another one later
                self.roof = None
                return None
            if mode in ("safe", "cover", "seek", "hunt", "path", "zone") and not any(
                    math.dist(m["pos"][:2], (x, y)) < 60 for m in enemies):
                if z > 2.0 + self.grid.ground(x, y) or self._roof_line_clear(x, y, rx, ry, ring):
                    return "climb"  # airborne: keep going
                return "approach"
            return None
        if risk or mode not in ("safe", "cover", "seek", "hunt") or any(
                math.dist(m["pos"][:2], (x, y)) < 120 for m in enemies):
            return None
        best = None
        for i, (rx, ry, rtop, ring, inner) in enumerate(roofs):
            if self.roof_bad.get(i, 0.0) > t or rtop - z > 48.0:
                continue
            if math.hypot(rx - nc[0], ry - nc[1]) + inner * 0.5 > nr - 25:
                continue
            d = math.hypot(rx - x, ry - y)
            if d < 140 and (best is None or d < best[0]):
                best = (d, i)
        if best is None:
            return None
        self.roof, self.roof_since = best[1], t
        rx, ry, _, ring, _ = roofs[best[1]]
        return "climb" if self._roof_line_clear(x, y, rx, ry, ring) else "approach"

    def _update_stuck(self, t, x, y, want, dx, dy, z, walk):
        """Detect 'trying to move, not moving' and start a committed sideways detour."""
        self.hist.append((t, x, y, want))
        while self.hist and t - self.hist[0][0] > 1.05:
            self.hist.pop(0)
        if self.detour or len(self.hist) < 8 or t - self.hist[0][0] < 0.9:
            return
        if min(h[3] for h in self.hist) < 0.5:
            return  # we weren't really trying to move the whole time
        path = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(self.hist, self.hist[1:]))
        span = self.hist[-1][0] - self.hist[0][0]
        if path / span > 0.3 * walk:
            return
        self.stuck_log = [s for s in self.stuck_log if t - s < 6.0] + [t]
        repeats = len(self.stuck_log)
        side = self.detour_side
        if self.grid is not None:  # pick the side with more room
            l = self.grid.clear_dist(x, y, z, -dy, dx, 14, self.radius)
            r = self.grid.clear_dist(x, y, z, dy, -dx, 14, self.radius)
            if abs(l - r) > 2:
                side = 1 if l > r else -1
        if repeats >= 2:
            side = -self.detour_side  # same side failed recently: try the other way
        self.detour_side = side
        px, py = -dy * side, dx * side
        # mostly sideways, a little backward so we unstick from the wall face
        hx, hy = _norm(px * 0.9 - dx * 0.35, py * 0.9 - dy * 0.35)
        dur = min(0.8 + 0.4 * repeats, 2.0)
        self.detour = (t + dur, hx, hy, repeats)
        self.hist.clear()

    # ---------------------------------------------------------------------------- cover
    def _cover_spot(self, t, x, y, zone):
        """Nearest open cell right next to a wall inside the safe disk (within ~30 m), refreshed
        every few seconds. Somewhere to wait out the phase that can't be seen from every side."""
        if self.grid is None:
            return None
        key = (tuple(zone["next_center"]), zone["next_radius"])
        if self.cover and self.cover[1] == key and t - self.cover_t < 4.0:
            return self.cover[0]
        g, nc, sr = self.grid, zone["next_center"], self._safe_r(zone)
        k0 = g.cell(x, y)
        best = None
        if k0 is not None:
            j0, i0 = divmod(k0, g.nx)
            sol = g.solid
            for dj in range(-15, 16):
                j = j0 + dj
                if not 1 <= j < g.ny - 1:
                    continue
                for di in range(-15, 16):
                    i = i0 + di
                    if not 1 <= i < g.nx - 1:
                        continue
                    k = j * g.nx + i
                    if sol[k] or not (sol[k + 1] or sol[k - 1] or sol[k + g.nx] or sol[k - g.nx]):
                        continue
                    cx, cy = g.center(k)
                    dc = math.hypot(cx - nc[0], cy - nc[1])
                    if dc > sr:
                        continue
                    score = math.hypot(di, dj) * CELL + 0.1 * abs(dc - 0.5 * sr)
                    if best is None or score < best[0]:
                        best = (score, cx, cy)
        self.cover_t = t
        self.cover = ((best[1], best[2]) if best else None, key)
        return self.cover[0]

    def _hide_spot(self, t, x, y, threats):
        """Nearest walkable spot (BFS over the street grid, within ~36 m) that none of `threats`
        can see: a building between us and them stops their bullets and lets HP regen start.
        Candidates are cells with open ground all around (room for the body) next to a wall.
        Cached ~1 s; time-boxed to ~4 ms."""
        g = self.grid
        if g is None or not threats:
            return None
        if self.hide and t - self.hide_t < 1.0:
            hx, hy = self.hide
            if all(not g.los(tx, ty, hx, hy) for tx, ty in threats):
                return self.hide
        k0 = g.cell(x, y)
        if k0 is None:
            return None
        nx_, sol = g.nx, g.solid
        j0, i0 = divmod(k0, nx_)
        seen = {k0}
        q = deque([k0])
        end = time.perf_counter() + 0.004
        found = None
        n = 0
        while q:
            k = q.popleft()
            n += 1
            j, i = divmod(k, nx_)
            ring = [k + di + dj * nx_ for di, dj in NB8]
            if n > 1 and not any(sol[r] for r in ring):
                near_wall = any(sol[k + 2 * di + 2 * dj * nx_] for di, dj in NB8
                                if 0 <= i + 2 * di < nx_ and 0 <= j + 2 * dj < g.ny)
                if near_wall:
                    cx, cy = g.center(k)
                    if all(not g.los(tx, ty, cx, cy) for tx, ty in threats):
                        found = (cx, cy)
                        break
            if not n & 31 and time.perf_counter() > end:
                break
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if abs(ii - i0) > 18 or abs(jj - j0) > 18 or not (1 <= ii < nx_ - 1 and 1 <= jj < g.ny - 1):
                    continue
                nk = jj * nx_ + ii
                if nk not in seen and not sol[nk]:
                    seen.add(nk)
                    q.append(nk)
        self.hide, self.hide_t = found, t
        return found

    # ---------------------------------------------------------------------------- weapons
    def _mortar_solution(self, me, tgt, st):
        """(yaw, pitch) to land a shell on tgt, leading it by the flight time; None if not possible."""
        x, y, z = me["pos"]
        stats = me.get("stats", {})
        z0 = z + stats.get("height", 9) + 0.5  # the tube is above the head (§5)
        v, g = st["speed"], st.get("gravity", self.gravity)
        tx, ty, tz = tgt["pos"]
        tvx, tvy = tgt["vel"][0], tgt["vel"][1]
        R0 = math.hypot(tx - x, ty - y)
        dx, dy = _norm(tx - x, ty - y)
        # a building between us and them: lob the high arc over it
        high = self.grid is not None and self.grid.clear_dist(x, y, z, dx, dy, R0, 0.5) < R0 - 3
        tf, p, px, py = 0.0, None, tx, ty
        for _ in range(3):
            px, py = tx + tvx * tf, ty + tvy * tf
            R = math.hypot(px - x, py - y)
            p = _mortar_pitch(R, tz + 2.0 - z0, v, g, high)
            if p is None:
                return None
            tf = R / (v * math.cos(p))
        if not (stats.get("min_pitch", -0.7) <= p <= stats.get("max_pitch", 1.3)) or tf > st.get("ttl", 7):
            return None
        if not high and self.grid is not None and self.grid.clear_dist(x, y, z, dx, dy, 10, 0.5) < 8:
            return None  # shell would hit the wall right in front of us
        return math.atan2(py - y, px - x), p

    def _weapons(self, me, enemies, slots, act, safe_to_charge):
        """Aim and triggers for every held weapon. Sets act aim/fire/reload; returns a tag, or None
        when there is nothing to shoot (the caller then picks a look direction)."""
        x, y, z = me["pos"]
        stats = me.get("stats", {})
        fire = [False, False]
        act["fire"] = fire
        W = {k: me["weapons"][i] for k, i in slots.items()}
        if "gun" in W:  # top the magazine up while nobody is around
            g = W["gun"]
            if not enemies and (g.get("reload") or 0) == 0 and (g.get("ammo") or 0) < g["stats"]["mag"] * (1.0 if flag("topup") else 0.5):
                act["reload"] = True
        if not enemies:
            return None  # a laser mid-charge is released here: it fires off and starts cooling down
        tgt = enemies[0]
        tp = tgt["pos"]
        d = math.dist(tp[:2], (x, y))
        aim, tag = None, ""
        blend_hold = False
        # holdfire: memory reports mechs behind walls for 5 s; bullets into a wall only empty the
        # magazine, so hold the gun and reload while the target is hidden
        blind = (flag("holdfire") and self.grid is not None and abs(tp[2] - z) < 4
                 and not self.grid.los(x, y, tp[0], tp[1]))
        if blind and "gun" in W:
            g = W["gun"]
            if (g.get("reload") or 0) == 0 and (g.get("ammo") or 0) < g["stats"]["mag"] * (0.9 if flag("topup") else 0.7):
                act["reload"] = True

        def laser_target(rng):  # laser cooks off mortar carriers (+60%): prefer them
            return next((m for m in enemies if "mortar" in (m.get("weapons") or [])
                         and math.dist(m["pos"][:2], (x, y)) < (min(rng, 120.0) if flag("cookclose") else rng)), tgt)

        # laser already charging: keep the beam on target, let go when full and lined up
        if "laser" in W:
            L = W["laser"]
            st = L["stats"]
            ch = L.get("charge") or 0
            if ch > 0:
                lt_ = laser_target(st["range"])
                lyaw, lpitch, ld = _lead(me, lt_, 1e9)
                release = ch >= st["charge"] and _aimed(me, lyaw, lpitch, ld, 2.0)
                if release and flag("laserhold") and self.grid is not None:
                    # laserhold: a full charge keeps for hold_s (2 s); don't spend it (and 1.65 s of cooldown)
                    # on a wall: hold it while the target is out of sight or the barrel line meets cover
                    ltp = lt_["pos"]
                    mh_ = stats.get("muzzle_height", 7.0)
                    hidden = (abs(ltp[2] - z) < 4 and not self.grid.los(x, y, ltp[0], ltp[1])) or not \
                        self.grid.shot_clear(x, y, z + mh_, me["aim"][0], me["aim"][1], min(ld, 40.0))
                    if hidden and ch < st["charge"] + st.get("hold_s", 2.0) - 0.2:
                        release = False
                fire[slots["laser"]] = not release
                if flag("laserblend") and "gun" in W and ch < st["charge"] - 0.1:
                    blend_hold = True  # gun block below takes the aim; the trigger stays held
                else:
                    aim, tag = (lyaw, lpitch), "laser"

        # lightning: point at anyone inside arc range; it fires whenever the cone holds the target
        if "lightning" in W:
            LG = W["lightning"]
            st = LG["stats"]
            yaw_t = math.atan2(tp[1] - y, tp[0] - x)
            if d < st["range"] * 0.95:
                if aim is None:
                    pitch_t = math.atan2(tp[2] + 4.5 - (z + stats.get("muzzle_height", 7)), d)
                    aim, tag = (yaw_t, pitch_t), "arc"
                in_cone = abs(_angdiff(me["aim"][0], yaw_t)) < math.radians(st["cone_deg"]) / 2
                floor = (15 if self.zone_boosting else 3) if flag("arcsave") else 30
                if in_cone and me["energy"] > floor and LG["cooldown"] <= 0:
                    fire[slots["lightning"]] = True

        # mortar: lob it when it's (nearly) ready and the target isn't close enough to splash us
        if aim is None and "mortar" in W and W["mortar"]["cooldown"] <= 0.3 and d > 15:
            sol = self._mortar_solution(me, tgt, W["mortar"]["stats"])
            if sol:
                myaw, mpitch = sol
                aim, tag = (myaw, mpitch), "mortar"
                if (W["mortar"]["cooldown"] <= 0 and abs(_angdiff(me["aim"][0], myaw)) * d < 3.0
                        and abs(me["aim"][1] - mpitch) < 0.03):
                    fire[slots["mortar"]] = True

        # laser: start a charge only when slowing to half speed is safe
        if aim is None and "laser" in W and safe_to_charge and not blend_hold:
            L = W["laser"]
            st = L["stats"]
            if L["cooldown"] <= 0 and d < st["range"] * 0.95:
                lyaw, lpitch, _ = _lead(me, laser_target(st["range"]), 1e9)
                aim, tag = (lyaw, lpitch), "laser"
                fire[slots["laser"]] = True

        # gun: lead the target; pull the trigger whenever the actual aim is on the lead point
        if "gun" in W:
            st = W["gun"]["stats"]
            gme, gtgt = me, tgt
            if flag("aimlat") or flag("aimavg"):
                # aimlat: the shot leaves ~0.075 s after this observation (the action runs for 2 ticks), so
                # move both ends on by that much; aimavg: lead with the target's smoothed velocity, since
                # a strafing mech reverses every second or so and its current velocity overshoots
                lat = 0.075 if flag("aimlat") else 0.0
                tv = tgt["vel"]
                if flag("aimavg") and tgt["id"] in self.vema:
                    tv = self.vema[tgt["id"]][:3]
                mv = me["vel"]
                gme = dict(me, pos=[me["pos"][i] + mv[i] * lat for i in range(3)])
                gtgt = dict(tgt, pos=[tgt["pos"][i] + tv[i] * lat for i in range(3)], vel=list(tv))
            # leadk: lead only part of the target's motion; a strafing mech often turns back while the
            # bullet flies, and a full lead then passes in front of it
            k = (0.5 if flag("lead50") else 0.7 if flag("lead70") else 0.85 if flag("lead85")
                 else 1.1 if flag("lead110") else 1.0)
            if k != 1.0:
                gtgt = dict(gtgt, vel=[gtgt["vel"][0] * k, gtgt["vel"][1] * k, gtgt["vel"][2]])
            gyaw, gpitch, gd = _lead(gme, gtgt, st["speed"])
            if aim is None:
                aim, tag = (gyaw, gpitch), "gun"
            if flag("holdlead") and not blind and self.grid is not None and abs(tp[2] - z) < 4:
                # holdlead: the bullet meets the target at the lead point, not where it stands now; if a
                # wall is in the way of that point, it is about to duck behind cover: stop now
                gh = gd * math.cos(gpitch)
                lx, ly = x + math.cos(gyaw) * gh, y + math.sin(gyaw) * gh
                if not self.grid.los(x, y, lx, ly):
                    blind = True
            if flag("muzzlecheck") and not blind and self.grid is not None:
                # muzzlecheck: most shots into cover hit a wall within 20 m of us (we fight from corners);
                # trace the barrel's actual line for the first 25 m and hold the trigger if it meets a wall
                mh = stats.get("muzzle_height", 7.0)
                reach_ = min(gd * math.cos(gpitch), 25.0)
                if not self.grid.shot_clear(x, y, z + mh, me["aim"][0], me["aim"][1], reach_):
                    blind = True
                    if flag("peekstep"):
                        # step sideways to whichever side clears the line, for the next 0.6 s
                        nx_, ny_ = -math.sin(gyaw), math.cos(gyaw)
                        for side in (1.0, -1.0) if self.strafe_side > 0 else (-1.0, 1.0):
                            ox, oy = x + nx_ * 3.5 * side, y + ny_ * 3.5 * side
                            if self.grid.shot_clear(ox, oy, z + mh, math.atan2(tp[1] - oy, tp[0] - ox), gpitch, reach_):
                                self.peek = (nx_ * side, ny_ * side, self.t_now + 0.6)
                                break
            tol = (2.0 if flag("tol2") else 6.0 if flag("tol6") else 5.0 if flag("tol5") else 4.0 if flag("tol4")
                   else 2.8 if flag("tol28") else 3.6 if flag("tol36")
                   else 3.2 if flag("tol3") else 2.5)
            far_ok = not (flag("farhold") and gd > 150 and math.hypot(*tgt["vel"][:2]) > 3.0)
            if flag("gatehv") or flag("gatehv2"):
                on = _aimed_hv(me, gyaw, gpitch, gd, 3.2 if flag("gatehv") else 4.0, 4.0 if flag("gatehv") else 4.5)
            else:
                on = _aimed(me, gyaw, gpitch, gd, tol)
            if gd < st["range"] and on and not blind and far_ok:
                fire[slots["gun"]] = True

        if aim is None:
            aim = (math.atan2(tp[1] - y, tp[0] - x), 0.0)
        act["aim"] = [aim[0], aim[1]]
        mf.draw.line([x, y, z + 7], [tp[0], tp[1], tp[2] + 4.5], "#ff5040")
        return tag

    # ---------------------------------------------------------------------------- goals
    def _want_range(self, me, foe, slots):
        """Distance we'd like to fight at, from what we hold (and whether we're losing)."""
        if me["hp"] < (0.2 if flag("retreat20") else 0.45 if flag("retreat45") else 0.35) * me["max_hp"] and not (flag("lategrit") and self.late):
            return 220.0  # disengage, let regen work (lategrit: not in the end game, there is nowhere to go)
        theirs = foe.get("weapons") or []
        if "lightning" in slots and "mortar" not in theirs:
            return 22.0 if flag("light22") else 40.0 if flag("light40") else 32.0
        if "mortar" in slots:
            return 60.0 if flag("mortar60") else 90.0 if flag("mortar90") else 140.0
        if "laser" in slots:
            return 160.0 if flag("laser160") else 60.0 if flag("laser60") else 80.0 if flag("laser80") else 80.0 if flag("close3") else 100.0 if flag("close2") else 120.0 if flag("close") else 160.0
        return 35.0 if flag("close3") else 55.0 if flag("close2") else 80.0 if flag("close") else 110.0

    def _drop_plan(self, obs, me, x, y, boost_speed, enemies):
        """The supply drop worth racing for right now, or None."""
        best = None
        for dr in obs.get("drops") or []:
            if dr.get("holder") not in (None, me["id"]):
                continue  # someone else is capturing: walking into a shooting gallery
            px, py = dr["pos"][0], dr["pos"][1]
            d = math.hypot(px - x, py - y)
            if d > 260:
                continue
            if dr["lands_in"] > d * 1.25 / boost_speed + 5:
                continue  # too early: don't stand in the open waiting for it
            if any(math.dist(m["pos"][:2], (px, py)) < dr["radius"] + 15 for m in enemies):
                continue  # contested: the clock freezes and everyone is aiming at the ring
            if best is None or d < best[0]:
                best = (d, dr)
        return best[1] if best else None

    def _drop_route(self, dr, zone, t, x, y, z, zone_field):
        """Route toward a drop via its own flow field (built only once the zone field is done)."""
        if self.grid is None or zone_field is None:
            return None
        key = ("drop", dr["id"])
        if self.drop_field is None or self.drop_field.key != key:
            cx, cy, r = self._zone_at(zone, t, t)
            self.drop_field = FlowField(self.grid, key, dr["pos"][:2], max(CELL, dr["radius"] - 3),
                                        (cx, cy), r + 40.0)
            return None
        self.drop_field.build(FIELD_SLICE_S)
        if not self.drop_field.done:
            return None
        return self.drop_field.route(x, y, z, self.radius + 0.5)

    # ---------------------------------------------------------------------------- main
    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = me["pos"]
        vx, vy = me["vel"][0], me["vel"][1]
        t = obs["t"]
        zone = obs["zone"]
        self.late = (zone["next_radius"] <= 100 or obs["alive"] <= 5) if flag("late5") else (zone["next_radius"] <= 70 or obs["alive"] <= 3)
        stats = me.get("stats", {})
        walk = stats.get("walk_speed", 11.7)
        boost_speed = stats.get("boost_speed", 19.5)
        energy = me["energy"]
        grounded = me["grounded"]
        act: mf.Action = {"tick": obs["tick"]}
        slots = {w["kind"]: i for i, w in enumerate(me["weapons"]) if w}
        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"),
                         key=lambda m: math.dist(m["pos"], me["pos"]))
        seen = {m["id"] for m in obs["mechs"]}
        self.t_now = t
        a_ = 1.0 - math.exp(-0.1 / 0.4)  # smoothed enemy velocity, time constant 0.4 s
        for m in enemies:
            pv = self.vema.get(m["id"])
            v = m["vel"]
            if pv is None or t - pv[3] > 0.5:
                self.vema[m["id"]] = (v[0], v[1], v[2], t)
            else:
                self.vema[m["id"]] = (pv[0] + a_ * (v[0] - pv[0]), pv[1] + a_ * (v[1] - pv[1]), v[2], t)

        # ---- events: unseen attackers (face them: rear hits do 1.5x), concussion ----
        for ev in obs.get("events") or []:
            if ev["type"] == "damaged" and ev.get("by") is not None:
                self.attackers[ev["by"]] = t
            if ev["type"] == "kill" and flag("regroup") and me["hp"] < 0.85 * me["max_hp"]:
                self.regroup = True
            if ev["type"] == "damaged" and ev.get("bearing") is not None and ev.get("by") not in seen:
                self.face = (ev["bearing"], t + 1.5)
            elif ev["type"] == "effect" and ev.get("effect") == "concuss":
                self.concuss_until = t + 1.5

        # ---- upgrades: speed and energy first, then survival ----
        if obs["offer"]:
            ids = [c["id"] for c in obs["offer"]["choices"]]
            pref = UP_POWER if flag("uppower") else UP_TANK if flag("uptank") else UPGRADE_PREF
            if flag("upservo"):  # mobility first: +8% walk and boost speed per stack
                pref = ["servos"] + [u for u in pref if u != "servos"]
            if flag("upmag"):  # +8 rounds and -20% reload: +31% sustained gun damage, vs +15% for gun_damage
                pref = ["gun_mag"] + [u for u in pref if u != "gun_mag"]
            if flag("laserup"):  # offered only while we hold a laser: +18% of 315 a shot, then a 25% faster charge
                pref = ["laser_damage"] + [u for u in pref if u != "laser_damage"]
                pref = pref[:2] + ["laser_charge"] + [u for u in pref[2:] if u != "laser_charge"]
            act["pick"] = min(range(len(ids)), key=lambda i: pref.index(ids[i]) if ids[i] in pref else 99)

        # ---- loot: take or swap in anything better within reach; remember a better one in sight ----
        cur1 = me["weapons"][1] if len(me["weapons"]) > 1 else None
        loot_goal = None
        foes_close = any(math.dist(m["pos"][:2], (x, y)) < 80 for m in enemies)
        for p in sorted(obs["pickups"], key=lambda p: math.dist(p["pos"][:2], (x, y))):
            k = p["kind"]
            if k in slots or k == "gun":
                continue  # can't hold two of a kind
            rank = LOOT_LASER if flag("laserfirst") else LOOT_FLIP if flag("lootflip") else LOOT_RANK
            if cur1 is not None and rank.get(k, 0) <= rank.get(cur1["kind"], 0):
                continue
            dh = math.dist(p["pos"][:2], (x, y))
            if dh < self.reach and abs(p["pos"][2] - z) < 4:
                if cur1 is not None:
                    if cur1.get("charge"):
                        continue  # can't swap a charging laser
                    act["drop"] = 1
                act["take"] = p["id"]
                break
            far = (150 if flag("laserfar") and k == "laser" else 120 if flag("lootfar") and t < 150
                   else 100 if flag("lootfar2") and k in ("lightning", "laser") else 40)
            if loot_goal is None and dh < far and not foes_close:
                loot_goal = (p["pos"][0], p["pos"][1])

        # ---- cubes: each one is +4% HP and damage (cap 10) and an upgrade at 1/3/6/10; kills drop them ----
        cube_goal = None
        if flag("cubes") and me.get("cubes", 0) < 12:
            best = None
            for c in obs.get("cubes") or []:
                dh = math.dist(c["pos"][:2], (x, y))
                if dh < (130 if flag("drones") else 70) and abs(c["pos"][2] - z) < 4 and (best is None or dh < best[0]):
                    best = (dh, c["pos"][0], c["pos"][1])
            if best is not None:
                cube_goal = best[1:]

        # ---- movement: zone > supply drop > cubes > loot > drift ----
        self._track_zone_mode(zone, t)
        target = self._zone_target(zone, x, y, z)
        outside = not me["in_zone"]
        field = self._update_field(zone, t)
        route = field.route(x, y, z, self.radius + 0.5) if (field and target is not None) else None
        risk = outside or self._zone_risk(zone, t, x, y, target, walk, route[1] if route else None)
        drop = None if risk or flag("nodrop") else self._drop_plan(obs, me, x, y, boost_speed, enemies)

        mode = ("path" if route else "zone") if target is not None else "safe"
        wp_d = None  # distance to the route waypoint when we're following the flow field
        pull = 1.0
        drop_boost = False
        # regroup: heal to 85% between fights, out of sight, unless someone is shooting at us
        under_fire = any(t - tt < 3.0 for tt in self.attackers.values())
        if flag("regroup"):
            if me["hp"] < 0.45 * me["max_hp"] and not under_fire:
                self.regroup = True
            if me["hp"] >= 0.85 * me["max_hp"] or risk:
                self.regroup = False
        regroup_spot = None
        if self.regroup and not risk and not under_fire:
            threats = [(m["pos"][0], m["pos"][1]) for m in enemies if math.dist(m["pos"][:2], (x, y)) < 230]
            regroup_spot = self._hide_spot(t, x, y, threats) if threats else self._cover_spot(t, x, y, zone)
        # under fire / outnumbered / hurt: break line of sight behind a building
        hide = None
        if flag("hide") and not risk and enemies:
            recent_hit = [m for m in enemies if t - self.attackers.get(m["id"], -99) < 3.0]
            near = [m for m in enemies if math.dist(m["pos"][:2], (x, y)) < 230]
            if recent_hit or len(near) >= 2 or (near and me["hp"] < 0.5 * me["max_hp"]):
                self.hiding_until = t + 4.0
            if t < self.hiding_until and near:
                hide = self._hide_spot(t, x, y, [(m["pos"][0], m["pos"][1]) for m in near])
        if hide is None and flag("peekreload") and not risk and enemies and "gun" in slots:
            # peek and reload: a 2.4 s reload in the open is free damage for them; step behind cover
            g_ = me["weapons"][slots["gun"]]
            if (g_.get("reload") or 0) > 0.5 and self.grid is not None:
                vis = [(m["pos"][0], m["pos"][1]) for m in enemies if math.dist(m["pos"][:2], (x, y)) < 160
                       and self.grid.los(x, y, m["pos"][0], m["pos"][1])]
                if vis:
                    hide = self._hide_spot(t, x, y, vis)
        if hide is None and flag("reloadduck") and not risk and enemies and "gun" in slots and self.grid is not None:
            # reload duck: during a reload, a short sidestep behind the corner we're fighting from (a far
            # hiding spot costs the whole reload in the open); peekstep brings us back out after
            g_ = me["weapons"][slots["gun"]]
            if (g_.get("reload") or 0) > 0.4:
                f0 = enemies[0]
                fx, fy = f0["pos"][0], f0["pos"][1]
                if math.dist((fx, fy), (x, y)) < 200 and self.grid.los(x, y, fx, fy):
                    ux, uy = _norm(fx - x, fy - y)
                    best_ = None
                    for side in (1.0, -1.0):
                        for k in (3.0, 5.0, 7.0):
                            ox, oy = x - uy * side * k, y + ux * side * k
                            if (not self.grid.los(ox, oy, fx, fy) and self.grid.los(x, y, ox, oy)
                                    and not self.grid.blocked(ox, oy, z)):
                                if best_ is None or k < best_[0]:
                                    best_ = (k, (ox, oy))
                                break
                    if best_ is not None:
                        hide = best_[1]
        if hide is None and regroup_spot is not None:
            hide = regroup_spot
        if hide is not None:
            mode = "hide" if regroup_spot is None or hide is not regroup_spot else "regroup"
            dh = math.hypot(hide[0] - x, hide[1] - y)
            gx, gy = _norm(hide[0] - x, hide[1] - y)
            pull = 1.0 if dh > 2.5 else 0.0
            drop = None
            mf.draw.point([hide[0], hide[1], z], "#ff4040", 6)
        elif drop is not None:
            mode = "drop"
            dpx, dpy = drop["pos"][0], drop["pos"][1]
            dd = math.hypot(dpx - x, dpy - y)
            droute = self._drop_route(drop, zone, t, x, y, z, field)
            if dd < drop["radius"] - 2.5:  # inside the ring: hold it, drift back to the middle
                gx, gy = _norm(dpx - x, dpy - y)
                pull = 0.6 * dd / drop["radius"]
            else:
                wp = droute[0] if droute else (dpx, dpy)
                gx, gy = _norm(wp[0] - x, wp[1] - y)
                drop_boost = dd / walk > drop["lands_in"] and energy > 50
                mf.draw.line([x, y, z + 1.5], [wp[0], wp[1], z + 1.5], "#ff80ff")
        elif cube_goal is not None and not risk:
            mode = "cube"
            gx, gy = _norm(cube_goal[0] - x, cube_goal[1] - y)
            mf.draw.point([cube_goal[0], cube_goal[1], z], "#40ff80", 5)
        elif loot_goal is not None and not risk:
            mode = "loot"
            gx, gy = _norm(loot_goal[0] - x, loot_goal[1] - y)
        elif route is not None:
            wp = route[0]
            gx, gy = _norm(wp[0] - x, wp[1] - y)
            wp_d = math.hypot(wp[0] - x, wp[1] - y)
            mf.draw.line([x, y, z + 1.5], [wp[0], wp[1], z + 1.5], "#ffd060")
        elif target is not None:
            gx, gy = _norm(target[0] - x, target[1] - y)
        else:
            spot = self._cover_spot(t, x, y, zone) if flag("cover") else None
            if spot is not None:
                # already safe: creep (silently, under step_speed) to a wall and wait there
                mode = "cover"
                ds = math.hypot(spot[0] - x, spot[1] - y)
                gx, gy = _norm(spot[0] - x, spot[1] - y)
                pull = 0.0 if ds < 4.0 else 0.4
                mf.draw.point([spot[0], spot[1], z], "#a0a0ff", 5)
            else:
                # already safe: drift toward the middle of the next circle, slowly enough to be silent
                nc = zone["next_center"]
                dc = math.hypot(nc[0] - x, nc[1] - y)
                gx, gy = _norm(nc[0] - x, nc[1] - y)
                pull = 0.0 if dc < zone["next_radius"] * 0.3 else 0.4

        # seek: safe, healthy and nobody in sight: walk toward the latest fight noise (kills, cubes)
        for snd in obs.get("sounds") or []:
            if snd["kind"] in ("gun", "death", "mortar", "lightning", "step", "boost"):
                self.heard = (snd["bearing"], t)
        if (flag("seek") and mode in ("safe", "cover") and not enemies and self.heard
                and t - self.heard[1] < 8.0 and me["hp"] >= 0.7 * me["max_hp"]):
            b = self.heard[0]
            px, py = x + 40 * math.cos(b), y + 40 * math.sin(b)
            nc = zone["next_center"]
            if math.hypot(px - nc[0], py - nc[1]) < zone["next_radius"] - 15:
                mode = "seek"
                gx, gy, pull = math.cos(b), math.sin(b), 1.0

        # hunt: kills are the score; with nothing in sight and nothing heard, healthy, walk to where an
        # enemy was last seen (within 30 s) if that spot is safely inside the next circle
        for m in enemies:
            self.last_seen[m["id"]] = (m["pos"][0], m["pos"][1], t)
        hunt_hp, hunt_age = (0.5, 60.0) if flag("hunt2") else (0.7, 30.0)
        if (flag("hunt") and mode in ("safe", "cover") and not enemies
                and me["hp"] >= hunt_hp * me["max_hp"]):
            nc = zone["next_center"]
            best = None
            for eid, (ex, ey, et) in list(self.last_seen.items()):
                if t - et > hunt_age:
                    del self.last_seen[eid]
                    continue
                d = math.hypot(ex - x, ey - y)
                if d > 12 and math.hypot(ex - nc[0], ey - nc[1]) < zone["next_radius"] - 15 and (best is None or et > best[0]):
                    best = (et, ex, ey)
            if best is not None:
                mode = "hunt"
                gx, gy, pull = *_norm(best[1] - x, best[2] - y), 1.0

        # dronego: idle and safe: walk toward a drone we saw earlier (2 cubes each, 12 per match, they never
        # leave home by more than 30 m) until it's in snipe range with line of sight; the drone snipe below
        # does the shooting
        for m in obs["mechs"]:
            if m["kind"] == "npc":
                self.drones_seen[m["id"]] = (m["pos"][0], m["pos"][1], m["pos"][2], t)
        # dronego2: also when every enemy in sight is over 150 m away and nobody has hit us for 3 s
        far_only = (flag("dronego2") and not under_fire
                    and all(math.dist(m["pos"][:2], (x, y)) > 150 for m in enemies))
        if (flag("dronego") and flag("drones") and mode in ("safe", "cover") and (not enemies or far_only) and not risk
                and me["hp"] >= 0.6 * me["max_hp"]):
            vis_npc = {m["id"] for m in obs["mechs"] if m["kind"] == "npc"}
            nc = zone["next_center"]
            best = None
            for did, (dx_, dy_, dz_, dt_) in list(self.drones_seen.items()):
                d = math.hypot(dx_ - x, dy_ - y)
                los = self.grid is None or self.grid.los(x, y, dx_, dy_)
                if did not in vis_npc and d < 90 and los:
                    del self.drones_seen[did]  # we should see it from here: it's dead (or wandered off)
                    continue
                if t - dt_ > 150 or abs(dz_ - z) > 12:
                    continue
                if math.hypot(dx_ - nc[0], dy_ - nc[1]) > zone["next_radius"] - 10:
                    continue
                if d > 260:
                    continue
                if did in vis_npc and los and 75 < d < 150:
                    continue  # the snipe has it from here
                if best is None or d < best[0]:
                    best = (d, dx_, dy_)
            if best is not None and best[0] > 75:
                mode = "dronego"
                gx, gy = _norm(best[1] - x, best[2] - y)
                pull = 1.0

        # cratego: idle and safe: walk toward the nearest ground crate in view until it's in easy range
        if flag("cratego") and flag("crates") and mode in ("safe", "cover") and not enemies and not risk:
            best = None
            for c in obs.get("crates") or []:
                d = math.hypot(c["pos"][0] - x, c["pos"][1] - y)
                if 35 < d < 150 and abs(c["pos"][2] - z) < 3.0 and (best is None or d < best[0]):
                    best = (d, c["pos"][0], c["pos"][1])
            if best is not None:
                nc = zone["next_center"]
                if math.hypot(best[1] - nc[0], best[2] - nc[1]) < zone["next_radius"] - 10:
                    mode = "crate"
                    gx, gy = _norm(best[1] - x, best[2] - y)
                    pull = 1.0

        # explore: early (one hunter at a time), idle and healthy: walk to the nearest 80 m cell inside the
        # next circle that we have not been within 70 m of, to find drones (2 cubes each, we see ~3 of 12)
        # and crates out of sight. Cells are on a fixed world grid so they stay put as the zone moves.
        if flag("explore"):
            ci, cj = int(math.floor(x / 80.0)), int(math.floor(y / 80.0))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    k = (ci + di, cj + dj)
                    if k not in self.explored and math.hypot((k[0] + 0.5) * 80 - x, (k[1] + 0.5) * 80 - y) < 70:
                        self.explored.add(k)
            if (mode in ("safe", "cover") and not enemies and not risk and t < (300 if flag("explore2") else 210)
                    and me["hp"] >= (0.5 if flag("explore2") else 0.6) * me["max_hp"]):
                nc, nr = zone["next_center"], zone["next_radius"] - 25
                best = None
                n_ = int(nr / 80.0) + 1
                i0, j0 = int(math.floor(nc[0] / 80.0)), int(math.floor(nc[1] / 80.0))
                for i in range(i0 - n_, i0 + n_ + 1):
                    for j in range(j0 - n_, j0 + n_ + 1):
                        if (i, j) in self.explored:
                            continue
                        px_, py_ = (i + 0.5) * 80, (j + 0.5) * 80
                        if math.hypot(px_ - nc[0], py_ - nc[1]) > nr:
                            continue
                        if self.grid is not None:
                            kc = self.grid.cell(px_, py_)
                            if kc is None or self.grid.solid[kc]:
                                continue
                        d = math.hypot(px_ - x, py_ - y)
                        if best is None or d < best[0]:
                            best = (d, px_, py_)
                if best is not None:
                    mode = "explore"
                    gx, gy = _norm(best[1] - x, best[2] - y)
                    pull = 1.0

        # roof: fight from a rooftop inside the next circle (ground mechs need line of sight up to us)
        roof_state = None
        if flag("roof") and self.grid is not None and getattr(self.grid, "roofs", None):
            roof_state = self._roof_plan(t, x, y, z, zone, risk, enemies, mode)
            if roof_state is not None:
                mode = roof_state
                rx, ry, _, _, rin = self.grid.roofs[self.roof]
                dr = math.hypot(rx - x, ry - y)
                gx, gy = _norm(rx - x, ry - y) if dr > 1e-6 else (0.0, 0.0)
                pull = 1.0 if roof_state == "climb" or dr > 0.4 * rin else 0.0

        ddx, ddy, urgency, why = self._dodge(obs, t, x, y, z, vx, vy, slots)
        sx, sy = self._strafe(obs, t, x, y)

        # range control: hold the distance our weapons like (pushes in while they reload)
        rcx = rcy = 0.0
        if enemies and not risk and mode not in ("drop", "cube"):
            f = enemies[0]
            d = math.dist(f["pos"][:2], (x, y))
            want = self._want_range(me, f, slots)
            if t < self.enemy_reload_until and flag("reloadpush"):
                want *= 0.6
            if flag("outnumbered") and sum(math.dist(m["pos"][:2], (x, y)) < 150 for m in enemies) >= 2:
                want = 250.0  # two or more on us: get out, let them fight each other
            ex, ey = _norm(x - f["pos"][0], y - f["pos"][1])
            k = max(-1.0, min(1.0, (want - d) / (30.0 if flag("rc30") else 60.0)))
            if flag("nochase"):
                k = max(0.0, k)  # back off or hold, never walk toward a fight
            rcx, rcy = ex * k * 1.2, ey * k * 1.2

        if mode in ("hide", "regroup"):
            sx = sy = rcx = rcy = 0.0
        if mode == "cube":
            sx, sy = _clip_back(sx, sy, gx, gy)

        # travelling to the zone: side moves may not push us backwards; at risk, only sidestep
        if flag("zonefix") and target is not None and mode in ("path", "zone"):
            sx, sy = _clip_back(sx, sy, gx, gy)
            rcx, rcy = _clip_back(rcx, rcy, gx, gy)
            if risk:
                sx = sy = rcx = rcy = 0.0
                along = ddx * gx + ddy * gy
                ddx, ddy = ddx - along * gx, ddy - along * gy

        # blend: zone pull dominates when it is urgent, dodges dominate when a hit is incoming
        zone_w = 2.5 if risk else 1.0
        sw = 1.2 if flag("strafe2") else 0.5 if flag("sw05") else 1.2 if flag("sw12") else 0.8
        mx = gx * pull * zone_w + sx * sw + ddx * 1.8 + rcx
        my = gy * pull * zone_w + sy * sw + ddy * 1.8 + rcy
        mag = min(1.0, math.hypot(mx, my))
        if enemies or urgency > 0:
            mag = 1.0  # never dawdle under fire
        hx, hy = _norm(mx, my)

        jump = False
        boost_climb = False
        if self.detour and t < self.detour[0]:
            _, hx, hy, rep = self.detour
            mag = 1.0
            mode = "detour"
            # every detour hops (clears ~2.7 m ledges); a repeat within 6 s also jets over it
            if grounded and rep >= 1:
                jump = True
            if not grounded and rep >= 2 and energy > 30:
                boost_climb = True
        else:
            self.detour = None
            if mag > 0.05:
                reach = 9.0 + math.hypot(vx, vy) * 0.4
                if flag("steerwp") and wp_d is not None and mode == "path":
                    # the waypoint is string-pulled to a cell we can walk straight to; the route turns
                    # there, so a wall past it is not in our way
                    reach = max(2.0, min(reach, wp_d + 1.0))
                hx, hy = self._steer(x, y, z, hx, hy, reach)
            self._update_stuck(t, x, y, mag, hx, hy, z, walk)

        if roof_state is not None:
            rx, ry, rtop, rring, _ = self.grid.roofs[self.roof]
            if roof_state == "climb":
                # straight at the roof's middle: press into the wall, hop, then jet until our feet clear it
                self.detour = None
                self.hist.clear()
                hx, hy = _norm(rx - x, ry - y)
                mag = 1.0
                need = (rtop - z) / 10.0 * 15.0 + 25.0  # jet drain 15/s at 10 m/s rise, plus margin
                near_wall = self.grid.clear_dist(x, y, z, hx, hy, 6.0, self.radius) < 4.5
                if grounded and near_wall and energy < need:
                    mag = 0.0  # wait for energy at the wall foot
                elif grounded and near_wall:
                    jump = True
                elif not grounded and z < rtop + 0.8 and energy > 2:
                    boost_climb = True
            elif roof_state == "roof":  # on the roof: never step off the edge
                if mag > 0.05 and not _pip(x + hx * 5.0, y + hy * 5.0, rring):
                    hx, hy = _norm(rx - x, ry - y)
                    mag = 0.6 if math.hypot(rx - x, ry - y) > 2.0 else 0.0

        # escape: boxed in (an alley, a courtyard, the stadium bowl): we've wanted to move for 6 s and
        # stayed inside an 8 m circle. Head straight for the next circle's centre, hop and jet over
        # whatever is in the way (100 energy climbs ~60 m), and don't sprint meanwhile so the energy is
        # there for the climb.
        esc = False
        if flag("escape"):
            self.esc_hist.append((t, x, y, mag))
            while self.esc_hist and t - self.esc_hist[0][0] > 6.0:
                self.esc_hist.pop(0)
            if t < self.esc_until:
                esc = True
            elif (len(self.esc_hist) > 25 and t - self.esc_hist[0][0] > 5.5 and roof_state != "roof"
                  and (risk or not enemies)
                  and sum(h[3] > 0.5 for h in self.esc_hist) > 0.8 * len(self.esc_hist)
                  and max(math.hypot(h[1] - x, h[2] - y) for h in self.esc_hist) < 8.0):
                self.esc_until = t + 6.0
                self.esc_hist.clear()
                esc = True
            if esc:
                nc = zone["next_center"]
                hx, hy = _norm(nc[0] - x, nc[1] - y)
                mag, mode = 1.0, "escape"
                self.detour = None
                self.hist.clear()
                jump = grounded and energy >= 50
                boost_climb = (not grounded) and energy > 2

        # boost: zone first, then urgent dodges and drop races (keeping a reserve for the zone)
        if risk and energy > (2 if outside else 15):
            self.zone_boosting = True
        elif not risk or energy < 3:
            self.zone_boosting = False
        dodge_boost = urgency >= 1.0 and energy > (25 if flag("dodge25") else 40) and t >= self.concuss_until
        # arcsave: in a lightning fight energy is damage (3 energy = 60 damage, boosting burns 17/s),
        # so don't spend it dodging; the zone still gets its boost
        arc_fight = (flag("arcsave") and "lightning" in slots and bool(enemies)
                     and math.dist(enemies[0]["pos"][:2], (x, y)) < self.lightning_range + 10)
        if arc_fight:
            dodge_boost = False
        boost = grounded and mag > 0.5 and (self.zone_boosting or dodge_boost or drop_boost)
        boost = boost or boost_climb
        if esc:
            boost = boost_climb  # keep the energy for the climb

        if (flag("peekstep") and self.peek is not None and t < self.peek[2] and enemies and not risk
                and mode not in ("hide", "regroup")):
            hx, hy = _norm(hx * 0.3 + self.peek[0], hy * 0.3 + self.peek[1])
            mag = 1.0
        act["move"] = [hx * mag, hy * mag]
        act["boost"] = bool(boost)
        act["jump"] = jump

        # ---- weapons (after movement: a laser only charges when slowing down is safe) ----
        lightning_near = any("lightning" in (m.get("weapons") or []) and math.dist(m["pos"][:2], (x, y)) < 60
                             for m in enemies)
        safe_to_charge = not risk and urgency < 0.5 and not lightning_near and mode != "drop"
        recent = {i for i, tt in self.attackers.items() if t - tt < 4.0}
        if flag("sticky") and self.grid is not None and enemies:
            # direct fire needs a clear line: memory keeps reporting mechs behind walls for 5 s
            clear = {m["id"] for m in enemies if self.grid.los(x, y, m["pos"][0], m["pos"][1])}
            keep = self.tgt_id in clear and t - self.tgt_since < 1.5
            focus = flag("focus")
            wenemies = sorted(enemies, key=lambda m: (not (keep and m["id"] == self.tgt_id), m["id"] not in clear,
                                                      m["id"] not in recent,
                                                      (m.get("hp", 1e9) if focus and math.dist(m["pos"][:2], (x, y)) < 200 else 1e9),
                                                      math.dist(m["pos"], me["pos"])))
            if wenemies[0]["id"] != self.tgt_id:
                self.tgt_id, self.tgt_since = wenemies[0]["id"], t
            elif not keep:
                self.tgt_since = t
        else:
            wenemies = sorted(enemies, key=lambda m: (m["id"] not in recent, math.dist(m["pos"], me["pos"])))
        engage = True
        if flag("discipline") and enemies:
            e0 = wenemies[0]
            engage = (obs["alive"] <= 3 or e0["id"] in recent or math.dist(e0["pos"][:2], (x, y)) < 70
                      or e0.get("hp", 1e9) < 0.35 * e0.get("max_hp", 1.0))
        wtag = self._weapons(me, wenemies, slots, act, safe_to_charge and engage)
        if not engage:
            act["fire"] = [False, False]  # stay quiet: gunfire carries 320 m
            wtag = "hold"
        if mode == "regroup" and not under_fire:
            act["fire"] = [False, False]  # let the 5 s regen timer run
            wtag = "regroup"
        if flag("heal") and mode == "hide" and me["hp"] < 0.35 * me["max_hp"]:
            act["fire"] = [False, False]  # dealing damage resets the 5 s regen timer too
            wtag = "heal"
        # nobody in sight: snipe NPC drones (350 HP, 2 cubes) from beyond their 45-60 m home range,
        # where their 2.5-degree-spread bullets mostly miss and our 0.6-degree gun doesn't
        far_only2 = (flag("dronego2") and not under_fire
                     and all(math.dist(m["pos"][:2], (x, y)) > 150 for m in enemies))
        if wtag is None and flag("drones") and (not enemies or far_only2) and not risk and mode not in ("hide", "regroup"):
            gun = me["weapons"][0]
            mh = me["stats"].get("muzzle_height", 7.0)
            best = None
            for m in obs["mechs"]:
                if m["kind"] != "npc":
                    continue
                d = math.hypot(m["pos"][0] - x, m["pos"][1] - y)
                cur = m["id"] == self.drone_id
                if d > 200 or d < (20 if cur else 70) or abs(m["pos"][2] - z) > 12:
                    continue
                if self.grid is not None and not self.grid.los(x, y, m["pos"][0], m["pos"][1]):
                    continue
                key = (not cur, d)
                if best is None or key < best[0]:
                    best = (key, m, d)
            if best is not None and gun and gun.get("ammo", 0) > 0 and not gun.get("reload"):
                _, m, d = best
                self.drone_id = m["id"]
                tf = d / max(gun["stats"].get("speed", 252.0), 1.0)
                vx_, vy_ = (m.get("vel") or [0, 0, 0])[:2]
                px, py = m["pos"][0] + vx_ * tf, m["pos"][1] + vy_ * tf
                yaw = math.atan2(py - y, px - x)
                pitch = math.atan2(m["pos"][2] + 1.75 - (z + mh), max(d, 1.0))
                act["aim"] = [yaw, pitch]
                act["fire"] = [_aimed(me, yaw, pitch, d, 1.2), False]
                wtag = "drone"
                mf.draw.line([x, y, z + mh], [px, py, m["pos"][2] + 1.75], "#ff40ff")
        # nobody in sight: shoot open a reachable crate (300 HP = 7 shots) for its cube and maybe a weapon
        if wtag is None and flag("crates") and not enemies and mode not in ("hide", "regroup"):
            gun = me["weapons"][0]
            best = None
            mh = me["stats"].get("muzzle_height", 7.0)
            for c in obs.get("crates") or []:
                cx_, cy_, cz_ = c["pos"]
                d = math.hypot(cx_ - x, cy_ - y)
                if d > (90 if flag("cratego") else 65) or abs(cz_ - z) > 3.0:
                    continue  # too far for the cube to be worth it, or on a roof
                if self.grid is not None and not self.grid.los(x, y, cx_, cy_):
                    continue
                key = (c["id"] != self.crate_id, d)
                if best is None or key < best[0]:
                    best = (key, c, d)
            if best is not None and gun and gun.get("ammo", 0) > 0 and not gun.get("reload"):
                _, c, d = best
                self.crate_id = c["id"]
                yaw = math.atan2(c["pos"][1] - y, c["pos"][0] - x)
                pitch = math.atan2(c["pos"][2] + 1.2 - (z + mh), max(d, 1.0))
                act["aim"] = [yaw, pitch]
                act["fire"] = [_aimed(me, yaw, pitch, d, 1.0), False]
                wtag = "crate"
                mf.draw.line([x, y, z + mh], [c["pos"][0], c["pos"][1], c["pos"][2] + 1.2], "#c0a040")
        if wtag is None:  # nothing to shoot: look where it matters
            if self.face and t < self.face[1]:
                act["aim"] = [self.face[0], 0.0]
                wtag = "face"
            elif self.threat and t < self.threat[1]:
                act["aim"] = [self.threat[0], 0.0]
                wtag = "listen"
            elif mag > 0.3:
                act["aim"] = [math.atan2(hy, hx), 0.0]
                wtag = ""
            else:
                act["aim"] = [me["aim"][0] + 0.35, 0.0]  # idle: sweep the 120° view around
                wtag = "scan"

        # ---- debug drawing ----
        pt = target if target is not None else zone["next_center"]
        mf.draw.point([pt[0], pt[1], z], "#40c0ff", 6)
        mf.draw.line([x, y, z + 1], [x + hx * 8 * mag, y + hy * 8 * mag, z + 1], "#40ff80")
        tag = mode + (" B" if boost else "") + (f" {why}" if why else "") + (" RISK" if risk else "")
        mf.draw.label(f"hp {me['hp']:.0f} e {energy:.0f} · {len(enemies)} seen · {tag} · {wtag}")
        return act

mf.run(Bot)
