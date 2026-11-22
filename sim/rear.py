import os, sys, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    t = sum(r["taken"] for r in res); tr = sum(r["taken_rear"] for r in res)
    print(f"taken {t/n:.0f}/match, rear {tr/n:.0f}/match = {100*tr/max(t,1):.1f}%")
