"""Gun accuracy by range band for bot variants.
usage: python3 aimstat.py N SEED0 "label=off1,off2" ...   (flags listed are switched OFF)"""
import os, sys, shutil, tempfile
from multiprocessing import Pool
import sweep

BANDS = ["<50 m", "50-100", "100-150", "150-230", "no foe"]

def agg(rows):
    t = {k: [0] * 5 for k in ("shots", "hits", "walls", "crates", "blocked")}
    for a in rows:
        if a:
            for k in t:
                t[k] = [x + y for x, y in zip(t[k], a.get(k, [0] * 5))]
    return t

def show(lab, t, n):
    tot_s, tot_h = sum(t["shots"][:4]), sum(t["hits"][:4])
    print(f"  {lab:24s} hit rate {100 * tot_h / max(tot_s, 1):5.1f}%  shots/match {sum(t['shots']) / n:6.0f}")
    for i, b in enumerate(BANDS):
        s = t["shots"][i]
        if s:
            print(f"      {b:8s} shots {s / n:6.1f}/match  hit {100 * t['hits'][i] / s:5.1f}%  into cover {100 * t['blocked'][i] / s:5.1f}%  missed {100 * (s - t['hits'][i] - t['blocked'][i] - t['crates'][i]) / s:5.1f}%  crate {100 * t['crates'][i] / s:5.1f}%")

def main():
    n, base = int(sys.argv[1]), int(sys.argv[2])
    specs = [a.split("=", 1) for a in sys.argv[3:]]
    root = tempfile.mkdtemp(prefix="aim_")
    paths = {lab: sweep.write_variant(root, lab, [f for f in off.split(",") if f]) for lab, off in specs}
    with Pool(os.cpu_count()) as pool:
        res = sweep.run([(lab, p, base + i) for lab, p in paths.items() for i in range(n)], pool)
    for lab, _ in specs:
        rs = res[lab]
        m, se, *_ = sweep.stats(rs)
        print(f"\n{lab}: score {m:.2f} ± {se:.2f}")
        show("us", agg(r.get("aimst") for r in rs), len(rs))
        show("house bots (each)", agg(a for r in rs for a in r.get("house_aimst") or []), len(rs) * 15)
    shutil.rmtree(root, ignore_errors=True)

if __name__ == "__main__":
    main()
