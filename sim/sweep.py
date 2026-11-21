"""Staged A/B sweep in the practice format, all variants sharing one process pool.

Variants are the current bot with sets of behaviour flags switched off (SPEEDY_OFF names, see
example_bot.py). Each variant is written to its own file with the flags fixed, so every match in the
pool can run any variant.

  stage 1  screen:      --screen matches per variant (default 24); keep the --keep best
  stage 2  contenders:  --more matches each for the kept ones (default 96, fresh seeds)
  stage 3  confirm:     the best contender and v1 on --confirm fresh seeds each (default 96)

python3 sweep.py            (from bot/sim)
"""
import argparse
import math
import os
import shutil
import statistics
import sys
import tempfile
import time
from multiprocessing import Pool

import sim

# string hashing is salted per interpreter; pin it so set iteration (and so the match) repeats exactly
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

HERE = os.path.dirname(os.path.abspath(__file__))
TIERS = [os.path.join(HERE, "baselines", d, "example_bot.py") for d in ("easy", "starter", "v1", "fighter")]
V1 = os.path.join(HERE, "baselines", "v1", "example_bot.py")
SQUAD = {"late": 300, "hunters": 1, "omniscient": False, "passive": True}
_house = os.environ.get("SIM_HOUSE")  # pick a house-bot setup from calibrate.CONFIGS (e.g. "strong")
if _house:
    _B = lambda d: os.path.join(HERE, "baselines", d, "example_bot.py")
    TIERS, SQUAD = {
        "cur": ([_B("easy"), _B("starter"), _B("v1"), _B("fighter")], SQUAD),
        "strong": ([_B("v1"), _B("fighter"), _B("b398"), _B("best")], SQUAD),
        "mid": ([_B("easy"), _B("starter"), _B("fighter"), _B("b398")], SQUAD),
        "mid2": ([_B("starter"), _B("v1"), _B("fighter"), _B("b398")], SQUAD),
        "strong_act": ([_B("v1"), _B("fighter"), _B("b398"), _B("best")], dict(SQUAD, passive=False)),
    }[_house]
CAUTIOUS = ["discipline", "nochase", "cover", "outnumbered", "hide"]
FLAGS = ["zonefix", "nochase", "discipline", "outnumbered", "cover", "hide", "sticky", "heal", "reloadpush"]


NEW = ["focus", "regroup", "strafe2"]
BASELINE = "pushed"


def variants():
    """Round 2: the pushed commit (aggressive) vs the new fight switches, alone and together."""
    v = {"pushed": CAUTIOUS + NEW, "new all": list(CAUTIOUS)}
    for f in NEW:
        v[f"pushed + {f}"] = CAUTIOUS + [g for g in NEW if g != f]
        v[f"new all without {f}"] = CAUTIOUS + [f]
    return v


def variants_round1():
    v = {"all on": []}
    v["aggressive"] = list(CAUTIOUS)
    for f in FLAGS:
        v[f"without {f}"] = [f]
    for f in ("zonefix", "sticky", "heal", "reloadpush"):
        v[f"aggressive without {f}"] = CAUTIOUS + [f]
    for f in CAUTIOUS:  # aggressive, but keep one cautious behaviour
        v[f"aggressive + {f}"] = [c for c in CAUTIOUS if c != f]
    return v


def write_variant(root, name, off):
    d = os.path.join(root, name.replace(" ", "_").replace("+", "plus"))
    os.makedirs(d, exist_ok=True)
    src = open(os.path.join(HERE, "..", "example_bot.py")).read()
    line = 'SPEEDY_OFF = set(os.environ.get("SPEEDY_OFF", "").split(","))'
    old = '_OFF = set(os.environ.get("SPEEDY_OFF", "").split(","))'
    assert old in src, "flag line not found in example_bot.py"
    src = src.replace(old, f"_OFF = {set(off)!r}  # sweep variant: {name}", 1)
    src = src.replace('if "SPEEDY_OFF" not in os.environ:\n    _OFF =', 'if False:\n    _OFF =', 1)
    open(os.path.join(d, "example_bot.py"), "w").write(src)
    shutil.copy(os.path.join(HERE, "..", "mechfight.py"), d)
    return os.path.join(d, "example_bot.py")


