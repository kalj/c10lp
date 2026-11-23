# Cyclone 10 LP (MKR Vidor 4000) vs Cyclone_CRAM_Mapper: first-pass toolkit

Scripts for the first steps of extending
[14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper) (studied at
commit `221f790`, 2026-09-30) to the 10CL016 on the Arduino MKR Vidor 4000.
Everything here reads Quartus *output* only.

## What reading the repo and sources changed in the plan

1. **The repo is much further along than the project brief assumes.** It already has C4/R4/R24/LOCAL_INTERCONNECT
   switch models (partial), the carry chain (hardware-verified), M9K init/mode, GCLK, IOB
   directives, a Yosys → nextpnr-generic → FASM → RBF flow (hardware-verified for small
   designs), and a "ζ" path that rebuilds any Quartus RBF byte-for-byte (NEORV32 booted
   Linux from it). Per the README, FFs have **no per-LE enable bit** ("silicon default").
   The open gaps are **C16 (not started)**, 12–13 of 37 R4 I-indices, the M9K/DSP boundary
   columns, and a chipdb routing model too sparse for dense designs.
2. **The 10CL016 is not the die the repo mapped.** Everything in the repo is the
   EP4CE6 ≡ EP4CE10 die (they proved byte-identical RBFs, `fuzz/cross_device_diff.py`).
   Evidence that the 10CL016 is the EP4CE15/EP3C16 die instead:
   - JTAG IDCODE `0x020F20DD` is shared by 10CL016, EP3C16 and EP4CE15, while
     10CL006/10CL010 share `0x020F10DD` with EP4CE6/EP4CE10 (OpenOCD's table; `jtagconfig` output).
   - Intel support, citing the handbook, gives the 10CL010 uncompressed RBF as 2,944,088 bits
     = 368,011 B (= EP4CE6). A forum answer gives ~509 kB for the 10CL016.
   - awtoau/pluribus issue #173 gives EP3C16/EP4CE15 = **510,856 B, 255-byte frames,
     37 periphery + 1966 CRAM frames**. That is exactly 32 + 2003×255 + 59 B, the same
     preamble/frames/postamble layout as the CE6 die.

   So **the repo's absolute offsets (COLUMN_BASE, CRC frame range, header size) will not
   transfer to the Vidor.** What should transfer is the *structure*: XOR-linear LUT
   encoding, ctrl/data pairs one frame apart, the slot/group Y encoding, CRC-16/0x8005 per
   frame. Step 4 becomes "re-derive the constants for a second die", not "check positions match".
3. **The intended shortcut for the Vidor is a 10CL006 board, not a different method.** If
   step 3 confirms 10CL006 ≡ EP4CE6 byte-for-byte, *all* existing repo results apply to
   10CL006/10CL010 boards unchanged (Trenz/QMTech sell them). That is a cheap,
   high-value result for an upstream issue even before any 10CL016 mapping.

## Results so far (2026-11-22, Quartus Lite 21.1.1 Build 850)

**Silicon (2026-11-22 evening, `hwtest.py`, log `out/hwtest_20261122_164830.jsonl`):** all four
loads PASS on the MKR Vidor 4000, SRAM over the USBBlaster sketch with openFPGALoader. That covers
Quartus 8888 = a&b, the Quartus 0000 control held low, `lo_x8888.rbf` = a&b, and
`lo_x8888_X30Y20N12.rbf` = a&b. So:
- The 10CL016 **does not check the header sum V**. Patched files work with mask 0000's header.
  (`--fix-header` is still useful for byte-identity, but it isn't needed to load.)
- Hand-patched LUTs work on silicon, including one placed purely by the `lutpos.py` model.
- The same evening, with `sketch/VidorTestBench` driving D1..D4: `hwtest.py --auto all` passed 7/7
  files and 112/112 readings, including both 5-LUT files `multipatch.py` wrote for mask sets Quartus
  never compiled (log `out/hwtest_20261122_182259.jsonl`).
- **Silicon sweep (`silicon_sweep.py`, log `out/sweep_20261122_184703.jsonl`):** 100 random LEs, each
  with a random asymmetric mask written only by `lutpos.py` (plus the 0x008A probe permutation) and
  gated by `gate.py`. Result: **100/100 correct on silicon, 1600/1600 readings**. The all-zero
  control held D5 low all 5 times, and no readback mismatch occurred.
- **Clocked logic (`regtest.py`, log `out/regtest_20261122_201231.jsonl`):** a LUT feeding a register
  in the same LE (`xdev.py` design `reg:MMMM`), with the register fed back into the LUT, so
  next = mask(D1, D3, D4, state), clocked by D2 from the SAMD21, state on D5. The LUT is rewritten from
  the reg:0000 template and the 0x008A probe, at X10Y10N0 and X30Y20N12. Results: **12/12 files
  correct over 40 clocked steps each**, checking power-up low, the hold between edges and the next
  state after each edge. The files were Quartus's own random masks, plus 4 functions Quartus never
  compiled: toggle, D flip-flop, set/reset, majority. In an offline replay, no other tested mask
  would have given the same sequence.
- **State machines from a general template (`tpatch.py`, `fsmtest.py`, log
  `out/fsmtest_20261122_213010.jsonl`):** `templates/fsm3` has 3 registers and 4 LUTs. Quartus placed
  it once, `quartus_cdb --back_annotate=lc` pinned every cell, and one pinned base build is
  everything `tpatch.py` needs. Six 8-state machines written only by `tpatch.py` ran correctly on
  silicon, **6/6 over 60 clocked steps**: up-counter with enable, Gray up/down counter, XNOR LFSR,
  a 1011 sequence detector, and 2 random machines. In an offline mutation test, 507 of the 518
  wrong LUT input orders that change a function would have been caught (the rest only differ in
  states the inputs never reached).
- **Bigger templates (night of 2026-11-22):**
  - `templates/cnt8`: 18 LUTs + 8 registers across 2 LABs. 6/6 machines Quartus never compiled were
    correct over 80 clocked steps: up counter, up/down, shift register, Johnson counter, 2 random
    256-state machines (`cnt8test.py`).
  - `templates/div24`: a 24-bit counter on the Vidor's 48 MHz clock (iCLK, PIN_E2, input only), with
    setup slack 16.8 ns (`quartus_sta`). 6/6 patched variants ran at the expected D5 frequency,
    including a mod-3 low group (3.81 Hz instead of 2.86 Hz) and an enable-ignoring variant
    (`div24test.py`). Every measurement is 0.085% low by the same ratio: the SAMD21's clock is
    ~47.96 MHz.
- `templates/ring32`: 43 LUTs + 32 registers across 4 LABs. 5/5 32-bit machines (shift register,
    XOR ring, 3 random) were correct over 100 clocked steps each, with 96–101 distinct states
    (`ring32test.py`). In a mutation test, 650/656 wrong LUT input orders would have been caught.
- **Silicon sweep extended to 400 random LEs (6,400 readings), all correct.** A soak loaded those
  400 files three times each, about 1,160 loads in all. There was 1 failed load (JTAG timeout while
  the CPU was at load ~16; nothing was loaded) and 0 failures in about 1,150 loads on an idle machine.
  So don't compile while the board is in use. One of the new LEs
  showed a byte-wrap case the model didn't cover (see "Position model").
- openFPGALoader's `--detect` names the part "EP3C16/EP4CE15/10CL016", matching the same-die result.

Raw output: `report1.txt`. Compiles take ~12 s on both dies (the 20 s guess was pessimistic).

**Control.** Rebuilding the repo's own `build_d1_golden.py` design (X10Y2N0, masks 0000 and
DEAD) gives files **byte-identical** to `results/golden_rbf_modeH/`, although the repo used
21.1.0. 21.1.1 is safe to mix with the repo's corpus.

**Geometry.** 10CL016 = 510,856 B = 32 + 2003 × 255 + 59. CRC-16/0x8005 init 0xFE54 on
frames 37..2002 (1966 frames), frames 0..36 periphery. Exactly as predicted.

**Same die.** 10CL006 ≡ EP4CE6 and 10CL016 ≡ EP4CE15 (F17 and U14 packages). Within each pair
the files differ only in ~314 header/periphery bytes plus a fixed set of 12 CRAM bits that is the same for
every design, including the wire (a family-level setting; same pattern on both dies, different
offsets). LUT cells are absolutely identical within each pair. Package makes no difference;
`ce15u` (I7) differs from `ce15` (C8) only by 7 routing bits, likely the speed grade.

**LUT at X10Y10N0 on the 10CL016.** One bit per minterm, bit 5 of bytes 222/223 in frames
401..408 (see `lutpatch.py calibrate`). XOR-linear: hold-out masks 4444, 6996 and DEAD are
predicted exactly. Across dies the layout is the same shape (8 frames × 2 bytes × 1 bit) but the
minterm order differs, so constants must be re-mined per die.

**Header checksum (new; the repo treats these bytes as opaque).** Holds on all 103 RBFs here,
both dies, plus the repo's goldens:
- bit 0 of each byte 0x29..0x48 is one bit of a 32-bit value V, LSB first;
- bytes 0x49..0x4A = CRC-16/0x8005, init 0xFFFF, little-endian, over bytes 33..0x48;
- V is an *additive* checksum of the CRAM: on the 10CL016, every set data bit in frames 37..2002
  (CRC bytes and periphery frames excluded) adds `2^((2·L − frame) mod 8)`, where
  `L = byte + PLANE_START[bit]` (bit 7→0, 6→251, 5→502, 4→753, 3→1005, 2→1257, 1→1509, 0→1761),
  the same row space `lutpos.py` uses. With Vidor project settings, V = 133,509 + that sum. Fits 105
  single-bit builds and every whole-file pair tested, including routing changes
  (`lutpos.header_weight`).
- **Same structure on the EP4CE6 die** (210-byte frames): each set data bit in frames 25..1751 adds
  `2^((byte + s[bit] − frame) mod 8)`, with s = bit for bits 0..6 and s = 0 for bit 7. One constant
  per project setup: 26,084 for all 58 repo goldens and our rebuilds of that design, 26,120 for our
  Vidor-pin CE6 builds, and 28,310 for the 10CL006.

**10CL016 LAB grid** (fitter probes, `out/grid_scan*.json`): LAB columns X = 1..40 except
13, 18, 25, 34 (memory/multiplier columns, not yet told apart), rows Y = 1..28, plus a hole at
X1..9 × Y15..19. That is 36 × 28 − 45 = 963 LABs = 15,408 LEs, exactly the datasheet count.

Memory and multiplier columns, confirmed by pinning blocks with the fitter: **X13 and X25 are M9K**
(the wide ~295-frame columns), **X18 and X34 are 18×18 multipliers** (25 frames). 2 × 28 = 56
of each, matching the datasheet. The swapped placement is rejected as illegal.

**LUT position model** (`lutpos.py`): predicts the 16 cells of any LE from per-column frame
bases, per-row (byte, bit) and an N offset. Bytes 0 and 1 of a frame hold no LUT bits: a cell
whose byte falls below 2 wraps to the top of the frame, one bit plane up (+251 for planes ≥ 5, else
+252). This is per byte, so a pair can straddle, as at X36Y11N18 (bytes 1, 2). The *minterm order* within those cells is relative
to the LE's physical inputs, and Quartus routes A..D to them in a placement-dependent order
(20 different permutations seen; stable across masks at one LE for single-LUT designs with
`dont_touch`). So:
- symmetric masks (0000, FFFF, 6996, …) can be written at any LE from only its mask-0000 build;
- asymmetric masks need one probe compile of mask `0x008A` (minterms a, a&b, a&b&c) at that LE,
  which fixes the permutation. `lutpatch.py --model` reads it automatically and refuses
  asymmetric masks without it.

`lutpos.py --check` explains every build in `out/` (317 builds at 156 LEs, 16 input
permutations seen). My first "blind" test used 6996, which can't detect permutations. The
single-minterm builds caught it. Stress test (2026-11-22): 54 new LEs next to the M9K and multiplier
columns, around the X1..9 × Y15..19 hole and on the die edges, each with 0000, the 0x008A probe and a
random asymmetric mask. 0 mismatches.

`lutpatch.py write --fix-header` (with a sweep, or `--model` using the rule) gives output
**byte-identical** to Quartus: 149 builds at 150+ LEs (incl. 54 random asymmetric masks at
unseen LEs), from just the mask-0000 build (+ the 0x008A
probe for asymmetric masks). Run `python3 selftest.py` (~30 s, no Quartus) to re-check everything. Without the flag the header
keeps mask 0000's values (6–9 bytes differ). Loading that file tests whether the chip checks V.

### Multi-LUT patching (2026-11-22)

`xdev.py` design `tree:M0-M1-M2-M3-MF` has four first-level LUTs on D1..D4 at X10Y10N0, X30Y20N12,
X22Y8N6 and X36Y23N30, feeding a final LUT at X16Y21N14 that drives D5. Quartus builds it twice:
once with all masks 0000 and once with all 0x008A. The two builds have the same routing (0 bits
differ outside the LUT cells), and the probe identifies all five input permutations in one go.
`multipatch.py` then writes any five masks without compiling. Three random mask sets came out
byte-identical to Quartus's builds of them. The board-test files `out/lo_tree_atleast2.rbf`
(D5 = at least two of D1..D4 open) and `out/lo_tree_parity.rbf` (odd number open) use mask sets
Quartus never compiled. Run them with `python3 hwtest.py tree`: 16 readings per file, moving one
jumper per step.

### The repo's "canon cells" (EP4CE6, `ce6probe.py`)

The repo needs per-position "canon cell" tables for asymmetric masks. Its `golden_rbf_modeH`
files show why:
- The golden design has no `dont_touch`, so mask 0000 (and FFFF) have no LUT and no input
  routing at all. FFFF vs 0000 differs in 0 LUT cells and 1 other bit.
- Every non-constant mask adds its input routing. At all 14 positions, 6996 and DEAD add the
  identical extra-bit set vs 0000, and 6996→DEAD touches only the 11 LUT cells.
- The input permutation is chosen per mask. At 0/14 positions does one permutation explain both DEAD
  and 4444, so a table keyed by position can't capture it.

With `dont_touch("on")` and one 0x008A probe at the same 14 positions on the EP4CE6 (70
compiles), 4444/DEAD/6996 written from the 0000 build with the repo's own cell addresses are
**byte-identical to Quartus, 42/42**. Draft follow-up in `UPSTREAM_COMMENT_DRAFT.md` (not posted).

### LAB tile across the dies (`tilecmp.py`)

Design `lab2`: one LUT drives all four inputs of another in the same LAB, at 4 LABs per die. In
LAB-relative coordinates (offset from the LAB's slot-0 LUT cells), the deterministic core is
identical on the EP4CE6 and the 10CL016:
- moving the destination slot, 9 core bits per slot match for 15/15 slots, and 8/15 are identical
  outright;
- the differences are an LE output-select bit (frame +8, byte lo / lo+1 of the slot) and the source's
  pin-input routing, both of which Quartus chooses depending on where the pins are.

Vertical inter-LAB routes (src 1–4 rows away) were inconclusive with this method, because Quartus's
wire choices are pin-dependent. That needs controlled designs.

**Local-interconnect input muxes, a pilot (`muxmap.py`, 936 compiles).** Design `mux`: dst's four
inputs are switched between a source at slot a and one at slot 30, with both sources kept alive by a
keeper LUT. Build pairs differ in 15–66 bits, because Quartus also re-allocates other lines. But each
(a, d) has a consistent core of 6–19 bits shared by both 10CL016 LABs, and 92% of it is present on the
EP4CE6 (98% of the part in dst's own mux bytes). In dst-relative coordinates the core depends on the
source slot alone: 8/13 slots give one pattern for all 12 destinations. It is a pair of one-hot
selects in the 16 frames before dst's LUT (one frame in −12..−9, one in −8..−4), each on a byte
pair of dst's bytes 0..3. That looks like a two-level, sparsely connected input mux. Switching
only one input (`mux1`, `muxmap1.py`) yields little data: Quartus changes dst's input order between
the two builds in about half the pairs. **Decoded (`mux4map.py --full`, 1,360 `mux4` builds).** In design `mux4`, four sources at known slots
drive dst's four inputs, and dst's asymmetric mask reveals which physical input each landed on.
Reading dst's select region directly (bytes 0..3, frames −12..−2 relative to its LUT; odd LEs map
column c → 3−c) instead of diffing build pairs sidesteps Quartus's line re-allocation:
- every bit in that region is owned by exactly one physical input;
- one table that doesn't depend on the dst slot, with 58 (physical input, source slot) entries
  (`li_local_table.json`), predicts all 1,280 builds over all 16 dst slots at two 10CL016 LABs.
  Leave-one-(LAB, slot)-out: **1,276/1,276** held-out builds exact;
- the same table predicts **all 80 EP4CE6 builds** exactly, with physical inputs 0/1 relabelled
  between the two cell-order conventions;
- the structure is two-level: a group select in frames −12..−4 plus a select in frame −3. Inputs
  1↔2 and 0↔3 are mirror images.

Not covered yet: sources from outside the LAB (LAB lines fed by row/column wires or pins). Writing these
bits on silicon also isn't covered, because it would be a hand-made routing change, which the board
rules forbid without a separate decision.

### General templates (`tpatch.py`)

Any netlist of `cyclone10lp_lcell_comb` instances plus registers on D1..D4 → D5 can be a template
(`templates/NAME/top.v`). `tpatch.py init NAME` compiles it once, back-annotates every logic cell
into `templates/NAME/locs.qsf` (committed, so the placement is reproducible) and builds the
pinned base. Lessons from `fsm3`:
- **The all-0000 template doesn't work for feedback designs.** Quartus optimises away registers that
  can never leave 0, which changes the routing. The base uses the masks written in `top.v`.
- **Quartus re-orders LUT inputs per mask**, re-routing as it goes. A 0x008A probe build was
  re-wired relative to the base, and so were all 6 random mask sets in `tpatch.py check`. So
  `tpatch.py` reads each LUT's input order from the base build alone. This needs asymmetric
  placeholder masks (`lutpos.unique_perm_mask`; about 66% of all masks qualify). Patched files keep
  the base's wiring.
- So for dense templates, files can't be checked byte for byte against Quartus. Quartus's
  re-wired builds still fit the position model (6/6), `gate.py` guarantees the file equals the base
  outside the LUT cells, and correctness is shown on silicon.

### Flip-flops (pilot, 2026-11-22, 41 builds)

- `xdev.py` designs `ff:base|hi|ena|sclr` pin one register with `FF_X{x}_Y{y}_N{odd}`. Quartus Lite
  21.1.1 honours it on the 10CL016 (the repo found `LCFF_*` rejected on its version).
- At all 16 LEs of X10Y10 and X30Y20, using the FF sets one bit in frame (LUT base + 11) at
  byte lo+3 (even LE) or lo−2 (odd LE), where lo is the low byte of that LE's LUT pair and the bit is
  the LUT's bit. It is clear when the FF sits at another N. This is a candidate "register output
  used" bit. X30Y20 also sets lo / lo+1 in the same frame when D bypasses the LUT. At X10Y10, Quartus
  sent D through the LUT instead (half the LUT bits set). Both are hypotheses until tested on more LEs. Update: in the two `reg:` templates, the FF-use
  bit marks exactly the pinned slots, N1 and N13.
- **Checked at 40 more random LEs (72 `ff:base` builds in all):**
  - **Bypass bit** (frame LUT base + 11, byte lo / lo+1 for even / odd LE, the LUT's bit): set in all
    24 builds where D skips the LUT, clear in all 48 where Quartus routed D through the LUT (half the
    LUT bits set). It reads as "register D comes straight from LAB routing".
  - **"Register used" bit** (same frame, byte lo+3 / lo−2): set at the register's LE and clear at the
    other 15 LEs of the LAB in 71/72 builds. The exception, X11Y4N25, has the register exactly there
    (back-annotation confirms it, and a rebuild is byte-identical) but the bit clear. So this is
    better read as one of the LE's **output selects** (register vs combinational output on one
    output path). That fits the repo's EP4CE6 finding that the FF is always present and that its
    use is decided by routing. At X11Y4N25 the register probably leaves through the other output
    path, whose select isn't mapped yet.
- Power-up high has no per-LE bit. Quartus uses NOT-gate push-back: the LUT inverts D and the
  output inversion goes elsewhere (map report: "NOT Gate Push-Back On").
- Enable and sync clear are LAB-wide control signals: about 20 LAB-local bits each, plus routing.
  Not separated yet.

## Files

| File | What it does | Tested here |
|---|---|---|
| `rbfgeom.py` | Infers frame size, CRC init and CRC-covered frames from any uncompressed RBF (solves the init over GF(2) from one frame); region-aware diff across devices | On the repo's EP4CE6 golden RBFs it independently recovers 1752×210 B, init 0xFE54, CRC frames 25..1751, which matches the repo. Synthetic 210/255/298-byte-frame dies pass |
| `xdev.py` | Quartus campaign driver: `parts`, `plan`, `build`, `sweep`, `report`. Caches RBFs, records timings, prints estimates | Project generation plus a stub Quartus; report/control path checked against repo goldens. **Not yet run with real Quartus** |
| `lutpatch.py` | Calibrates the LUT codec at one LE from a 17-compile sweep, verifies XOR-linearity against other masks, writes any mask and re-patches CRCs with the inferred init | On a synthetic 255-byte-frame die: verify MATCH, written RBF has 0 data-bit diffs vs the "Quartus" one, CRCs valid |
| `lutpos.py` | 10CL016 LUT position model: (X,Y,N) → 16 (frame, byte, bit) cells; `--check` against all builds | 124/124 builds match |
| `selftest.py` | Re-checks every result above against cached builds, no Quartus (`--out DIR`; SKIPs what isn't built) | 14/14 PASS |
| `multipatch.py` | Rewrites all LUTs of a multi-LUT Quartus template (default: xdev `tree:` design, 5 LUTs across the die) from two builds (all-0000 template + all-008A probe) | 3/3 random mask sets byte-identical to Quartus |
| `sketch/VidorTestBench` | USBBlaster example + serial test bench (drive D1..D4, read D5) for `hwtest.py --auto` | sanity check + `--auto all` 7/7 PASS, 112/112 readings (2026-11-22) |
| `corpus.py` | Rebuild/verify the 4,314-build Quartus corpus from `corpus.json`, regenerate the hardware-test files | 4314/4314 verified; 6 rebuilt from scratch identical |
| `regtest.py` | Clocked silicon test: patched LUT → register with feedback, stepped by the test bench | 12/12 files, 40 clocked steps each |
| `tpatch.py` | General template patcher: back-annotated placement, input orders from the base build, any LUT masks | fsm3: 6/6 state machines on silicon |
| `fsmtest.py` | Clocked test of 8-state machines written into `templates/fsm3` | 6/6, 60 steps each |
| `templates/` | Template designs (`top.v`) and their back-annotated placement (`locs.qsf`) | fsm3 |
| `cnt8test.py`, `div24test.py`, `ring32test.py` | Silicon tests for `templates/cnt8` (8-bit machines, 2 LABs), `templates/div24` (48 MHz counter) and `templates/ring32` (32-bit machines, 4 LABs) | 6/6, 6/6, 5/5 |
| `ce6probe.py` | EP4CE6: `dont_touch` + one 0x008A probe vs the repo's canon cells, at its 14 golden positions | 42/42 byte-identical |
| `tilecmp.py` | Compares LAB-relative routing bits between the EP4CE6 and 10CL016 dies (`lab2` designs) | intra-LAB core identical |
| `muxmap.py`, `muxmap1.py`, `mux4map.py` | Intra-LAB LUT-input mux encoding (`mux`, `mux1`, `mux4` designs; data only). `mux4map.py --full` writes `li_local_table.json` | 1,276/1,276 held-out builds; EP4CE6 80/80 |
| `gate.py` | Pre-load safety gate: a patched file may differ from its Quartus template only in declared LUT cells, frame CRCs and the header sum/CRC | 5 good files pass, 4 negative cases fail |
| `silicon_sweep.py` | Model-written random masks at many random LEs, gated, then loaded and tested by the test bench | 400/400 LEs correct on silicon (6,400 readings) |
| `hwtest.py` | Guided first hardware test: loads the `lo_*` files to SRAM, logs your D5 readings | dry run only |
| `UPSTREAM_ISSUE.md` | Text of [14sea/Cyclone_CRAM_Mapper#3](https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3) as posted | posted 2026-11-22 |
| `vidor_pack.py` | RBF → bit-reversed `app.h` array for Arduino's flash route; `--check-ttf` to confirm the .ttf/.rbf relationship | Logic only |

Python 3.10+, no dependencies. `QUARTUS_BIN` defaults to `~/intelFPGA_lite/21.1/quartus/bin`.
Use **21.1 (Lite)** if you can, because the repo's whole corpus is Quartus 21.1. A different
version may change the bitstream. The control builds will tell you either way.

## Reproducing

Everything above can be rebuilt from this repo, the original mapper and Quartus. No files from me
are needed: RBF/SOF files aren't committed. `corpus.json` lists every build behind the results
(device, design, LE, pin variant) with the SHA-256 that Quartus produced here.

**You need:**
- Quartus Prime Lite 21.1 with Cyclone IV E and Cyclone 10 LP support. 21.1.1 Build 850 was used
  here. Set `QUARTUS_BIN` if it isn't in `~/intelFPGA_lite/21.1/quartus/bin`.
- Python 3.10+, standard library only.
- [14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper) cloned next to this
  repo, for the control and its golden files.

```bash
git clone https://github.com/14sea/Cyclone_CRAM_Mapper
git clone https://github.com/kalj/c10lp && cd c10lp
python3 selftest.py            # before any build: everything SKIPs except the header CRC check
python3 corpus.py plan --jobs 6   # 4,314 compiles: ~3.5 h at 6 parallel (~7.5 h at 2)
python3 corpus.py build --jobs 6
python3 corpus.py verify       # expect 4314 identical
python3 corpus.py derived      # out/lo_* hardware-test files, out/sweep/, out/reg/, out/fsm/; no Quartus
python3 selftest.py            # expect 14 PASS
```

- **Partial runs:** `--only PREFIX` builds a subset, e.g. `--only c10_016__lut0000_X10Y10N0` or
  `--only ce6__`. `selftest.py` skips the checks whose builds are missing.
- **Determinism:** 6 builds recompiled from scratch (repo control, 10CL006, 10CL016 LUT, the
  5-LUT tree, an FF build) matched `corpus.json` byte for byte.
- **Other Quartus versions:** `verify` reports which files differ. The control check in
  `selftest.py` (rebuild vs the repo's 21.1.0 goldens) tells you whether that matters.

**On the board** (Vidor with `sketch/VidorTestBench` uploaded, nothing on the header; see
"Loading bitstreams on the Vidor" below):
```bash
python3 hwtest.py --auto all          # 7 files x 16 input combinations, ~1 min
python3 silicon_sweep.py board        # 100 model-written LEs, ~13 min (needs the sweep builds)
python3 regtest.py write && python3 regtest.py board   # clocked LUT->register test, ~2 min
python3 fsmtest.py write && python3 fsmtest.py board   # 8-state machines in templates/fsm3, ~1 min
```

## Step-by-step exploration (how this started)

The commands below are the original plan, kept for the record. `corpus.py` is the faster way to
get the same builds.

```bash
python3 xdev.py parts                    # confirm part names (EP4CE15U14?? etc.)
python3 xdev.py plan                     # 18 compiles, ~3 min estimated at 2 parallel
python3 xdev.py build --jobs 2
python3 xdev.py report --repo ~/src/Cyclone_CRAM_Mapper > report1.txt
python3 rbfgeom.py info out/c10_016__wire__vidor.rbf
```

What `report` answers:
- **Control:** whether your CE6 rebuild of the repo's `X10_Y2_N0` 0000/DEAD pair has
  the same LUT cells as the repo's golden files (and whether it is byte-identical).
- **Geometry:** whether 10CL016 really is 510,856 B / 255-byte frames, and its CRC init.
- **Same die?:** `ce6` vs `c10_006` and `ce15` vs `c10_016` (and `ce15u`, same U256 package)
  diffs, split into header / CRAM / CRC regions. Package differences (F256 vs U256)
  should only show up in I/O bits, if they show up at all.
- **LUT bits:** the 0000→FFFF / 0000→8888 pair-diffs in (frame, byte-in-frame, bit)
  coordinates, compared across devices, both absolute and as a relative shape.

If `ce15` vs `c10_016` is byte-identical (or differs only in the header), the Cyclone IV
side of Quartus becomes a second view of your chip (the same trick the repo used with CE10).

Then the 10CL016 LUT calibration:
```bash
python3 xdev.py sweep --device c10_016 --loc 10,10,0 --dry-run   # 17 compiles
python3 xdev.py sweep --device c10_016 --loc 10,10,0
python3 lutpatch.py calibrate --device c10_016 --loc 10,10,0
python3 lutpatch.py verify    --device c10_016 --loc 10,10,0   # vs FFFF, 8888
python3 lutpatch.py write     --device c10_016 --loc 10,10,0 --mask 6996 -o x6996.rbf
```
X=10/Y=10 is a guess at a legal LAB on the 10CL016. If the fitter rejects it, change `--loc`.
Mapping the 10CL016 LAB grid (the repo's jailbreak probe) is a natural next script once
we've seen the first real compile times.

**Time estimates.** The repo measured 9–10 s per compile on the CE6 die. I assumed ~20 s
for the 10CL016 until real numbers exist; `plan` and `build` replace the assumption with
the median of your own compiles. Step 3 (18 compiles) is about 3 min. The sweep (17) is
about 3 min. For scale, the repo's 12,000-compile route factory would be ~33 h at 2 parallel.
I'll estimate each campaign before you run it.

## Loading bitstreams on the Vidor

The SAMD21 is wired to the FPGA's JTAG pins. The board's JTAG header is not fitted.

**Route A (recommended for fuzzing): SRAM over JTAG via a USB-Blaster emulator on the SAMD21.**
Volatile, fast, no flash wear, and power-cycling restores the Arduino image from flash.
0. Already in place on this machine: `openFPGALoader` (knows IDCODE 0x020f20dd) and its udev
   rules for `09fb:6001` (group `plugdev`, which you're in). Still missing: the SAMD core and the
   library. Install them with
   `arduino-cli core install arduino:samd && arduino-cli lib install USBBlaster`, then
   `arduino-cli lib examples USBBlaster` shows the example sketch path to compile/upload with
   `-b arduino:samd:mkrvidor4000`.
1. Arduino IDE → Library Manager → **USBBlaster** (Arduino's emulator for the MKR Vidor 4000,
   shipped precompiled). Upload its example sketch. The forum release notes say it needed
   SAMD core 1.6.25. If a newer core fails, try that version.
   Open-source alternative: [sameer/usbd-blaster](https://github.com/sameer/usbd-blaster)
   (Rust, last updated 2020, flashed with `bossac` after a double-tap reset).
2. On Linux the board should enumerate as `09fb:6001`. Add a udev rule for it.
3. `openFPGALoader -c usb-blaster --detect` should report IDCODE `0x020f20dd`.
   (The repo needed a source-built openFPGALoader for the CE6 IDCODE. The 10CL016's is
   probably known already, since openFPGALoader supports a QMTech 10CL016 board.)
4. `openFPGALoader -c usb-blaster out/c10_016__lut8888_X10Y10N0__vidor.rbf`
   (`quartus_pgm -m jtag -o "p;file.sof"` also works through the emulator).
5. To go back to normal Arduino use: double-tap reset, then upload any sketch.

**Route B: Arduino's flash route** (for persistent demos only). Arduino embeds the
bit-reversed bitstream in the sketch's `.fpga_bitstream` section. The bootloader sends it over
JTAG to the boot image in the FPGA, which writes it to the QSPI user area after the 512 kB
boot image. Use `vidor_pack.py` for patched RBFs, but run `--check-ttf` against one Quartus
build first.

**First hardware test.** You need a USB cable, a multimeter (D5 to GND) *or* an LED with a 330 Ω
series resistor from D5 to GND, and a jumper wire or two. D1/D2 have weak pull-ups, so leaving them
unconnected = 1 and a jumper to GND = 0. Expect D5 = D1 AND D2: 3.3 V with nothing connected, 0 V when
either one is grounded. D3/D4 don't matter. Never connect D5 to anything but the meter/LED.

These test files drive D5 at the I/O standard's **minimum current strength** (pin variant
`vidorlo`), to limit the current if the SAMD21 ever drove the same pin.

**No jumpers, no meter: `python3 hwtest.py --auto all`** (`--port` if not /dev/ttyACM0). Upload `sketch/VidorTestBench` instead of
the plain USBBlaster example:
`arduino-cli compile -u -p /dev/ttyACM0 -b arduino:samd:mkrvidor4000 sketch/VidorTestBench`.
It is the same USB-Blaster plus a serial test bench on `/dev/ttyACM0`: the SAMD21 drives D1..D4
and reads D5 itself, through all 16 input combinations for every file. Safety rules:
- D5 is never driven by the SAMD21.
- D1..D4 are driven only between a successful load and the next load. They are inputs while
  loading and after power-up.
- If the D1..D4 readback ever disagrees with what was driven (another driver on the pin), the
  sketch is disarmed at once and the run stops.
Disconnect any meter/LED/jumpers on D1..D4 first.

**Manual: `python3 hwtest.py`.** It checks the USB-Blaster and IDCODE, loads each file into SRAM
only (never flash), asks what D5 reads for the four D1/D2 combinations and logs the answers to
`out/hwtest_<time>.jsonl`. `python3 hwtest.py --check` runs only the preflight checks. It follows
this order:
1. `out/lo_quartus_8888.rbf` (Quartus's own build). This tests the setup.
2. `out/lo_quartus_0000.rbf` (Quartus, constant 0). D5 must read low. An unconfigured FPGA leaves D5
   floating with a weak pull-up, which a meter also reads as high, so this low reading proves the
   chip is really configured.
3. `out/lo_x8888.rbf` (patched from mask 0000, header checksum stale). This tests whether the chip
   checks the header.
4. If 3 works: `out/lo_x8888_X30Y20N12.rbf` (patched by the position model at a far-away LE, stale
   header). This tests `lutpos.py` on silicon.
   If 3 fails: `out/lo_x8888_hdr.rbf` (header fixed; byte-identical to 1).

## Hazards (read before flashing)

- **Every MKR header pin is also a SAMD21 GPIO.** The test designs drive only D5 (`PIN_T2`).
  Checked 2026-11-22: the D1–D5 ↔ N3/P3/R3/T3/T2 mapping matches Arduino's
  `VidorFPGA/constraints/MKRVIDOR4000/vidor_s_pins.qsf`. All unused FPGA pins are tri-stated
  inputs with weak pull-ups (Quartus default; see the `.pin` report). The USBBlaster example sketch
  has no pinMode/digitalWrite on header pins, but its JTAG code is a precompiled library and
  couldn't be read.
  Make sure the loaded SAMD21 firmware leaves D1–D5 as inputs, and put a ≥330 Ω resistor in
  series with any LED or meter. Don't flash designs that drive other Vidor pins (HDMI,
  SDRAM, flash, NINA, SAM_INT) until you've checked what's on the other end.
- **Only flash LUT-mask patches at first.** Repo lesson: hand-built routing bits caused
  driver contention and protective resets on silicon. Keep routing patches gold-anchored
  (byte-identical to a Quartus build) until a model is proven.
- A Quartus RBF plus Quartus's `.sof` can always be loaded through Route A as a known-good
  recovery. Power-cycling also reloads Arduino's image from flash.

## Legal notes (I'm not a lawyer)

- The Quartus Prime Lite licence (25.1std, as quoted in pluribus #165) forbids decompiling or
  reverse-engineering *the software* "except as otherwise permitted by applicable law".
  Nothing here touches Quartus binaries or databases. It only compiles designs and diffs the
  output files, the same black-box method the CRAM mapper uses.
- In the EU (you're in Sweden), Software Directive 2009/24/EC Art. 5(3) lets a licensed user
  observe, study or test a program's functioning while running it, and Art. 8 voids contract
  terms contrary to it. That supports black-box fuzzing. It does not cover disassembling
  Quartus or decoding its device-database files, so stay out of those.
- The same licence has a clause against publishing benchmark/test results of the software
  without permission (2.2.8, flagged but unexamined in pluribus #165). Our results describe
  the device's bitstream, not Quartus's performance, but read the clause in your installed
  licence before publishing.
- Don't commit RBF/SOF blobs to the PR. Commit scripts and derived facts. The repo itself says
  redistribution of its blobs "remains subject to Altera/Intel's original terms".

## Suggested contribution sequence

1. **Done:** posted as [#3](https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3) on 2026-11-22.
   Originally planned as: issue "Cross-die results: 10CL006 vs EP4CE6, 10CL016 vs EP4CE15" with the `report`
   output, IDCODE/size evidence and the 255-byte-frame geometry, asking whether the author
   wants multi-die support upstream (the repo hard-codes `DEVICE`, sizes and CRC frame
   ranges in `config.py` / `bitstream.py`).
2. Only then: PR adding a device-geometry abstraction (`rbfgeom.py`-style inference) plus
   Vidor loading docs. Mapping work on the 10CL016 (LUT constants first) goes in after the
   author agrees on structure.
3. Gap to offer: **C16** is the one wire class with zero coverage, and the method should
   carry over between dies. Coordinate with the author before starting, because they appear to be active
   (commits through 2026-09-30).
