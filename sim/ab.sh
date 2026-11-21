#!/usr/bin/env bash
# A/B table: v1 baseline, v2 all flags on, and v2 with each flag off, against each opponent pool.
# usage: ./ab.sh [matches] [flags...]
cd "$(dirname "$0")"
N=${1:-384}; shift; FLAGS=${*:-zonefix nochase discipline outnumbered cover hide}
# snapshot the bot so edits made while this runs can't leak into later rows
SNAP=$(mktemp -d "${TMPDIR:-/tmp}/ab_snap.XXXX"); cp ../example_bot.py ../mechfight.py "$SNAP/"
S=baselines/starter/example_bot.py V=baselines/v1/example_bot.py C=$SNAP/example_bot.py
row() { r=$(SPEEDY_OFF="$3" python3 sim.py --candidate "$1" --opponents "$2" --matches $N --jobs 24 --seed 7)
  echo "$r" | awk -v lab="$4" '/mean score/{s=$5" "$6" "$7" "$8} /mean place/{p=$3} /died in/{d=$3" zone:"$NF} /worst/{w=$4}
    END{printf "  %-26s score %-22s place %-5s died %-12s maxms %s\n", lab, s, p, d, w}'; }
for pool in "$V" "$S,$V"; do
  echo "=== opponents: $(echo $pool | sed 's|baselines/||g; s|/example_bot.py||g')"
  row $V "$pool" "" "v1 (submitted)"
  row $C "$pool" "" "v2 all on"
  for f in $FLAGS; do row $C "$pool" "$f" "v2 without $f"; done
done
