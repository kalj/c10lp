# c10lp: bitstream mapping for the Cyclone 10 LP 10CL016 (Arduino MKR Vidor 4000)

Black-box mapping of the 10CL016's configuration bitstream, extending
[14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper) (EP4CE6) to the chip on the
Arduino MKR Vidor 4000. The method is the same: compile tiny designs with Quartus Prime Lite, diff
the uncompressed RBFs, and model what changes. Nothing here reads Quartus binaries or databases.

**Status (2026-11-23):**
- **Die identity:** the 10CL016 is the EP4CE15 die, and the 10CL006 is the EP4CE6 die.
- **Header checksum:** decoded on both dies. The chip doesn't check it.
- **LUTs:** any LUT at any LE can be written without Quartus (position model plus an input-order
  probe). Checked at 400 random LEs on silicon.
- **Templates:** a Quartus-placed design (including from Verilog via Yosys) can have its LUT
  contents, and some intra-LAB connections, rewritten without Quartus. Checked on silicon with
  designs up to 43 LUTs and 32 registers across 4 LABs, and at 48 MHz.
- **Intra-LAB routing:** the LUT-input selects for LE-output sources are decoded. Each LE's local
  line reaches exactly two of a LUT's four inputs directly. Rewires based on that rule were
  predicted right in 40/40 blind silicon tests.
- **Memory:** M9K ROM and RAM initial contents can be written without Quartus (all 7 layouts,
  byte-identical to Quartus; correct on silicon, including RAM writes by the design).
- **Arithmetic mode:** the LUT model for carry chains is decoded (sum and carry from one mask) and
  verified on silicon, at three LABs. The carry-in select bit is found offline.
- **Flip-flop controls (offline):** per-register sync clear/load, async clear and enable-line select
  bits are located and consistent across LABs.
- **Neighbour-LAB links (offline):** the dst-side select code for a net from the adjacent LAB depends
  only on direction and source slot (94/96 blind).
- **LAB control lines and LE outputs (offline):** the control-line mux from local LEs and the
  per-LE comb/registered output selects are located.
- **Open:** general routing between LABs (row/column wires),
  routing of pins onto control lines, and all offline-only bits on silicon.

