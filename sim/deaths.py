"""How the candidate dies: python3 deaths.py N SEED0"""
import os, sys, collections, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    dead = [r for r in res if r["death_t"] is not None and not r["zone_death"]]
    print(f"{n} matches: survived {sum(r['death_t'] is None for r in res)}, zone deaths {sum(bool(r['zone_death']) for r in res)}, combat deaths {len(dead)}")
    print("attackers in last 10 s of a combat death:", sorted(collections.Counter(r["attackers10"] for r in dead).items()))
    b = collections.Counter(int(r["death_t"] // 60) for r in dead)
    print("combat deaths by minute:", sorted(b.items()))
    kb = collections.Counter(int(t // 60) for r in res for t in r["kill_ts"])
    print("kills by minute:", sorted(kb.items()), " mean kills", round(sum(len(r['kill_ts']) for r in res) / n, 2))
    print("score", round(sum(16 - r["place"] for r in res) / n, 2))
