"""Fresh-seed confirmation of a few variants against the pushed baseline.
usage: python3 confirm.py N SEED_BASE "label=off1,off2" ...   (flags listed are switched OFF)"""
import math, os, sys, shutil, tempfile, time
from multiprocessing import Pool
import sweep

def main():
    n, base = int(sys.argv[1]), int(sys.argv[2])
    specs = [a.split("=", 1) for a in sys.argv[3:]]
    root = tempfile.mkdtemp(prefix="confirm_")
    paths = {lab: sweep.write_variant(root, lab, [f for f in off.split(",") if f]) for lab, off in specs}
    t0 = time.time()
    with Pool(os.cpu_count()) as pool:
        res = sweep.run([(lab, p, base + i) for lab, p in paths.items() for i in range(n)], pool)
    sweep.table(f"confirm, {n} fresh matches each, seeds {base}+ ({time.time() - t0:.0f} s)", res)
    for lab, _ in specs:
        print(f"  {lab:32s} mean cubes held at end {sum(r.get('cubes', 0) for r in res[lab]) / len(res[lab]):.2f}"
              f"  zone deaths {sum(1 for r in res[lab] if r.get('zone_death'))}/{len(res[lab])}")
    ref = specs[0][0]
    rm, rse, *_ = sweep.stats(res[ref])
    for lab, _ in specs[1:]:
        m, se, *_ = sweep.stats(res[lab])
        d, dse = m - rm, math.sqrt(se ** 2 + rse ** 2)
        print(f"  {lab} - {ref} = {d:+.2f} ± {dse:.2f}  ({d / dse:+.1f} s.e.)  {'BETTER' if d > 2 * dse else 'not clearly better'}")
    shutil.rmtree(root, ignore_errors=True)

if __name__ == "__main__":
    main()