The chronological record, with every campaign, log file and decision, is in
[`NIGHT_LOG.md`](NIGHT_LOG.md). Discussion with the original mapper's author is in
[issue #3](https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3).

## Quick start

```bash
git clone https://github.com/14sea/Cyclone_CRAM_Mapper      # golden files for the control
git clone https://github.com/kalj/c10lp && cd c10lp
python3 selftest.py                    # re-checks every result from cached builds (SKIPs without them)
python3 corpus.py build --jobs 6       # rebuild the Quartus corpus (see "Reproducing")
```

Write a LUT at any LE (after one mask-0000 and one 0x008A probe build there):
```bash
python3 xdev.py build --device c10_016 --design lut:0000 --design lut:008A --loc 30,20,12 --no-control
python3 lutpatch.py write --device c10_016 --loc 30,20,12 --model --mask 8888 -o x.rbf
```

From Verilog (ports A, B, C, D → Q; registers clocked by B):
```bash
python3 v2bit.py init  examples/cnt4rom.v mydesign        # Yosys + one Quartus placement (2 compiles)
python3 v2bit.py write edited.v mydesign -o x.rbf          # no Quartus, if the netlist shape is unchanged
python3 v2bit.py board edited.v mydesign x.rbf             # load to SRAM and check against a simulation
```

## Results

### Die identity and geometry

- **Control:** the repo's own `build_d1_golden.py` design (X10Y2N0, masks 0000/DEAD) rebuilt with
  Quartus 21.1.1 is **byte-identical** to its 21.1.0 goldens. The two versions can be mixed.
- **Geometry:** 10CL016 RBF = 510,856 B = 32 + 2003 × 255 + 59. CRC-16/0x8005 (reflected), init
  0xFE54, over frames 37..2002; frames 0..36 are periphery. EP4CE6: 368,011 B, 1752 × 210,
  CRC frames 25..1751.
- **Same die:** 10CL006 ≡ EP4CE6 and 10CL016 ≡ EP4CE15 (F17 and U14 packages). Each pair differs only
  in ~314 header/periphery bytes, plus a fixed set of 12 CRAM bits that is the same for every design.
  The LUT cells are identical. `openFPGALoader --detect` names the part "EP3C16/EP4CE15/10CL016".
  So all of the repo's EP4CE6 results apply to 10CL006/10CL010 boards unchanged.
- **LAB grid:** LAB columns X = 1..40 except 13, 25 (M9K) and 18, 34 (18×18 multipliers), with
  rows Y = 1..28 and a hole at X1..9 × Y15..19. That is 963 LABs = 15,408 LEs, the datasheet
  count.

### Header checksum

Bytes the repo treats as opaque. These rules hold on every RBF here (5,000+, both dies):
- bit 0 of bytes 0x29..0x48 holds a 32-bit value V, LSB first;
- bytes 0x49..0x4A = CRC-16/0x8005, init 0xFFFF, little-endian, over bytes 33..0x48;
- **10CL016:** V = constant + Σ over set data bits in frames 37..2002 (excluding CRC bytes) of
  `2^((2·L − frame) mod 8)`, with `L = byte + PLANE_START[bit]` (bit 7→0, 6→251, 5→502, 4→753, 3→1005,
  2→1257, 1→1509, 0→1761). `lutpos.header_weight`; the constant is 133,509 for the Vidor project
  settings;
- **EP4CE6:** each set data bit in frames 25..1751 adds `2^((byte + s[bit] − frame) mod 8)`, with
  s = bit for bits 0..6 and 0 for bit 7. There is one constant per project setup (26,084 for all 58 repo
  goldens).

The 10CL016 **doesn't check V** on silicon. Patched files load fine with a stale header.
`--fix-header` makes them byte-identical to Quartus anyway.

### I/O periphery (offline, `io:` design, `periph.py`)

Frames 1..36 hold the I/O configuration. They form one byte stream of 9 logical 255-byte frames,
with every byte stored 4 times in a row, and each logical frame ends in the same CRC-16 as the core
frames (414/414 checked). In the header sum, a logical bit (frame k, byte p, plane b) weighs
2^((p + 4k + c_b) mod 8), with one offset c_b per plane, fitted on all 138 legal input pins. With that, `periph.py` rebuilds all 15 Quartus I/O variants from one base
byte for byte. Each variant changes one setting:

- pull-up and bus hold: one bit each per pin, adjacent bytes;
- drive strength and I/O standard: a few bits per output pin;
- minimum current is the same as 4 mA, and 8 mA is the LVTTL default.

The `vidorlo` hardware files differ from `vidor` only in Q's 6 drive-strength bits (11/11 build pairs). The weak pull-up is one
bit per pin, located for all 138 pins Quartus accepts as inputs here (`io_pullup.json`), and toggled
byte-identical to Quartus both ways at every pin. The other settings sit at fixed offsets from it
(`io_tile.json`): bus hold at −1, open drain at −4, output enable from the core at +1 (9/9 pins each), and
the 8 → 4 mA drive change at +5..+17 bytes, which predicts
137/137 output pins. The periphery stream uses bytes 1..252 of each logical frame and then continues in
the next frame. Nothing here
has been tested on silicon, and `gate.py` still refuses any periphery change.

### LUT position model (`lutpos.py`)

- **Layout:** a LUT is 8 consecutive frames × 2 adjacent bytes × 1 bit, XOR-linear in the mask.
  The frame base steps 35 per LAB column, with gaps at the memory/multiplier columns.
- **Y and N:** Y moves (byte, bit) in 70-byte steps down the frame, wrapping into the next bit
  plane. N shifts the byte pair by −2 within an LE pair, by −8 per pair, and by an extra −6 after LE
  7. Odd LEs swap the two bytes.
- **Byte wrap:** bytes 0 and 1 of a frame hold no LUT bits. A cell whose byte falls below 2 wraps
  to the top of the frame, one bit plane up (+251 for planes ≥ 5, else +252), per byte.
- **Input order:** the minterm order follows the LE's *physical* inputs, and Quartus picks the input
  order per placement (20 different orders seen). Symmetric masks can be written from the mask-0000
  build alone. Asymmetric masks need one probe compile with mask **0x008A** (minterms a, a&b, a&b&c),
  which identifies the order.
- **Accuracy:** the model explains **719/719 LUT builds at 556 LEs**. `lutpatch.py --model
  --fix-header` output is byte-identical to Quartus for 149 builds, including random asymmetric masks
  at LEs the model had never seen.

### Templates and patching

- **`multipatch.py`:** rewrites every LUT of a fixed multi-LUT template (5 LUTs across the die) from
  an all-0000 build plus an all-0x008A probe. It reproduces Quartus byte for byte (3/3 random mask
  sets).
- **`tpatch.py`:** works with any netlist of `cyclone10lp_lcell_comb` instances plus registers
  (`templates/NAME/top.v`). Quartus places it once, `quartus_cdb --back_annotate=lc` pins every cell
  (`locs.qsf`, committed), and one pinned base build is all that's needed. Lessons:
  - the base uses the masks written in `top.v`. An all-0000 base lets Quartus optimise away
    feedback registers;
  - in dense templates Quartus re-orders LUT inputs **and** re-routes for every mask set, so a probe
    build isn't routing-identical to the base. `tpatch.py` therefore reads each LUT's input order
    from the base build itself, which needs asymmetric placeholder masks
    (`lutpos.unique_perm_mask`). Patched files keep the base's routing. Quartus's own builds of
    other mask sets can't be compared byte for byte, so correctness is shown on silicon.
- **`v2bit.py`:** Verilog → Yosys (`synth -flatten; abc -lut 4`) → LUT4/flip-flop netlist → tpatch
  template → bitstream.
  - **Edits:** `write` accepts an edited design if its netlist matches the template up to relabelled
    nets, register order and LUT input order (a small isomorphism search). It also accepts up to 2 LUT
    inputs with a different source when the direct-rewire rule allows it (see below).
  - **Refusals:** otherwise `write` refuses with the reason. Typical causes are a different compare
    constant, or a table that ignores some state bits.
  - **Template details:** unused LUT inputs get masks that ignore them (an undriven input reads 1),
    and registers are `(* noprune *)` because Quartus drops registers that nothing reads.

### Silicon validation

All on the Vidor, SRAM loads over Arduino's USBBlaster library, D5 at minimum drive strength, with
the SAMD21 test bench driving D1..D4 and reading D5 (see "Hardware"). Every file passed `gate.py`
before loading. Every run reloaded a Quartus all-zero control that had to hold D5 low.

| Test | Script | Result |
|---|---|---|
| Patched LUT, stale header; LUT placed purely by the model | `hwtest.py` | 4/4 (manual), 7/7 files × 16 combinations (auto) |
| Random LEs, random asymmetric masks written by the model | `silicon_sweep.py` | **400/400 LEs**, 6,400 readings, each loaded 3× (~1,160 loads) |
| 5-LUT design across the die (at-least-two, parity) | `hwtest.py tree` | 2/2, 16/16 each |
| LUT → register with feedback (toggle, DFF, set/reset, majority) | `regtest.py` | 12/12, 40 clocked steps each |
| 8-state machines (`templates/fsm3`) | `fsmtest.py` | 6/6, 60 steps |
| 8-bit machines across 2 LABs (`templates/cnt8`) | `cnt8test.py` | 6/6, 80 steps |
| 32-bit machines, 43 LUTs, 4 LABs (`templates/ring32`) | `ring32test.py` | 5/5, 100 steps |
| 24-bit counter on the 48 MHz clock (`templates/div24`, incl. a mod-3 variant) | `div24test.py` | 6/6 at the predicted frequency (setup slack 16.8 ns) |
| Verilog designs and edits (`examples/`) | `v2bit.py board` | 5/5, plus 4/4 rewired edits and 2 unedited bases |
| Single-input routing rewires (rule-based, blind) | `blindtest.py` | **40/40 predictions right** at 4 LABs and 4 dst slots |
| M9K ROM contents written without Quartus (random, count pattern) | `m9ktest.py` | 3/3 incl. Quartus control, 2,080 readings each |
| M9K layouts 36×256, 1×8192, 2×4096, 9×1024 (model-written random contents) | `m9ktest2.py` | 5/5 incl. Quartus control, up to 2,048 steps |
| ROM edits from Verilog (`examples/romseq.v`, edited hex) | `v2bit.py board` | 3/3 |
| M9K RAM: patched initial contents, then writes by the design | `ramtest.py` | 3/3 passes × 512 words |
| Arithmetic-mode LUT, sum path (random masks) | `arithtest.py` | 4/4 |
| Chain-start carry function, all 16 2-input functions | `carrytest.py` | 16/16 |
| Two-stage carry chain (random chain-start and middle carry functions) | `carrytest.py chain3` | 12/12 |
| Arithmetic LE using sum and carry (unified model) | `carrytest.py both` | 12/12 |
| Carry-chain counter rewritten (up, down, 4 random machines), 3 LABs | `cnt4ctest.py` | 18/18 |

In the clocked tests, offline mutation tests show that wrong LUT input orders would have been caught
(507/518 and 650/656). The measured 48 MHz frequencies are all 0.085% low, so the SAMD21's clock is
about 47.96 MHz.

### Routing inside a LAB

- **LUT-input select table (`mux4map.py`, `li_local_table.json`).** Four sources at known slots drive
  a LUT's four inputs, and the LUT's asymmetric mask reveals which physical input each landed on.
  Reading the select bits directly (bytes 0..3 of the dst LE, frames −12..−2 before its LUT; odd LEs
  map column c → 3−c) gives:
  - one 58-entry (physical input, source slot) table that doesn't depend on the dst slot;
  - **1,276/1,276** held-out builds predicted exactly, and **80/80 on the EP4CE6** (with inputs 0/1
    relabelled), so this is the same on both dies;
  - on Quartus's own routing of the templates, it predicts 157/166 inputs fed from another LE of the
    LAB. Inputs from the LE's own register use the internal feedback path;
  - the structure is two-level: a group select in frames −12..−4 plus a select in frame −3.
- **Direct inputs (`sharemap.py`, `lirule.py`, `li_direct.json`).** Quartus only ever shares a source
  between one fixed pair of inputs, so each LE's local line reaches exactly two of a LUT's inputs
  directly:

  | source slot N | direct physical inputs |
  |---|---|
  | 4, 8, 14 | 0, 2 |
  | 22, 26, 30 | 0, 3 |
  | 0, 2, 16, 18, 20, 24, 28 | 1, 2 |
  | 6, 10, 12 | 1, 3 |

  Other connections use a second path set up on the source LE's side. Rewriting only the dst's select
  bits makes input p read source s **iff p is a direct input of s and s's local line is driven** (the
  input already reading s does so directly). Otherwise the input reads an undriven line, which shows
  up as a constant.
