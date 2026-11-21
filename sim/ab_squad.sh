#!/usr/bin/env bash
# Practice-format A/B (squad of house bots, calibrated: see calib.sh). One row per variant.
# usage: ./ab_squad.sh [matches] [seed]
cd "$(dirname "$0")"
N=${1:-192}; SEED=${2:-7}
E=baselines/easy/example_bot.py S=baselines/starter/example_bot.py V=baselines/v1/example_bot.py F=baselines/fighter/example_bot.py
SNAP=$(mktemp -d "${TMPDIR:-/tmp}/ab_snap.XXXX"); cp ../example_bot.py ../mechfight.py "$SNAP/"; C=$SNAP/example_bot.py
CAUTIOUS=discipline,nochase,cover,outnumbered,hide
row() { r=$(SPEEDY_OFF="$2" python3 sim.py --candidate "$1" --tiers $E,$S,$V,$F --passive --late 300 --matches $N --jobs 24 --seed $SEED)
  echo "$r" | awk -v lab="$3" '/mean score/{s=$5" "$6" "$7" "$8} /mean place/{k=$NF} /died in/{d=$NF" zone / "$7" s"} /worst/{w=$4}
    END{printf "  %-30s score %-22s kills %-5s median death %-6s maxms %s\n", lab, s, k, d, w}'; }
echo "=== practice format, $N matches, seed $SEED"
row $V "" "v1 (submitted)"
row $C "" "v2 all on"
row $C "$CAUTIOUS" "v2 aggressive (cautious off)"
for f in zonefix nochase discipline outnumbered cover hide sticky heal reloadpush; do row $C "$f" "v2 without $f"; done
for f in zonefix sticky heal reloadpush; do row $C "$CAUTIOUS,$f" "aggressive without $f"; done
