"""Where the placement points go: python3 life.py N SEED0  (house bots from SIM_HOUSE)"""
import os, sys, collections, statistics as st, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    pts = [16 - r["place"] for r in res]
    print(f"=== {n} matches, house {os.environ.get('SIM_HOUSE', 'realmove')}: score {st.mean(pts):.2f}, kills {st.mean(len(r['kill_ts']) for r in res):.2f}")
    print("points histogram:", sorted(collections.Counter(pts).items()))
    surv = [r for r in res if r["death_t"] is None]
    zone = [r for r in res if r["zone_death"]]
    comb = [r for r in res if r["death_t"] is not None and not r["zone_death"]]
    print(f"survived {len(surv)}, zone deaths {len(zone)}, combat deaths {len(comb)}")
    for lab, grp in (("survived", surv), ("zone", zone), ("combat", comb)):
        if grp:
            print(f"  {lab:8s} mean points {st.mean(16 - r['place'] for r in grp):5.2f}  kills {st.mean(len(r['kill_ts']) for r in grp):4.2f}  life {st.mean(r['life'] for r in grp):5.0f} s  hunters left {st.mean(r['hunters_alive'] for r in grp):4.1f}")
    print("combat deaths by minute:", sorted(collections.Counter(int(r["death_t"] // 60) for r in comb).items()))
    print("attackers in last 10 s:", sorted(collections.Counter(r["attackers10"] for r in comb).items()))
    print("kills by minute (all matches):", sorted(collections.Counter(int(t // 60) for r in res for t in r["kill_ts"]).items()))
    # points lost: by when we died, how many enemies were still alive
    lost = collections.Counter()
    for r in comb + zone:
        lost[int(r["death_t"] // 60)] += r["hunters_alive"]
    print("enemies still alive at our death, summed per minute of death (= points left on the table):", sorted(lost.items()))
    ups = collections.Counter(k for r in res for k, v in r["ups"].items() if v)
    print("upgrades per match:", {k: round(v / n, 2) for k, v in ups.most_common()}, " cubes left", round(st.mean(r["cubes"] for r in res), 2))
    print(f"dealt {st.mean(r['dealt'] for r in res):.0f}  taken {st.mean(r['taken'] for r in res):.0f}")
