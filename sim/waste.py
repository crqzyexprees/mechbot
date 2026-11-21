"""Where our damage goes and how house bots die: python3 waste.py N SEED0"""
import os, sys, collections, statistics as st, sim, sweep
from multiprocessing import Pool
if __name__ == "__main__":
    n, s0 = int(sys.argv[1]), int(sys.argv[2])
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mechfight-kit"))
    bot = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "example_bot.py"))
    with Pool(os.cpu_count()) as p:
        res = [r[0] for r in p.map(sim.one_match, [(kit, bot, sweep.TIERS, s0 + i, 1, sweep.SQUAD) for i in range(n)])]
    causes = collections.Counter()
    killed_dmg = wasted_dmg = 0.0
    wasted_by = collections.Counter()
    partial = []
    for r in res:
        my_death = r["death_t"] if r["death_t"] is not None else 1e9
        for h in r["house_fate"]:
            c = h["cause"]
            if c is None:
                causes["alive at end"] += 1
            elif c.startswith("by"):
                causes["killed by us"] += 1
            else:
                causes[f"{c}" + (" (before our death)" if h["t"] < my_death else " (after our death)")] += 1
            if c is not None and c.startswith("by"):
                killed_dmg += h["from_me"]
            else:
                wasted_dmg += h["from_me"]
                if h["from_me"] > 0:
                    partial.append(h["from_me"] / h["max_hp"])
                    gap = my_death - h["last_hit_me"]
                    wasted_by["we died within 10 s of last hit" if gap < 10 else "escaped 10-30 s before we died" if gap < 30 else "escaped 30+ s before we died / we survived"] += h["from_me"]
    print(f"=== {n} matches, house {os.environ.get('SIM_HOUSE', 'realmove')}, score {st.mean(16 - r['place'] for r in res):.2f}")
    print("house bot fates per match:", {k: round(v / n, 2) for k, v in causes.most_common()})
    tot = killed_dmg + wasted_dmg
    print(f"our damage per match: on bots we killed {killed_dmg / n:.0f}, on bots we did not kill {wasted_dmg / n:.0f} ({100 * wasted_dmg / tot:.0f}%)")
    print("bots we hurt but never killed, per match:", round(len(partial) / n, 2), " damage as share of their max HP, quartiles:",
          [round(q, 2) for q in st.quantiles(partial, n=4)] if len(partial) > 3 else partial)
    print("wasted damage split:", {k: round(v / n) for k, v in wasted_by.most_common()})
    kills = sum(1 for r in res for h in r["house_fate"] if h["cause"] and h["cause"].startswith("by"))
    print(f"damage per kill (on killed bots): {killed_dmg / max(1, kills):.0f}   mean max HP of house bots {st.mean(h['max_hp'] for r in res for h in r['house_fate']):.0f}")