- **Silicon (`rewire.py`):** the rule explains all 49 rewire outcomes it was derived from. Then
  it predicted **19/19** (`blind_predictions.json`) and **21/21** (`blind_predictions_2.json`, three
  more LABs and dst slots), each time with the predictions committed before any load.
- **Second path, offline only (`secondpath.py`, `li_second_path_pairs.json`).** When an LE output
  reaches a non-direct input, the *source* LE gets its output-select bit at frame +8 and a 2-bit line
  select, which depends on which input reads it (18 (input, source) signatures, the same at two
  LABs). Dst-only rewires to a source whose second path was already on: 4/6, both failures explained
  by the per-input line. Switching on source-side drivers on silicon was deliberately **not** done:
  a driver onto a block-wide line could fight another driver.
- **Across dies (`tilecmp.py`):** in LAB-relative coordinates the deterministic intra-LAB routing
  bits are identical on the EP4CE6 and the 10CL016. Inter-LAB routes can't be decoded with loosely
  constrained designs, because Quartus picks different wires for the same source position
  (`mux4xmap.py`).

### The repo's "canon cells" (EP4CE6, `ce6probe.py`)

The repo needs per-position "canon cell" tables for asymmetric masks. Its golden design has no
`dont_touch`:
- **Constant masks have no LUT.** Masks 0000/FFFF have no LUT and no input routing at all.
- **The canon cells are input routing.** Every other mask adds its input routing (identical for 6996
  and DEAD at all 14 positions).
