"""Paired screen: every variant plays the same seeds (the sim is repeatable), so differences per seed
cancel most of the match-to-match noise. Low-noise measures: hit rate, damage dealt, damage taken.
usage: SIM_HOUSE=cur python3 pair.py N SEED0 "base=off1,off2" "label=off..." ...   (first = reference)"""
import math, os, statistics as S, sys, shutil, tempfile, time
from multiprocessing import Pool
import sweep

def m_se(xs):
    return S.mean(xs), (S.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0)

def hits(r):
    a = r.get("aimst") or {}
    return sum(a.get("hits", [0] * 5)[:4]), sum(a.get("shots", [0] * 5)[:4]), sum(a.get("blocked", [0] * 5)[:4])

def main():
    n, base = int(sys.argv[1]), int(sys.argv[2])
    specs = [a.split("=", 1) for a in sys.argv[3:]]
    root = tempfile.mkdtemp(prefix="pair_")
    try:
        paths = {lab: sweep.write_variant(root, lab, [f for f in off.split(",") if f]) for lab, off in specs}
        t0 = time.time()
        with Pool(os.cpu_count()) as pool:
            res = sweep.run([(lab, p, base + i) for lab, p in paths.items() for i in range(n)], pool)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    ref = specs[0][0]
    print(f"=== paired, {n} seeds from {base} ({time.time() - t0:.0f} s), house bots: {os.environ.get('SIM_HOUSE', 'realmove')}")
    print(f"  {'':12s} {'score':>13s} {'hit %':>7s} {'cover %':>8s} {'dealt/match':>12s} {'taken/match':>12s} {'life s':>7s}")
    for lab, _ in specs:
        rs = res[lab]
        h, s_, b = (sum(x) for x in zip(*(hits(r) for r in rs)))
        sc = m_se([16 - r["place"] for r in rs])
        print(f"  {lab:12s} {sc[0]:6.2f} ± {sc[1]:.2f} {100 * h / max(s_, 1):7.1f} {100 * b / max(s_, 1):8.1f}"
              f" {S.mean(r['dealt'] for r in rs):12.0f} {S.mean(r['taken'] for r in rs):12.0f} {S.mean(r['life'] for r in rs):7.0f}")
    print(f"  differences vs {ref}, same seeds (± = paired standard error):")
    for lab, _ in specs[1:]:
        a, b_ = res[ref], res[lab]
        d = lambda f: m_se([f(y) - f(x) for x, y in zip(a, b_)])
        sc, dl, tk = d(lambda r: 16 - r["place"]), d(lambda r: r["dealt"]), d(lambda r: r["taken"])
        hr = d(lambda r: 100 * hits(r)[0] / max(hits(r)[1], 1))
        flag_ = lambda m, se: "  *" if abs(m) > 2 * se else ""
        print(f"  {lab:12s} score {sc[0]:+.2f} ± {sc[1]:.2f}{flag_(*sc):3s} hit {hr[0]:+5.1f} ± {hr[1]:.1f}{flag_(*hr):3s}"
              f" dealt {dl[0]:+6.0f} ± {dl[1]:4.0f}{flag_(*dl):3s} taken {tk[0]:+6.0f} ± {tk[1]:4.0f}{flag_(*tk)}")

if __name__ == "__main__":
    main()
