"""House-bot motion in the sim vs the real stream (median heading change per 0.1 s, share >45, >120 deg).
usage: python3 motion.py N SEED0 SMOOTH_DEG [SMOOTH_DEG ...]   (0 = off)"""
import os, sys, statistics as S
from multiprocessing import Pool
import sweep, sim

def one(a):
    seed, sm = a
    al = ms = None
    if isinstance(sm, tuple):
        sm, al, ms = (tuple(sm) + (None, None))[:3]
    kit = os.path.abspath(os.path.join(sweep.HERE, "..", "..", "mechfight-kit"))
    sq = dict(sweep.SQUAD, smooth_deg=sm, smooth_alpha=al, min_speed=ms) if sm else sweep.SQUAD
    r = sim.one_match((kit, os.path.join(sweep.HERE, "..", "example_bot.py"), sweep.TIERS, seed, 1, sq))[0]
    # lead-factor table: predict a house bot's position T s ahead from pos + k*vel*T
    byk = {}
    pos = {(tk, i): (x, y, vx, vy) for tk, i, x, y, vx, vy in r.get("htr", [])}
    for (tk, i), (x, y, vx, vy) in pos.items():
        for T in (0.2, 0.4, 0.6):
            q = pos.get((tk + round(T * 20), i))
            if q is None:
                continue
            for k in (0.0, 0.5, 0.7, 0.85, 1.0, 1.15):
                e = ((q[0] - x - k * vx * T) ** 2 + (q[1] - y - k * vy * T) ** 2) ** 0.5
                byk.setdefault((T, k), []).append(e)
    return (sm, al, ms), r.get("hmot", []), 16 - r["place"], byk

def main():
    n, base = int(sys.argv[1]), int(sys.argv[2])
    sms = [tuple(list(float(v) for v in x.split(":")) + [None])[:3] if ":" in x else (float(x), None, None) for x in sys.argv[3:]]
    with Pool(os.cpu_count()) as p:
        out = p.map(one, [(base + i, sm) for sm in sms for i in range(n)])
    print("real stream (mech 10): median 6.4 deg, >45 deg 9%, >120 deg 0%")
    print("  real T=0.4s: k=0 3.59 m 24%  k=0.5 2.19 m 63%  k=0.7 1.86 m 72%  k=0.85 1.79 m 75%  k=1.0 1.89 m 73%  k=1.15 2.20 m 66%")
    print("  real T=0.6s: k=0 5.15 m 14%  k=0.5 3.44 m 33%  k=0.7 3.19 m 44%  k=0.85 3.29 m 50%  k=1.0 3.61 m 47%  k=1.15 4.15 m 31%")
    for sm in sms:
        t = [x for s, h, _, _ in out if s == sm for x in h]
        sc = [v for s, _, v, _ in out if s == sm]
        bk = {}
        for s_, _, _, b in out:
            if s_ == sm:
                for key, v in b.items():
                    bk.setdefault(key, []).extend(v)
        print(f"cap {sm[0]:4.0f} blend {sm[1] or 0:.2f} minspeed {sm[2] or 0:.2f}: median {S.median(t):5.1f} deg  >45 {100 * sum(x > 45 for x in t) / len(t):4.1f}%"
              f"  >120 {100 * sum(x > 120 for x in t) / len(t):4.1f}%   (n={len(t)})  our score {S.mean(sc):.2f}")
        for T in (0.2, 0.4, 0.6):
            row = []
            for k in (0.0, 0.5, 0.7, 0.85, 1.0, 1.15):
                e = bk.get((T, k), [])
                if e:
                    row.append(f"k={k:.2f} {S.mean(e):.2f} m {100 * sum(x < 2.5 for x in e) / len(e):3.0f}%")
            print(f"      T={T}s " + "  ".join(row))

if __name__ == "__main__":
    main()