- **The input order is chosen per mask.** That's why a position-keyed σ⁻¹ table only works for
  symmetric masks.

With `dont_touch("on")` plus one 0x008A probe, 4444/DEAD/6996 written with the repo's own cell
addresses are **byte-identical to Quartus at 42/42** positions/masks.

### M9K memory contents (`m9kpatch.py`)

Design `rom:SITE:SPEC` (`xdev.py`): a 9-bit counter addresses a 9×512 altsyncram ROM pinned to an M9K
site, and D5 shows q[0..3]. Each stored bit is one CRAM cell:
- frame = F[X] + word // 2, with F = 517 for column X13 and 1185 for X25;
- byte = ROW[Y].byte − 14 − word % 2 − 2·bit, plane = ROW[Y].plane (the LAB row table of `lutpos.py`),
  with the same per-byte wrap as LUT cells;
- Quartus only stores bits the design reads;
- header sum: M9K bits weigh 2^((2L + frame + 7) mod 8), the frame with the opposite sign to LAB bits.

**63/63 ROM builds byte-identical to Quartus** (single-bit probes and random 512-word contents at 16
sites in both columns, 4 held out).

**All M9K layouts** (`rom2:` design, D5 = parity of all bits): an M9K is 256 rows (frames) × 36 bit
positions, and each layout interleaves (word, bit) into (row, position) (`m9kpatch.LAYOUTS`: 36×256,
18×512, 9×512, 9×1024, 4×2048, 2×4096, 1×8192). 113/113 probe and random-content builds are
byte-identical, plus all 7 layouts at a held-out site in the other memory column (7/7). On silicon (`m9ktest.py`), random contents and a count pattern
written only by `m9kpatch.py` read back correctly over 520 clocked steps each.

