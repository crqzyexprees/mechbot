#!/usr/bin/env bash
# Squad-mode calibration: real practice results are starter 1.15, v1 2.96.
cd "$(dirname "$0")"
E=baselines/easy/example_bot.py S=baselines/starter/example_bot.py V=baselines/v1/example_bot.py F=baselines/fighter/example_bot.py
N=${N:-192}
row() { python3 sim.py --candidate $1 --tiers "$2" $3 --matches $N --jobs 24 --seed 11 | awk -v n="$4" '/mean score/{s=$5" "$6" "$7" "$8} /mean place/{k=$NF} /died in/{d=$5" "$6" "$7" "$8} END{printf "  %-8s score %-22s kills %-5s %s\n", n, s, k, d}'; }
while read -r label tiers opts; do
  [ -z "$label" ] && continue
  echo "=== $label  [$opts]"
  for c in $S $V; do row $c "$tiers" "$opts" "$(basename $(dirname $c))"; done
done <<CFG
easy/starter/v1/fighter,passive $E,$S,$V,$F --passive --late 300
easy/starter/v1/fighter,provoke $E,$S,$V,$F --late 300
easy/easy/starter/v1,passive $E,$E,$S,$V --passive --late 300
easy/easy/starter/v1,provoke $E,$E,$S,$V --late 300
CFG
