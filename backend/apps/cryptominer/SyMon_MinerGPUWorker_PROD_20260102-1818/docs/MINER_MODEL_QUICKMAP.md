\
# Antminer Model Quick Map (Basic)

Use this as a fast “what family is this?” reference while you sort firmware.

## Rule 0
Always match firmware to **exact miner model** (T17 vs T17e vs T17+ etc) and to the **control-board family** when Bitmain calls it out.

## Families (high level)
- **S7 / S9 / T9 (legacy):** SD recovery common; older boot chain; upgrade scripts often include `runme.sh` style flows.
- **S15 / T15 (transitional):** Mixed behavior; some SD recovery; security tightening begins.
- **S17 / T17 (modern Zynq):** Signed packages; SD images are factory recovery, not normal upgrades.
- **S19 / T19+ (post-S17):** Same philosophy as S17/T17 with further lockdown.

## “fix_upgrade” packages
Usually a repair kit to restore the ability to upgrade (filesystem/overlay issues). Not a bypass tool.
