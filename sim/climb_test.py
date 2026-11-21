"""Kinematic check of the roof climb: one mech, no enemies, zone centred on a roof."""
import sys, os, json, gzip, math, copy
sys.path.insert(0, os.getcwd())
import sim
kit = os.path.abspath('../../mechfight-kit')
lines = gzip.open(kit + '/check/stream.jsonl.gz', 'rt')
hello = json.loads(lines.readline()); hello['map']['dir'] = kit + '/arena'
tmpl = json.loads(lines.readline())
os.environ['SPEEDY_OFF'] = "discipline,nochase,cover,outnumbered,hide,regroup,focus,strafe2,uptank,lootfar,cratego,widefield,terrain,inflate,hunt,hunt2"
cls, mf = sim.load_bot(os.path.abspath('../example_bot.py'))
pip = cls.__init__.__globals__['_pip']
M = hello['config']['mech']
def run(ri, start_d, start_ang, T=40.0):
    bot = cls(hello); g = bot.grid
    rx, ry, top, ring, inner = g.roofs[ri]
    # start point: start_d from the centroid, pushed out until outside the building
    found = False
    for k in range(400):
        ang = start_ang + 0.7 * (k // 40); d = start_d + 2 * (k % 40)
        x, y = rx + d * math.cos(ang), ry + d * math.sin(ang)
        if not g.blocked(x, y, g.ground(x, y)) and not pip(x, y, ring):
            found = True; break
    if not found:
        return dict(roof=ri, skipped="no open start point")
    z = g.ground(x, y); vx = vy = vz = 0.0; e = 100.0; last_spend = -9; grounded = True
    dt = 0.05; act = {}; on_t = None; maxz = z
    for tick in range(int(T / dt)):
        t = tick * dt
        if tick % 2 == 0:
            o = copy.deepcopy(tmpl); o['tick'] = tick; o['t'] = t
            s = o['self']; s['pos'] = [x, y, z]; s['vel'] = [vx, vy, vz]; s['energy'] = e; s['grounded'] = grounded; s['in_zone'] = True
            o['mechs'] = []; o['projectiles'] = []; o['sounds'] = []; o['events'] = []; o['crates'] = []; o['cubes'] = []; o['pickups'] = []
            o['zone'] = {"center": [rx, ry], "radius": 400, "next_center": [rx, ry], "next_radius": 200, "shrink_start": 999, "shrink_end": 1100, "dps": 20}
            act = bot.act(o) or {}
        mv = act.get('move', [0, 0]); boost = act.get('boost'); jump = act.get('jump')
        spd = M['boost_speed'] if (boost and grounded and e > 0) else M['walk_speed']
        acc = M['ground_accel'] if grounded else M['air_accel']
        tvx, tvy = mv[0] * spd, mv[1] * spd
        dvx, dvy = tvx - vx, tvy - vy; dl = math.hypot(dvx, dvy); mx = acc * dt
        if dl > mx: dvx, dvy = dvx / dl * mx, dvy / dl * mx
        vx += dvx; vy += dvy
        spent = False
        if grounded and jump: vz = M['jump_speed']; grounded = False
        if not grounded:
            vz -= M['gravity'] * dt
            if boost and e > 0:
                vz = min(vz + M['jet_accel'] * dt, max(vz, M['max_rise_speed'])); e -= M['jet_drain'] * dt; spent = True
        elif boost and math.hypot(*mv) > 0.1:
            e -= M['boost_drain'] * dt; spent = True
        if spent: last_spend = t
        elif t - last_spend > M['energy_regen_delay']: e = min(100, e + M['energy_regen'] * dt)
        e = max(0, e)
        # horizontal move with wall test (body = centre + 4 rim points), axis by axis to slide
        def solid(px, py, pz):
            for ox, oy in ((0, 0), (2.5, 0), (-2.5, 0), (0, 2.5), (0, -2.5)):
                if g.blocked(px + ox, py + oy, pz): return True
            return False
        z += vz * dt
        if not solid(x + vx * dt, y, z): x += vx * dt
        else: vx = 0
        if not solid(x, y + vy * dt, z): y += vy * dt
        else: vy = 0
        floor = top if (pip(x, y, ring) and z >= top - 1.2) else g.ground(x, y)
        if z <= floor:
            z, vz, grounded = floor, 0.0, True
        else:
            grounded = z <= floor + 0.05 and vz <= 0
            if z > floor + 0.05: grounded = False
        maxz = max(maxz, z)
        if TRACE and tick % 10 == 0:
            print(f't={t:4.1f} pos=({x:7.1f},{y:7.1f}) z={z:5.1f} top={top:4.1f} e={e:5.1f} gr={grounded} mv={[round(v,2) for v in mv]} j={jump} b={boost} roof={bot.roof} on={pip(x,y,ring)} dc={math.hypot(x-rx,y-ry):5.1f}')
        on = pip(x, y, ring) and abs(z - top) < 0.5 and grounded
        if on and on_t is None: on_t = t
    return dict(roof=ri, height=round(top - g.ground(rx + start_d, ry), 1), on_roof_at=on_t, end_on=pip(x, y, ring) and abs(z - top) < 0.5,
                end_dist_to_centre=round(math.hypot(x - rx, y - ry), 1), maxz_over_top=round(maxz - top, 1), energy=round(e))
TRACE = len(sys.argv) > 1
import random
rng = random.Random(1)
bot0 = cls(hello); R = bot0.grid.roofs
import time
picks = rng.sample(range(len(R)), min(len(R), 20)); angs = [rng.uniform(0, 6.28) for _ in picks]
for ri, a in zip(picks, angs):
    if TRACE and ri != int(sys.argv[1]): continue
    t0 = time.time()
    print(run(ri, R[ri][4] + 30, a), round(time.time() - t0, 1), 's', flush=True)
