"""Drone smoke test: python3 npctest.py N SEED0 [OFF-list]"""
import os, sys, statistics as st, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    if len(sys.argv) > 3:
        os.environ["SPEEDY_OFF"] = sys.argv[3]
    kit = os.path.abspath("../../mechfight-kit"); bot = os.path.abspath("../example_bot.py")
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    print(f"score {st.mean(16 - r['place'] for r in res):.2f}  kills {st.mean(len(r['kill_ts']) for r in res):.2f}  drone kills {st.mean(r['npc_kills'] for r in res):.2f}"
          f"  house drone kills {st.mean(r['house_npc_kills'] for r in res):.2f}  drones seen {st.mean(r['npc_seen'] for r in res):.2f} hit {st.mean(r['npc_hit'] for r in res):.2f}  cubes {st.mean(r['cubes'] for r in res):.2f}  life {st.mean(r['life'] for r in res):.0f}"
          f"  errors {sum(len(r['errors']) if isinstance(r['errors'], list) else r['errors'] for r in res)}  max ms {max(r['max_ms'] for r in res):.1f}")
