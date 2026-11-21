"""Where do our shots into cover stop: right in front of us, mid-way, or next to the target?"""
import os, sys
from multiprocessing import Pool
import sweep, sim

def one(seed):
    kit = os.path.abspath(os.path.join(sweep.HERE, "..", "..", "mechfight-kit"))
    r = sim.one_match((kit, os.path.join(sweep.HERE, "..", "example_bot.py"), sweep.TIERS, seed, 1, sweep.SQUAD))[0]
    return (r.get("aimst") or {}).get("block_at", []), sum((r.get("aimst") or {}).get("shots", [0])[:4])

def main():
    n, base = int(sys.argv[1]), int(sys.argv[2])
    with Pool(os.cpu_count()) as p:
        out = p.map(one, [base + i for i in range(n)])
    bl = [b for o, _ in out for b in o]
    shots = sum(s for _, s in out)
    print(f"{len(bl)} shots into cover of {shots} ({100 * len(bl) / shots:.1f}%)")
    for lab, f in [("within 6 m of us", lambda a, d: a < 6), ("6-20 m from us", lambda a, d: 6 <= a < 20),
                   ("mid-way", lambda a, d: a >= 20 and d - a >= 15), ("within 15 m of target", lambda a, d: a >= 20 and d - a < 15)]:
        k = sum(1 for a, d in bl if f(a, d))
        print(f"  {lab:24s} {k:6d}  {100 * k / max(len(bl), 1):5.1f}%")

if __name__ == "__main__":
    main()
