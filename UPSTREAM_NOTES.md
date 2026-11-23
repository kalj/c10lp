# Notes from the upstream repo (14sea/Cyclone_CRAM_Mapper), for the routing work

Read as data from the local clone (493 commits, last 2026-09-30), 2026-11-23. EP4CE6 numbers:
210-byte frames, 35 frames (7,350 bytes) per standard LAB column. Our 10CL016 has 255-byte frames.

## What they have for routing between LABs

- **Wire names from timing reports.** `fuzz/compile.py: extract_routing()` runs
  `report_timing -from A -to Q -detail full_path -show_routing -npaths 1` in `quartus_sta` and
  parses the Data Arrival Path rows (`type, location, element`). The elements are node names like
  `C4_X10_Y10_N0_I0`, `R4_X22_Y5_N0_I17`, `LOCAL_INTERCONNECT_X10_Y14_N0_I3`.
- **C4 (column wire, ~4 rows), I = 0 only:** verified on 63 wires. The switch bit sits at the LAB
  column's end + a slot base (2405 / 2475 / 2338 for (y−2) mod 3 = 0 / 1 / 2) + 3·((y−2) div 3),
  and the bit position falls with the group. That is the same row/slot structure as our LUT row
  model (`lutpos.ROW`). C4 I ≠ 0 and R24 write models are marked dead in their code: the mined
  cells landed on CRC bytes.
- **R4 (row wire, ~4 columns): 26/37 I-indices.** Each index is a pair of bits in the column
  *before* the wire's X ("PREV column"), at per-index base offsets. Converted to frames, the pairs
  sit at frames 13–18 of the column (e.g. I=0: frames 16/18, I=17: 13/15, I=20: 13/14). That's the
  same frame band as our neighbour-link driver bits (+16/+18, `li_neighbour.json`), so our
  "direct links" may be R4 drivers. The timing reports will tell. Their model fails at the wide
  columns next to M9K/DSP.
- **Clocks:** about 450 `clk_lab_sel_probe` files plus GCLK probes (`results/clk_*`). Not
  compared with our `gclk.json` yet.
- **Route synthesis:** a per-edge signature cache (13,562 entries, ~2.7% of LAB pairs; 96.5% of
  sinks have one mined source) and replay of observed cells, not formulas.

## Lessons to carry over

1. **Context dependence (their pitfall 14):** a route mined from a sparse design can fail inside
   a dense one, because the router used resources that are taken there. Codec evidence alone
   doesn't prove silicon function.
2. **Co-occurrence trap (R4 campaign spec):** hops in a chain change together in fixed bundles,
   so intersect/union over many builds can't isolate one hop, and a "driver end" anchoring that
   looked right was the neighbour hop. Their pass bar: (a) recover ≥3 already-known indices with
   the same method first; (b) isolate from a pair of designs differing in exactly one net;
   (c) ≥3 distinct columns vote the same bits, negatives < 8%; (d) no alias with a neighbouring
   column's index.
3. **Wrong-offset cross-LAB cells reset the FPGA on load (their pitfall 12),** not just a
   wrong function. Our gate (only declared cells, all CRCs valid) and SRAM-only loads cover this,
   but routing patches should keep using only cell values Quartus itself produced, until a model
   is validated.
4. **Separate infrastructure cells from the route (pitfall 16, bug #1):** I/O and clock cells got
   baked into route diffs and were then applied twice. Keep design pairs identical in pins and
   clocks.
5. **CRC-overlapping "cells" are artefacts:** two of their dead models came from cells on CRC
   bytes. Our CRC handling (core and periphery) excludes those.
6. **The end-to-end blocker on their side** was the I/O-to-fabric bridge and a router that
   wouldn't converge, not single-wire models. Relevant for the toolchain step later.

## Plan for our step 1, adjusted

- Use `report_timing -show_routing` (allowed) on two-LUT designs to label every hop.
- Start with dx = 1..4 row hops and dy = 1..4 column hops at fixed endpoints. Compare against
  their C4 I=0 and R4 base tables, converted to our frame size, as a cross-check.
- Single-net differencing with fixed endpoints and fixed pins (their pass bar), across ≥3 columns
  and rows.
- Silicon: only gate-checked files whose routing cells equal a Quartus build's, until a formula
  has passed blind prediction offline.
