"""List zone-death matches of the current bot in the practice format: python3 zscan.py N SEED0"""
import os, sys, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])
    z = [(s0 + i, r[0]["death_t"], r[0]["place"]) for i, r in enumerate(res) if r[0]["zone_death"]]
    print(f"zone deaths {len(z)}/{n}:", z)
