"""Which way our 50-100 m misses pass the target: along its velocity (+ = ahead, over-led) and vertical."""
import os, sys, tempfile, statistics as S
from multiprocessing import Pool
import sweep
def main():
    n, base, off = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    root = tempfile.mkdtemp(prefix="miss_")
    p = sweep.write_variant(root, "v", [f for f in off.split(",") if f])
    with Pool(os.cpu_count()) as pool:
        res = sweep.run([("v", p, base + i) for i in range(n)], pool)
    al = [x for r in res["v"] for x in (r.get("aimst") or {}).get("miss_along", [])]
    zz = [x for r in res["v"] for x in (r.get("aimst") or {}).get("miss_z", [])]
    print(f"misses within 12 m: {len(al)}  along-track mean {S.mean(al):+.2f} m  median {S.median(al):+.2f}")
    for lo, hi in [(-99, -6), (-6, -3), (-3, -1), (-1, 1), (1, 3), (3, 6), (6, 99)]:
        print(f"  {lo:+4d}..{hi:+3d} m  {100 * sum(lo <= x < hi for x in al) / len(al):5.1f}%")
    rv = [x for r in res["v"] for x in (r.get("aimst") or {}).get("miss_rev", [])]
    sp = [x for r in res["v"] for x in (r.get("aimst") or {}).get("miss_sp", [])]
    print(f"target reversed during flight: {100 * sum(rv) / max(len(rv), 1):.1f}% of misses; target standing (<1 m/s) when fired: {100 * sum(x <= 1.0 for x in sp) / max(len(sp), 1):.1f}%")
    print(f"vertical mean {S.mean(zz):+.2f} m  share above/below body (|dz|>4.5): {100 * sum(abs(x) > 4.5 for x in zz) / len(zz):.1f}%")

if __name__ == "__main__":
    main()