### Flip-flop controls (offline, `ffe2:` design, `ff_control.json`)

Each register has three control bits in its LAB, in its LE's byte column:

- **Sync enable** (frame +11): the same bit serves sync clear and sync load, and LAB-wide bits choose
  which. It is additive over all 16 combinations of 4 registers and identical at 3 LABs.
- **Async-clear enable** (frame +10): additive, identical at 2 LABs.
- **Pair select** (frame +11, in the async-clear byte columns): picks one of the LAB's two {clock,
  clock-enable} pairs. A different clock or a different enable flips the same bit. Quartus always
  keeps the lowest register of each 4-LE group on pair 0, so 4 of the 16 select bits are predicted
  rather than observed.

A blind test at 3 new LABs predicted 16/18 cases. The 2 misses were byte-wrap cases, and a wrap rule
fitted afterwards makes it 18/18. Routing a signal onto the LAB-wide lines is not mapped, and nothing
here has been tested on silicon.

### LAB control lines and LE outputs (offline, `ffc:` / `oreg:` designs)

- **LAB-wide control bits** (`ff_control.json` → `lab_wide`). A few bits are identical at 5 LABs
  whenever a signal drives sclr, aclr or the enable of pair 0, when the registers split over both
  pairs, or when the clock changes. The other bits per LAB are the routing of the signal onto the
  control line.
- **Control-line mux from local LEs** (`li_control.json`). With the control coming from an LE in
  the same LAB, sclr and enable share one slot-dependent code (identical at 2 LABs for 9/11 slots).
  The one bit where they differ follows the LUT-input direct rule: input 0 vs input 1 reach, 9/9.
- **Comb vs registered output** (`le_output_select.json`). Each LE has two local outputs, the
  direct line and the second path. Each has one select bit in the LE's plane: frame +9 for the
  direct line, frame +8 for the second path, with 1 = combinational. Swapping the two outputs flips
  exactly those 2 bits at all 13 slots measured, at 2 LABs, and with both outputs registered both
  bits are 0.

### Global clocks (offline, `gclk:` design, `gclk.json`)

With 4 registers clocked from each of the 16 dedicated clock pins at 3 LABs, 59 bits change, and none
of them is in the LAB's control column. 40 bits are global: identical at all 3 LABs, in per-side
frame groups, with the pins grouping by side (4 per side). 19 are regional: they move with the LAB
to a spine frame pair (487–488 for X10Y10, 1592–1594 for X22Y8 and X30Y20). They form a one-cold
GCLK select, a one-hot side select and 3 index bits. Meanings are inferred. A sweep over 94 LABs gives
a model: 2 quadrant bits (left/right × top/bottom), plus a 4-bit row clock select in one of 4 spine
frames, at the LAB row's LUT byte −62. It fits 93/94 LABs; row 14 is an observed exception.

### Neighbour-LAB links (offline, `xr:` design, `li_neighbour.json`)

