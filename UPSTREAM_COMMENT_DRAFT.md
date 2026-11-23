<!-- DRAFT follow-up comment for 14sea/Cyclone_CRAM_Mapper#3. NOT posted. -->

A follow-up on your EP4CE6 "canon cells". I think they have a simple cause and a simple fix, and I
checked it against your own `results/golden_rbf_modeH/` files and cell addresses.

**What the goldens show** (`fuzz/bitstream.py` `LutCodec.from_cram_model` for the 16 cell
addresses; diffs exclude frame CRC bytes and the header):
- **0000 isn't a LUT.** mask0000 vs maskFFFF differs in 0 LUT cells and 1 bit elsewhere, so for a
  constant Quartus drops the LUT and its input routing and drives the pin from a constant.
- **The canon cells are input routing.** vs mask0000, 6996 and DEAD change 35–64 bits outside the LUT,
  and **the two sets are identical at all 14 positions**, so they don't depend on the function. The
  2-input 4444 changes 22–44, mostly the same bits. Against a 4-input base, 6996→DEAD touches only
  the 11 LUT cells, at 14/14 positions.
- **σ is chosen per mask, not per position.** Your cell addresses plus an input permutation explain
  the LUT cells of 6996, DEAD and 4444 at every position. But at 0/14 positions does one permutation
  explain both DEAD and 4444, and 5 different permutations occur for DEAD across the 14. A table
  keyed by (foff, fb8, group) can't capture that, which fits σ⁻¹ only being valid for symmetric masks.

**The fix:** put `.dont_touch("on")` on the `lcell_comb`. Then Quartus keeps the LUT and its 4
input routes even for 0000, and one compile with mask 0x008A (minterms a, a&b, a&b&c) identifies
the input permutation at that placement.

I rebuilt that at your 14 D1++ positions on the EP4CE6 (AX301 pins E16/M16/M15/E15 → G15;
`ce6probe.py` in https://github.com/kalj/c10lp):
- 0 bits outside the LUT for 008A/4444/DEAD/6996 vs 0000, at 14/14 positions;
- one permutation explains every mask, at 14/14;
- writing 4444, DEAD and 6996 from the 0000 build with the probe's permutation (plus frame CRCs and
  the header sum from my first post) is **byte-identical to Quartus for 42/42 files**. No σ⁻¹ table,
  no canon cells.

On the 10CL016 the same method holds at scale. On silicon (MKR Vidor 4000) it has been checked with:
100/100 random LEs; a 5-LUT design across the die; LUT→register designs; 8-state and 8-bit state
machines in a 2-LAB template; and a 24-bit counter at 48 MHz. All of these use functions Quartus
never compiled.

One caveat for bigger designs: in dense multi-LUT templates Quartus re-orders inputs *and*
re-routes per mask set, so there a probe build isn't routing-identical to the base. What works is
to read each LUT's permutation from the base build itself (asymmetric placeholder masks) and keep
the base's routing. Patched files are then not byte-identical to Quartus's own build of those
masks, but they are correct on silicon.

Two smaller observations, in case they're useful:
- **The LAB tile is the same on both dies at bit level** for what I could test. One LUT drives all four
  inputs of another in the same LAB, at 4 LABs per die. In coordinates relative to the LAB's slot-0
  LUT cells, the deterministic core is identical on the EP4CE6 and the 10CL016 (9 bits per dst slot,
  15/15 slots). The rest is pin-dependent routing that Quartus chooses differently.
- **Local-interconnect input muxes, decoded for LE-output sources (follow-up the same night):** with
  four sources at known slots per dst LUT (its asymmetric mask reveals which physical input each
  landed on), reading dst's select bits directly instead of diffing pairs gives a clean model. A
  58-entry (physical input, source slot) table, independent of the dst slot, predicts dst's select
  bits exactly in 1,276/1,276 held-out builds on the 10CL016 and in 80/80 builds on the EP4CE6. It's
  two-level: a group select in frames −12..−4 before the LUT plus a select in frame −3. Table:
  `li_local_table.json` in the repo above.
- **(Earlier pilot) Local-interconnect input muxes:** switching dst's inputs between two sources in the same LAB leaves
  a consistent core of 6–19 bits per (source slot, dst slot). It's in dst's own bytes 0..3 in the 16
  frames before its LUT, set by the source slot alone (two one-hot selects, one frame in −12..−9 and
  one in −8..−4). 92% of it is identical between the two dies. That may connect to your finding that
  LI is "not per-wire emittable": the encoding looks regular, but Quartus moves other lines around
  whenever one changes. So it can only be read out with designs that pin everything else.
