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

## Clock models compared (2026-11-23)

Their clock data (`results/clk_lab_sel_decomposed.json`, `clk_lab_sel_per_le.json`; GCLK_PIN /
LAB_CLK_SEL / LAB_CLK_SEL_LE in their CLAUDE.md) is a set of XOR signatures. Ours (`gclk.json`,
`ff_control.json`) is a structural model. Converted to (frame, byte, bit) with their own row model
(`config.cram_ctrl_addr` / `cram_ctrl_bit`):

- **Row clock select: same structure, same offset.** Each of their 13 LABs has exactly one
  LAB-specific cell in a spine frame pair (909/910 on the EP4CE6, ours 488/489 and 1593/1594). In
  4/13 LABs (X10Y2, X16Y4, X22Y4, X22Y10) it sits at the LAB row's LUT byte −63 in the LUT's own
  bit plane. That is the −1 bit of our row select (LUT byte −62 + {−1, 0, 5, 6, 7, 8}), found on
  silicon here. In the other LABs it sits elsewhere, consistent with our finding that the select
  pattern depends on which global clock the row uses (c0 {+5, +7}, c1 {+5, +8}, {−1}). Their probes
  let Quartus choose the global.
- **Shared region/tree blocks.** Their LAB sets fall into two groups that share a block of
  ~15–25 cells (frames 55–95 vs 196–235 plus a few far frames). Group A: X10 rows 2–6, 18, 21 and
  all four X16/X22 LABs (rows 4 and 10). Group B: X10 rows 8–16. It isn't a clean top/bottom split
  like our quadrant bits; it may reflect which global Quartus picked per probe as much as geometry.
  Not resolved.
- **Per-LE layer = whole-LE signature, not a clock bit.** Their `nN_specific` sets (46–63 cells)
  hold that LE's LUT cells (frames +1, +2, +5, +6), its input-mux codes (frames −12..−2), its
  output-select bits at frames +8/+9 (our comb/registered selects, consistent), and bits at frames
  +16/+18 (our neighbour-link / R4 driver band). They don't isolate a clock-select bit; ours is the
  per-register pair select at frame +11 (`ff_control.json`).
- **Per-pin layer.** Their GCLK_PIN sets (E1 = 3 cells, R8 = 5, N1 = 38) correspond to our per-side
  clock-control bits (40 global bits for 16 pins, grouped by side). Their docs list N1 apart from
  the "9 dedicated clock pins", and its much larger set suggests it's routed differently; I haven't
  checked which kind of pin it is.

Net: the two models agree where they overlap, and our structural model explains their signatures.
Nothing in theirs contradicts ours. Their data adds one more die where the row select sits at
LUT byte −62/−63, which suggests it's a family-wide layout.
