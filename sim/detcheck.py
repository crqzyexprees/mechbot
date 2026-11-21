"""Same code + same seed twice: do the matches come out identical?"""
import os, sys
import sweep, sim

def main():
    kit = os.path.abspath(os.path.join(sweep.HERE, "..", "..", "mechfight-kit"))
    bot = os.path.join(sweep.HERE, "..", "example_bot.py")
    for seed in (1900000, 1900001):
        rows = []
        for _ in range(2):
            r = sim.one_match((kit, bot, sweep.TIERS, seed, 1, sweep.SQUAD))[0]
            rows.append((r["place"], round(r["dealt"], 1), round(r["taken"], 1), r["life"], sum((r["aimst"] or {}).get("shots", []))))
        print(seed, rows, "IDENTICAL" if rows[0] == rows[1] else "DIFFERENT")

if __name__ == "__main__":
    main()