A net from an LE to an LE in the adjacent LAB (dx = ±1, same row) sets dst-side select bits in the
same LUT-input mux as local lines. The code depends only on direction and source slot: identical at
2 LAB pairs and 6 dst slots for all 16 source slots, in both directions, and predicted 94/96
blind codes at 3 new LABs. At dx = 2 Quartus picks
general routing and the code varies. On the source side, the LE drives the link from one of its two general outputs (fixed per
direction and slot), plus 1–2 driver bits in the routing frames between LAB columns (set as predicted
in 92/93 builds at 3 other LABs). Nothing here has been tested on silicon. Vertical neighbours (dy = ±1) have no fixed code: Quartus routes them per build
over general wires.

### M9K RAM (`ram:` design, `ramtest.py`)

The initial contents of a single-port M9K RAM use exactly the ROM encoding (5/5 builds
byte-identical, random contents included; as with ROMs, only bits the design reads are stored). On
silicon, random initial contents written by `m9kpatch.py` read back correctly over all 512 words. The
design then overwrote every word through its own write port and read the new contents back
correctly.

### Arithmetic mode (`templates/arith2`, `arith3`, `arith3b`; `arithtest.py`, `carrytest.py`)

One model covers every arithmetic-mode LE seen, on silicon:
- the LE stores its full 16-bit mask M in its LUT cells, with the carry-in in place of input c;
- **sum = M[a + 2b + 4·cin + 8·d]**;
- **carry-out = M[a + 2b + 4·cin]**, the d = 0 half of the mask, whatever d is.

Quartus stores less when it can:
- if the sum is unused, it stores only the d = 0 half. Bit j = a + 2b + 4cin then sits in physical
  cell 4(j mod 4) + j div 4 (20/20 builds);
- at a chain start (no carry in, cin = 0) it repeats that half across cin: f(k) = 1 for k = a + 2b sets
  cells 4k and 4k+1 (20/20 builds). The base build doesn't reveal a chain start's input order the
  usual way, so `tpatch.Template(..., partial=True)` keeps it fixed and its carry function is written
  directly.

On silicon (LUT-only patches on Quartus templates):
- sum path 4/4 (`arithtest.py`);
- all 16 chain-start carry functions 16/16 (`carrytest.py`);
- two-stage chains with random carry functions 12/12 (`carrytest.py chain3`);
- an LE using both outputs, sum and carry readouts for 6 random masks, 12/12 (`carrytest.py both`);
- **a carry-chain counter** (`templates/cnt4c`, `cnt4ctest.py`): the model predicts Quartus's standard
  counter masks (LSB 0x6688, bit i 0x5AA0; datad must be 1 so the sum reads the upper half). Up, down
  (6644/5A50) and 4 random machines, chain start included: 6/6 correct over 60 clocked steps, at
  each of three LABs (X3Y1, X22Y12, X30Y20; 18/18).

**Carry-in select (offline only):** one bit per LE, in frame (LUT frame 0 − 1) at the LE's low byte (+1
for odd slots), LUT plane, active low. It is 0 in 23/23 arithmetic LEs with a carry input, and 1 in
9/9 chain starts and 573/575 plain LEs (the 2 exceptions are a byte-wrap LE). Not written on silicon:
it is a non-LUT configuration bit. Not mapped: other arithmetic-mode bits, and the physical input order
at other placements.

### ROMs in Verilog designs (`v2bit.py`)

Instantiate `m9k_rom #(.W(w), .D(d), .INIT("file.hex")) rom (.clk(B), .addr(a), .q(q))` (synchronous
address, unregistered q, one hex word per line). `v2bit.py init` turns it into an M9K `altsyncram`
with the design's contents and records the M9K site. `write` rewrites changed contents with
`m9kpatch.py`; only q bits the design reads are stored. For `examples/romseq.v` with two edited hex
files, the ROM part matched Quartus's build of the edited MIF bit for bit (1,101/1,101 and
1,024/1,024 bits), and both edits are correct on silicon. An M9K's output before its first clock edge
isn't defined, so the simulator check skips that one reading.

### Flip-flops (pilot)

- **Placement:** `FF_X{x}_Y{y}_N{odd}` placement works on Quartus Lite 21.1.1.
- **Bypass bit:** in frame (LUT base + 11), byte lo / lo+1 for even / odd LEs, the LUT's bit. It is
  set iff the register's D bypasses the LUT (72/72 builds).