def run(jobs, pool):
    """jobs: list of (label, bot_path, seed) -> {label: [result, ...]}"""
    kit = os.path.abspath(os.path.join(HERE, "..", "..", "mechfight-kit"))
    args = [(kit, path, TIERS, seed, 1, SQUAD) for _, path, seed in jobs]
    out = {}
    for (label, _, _), res in zip(jobs, pool.map(sim.one_match, args, chunksize=1)):
        out.setdefault(label, []).extend(res)
    return out


def stats(rs):
    sc = [16 - r["place"] for r in rs]
    se = statistics.stdev(sc) / math.sqrt(len(sc)) if len(sc) > 1 else 0.0
    deaths = sorted(r["death_t"] for r in rs if r["death_t"] is not None)
    return (statistics.mean(sc), se, statistics.mean(r["kills"] for r in rs),
            deaths[len(deaths) // 2] if deaths else None, max(r["max_ms"] for r in rs), len(sc))


def table(title, res):
    print(f"\n=== {title}")
    rows = sorted(((stats(rs), lab) for lab, rs in res.items()), key=lambda x: -x[0][0])
    for (m, se, k, d, ms, n), lab in rows:
        print(f"  {lab:32s} score {m:5.2f} ± {se:4.2f}  kills {k:4.2f}  median death {d or 0:5.0f} s  "
              f"worst tick {ms:4.1f} ms  (n={n})")
    sys.stdout.flush()
    return [lab for _, lab in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", type=int, default=24)
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--more", type=int, default=96)
    ap.add_argument("--confirm", type=int, default=96)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    t0 = time.time()
    root = tempfile.mkdtemp(prefix="sweep_")
    paths = {"v1 (submitted)": V1}
    for name, off in variants().items():
        paths[name] = write_variant(root, name, off)
    with Pool(a.jobs) as pool:
        # stage 1: everyone on the same seeds
        jobs = [(lab, p, 900000 + i) for lab, p in paths.items() for i in range(a.screen)]
        res = run(jobs, pool)
        order = table(f"stage 1: screen, {a.screen} matches each ({time.time() - t0:.0f} s)", res)
        kept = [lab for lab in order if lab not in ("v1 (submitted)", BASELINE)][:a.keep] + [BASELINE]
        # stage 2: contenders (and the baseline, and v1) on fresh seeds, pooled with stage 1
        jobs = [(lab, paths[lab], 910000 + i) for lab in kept + ["v1 (submitted)"] for i in range(a.more)]
        more = run(jobs, pool)
        for lab, rs in more.items():
            res[lab].extend(rs)
        order = table(f"stage 2: contenders, +{a.more} matches ({time.time() - t0:.0f} s)",
                      {lab: res[lab] for lab in kept + ["v1 (submitted)"]})
        best = [lab for lab in order if lab not in ("v1 (submitted)", BASELINE)][0]
        # stage 3: confirmation on seeds neither stage has used
        jobs = [(lab, paths[lab], 920000 + i) for lab in (best, BASELINE) for i in range(a.confirm)]
        conf = run(jobs, pool)
        table(f"stage 3: confirm '{best}' vs {BASELINE} on fresh seeds ({time.time() - t0:.0f} s)", conf)
        (bm, bse, *_), (vm, vse, *_) = stats(conf[best]), stats(conf[BASELINE])
        diff, dse = bm - vm, math.sqrt(bse ** 2 + vse ** 2)
        print(f"\nbest: {best}  flags off: {sorted(variants()[best])}")
        print(f"confirm: {best} - {BASELINE} = {diff:+.2f} ± {dse:.2f}  ->  "
              f"{'BETTER' if diff > 2 * dse else 'NOT CLEARLY BETTER'} (needs > 2 s.e.)")
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
