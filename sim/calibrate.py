"""Does the sim rank our real-scored commits the way the real scorer did?
usage: python3 calibrate.py CONFIG N SEED0      CONFIG in CONFIGS below.
Each commit's bot runs as it was submitted (its own default switches), on the same seeds."""
import math, os, statistics, subprocess, sys, time
from multiprocessing import Pool
import sim, sweep

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.environ.get("CALIB_DIR", os.path.join(HERE, ".calib_bots"))
B = lambda d: os.path.join(HERE, "baselines", d, "example_bot.py")
# real practice scores (sim-visible differences; roof/loot-only/lightning-only tests left out)
REAL = {"starter": 1.15, "ff3653f": 2.96, "2b1e2e4": 3.31, "080afbf": 3.19, "6b70f38": 3.49, "861f493": 3.10,
        "379f5bf": 3.52, "ed981aa": 3.96, "2e8d5c2": 4.06, "39da462": 3.96, "eac4376": 3.77, "2025b71": 3.98,
        "a80dbe0": 3.79, "36e24d0": 3.73, "e7f1836": 4.15, "a0d7583": 3.79,
        "70e5d61": 4.42, "c36b625": 4.08, "7f3176e": 4.27}
CONFIGS = {
    "cur":        ([B("easy"), B("starter"), B("v1"), B("fighter")], {"late": 300, "hunters": 1, "omniscient": False, "passive": True}),
    "strong":     ([B("v1"), B("fighter"), B("b398"), B("best")], {"late": 300, "hunters": 1, "omniscient": False, "passive": True}),
    "mid":        ([B("easy"), B("starter"), B("fighter"), B("b398")], {"late": 300, "hunters": 1, "omniscient": False, "passive": True}),
    "mid2":       ([B("starter"), B("v1"), B("fighter"), B("b398")], {"late": 300, "hunters": 1, "omniscient": False, "passive": True}),
    "realmove":   ([B("easy"), B("starter"), B("v1"), B("fighter")], {"late": 300, "hunters": 1, "omniscient": False, "passive": True,
                                                                    "smooth_deg": 90, "smooth_alpha": 0.3, "min_speed": 0.85}),
    "strong_act": ([B("v1"), B("fighter"), B("b398"), B("best")], {"late": 300, "hunters": 1, "omniscient": False, "passive": False}),
}

def bot_path(c):
    if c == "starter":
        return B("starter")
    d = os.path.join(SCRATCH, c)
    p = os.path.join(d, "example_bot.py")
    if not os.path.exists(p):
        os.makedirs(d, exist_ok=True)
        open(p, "w").write(subprocess.run(["git", "show", f"{c}:example_bot.py"], cwd=HERE, capture_output=True,
                                          text=True, check=True).stdout)
        open(os.path.join(d, "mechfight.py"), "w").write(open(os.path.join(HERE, "..", "mechfight.py")).read())
    return p

def ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for k, i in enumerate(o):
        r[i] = k
    return r

def corr(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return num / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))

def main():
    cfg, n, base = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    tiers, squad = CONFIGS[cfg]
    kit = os.path.abspath(os.path.join(HERE, "..", "..", "mechfight-kit"))
    names = list(REAL)
    jobs = [(c, (kit, bot_path(c), tiers, base + i, 1, squad)) for c in names for i in range(n)]
    t0 = time.time()
    with Pool(os.cpu_count()) as pool:
        outs = pool.map(sim.one_match, [a for _, a in jobs], chunksize=1)
    res = {}
    for (c, _), o in zip(jobs, outs):
        res.setdefault(c, []).extend(o)
    print(f"=== {cfg}: {n} matches per commit, seeds {base}+ ({time.time() - t0:.0f} s)")
    sims = []
    for c in names:
        m, se, k, *_ = sweep.stats(res[c])
        sims.append(m)
        print(f"  {c:8s} real {REAL[c]:.2f}   sim {m:5.2f} ± {se:.2f}   kills {k:.2f}")
    real = [REAL[c] for c in names]
    ref = "70e5d61"
    print(f"  paired vs {ref} (real 4.42), same seeds:")
    for c in names:
        if c == ref:
            continue
        dd = [(16 - b["place"]) - (16 - a["place"]) for a, b in zip(res[ref], res[c])]
        m_, se_ = statistics.mean(dd), statistics.stdev(dd) / math.sqrt(len(dd))
        print(f"    {c:8s} real {REAL[c] - REAL[ref]:+.2f}   sim {m_:+.2f} ± {se_:.2f}")
    print(f"  Pearson r = {corr(sims, real):+.2f}   Spearman = {corr(ranks(sims), ranks(real)):+.2f}"
          f"   (without starter: Pearson {corr(sims[1:], real[1:]):+.2f}, Spearman {corr(ranks(sims[1:]), ranks(real[1:])):+.2f})")

if __name__ == "__main__":
    main()