- **Output select:** same frame, byte lo+3 / lo−2. It selects the register for one LE output path
  (71/72 builds; the exception uses the other output path).
- **Power-up high** has no per-LE bit: Quartus uses NOT-gate push-back.
- **Enable and sync clear** are LAB-wide control signals, not separated yet.

## Tools

| Area | Files |
|---|---|
| Core | `rbfgeom.py` (frame size, CRC init and CRC frames inferred from any RBF), `xdev.py` (Quartus campaign driver and design generator: `parts`, `plan`, `build`, `sweep`, `report`), `lutpos.py` (position model, `--check`), `lutpatch.py` (LUT codec, `--model`, `--fix-header`), `gate.py` (pre-load safety gate), `selftest.py` (24 checks, no Quartus), `corpus.py` + `corpus.json` (rebuild and verify every build) |
| Templates | `multipatch.py`, `tpatch.py`, `templates/` (`top.v`, `locs.qsf`, `extra.qsf`), `v2bit.py`, `examples/` |
| I/O | `periph.py` (periphery format, I/O settings), `io:` designs in `xdev.py` |
| Memory | `m9kpatch.py` (M9K ROM/RAM contents, all layouts), `m9ktest.py`, `m9ktest2.py`, `ramtest.py` (silicon tests) |
| Arithmetic | `templates/arith2`, `arith3`, `arith3b`, `cnt4c`; `arithtest.py`, `carrytest.py`, `cnt4ctest.py` |
| Hardware | `sketch/VidorTestBench` (USBBlaster + serial test bench), `hwtest.py`, `silicon_sweep.py`, `regtest.py`, `fsmtest.py`, `cnt8test.py`, `div24test.py`, `ring32test.py`, `vidor_pack.py` (Arduino flash-route packing; logic only) |
| Routing | `muxmap.py`, `muxmap1.py`, `mux4map.py`, `mux4xmap.py`, `mux1cmap.py`, `limcheck.py`, `sharemap.py`, `lirule.py`, `rewire.py`, `blindtest.py`, `secondpath.py`, `secondtest.py`, `tilecmp.py` |
| Data | `li_local_table.json`, `li_direct.json`, `li_lone_pairs.json`, `li_single.json`, `li_second_path*.json`, `li_neighbour.json`, `li_control.json`, `gclk.json`, `io_*.json`, `ff_control.json`, `le_output_select.json`, `blind_predictions*.json` |
| EP4CE6 / repo | `ce6probe.py` |
| Upstream | `UPSTREAM_ISSUE.md`, `UPSTREAM_COMMENT_1.md`, `UPSTREAM_COMMENT_2.md` (texts as posted on #3) |

Python 3.10+, standard library only. `yosys` is needed for `v2bit.py`. `QUARTUS_BIN` defaults to
`~/intelFPGA_lite/21.1/quartus/bin`.

## Hardware

### Loading bitstreams

The SAMD21 is wired to the FPGA's JTAG pins.
1. Install the SAMD core and the USBBlaster library:
   `arduino-cli core install arduino:samd && arduino-cli lib install USBBlaster`.
2. Upload the test bench, which is the USBBlaster example plus a serial command set:
   `arduino-cli compile -u -p /dev/ttyACM0 -b arduino:samd:mkrvidor4000 sketch/VidorTestBench`.
   It enumerates as `09fb:6001` (needs a udev rule) plus a CDC serial port.
3. Check: `openFPGALoader -c usb-blaster --detect` should report IDCODE `0x020f20dd`.
4. Load to **SRAM only**: `openFPGALoader -c usb-blaster file.rbf`. Never use `-f` (flash).
   Power-cycling restores the Arduino image.

Arduino's flash route (persistent demos only) embeds the bit-reversed bitstream in a sketch. See
`vidor_pack.py`, and run `--check-ttf` against one Quartus build first.

### Test bench

`hwtest.py --auto` and the other test scripts use the sketch's serial commands. The SAMD21 drives
D1..D4 and reads D5:
- D5 is never driven by the SAMD21.
- D1..D4 are driven only between a successful load and the next load. They are inputs while
  loading and after power-up.
- Every reading checks the D1..D4 readback. A mismatch (another driver on a pin) disarms the bench
  and stops the run.
- Nothing may be connected to the header during automatic runs.

Without the sketch, `python3 hwtest.py` asks for meter readings (D5 to GND via ≥330 Ω or a
meter; jumpers from D1/D2 to GND).

### Safety rules used here

- SRAM loads only. Only the VidorTestBench sketch.
- Every file passes `gate.py`: it may differ from its Quartus base only in declared LUT cells, frame
  CRCs and the header sum/CRC. Approved exceptions add exactly the declared select bits
  (`rewire.py`, `v2bit.py` rewires; `m9ktest.py`: exactly the model's M9K content cells).
- Header pins D1..D5 only, with D5 at minimum drive (pin variant `vidorlo`). The 48 MHz clock input
  (iCLK, PIN_E2) is read only.
- Stop on a failed load, a readback mismatch, or an all-zero control not holding D5 low.
- Don't compile while the board is in use. One JTAG load failed at load average ~16, against 0
  failures in ~1,150 loads on an idle machine.

### Hazards

- **Every MKR header pin is also a SAMD21 GPIO.** D1..D5 = PIN_N3/P3/R3/T3/T2, checked against Arduino's
  `VidorFPGA/constraints/MKRVIDOR4000/vidor_s_pins.qsf`. Unused FPGA pins are tri-stated with weak
  pull-ups. Don't drive other Vidor pins (HDMI, SDRAM, flash, NINA, SAM_INT) without checking what's
  on the other end.
- **Hand-made routing can make two drivers fight.** The repo saw driver contention and protective
  resets. Only dst-side LUT-input select rewrites allowed by the direct-rewire rule have been loaded
  here. Source-side drivers have not.

## Reproducing

`corpus.json` lists every Quartus build behind the results (device, design, LE, pin variant) with
the SHA-256 Quartus produced here. RBF/SOF files aren't committed.

You need Quartus Prime Lite 21.1 with Cyclone IV E and Cyclone 10 LP (21.1.1 Build 850 was used),
Python 3.10+, `yosys` for `v2bit.py`, and Cyclone_CRAM_Mapper cloned next to this repo.

```bash
python3 corpus.py plan --jobs 6      # 7,177 compiles: ~3.7 h at 6 parallel (~11 h at 2)
python3 corpus.py build --jobs 6     # --only PREFIX for a subset
python3 corpus.py verify             # expect 7177 identical
python3 corpus.py derived            # hardware-test files (out/lo_*, sweep, reg, fsm, cnt8, div24, ring32)
python3 selftest.py                  # expect 24 PASS
```

Builds recompiled from scratch matched `corpus.json` byte for byte. Quartus is deterministic for
these settings. With another Quartus version, `verify` lists what differs, and the control check in
`selftest.py` says whether it matters.

On the board (test bench uploaded, header free):
```bash
python3 hwtest.py --auto all                            # ~1 min
python3 silicon_sweep.py board                          # 100 LEs, ~13 min
python3 regtest.py write && python3 regtest.py board    # ~2 min
python3 fsmtest.py write && python3 fsmtest.py board    # ~1 min
python3 blindtest.py board                              # rewires, ~5 min
```

## Legal notes (not legal advice)

- The Quartus Prime Lite licence forbids reverse-engineering *the software* except as permitted by
  law. Nothing here touches Quartus binaries or databases; it compiles designs and diffs the output,
  as the CRAM mapper does. In the EU, Software Directive 2009/24/EC Art. 5(3) allows observing and
  testing a program's functioning while running it.
- The licence also has a clause (2.2.8) about publishing benchmarking or testing results. The results
  here describe the device's bitstream.
- No RBF/SOF files are committed. Only scripts and derived facts are.

## Upstream

- [Issue #3](https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3) (2026-11-22): the cross-die
  results, the header checksum and the 10CL016 LUT model, plus a question about multi-die support
  upstream.
- Follow-ups (2026-11-23): the canon-cell explanation with the 42/42 EP4CE6 result, and the
  intra-LAB routing rule with the blind silicon tests.
- No reply yet. Next ideas, after coordinating with the author: a device-geometry abstraction in
  the repo (`rbfgeom.py`-style), inter-LAB routing (where the author's C4/R4 work could save a lot),
  and C16, the one wire class the repo hasn't covered.
