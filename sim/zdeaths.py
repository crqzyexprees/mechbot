"""Zone deaths of the candidate: python3 zdeaths.py N SEED0"""
import os, sys, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    z = [r for r in res if r["zone_death"]]
    for r in z:
        print(f"t {r['death_t']:6.1f} place {r['place']:2d} alive_others {r['hunters_alive']:2d} kills {r['kills']} taken {r['taken']:.0f}")
    print("zone deaths", len(z), "of", n, " points lost if they had lived to next death ~", )
