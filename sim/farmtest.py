"""Cube economy per variant, paired seeds: python3 farmtest.py N SEED0 "label=off,..." ..."""
import os, sys, shutil, tempfile, statistics as S, math
from multiprocessing import Pool
import sim, sweep
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    specs = [a.split("=", 1) for a in sys.argv[3:]]
    root = tempfile.mkdtemp(prefix="farm_")
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    try:
        paths = {lab: sweep.write_variant(root, lab, [f for f in off.split(",") if f]) for lab, off in specs}
        jobs = [(kit, p, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for lab, p in paths.items() for i in range(n)]
        with Pool(os.cpu_count()) as pool:
            out = pool.map(sim.one_match, jobs)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    base = None
    for j, (lab, _) in enumerate(specs):
        rs = [o[0] for o in out[j * n:(j + 1) * n]]
        sc = [16 - r["place"] for r in rs]
        if base is None: base = sc
        d = [a - b for a, b in zip(sc, base)]
        sd = S.stdev(d) / math.sqrt(n) if j else 0
        print(f"{lab:10s} score {S.mean(sc):5.2f}  diff {S.mean(d):+5.2f} ± {sd:4.2f}  cubes {S.mean(r['cubes'] for r in rs):4.1f}  "
              f"npc_kills {S.mean(r['npc_kills'] for r in rs):4.2f}  npc_seen {S.mean(r['npc_seen'] for r in rs):4.1f}  kills {S.mean(r['kills'] for r in rs):4.2f}  "
              f"survive {sum(r['death_t'] is None for r in rs)/n:4.2f}  zone {sum(bool(r['zone_death']) for r in rs)}")
