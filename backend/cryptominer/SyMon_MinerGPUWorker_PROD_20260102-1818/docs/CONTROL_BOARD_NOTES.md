\
# Control Board Notes (Practical)

## 7007 vs 7010 naming confusion
A board can physically contain a Zynq-7007S SoC while the firmware family is labeled “7010 Xilinx.”
Bitmain labels often reflect the *platform family* (board generation) rather than exact silicon SKU.

## What you do with that
- Identify your board family by miner model + Bitmain’s firmware notes.
- Don’t cross-flash between generations.
