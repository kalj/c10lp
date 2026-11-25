# Research log (started 2026-11-22 ~22:00 as the night-run log)

## Summary (written ~04:00, 2026-11-23)

Everything is committed locally. Nothing was pushed, posted or deleted. The board ran only gated,
SRAM-only loads on D1..D5.

**On silicon (all with functions Quartus never compiled, written by our tools):**
- **Multi-LAB templates:** `cnt8` (18 LUTs, 2 LABs) 6/6 machines; `ring32` (43 LUTs, 32 registers,
  4 LABs) 5/5 32-bit machines over 100 clocked steps. A mutation test shows wrong LUT input orders
  would be caught (650/656).
- **Full speed:** `div24`, a 24-bit counter on the Vidor's 48 MHz clock (PIN_E2, input only). 6/6
  patched variants ran at the predicted frequency, including a mod-3 counter. The SAMD21 clock is
  ~47.96 MHz.
- **Position model at 400 random LEs** (6,400 readings), all correct, each loaded 3 times in a soak
  of ~1,160 loads. **1 load failed** (JTAG timeout while the CPU was at load ~16; nothing loaded; run
  stopped per rule 4, then diagnosed read-only). **0 failures on an idle machine.** Lesson: don't
  compile while the board is in use.

**Offline findings:**
- **The repo's "canon cells" explained and removed:** their golden design has no `dont_touch`, so a
  constant mask has no LUT and no input routing, and the input order is chosen per mask. With
  `dont_touch("on")` + one 0x008A probe, their 14 positions on the EP4CE6 give **42/42 byte-identical**
  files using their own cell addresses (`ce6probe.py`).
- **Intra-LAB LUT-input muxes decoded** (`mux4map.py`, `li_local_table.json`): one 58-entry table,
  independent of the dst slot, predicts the select bits exactly in **1,276/1,276 held-out builds** on
  the 10CL016 and **80/80 on the EP4CE6**. It is a two-level mux, the same on both dies. It also
  holds on Quartus's own routing of the templates: 157/166 inputs from other LEs (`limcheck.py`).
- **LAB-line (external) sources** use the same two-level mux, with the second stage mostly in frame −2
  instead of −3. Which LAB line carries a signal is Quartus's choice, so the wire→line stage is the
  next (big) routing step.
- **The LAB tile is the same across the dies** for the parts that don't depend on pins (`tilecmp.py`).
  Vertical inter-LAB routing was inconclusive with simple designs.
- **Position model fix:** the byte wrap is per byte (bytes < 2). Found at 1 of the 300 new LEs.
  `lutpos --check`: 719/719 builds at 556 LEs.

**For you:**
- Follow-up comment for #3 (canon cells, LAB tile, LI muxes): posted 2026-11-23 at your request,
  text in `UPSTREAM_COMMENT_1.md`.
- Writing routing bits (like the LI table) to silicon would break board rule 2 (no hand-made routing
  changes). Yours to decide; a careful way would be gate-checked single-mux changes inside a template.
- 19 local commits on top of origin/master (as of this summary); nothing pushed.
- `out/` is 2.3 GB (4,314 builds, all listed in `corpus.json`).

## Details

Autonomous session; the board and machine are free for 12–18 h. Rules: board rules from
README (SRAM only, every file gated, D1..D5 only, stop on anything odd), nothing posted,
pushed or deleted, commits local only.

Plan: 1) bigger templates on silicon (multi-LAB, 48 MHz); 2) does the repo's EP4CE6 routing
knowledge transfer to the 10CL016 die; 3) the repo's "canon cell" puzzle vs per-mask input
re-ordering; 4) reliability soak + 300 more silicon LEs; 5) 10CL016 routing pilot (data only).

## Progress

(Times before 23:40 are approximate; later ones come from `date`.)
- ~22:50 **Block 1a done:** `templates/cnt8` (18 LUTs + 8 registers, Quartus placed it across 2 LABs,
  X3Y2 + X4Y2). 6/6 machines Quartus never compiled were correct on silicon over 80 clocked steps
  each: up counter, up/down counter, shift register, Johnson counter, 2 random 256-state machines
  (`cnt8test.py`, log `out/cnt8test_20261122_225019.jsonl`).
- ~22:52 Checked the Vidor's 48 MHz clock pin in Arduino's `vidor_s_pins.qsf`: `iCLK` = PIN_E2 (input
  only). D1..D5 = N3/P3/R3/T3/T2 confirmed again.
- ~22:55 **Block 1b done:** `templates/div24`, a 24-bit counter (33 LUTs) on the Vidor's 48 MHz
  clock (PIN_E2, input only). quartus_sta on the pinned base: setup slack 16.8 ns at 48 MHz, Fmax
  250 MHz. 6/6 variants written by tpatch.py ran at the expected D5 frequency, measured by polling
  D5 over serial at ~1870 samples/s: binary counter on bits 23/21/19, a mod-3 low group (3.81 and
  15.25 Hz instead of 2.86 / 11.44 Hz), and a "free" variant that ignores the D1 enable. With D1 = 0
  every counter froze, except "free". All measurements are 0.085% low by the same ratio: the
  SAMD21's "48 MHz" is ~47.96 MHz (`div24test.py`, log `out/div24test_20261122_225445.jsonl`).
- ~23:10 **Block 3 done, a clear result for the repo.** Their goldens' "canon cells" are input routing:
  - their design has no `dont_touch`, so a constant mask (0000/FFFF) has no LUT and no input routing;
  - vs mask0000, 6996 and DEAD add identical extra-bit sets at all 14 positions;
  - σ is chosen per mask (0/14 positions have one order for DEAD and 4444).
  With `dont_touch("on")` plus one 0x008A probe at their 14 positions on the EP4CE6 (70 compiles,
  `ce6probe.py`), 4444/DEAD/6996 come out **byte-identical, 42/42**, using their own cell addresses.
  Follow-up comment drafted that night; posted 2026-11-23 (`UPSTREAM_COMMENT_1.md`).
- ~23:25 **Block 2, intra-LAB routing (176 compiles, `tilecmp.py`).** `lab2` design: src LUT at slot ns
  drives all 4 inputs of dst LUT at slot nd in the same LAB, at 4 LABs per die. In LAB-relative
  coordinates (frame/byte offset from the LAB's slot-0 LUT):
  - moving dst: the 9 core bits per slot are identical on EP4CE6 and 10CL016 for all 15 slots, and
    8/15 slots are fully identical. The rest is one LE output-select bit (frame +8, byte lo / lo+1 of
    the dst slot) that Quartus sets on some slots depending on the route to the output pin;
  - moving src: 16–21 shared bits per slot (Jaccard 0.70–0.95). The differences are src input
    routing from the pins.
  So the LAB tile looks bit-identical across the dies; what differs is Quartus's pin-dependent
  routing choices.
- ~23:35 **Block 2, vertical inter-LAB (64 compiles, `tilecmp.py --vertical`): inconclusive.**
  - Around dst, almost no bits change with dy: the input-mux choice is the same for all dy.
  - Around src, 17–27 bits are shared per dy (Jaccard 0.55–0.81). The differences are the src pin
    inputs and Quartus's choice of driver and wire, both pin-dependent.
  This method can't separate "different encoding" from "Quartus picked different wires". Isolating
  wires needs controlled designs (the repo's signature mining). Not pursued further tonight.
- ~23:35 **Position model fix:** one of the 300 new sweep LEs (X36Y11N18) has LUT bytes (1, 2), and byte 1
  wraps to byte 252 one bit plane up while byte 2 stays. The wrap rule is now per byte (bytes < 2
  wrap), which is the same as the old rule for every earlier case. `lutpos --check` (now including
  vidorlo builds): 719 builds at 556 LEs, 0 mismatches, 20 input permutations seen.
- 23:42 **Board stop and restart.** The first 300-LE board run stopped after 7 PASS: a load
  failed with a JTAG timeout and the garbage IDCODE 0x2f2e2f2e, so nothing was loaded or driven
  (rule 4: stop). Read-only diagnosis: the USB-Blaster is still on USB, the sketch answers, and 3/3
  detects read 0x020F20DD. The load average was ~16 at the time (a 4-job compile plus the selftest ran
  alongside), so the likely cause is USB service starved by CPU load. New practice: no compiles while
  the board is in use. Restarted the run once on an idle machine; if a load fails again, all board
  work stops for the night.
- 23:42 selftest 13/13 PASS after the lutpos wrap fix.
- 00:16 **Block 4 silicon: 300/300 new LEs correct** (log `out/sweep_20261122_234204.jsonl`),
  13/13 controls held D5 low, and no load hiccup on the idle machine. With the first 100, that's
  **400 random LEs, 6,400 readings, all correct**, every file written by the position model and gated.
- 00:16 Starting Block 5 compiles: the "mux" design for intra-LAB local-line input-mux encoding,
  936 builds (2 LABs on the 10CL016, 1 on the EP4CE6), 6 parallel, ~1.2 h. Board idle meanwhile.
- 01:10 **Block 5, intra-LAB input-mux pilot (936 compiles, `muxmap.py`).** Build pairs differing
  only in which source slot (a or 30) drives dst's four inputs differ in 15–66 bits, not just dst's
  selects: Quartus re-allocates local lines too (Jaccard 0.27 between LABs). But each (a, d) has a
  **consistent core of 6–19 bits** shared by both 10CL016 LABs. **92%** of the core bits are also
  present on the EP4CE6, and **98%** of the core bits that sit in dst's own bytes 0–3 in the 16 frames
  before its LUT (its input muxes) are. That's the start of a per-wire local-interconnect model that
  is the same on both dies; turning it into one needs controlled designs that stop Quartus moving
  other nets.
- 01:10 Soak pass 1: the original 100 LEs again, 100/100, 5/5 controls, no hiccup. Pass 2 (300 LEs)
  running.
- 01:11 **Mux core structure:** in dst-relative coordinates the input-mux core is set by the source
  slot alone. 8 of 13 source slots give one identical pattern for all 12 destinations; the rest give
  2–3 patterns. Each pattern is a pair of one-hot selects in the 16 frames before dst's LUT, one frame
  in −12..−9 and one in −8..−4, each on a byte pair ({1, 2} or {0, 3}) of dst's bytes 0..3, plus
  common bits in frames −3/−2. Example, a = 0: frames −12 (bytes 1, 2) and −8 (bytes 0, 3). That is
  a two-level, sparsely connected input mux, where two of the four physical inputs reach a given local
  line through one select and two through another. This could become a generative LI model; next step:
  designs that drive only one physical input, to separate the per-input selects.
- 01:44 Soak pass 2: the 300 LEs again, 300/300, 13/13 controls, no hiccup. Pass 3 (both sets) running.
- 02:29 **Block 4 soak done.** Pass 3: 100/100 and 300/300, 18/18 controls. Night total: **~1,160 loads**
  through the USB-Blaster sketch, with **1 failed load** (JTAG timeout under ~16 load average, nothing
  loaded) and **0 failures in ~1,150 loads on an idle machine**. Every one of the 400 sweep LEs passed
  every time it was loaded (3x each, 19,200 readings). Every control held D5 low, and no readback
  mismatch occurred.
- 02:29 Starting mux1 compiles (144, board idle).
- 02:37 **mux1 (144 compiles, `muxmap1.py`):** with only dst.dataa switched, Quartus still changed dst's
  input order between the A and B builds in 23/48 pairs (17/24 on the EP4CE6), and the two LABs chose
  different physical inputs, so there is little usable data. In the usable pairs, one physical input's
  selects stay mostly within one byte column of dst's bytes 0..3. Next step (not done): builds where 4
  distinct known sources drive dst's 4 inputs, decoded per byte column using the order revealed by the
  LUT cells. Stopping the LI thread here.
- 02:40 **Scale: `templates/ring32`** (32 registers, 43 LUTs, Quartus placed it across 4 LABs X3..X6 Y1).
  5/5 32-bit machines written by tpatch.py were correct on silicon over 100 clocked steps each, with
  96–101 distinct states: shift register, XOR ring, 2 random machines, and 1 random machine with a
  random output tree (`ring32test.py`, log `out/ring32test_20261123_023850.jsonl`). Mutation test:
  650/656 wrong LUT input orders would have been caught.
- 02:58 **Local-interconnect input muxes decoded, stage 1 (`mux4map.py`, 240 compiles).** Design `mux4`:
  four sources at known slots drive dst's four inputs, and dst's mask (3CEC) reveals which physical
  input each source landed on (unique in 240/240 builds). Reading dst's select region directly,
  instead of diffing build pairs, sidesteps Quartus's line re-allocation:
  - ~85–90% of the bits in dst's region are each controlled by exactly one physical input's source;
  - stage 1 (frames −12..−4 of dst's bytes 0..3; odd LEs map column c → 3−c): **35 of 43 (input,
    source) entries are exactly one bit**. The multi-bit ones were seen in too few builds;
  - the table from one 10CL016 LAB **predicts the other LAB's stage-1 bits exactly in 76/78 builds**,
    and the EP4CE6's in 67/78 (with physical inputs 0/1 relabelled; the two cell-order conventions
    differ);
  - structure: inputs 1↔2 and 0↔3 are mirror images, e.g. (in 1, src 0) → (frame −8, col 0) and
    (in 2, src 0) → (−8, col 3). Each input reaches only some source lines (sparse mux), and some
    sources share a stage-1 bit (in 1: src 20 and 24 → (−6, 0)), so frames −3/−2 are a second stage.
  Not yet: the second stage, LAB-line (non-local) sources, and all dst slots (only 16 and 6 measured).
  This is groundwork for writing intra-LAB routing without Quartus. Data only, nothing loaded.
- 02:58 Starting the full mux4 coverage: all 16 dst slots on both 10CL016 LABs, 1,120 new compiles at 6 parallel
  (~1.5–2 h). Board idle.
- 03:50 **Intra-LAB LUT-input mux model complete for local sources (1,120 more compiles, `mux4map.py --full`).**
  All 16 dst slots on both 10CL016 LABs, 40 random source sets each:
  - per (LAB, dst slot), every bit of dst's mux region (bytes 0..3, frames −12..−2) is owned by exactly
    one physical input. The owner model reproduces 1,280/1,280 builds;
  - **one slot-independent table** (58 (input, source slot) entries, `li_local_table.json`) predicts
    1,280/1,280 builds, and **leave-one-(LAB, slot)-out: 1,276/1,276 held-out builds exact** (4 used an
    entry seen nowhere else);
  - **the same table predicts all 80 EP4CE6 builds exactly** (inputs 0/1 relabelled), so this part of
    the LAB is bit-identical across the dies;
  - the structure is two-level: a group select in frames −12..−4 plus a select in frame −3, e.g.
    (in 0, src 2) = (−10, c1) + (−3, c1) and (in 0, src 4) = (−10, c1) + (−3, c0). Inputs 1↔2 and
    0↔3 are mirror images. 58/64 (input, source) combinations were seen.
  Not covered: sources from outside the LAB (LAB lines from R4/C4/pins), and whether writing these
  bits without Quartus works on silicon (rule 2 forbids loading such files; it needs your OK).
- 03:53 **Independent check of li_local_table.json on Quartus-routed templates** (`limcheck.py`; cnt8, div24,
  fsm3, ring32 base builds, which Quartus routed itself). For inputs fed from *another* LE in the same
  LAB, the predicted select bits are set for **30/31 LUT-output sources and 127/135 register-output
  sources**, so register outputs use the same local line as the LE's LUT output. Inputs from the LUT's
  *own* register match 0/64: that path is the LE-internal feedback, not the local interconnect (as
  expected). The 9 misses are probably signals Quartus brought in another way (e.g. a LAB-wide line);
  not investigated.
- 03:54 Bonus: `mux4x` (sources in neighbouring LABs, ±1/±2 in row or column), to see if LAB-line sources
  follow the same owner structure. 240 compiles, data only.
- 04:05 **Bonus result, LAB-line (external) sources (`mux4xmap.py`, 240 compiles):** with the four sources in neighbouring
  LABs, dst's select bits use the same two-level structure: group selects in frames −12..−4, and a
  second stage mostly in frame **−2** (local sources mostly use −3). Most bits are still owned by one
  physical input. 3–16 per slot aren't owned by any single *source position*, because Quartus decides
  which LAB line carries a signal. A full map needs the wire→LAB-line stage, which is the actual
  routing problem and best coordinated with the repo author. Stopping here.

## Day session (2026-11-23)

- 07:03 Approved by you: test a hand-made routing change on silicon (a single LUT input's select bits,
  from li_local_table.json), as the one exception to board rule 2. Starting.
- 07:10 **First routing writes on silicon (`rewire.py`, logs `out/rewire_*.jsonl`).** Base: Quartus mux4 build
  (vidorlo) at X10Y10, dst slot 16, sources 0/4/8/12. Each test rewrote one physical input's select
  bits (or two, in a swap) from li_local_table.json, plus dst's LUT mask so D5 shows that input. Gate:
  only those select bits may change, and the region must equal the table's prediction.
  - **5/14 rewires worked**: input 1→src 12, 0→8, 2→0, 2→4, and the swap 0↔2 (0→8 with 2→4).
    Repeated tests behaved identically.
  - **Every failure reads a constant 1**: the new code selects nothing, and the input sits at its
    default. Never a wrong source. Both controls held, no readback mismatch, no reset.
  - **Why (likely):** in all training builds all four inputs select sources at once, so only the
    union of their bits is pinned down. Which input owns a bit (especially the shared second-stage
    frames −3/−2) can be wrong without the union prediction failing (hence 1,276/1,276), but
    single-input rewrites expose it.
  - **Stopped silicon rewiring here:** if ownership is wrong, a rewrite could turn on two first-stage
    selects in one mux and connect two LE outputs inside the FPGA (driver contention). No sign of it,
    but it can't be ruled out until ownership is pinned. Next: offline single-input data; ask you
    before any further silicon rewire.
- 07:11 Offline: `mux1p` single-local-input builds to pin down bit ownership per input (240 compiles).
- 07:23 **mux1p (240 compiles), single local input:** for the 4 entries that worked on silicon, the table
  entry is present in every single-input build (8–16 builds each). For 6 of the 7 that failed, Quartus
  *never* puts a lone local source on that (input, source) pair. They only occur in four-source builds,
  which suggests they aren't plain local-line paths. The seventh, (2, 12), always has extra bits next
  to the entry. Conclusion: li_local_table.json predicts Quartus's full select regions, but it is *not*
  yet a safe per-input write table. Only entries Quartus uses for a lone source are candidates.
  Silicon rewiring stays stopped; this needs targeted work, best together with the repo author's
  knowledge.
- 07:27 **Usability: `v2bit.py`**, Verilog → Yosys → tpatch template → bitstream. On silicon: the ROM counter
  (`examples/cnt4rom.v`) passed with its base table and 3 edited tables written without Quartus (60 clocked
  steps each), and `examples/pop2.v` passed 16/16. Edits avoid Quartus only if Yosys keeps the netlist's
  shape (matched up to relabelling and LUT input order); otherwise `write` refuses and asks for init.
- 07:28 **Inter-LAB pilot (existing mux4x data, no compiles):** in the dst LAB's band, 341 / 305 bits vary
  across the 120 builds per LAB, and *none* is explained by "a source sits at offset (dx, dy)". Quartus picks
  different wires for the same source position, so wire→LAB-line routing needs single-route experiments
  with everything else pinned (the repo's signature mining). Stopped; best coordinated with the author.

### Day session summary
- Routing writes on silicon (approved exception): **5/14 single-input rewires work**. The rest read a
  constant 1 (harmless). The table predicts Quartus's full select regions but doesn't yet pin bit ownership
  per input, so silicon rewiring is stopped until that's resolved (possible driver-contention risk).
- `v2bit.py`: Verilog → Yosys → template → bitstream, with structure-preserving edits written without
  Quartus. **5/5 on silicon.**
- Inter-LAB routing: not decodable from loosely constrained designs.
- 08:30 You approved continuing silicon rewiring, limited to (input, source) pairs Quartus uses for a lone
  source. Step 1: `mux1c` (one local source, other dst inputs tied to constants), 240 compiles, for clean codes.
- 08:44 Lone-source pairs from mux1c: 26 (inputs 0, 1, 2 only; Quartus never uses input 3 for a lone source).
  6 more mux4 bases built; every base's select region equals the table prediction. Board run with --lone.
- 08:51 **Lone-source-filtered rewires on 6 bases: 18/30 work**, and the outcome follows a sharp rule. It depends on
  which input *already* selects the target source:
  - work: in1 sharing with in2/in3 (11/11), in2 sharing with in1 (6/6), in0 sharing with in2 (1/1);
  - fail: in0 sharing with in3 (0/4, reads constant 1), in2 sharing with in3 (0/2, constant 1), and
    in1/in2 sharing with in0 (0/6, reads constant **0**).
  The same (input, source) pair can pass in one base and fail in another, so it's not a bad table entry.
  Likely some inputs reach a local line through an intermediate wire shared with another input, which
  single-input codes don't capture. Every base's select region still matched the table's prediction,
  and every control held D5 low, with no readback mismatch or reset. The constant-0 failures are new and
  unexplained, so **silicon rewiring is stopped again**. Usable rule for now: a rewire is OK in the
  (input, holder) combinations listed under "work".
- 09:00 Mapping the "intermediate wire" offline: `mux4d` (two dst inputs share one local source), 160 compiles.
- 09:10 **"Intermediate wire" mapped (`sharemap.py`, `lirule.py`, 160 mux4d compiles).** When two dst inputs share
  one local source, Quartus's select region matches the table exactly (148/148 where the table covers it),
  so sharing needs no extra dst bits. But Quartus only ever shares a source between one fixed pair of
  inputs, which depends on the source slot: sources 4/8/14 → inputs {0, 2}, 22/26/30 → {0, 3},
  0/2/16/18/20/24/28 → {1, 2}, 6/10/12 → {1, 3} (`li_direct.json`).
  - **Model:** an LE's local line reaches exactly two of a LUT's inputs directly; any other connection
    goes through a second path set up on the source LE's side (outside dst's bits).
  - **Rule:** a dst-only rewire of input p to source s works iff p is one of s's direct inputs and s's
    local line is driven (the input already selecting s does so directly).
  - **Predicts 49/49 rewire outcomes on silicon**, every pass and every failure today.
  The failures selected undriven lines, which is consistent with the constant readings and not with
  two outputs fighting. Board not used for this step.
- 09:17 **Blind test:** 6 new mux4 bases, 19 candidates (table entries, lone-source pairs only). Predictions
  from lirule.py committed *before* any load (`blind_predictions.json`): 17 work, 2 fail.
- 09:22 **Blind test result: 19/19 predicted correctly** (17/17 predicted rewires worked on silicon, 2/2
  predicted failures failed), on 6 bases never used before, including first-time pairs like input 0 →
  sources 14, 22, 30. All 12 controls held, no readback mismatch. Logs: `out/rewire_<base>_20261123_09*.jsonl`.
- 09:27 Pushed (b2392ed) and posted the routing update on #3 at your request (`UPSTREAM_COMMENT_2.md`):
  https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3#issuecomment-7095463508
- 09:32 **Blind test 2 (other LABs and dst slots):** bases at X30Y20 dst 6, X3Y25 dst 24, X37Y5 dst 30
  (2 source sets each). All 6 bases' Quartus select regions equal the table prediction. 21 candidates;
  predictions committed before any load (`blind_predictions_2.json`): 16 work, 5 fail.
- 09:43 **Blind test 2 result: 21/21 predicted correctly** at X30Y20 dst 6, X3Y25 dst 24, X37Y5 dst 30:
  16/16 predicted rewires worked, 5/5 predicted failures failed, every control held. (By mistake the board
  test ran twice; the second, silenced run also scored 21/21. No harm, same gated files.) Together with
  blind test 1: **40/40 blind predictions right**, at 4 LABs and 4 dst slots, even and odd LEs.
- 09:44 **Second path decoded (offline, `secondpath.py`, existing 1,280 mux4 builds).** When an LE output is used
  by a non-direct LUT input, the *source* LE always gets its output-select bit at frame +8, plus a 2-bit
  pair in its own window (e.g. src 16: (−16, c2)+(−15, c2); src 8/12: (13, c4)+(14, c5)). This is the same at
  both LABs for most slots (`li_second_path.json`). It looks like a driver from the LE onto a LAB-wide
  line, which the dst then reads through its non-direct select code.
- 09:45 You approved a careful silicon test of the second path. Plan: (A) dst-only rewires to a source Quartus
  already drives through its second path, so no new drivers; (B) source-side enable only where the signature
  bits are clear and no LE in the LAB has its frame +8 output select set; one file at a time; stop at the first
  wrong reading.
- 09:48 **Second path part A (dst-only, no new drivers): 4/6.** In bases where Quartus already drives source s through
  its second path, rewiring another non-direct input to s worked for in0←src0 (3 bases) and in1←src30, and
  failed for in0←src2 (2 bases, reading constant 1, an undriven line). Source 2 has more than one second-path
  line; Quartus used one that reaches input 3, not the one the (0, 2) code reads. So second-path lines are
  per (reading input, source), not per source. All controls held.
- 09:49 **Per-(input, source) second-path signatures** (`li_second_path_pairs.json`, 18 pairs, same at both LABs): the
  source-side line select depends on which input reads it, e.g. in0←src2 = (−16, c0)+(−13, c1)+(8, c2) but
  in3←src2 = (8, c2) only. That explains part A's two failures.
- 09:49 **Part B blocked by its own safety check:** in every base, the dst LE (slot 16) has its frame +8 output-select bit
  set, because that bit also routes its output towards D5. Some bases also have it on an LE Quartus routes through a
  second path. The agreed condition was "no LE has it set", so 0 candidates. I didn't relax it on my own: a
  source's second-path driver could target a wire the dst uses towards the pin (two drivers). Waiting for your call.
- 09:51 You chose to keep the second path offline; source-side drivers are not enabled on silicon. Moving to step 3:
  wiring edits (direct rewires) in v2bit.py.
- 09:57 **Step 3: wiring edits from Verilog (`v2bit.py`).** `write` now accepts edits that change up to 2 LUT inputs'
  sources (fewest substitutions first) and applies them as dst-only rewires when the li_direct rule allows; it
  refuses otherwise with the reason (second path needed, no table entry, line not driven). Templates now keep
  every register (`(* noprune *)`, since Quartus drops registers the base design doesn't read).
  Example `examples/cnt4sel.v` (D5 = n[I] ^ n[J] of a counter): 4 edits were allowed in 4 templates, and **all
  4 passed on silicon** (60 clocked steps each), as did 2 unedited bases. Over the board's input sequence the
  edited and unedited designs differ in 62–63/120 readings, so a rewire that silently failed would have shown.
- 10:27 Started M9K contents on the 10CL016 (your choice). Design `rom:`: a 9-bit address counter (D2 clock,
  D1 enable) feeds a 9×512 altsyncram ROM pinned to an M9K site, and D5 = one of q[0..3] picked by D3/D4.
  D1..D5 only. Offline mining first; I'll ask before any board test (it needs a new gate exception).
- 10:35 **M9K ROM contents decoded (`m9kpatch.py`, ~75 compiles).** Each stored ROM bit is one CRAM cell:
  frame = F[X] + word//2 (F = 517 for X13, 1185 for X25), byte = ROW[Y].byte − 14 − word%2 − 2·bit, plane = ROW[Y].plane
  (lutpos's LAB row table), with the same per-byte wrap as LUT cells. Quartus only stores the bits the design
  reads (q[0..3] here). Header sum: M9K bits weigh 2^((2L + frame + 7) mod 8), the frame with the opposite sign
  to LAB bits. **63/63 ROM builds byte-identical to Quartus**: single-bit probes and random 512-word contents at
  16 sites in both columns, 4 of them held out.
- 10:38 You approved an M9K board test (new gate exception: exactly the model's M9K content cells, on a Quartus
  ROM base). `m9ktest.py`: Quartus r1 as timing control plus 2 patched contents, 520 clocked steps each, stop at the
  first wrong reading.
- 10:41 **M9K silicon test: 3/3** (`out/m9ktest_20261123_103859.jsonl`): Quartus's random ROM (timing control), plus
  random contents and a count pattern written only by m9kpatch.py, 520 clocked steps / 2,080 readings each, all
  correct. All 4 controls held, no readback mismatch.
- 10:48 Pushed. You asked for all of: more M9K layouts, ROMs in v2bit.py, and carry chains. Offline first; I'll ask
  before any board test of new layouts or carry bits. Starting `rom2:` probes for 7 M9K layouts.
- 10:56 **All M9K layouts decoded** (`rom2:`, ~134 compiles). An M9K is 256 rows (frames) × 36 bit positions; each layout
  interleaves (word, bit) into (row, position), now in `m9kpatch.LAYOUTS` for 36×256, 18×512, 9×512, 9×1024, 4×2048,
  2×4096 and 1×8192. **113/113 probe and random-content builds byte-identical**, plus all 7 layouts with new random
  contents at a held-out site in the other memory column (X25_Y20): 7/7.
- 11:00 **ROMs in v2bit.py:** a design instantiates `m9k_rom #(.W, .D, .INIT("x.hex"))` (Yosys black box). `init` makes it an
  M9K altsyncram with the design's contents as the MIF and back-annotates the M9K site. `write` matches the netlist with the
  ROM ports pinned, and rewrites changed contents via m9kpatch (only q bits the design reads). The simulator models the
  registered address. `examples/romseq.v` (counter → 512-word ROM → D5): two edited hex files written without Quartus; the
  ROM part equals Quartus's build of the edited MIF bit for bit (1,101/1,101 and 1,024/1,024), nothing else changed.
- 11:06 Carry pilot: in arithmetic mode the LUT cells hold the mask as usual for an LE with a carry input (e1), but the
  chain-start LE (e0, no cin) stores a 2-bit-different pattern, so its input order can't be identified (`tpatch` partial
  templates keep such LEs fixed). Silicon test of e1 with LUT-only patches (within the board rules): `arithtest.py`.
- 11:07 **Arithmetic-mode LUT on silicon (`arithtest.py`, LUT-only patches of e1):** the sum path is the full mask with cin in
  place of input c: D5 = mask[C, B, cin, D] for 4/4 random masks. The chain start (e0, mask 11CC) gave cout = B, independent
  of A and D, which is consistent with cout = the mask's lower half (0xCC = b over a, b, cin) at cin = 0. One data point, since
  e0's input order isn't identified. Controls held.
- 11:59 Pushed. You approved two M9K board tests: (A) layouts with model-written random contents (`m9ktest2.py`), and (B) v2bit
  ROM edits (`v2bit.py board`).
- 12:04 **M9K test A: 5/5** (`out/m9ktest2_20261123_115939.jsonl`): Quartus's 36×256 control plus model-written random contents in
  36×256, 1×8192, 2×4096 and 9×1024, up to 2,048 clocked steps each, D5 = word parity. All controls held.
- 12:04 **M9K test B (v2bit ROM edits): 3/3** after a fix. The first run failed only at the very first reading, before any clock
  edge, for 2 of 3 files: an M9K's output before its first clock edge isn't word 0. `v2bit.py board` now skips that
  reading for designs with ROMs (as m9ktest.py already did). Then the two edited ROMs and the original all PASS (60 clocked
  steps). The edited and original designs differ in 69–85/120 readings, so the test discriminates.
- 12:10 Next (your "continue with something else"): decode how the chain-start LE in arithmetic mode stores its mask
  (20 compiles of templates/arith2 with different e0 masks), so carry chains become fully patchable.
- 12:14 **Chain-start carry LE decoded and patched on silicon.** When the chain-start LE's sum output is unused, Quartus
  stores only its carry function f(a, b) (cin = 0), taken from the mask's low nibble: f(k) = 1 for k = a + 2b sets physical LUT
  cells 4k and 4k+1. That holds for 20/20 Quartus builds. `carrytest.py` rewrote e0's cells for **all 16 carry functions**,
  and D5 (e1 passing its carry input) **matched f(A, B) 16/16**, independent of C and D. LUT-only, gate-checked, controls held.
  With the sum path (4/4 earlier), both halves of arithmetic-mode LUTs are now patchable on silicon, at least for this
  template's placement.
- 12:28 You allowed pushing without asking, and asked me to keep investigating until 16:00. Plan: middle-of-chain carry
  (3-LE chain), a carry-chain counter template, then flip-flop enable/clear offline.
- 12:32 **Middle-of-chain carry decoded and verified on silicon.** With its sum output unused, a mid-chain LE stores only its
  carry function g(a, b, cin), taken from the mask's low byte: bit j = a + 2b + 4cin sets physical LUT cell 4(j mod 4) + j div 4
  (20/20 Quartus builds). The chain-start encoding is the same rule with cin = 0, stored in both cells. `carrytest.py chain3`:
  random (f, g) pairs written into e0/e1, **12/12 two-stage carry chains correct** (D5 = g(C, B, f(A, B)) for all 16 inputs).
- 12:37 **Unified arithmetic-LE model, verified on silicon** (`carrytest.py both`, `templates/arith3b`). An arithmetic-mode LE
  stores its full mask M (here a → p2, b → p3, cin → p0, d → p1); **sum = M[a + 2b + 4cin + 8d]** and **cout = M[a + 2b + 4cin]**,
  the d = 0 half, whatever d is. With the sum unused Quartus stores only that half; at the chain start it repeats it over cin.
  6 random masks × (sum, cout) readouts: **12/12 match the model** on silicon.
- 12:41 **Carry-chain counter rewritten on silicon** (`templates/cnt4c`, `cnt4ctest.py`): the model predicts Quartus's standard counter
  masks (LSB 0x6688, bit i 0x5AA0; datad must be 1 for the sum). Up counter, down counter (6644/5A50) and 4 random
  machines written into the template, chain start included (written with order a→p2, b→p3, cin→p0, d→p1): **6/6
  correct** over 60 clocked steps. tpatch init now accepts arithmetic chain starts as fixed LEs.
- 12:44 **Flip-flop enable/sync clear (32 compiles, `ffe:` design): inconclusive.** Per register, using the control changes
  60–81 bits, including its LE's LUT frames and pin routing that Quartus re-chooses. The additive per-register model fits
  only 4/15 combinations, so it's not a single control bit per register in this kind of design. Not pursued further today.
- 12:44 Next: M9K in RAM mode (single-port, writable): do initial contents use the ROM encoding, and does a design's write
  path work on top of patched initial contents?
- 12:45 **M9K RAM mode:** initial contents of a single-port RAM use exactly the ROM encoding (5/5 builds byte-identical,
  incl. random contents; only the read q[0] is stored). Board test `ramtest.py` (M9K-content class, as approved earlier).
- 12:46 **RAM on silicon: 3/3 passes** (`out/ramtest_20261123_124619.json`): random initial contents written only by the model
  read back correctly over all 512 words. The design then wrote a new random bit everywhere (and read the old one during each
  write, as configured), and read the new contents back, all correct. Controls held.
- 12:57 selftest now 17 checks (arithmetic encodings, M9K RAM). Note: I pushed one commit (db6d34c) with the template check
  failing before I'd rerun it; fixed in the next commit (17/17 PASS).
- 12:59 **Carry-in select bit found (offline).** Plain vs arithmetic chains at 5 LABs. The consistent core is mostly LUT cells (the
  arithmetic LE stores its mask under another input order), plus one bit per LE that has a carry input: frame (LUT frame 0 − 1),
  byte = the LE's low byte (+1 for odd slots), LUT plane. It's **active low**: 0 in 23/23 arithmetic LEs with a carry input,
  1 in 9/9 chain starts and in 573/575 plain LEs. The 2 exceptions are the byte-wrap LE X36Y11N18, where my simple formula
  doesn't apply the wrap. Not tested on silicon: writing it is a non-LUT config bit, outside the approved classes.
- 13:02 **Carry counter at other LABs:** cnt4c pinned to X22Y12 and X30Y20 (`cnt4c_x22y12`, `cnt4c_x30y20`). Up, down and 4 random
  machines are correct, **6/6 at each LAB** (18/18 with X3Y1). So the chain-start input order (a→p2, b→p3, cin→p0, d→p1)
  holds beyond X3Y1, and LEs 1–2 read (2, 3, 0, 1) from their bases at every LAB.
- 13:03 Tying arithmetic LEs' datad to constant 1 (instead of a pin held high) changes what Quartus stores: 2 of 4 LEs no longer
  match their placeholder. So arithmetic templates keep datad on a pin held at 1.
- 13:04 No reply on #3 yet. Bounded pilot (≤ 1.5 h, data only) on inter-LAB routing with a controlled design `xr:`: one source LE
  (pins in) in LAB L1, one dst LE in LAB L2 = L1 + (dx, 0) reading *only* the source on dataa (other inputs unconnected), dst → D5.
- 13:08 **Inter-LAB pilot, first result:** with one net crossing to the *neighbouring* LAB (dx = 1), the dst's select code depends only on the
  source slot, identical at two LAB pairs for 16/16 slots, presumably the direct links between neighbouring LABs. At dx = 2 it's
  Quartus's wire choice (2/16 identical). Mapping the direct links: dx = ±1, dst slots 16 and 6, 2 LAB pairs (128 compiles).
- 13:19 **Neighbour-LAB links (offline, 320 compiles):** for a net from a source LE to an LE in the LAB at dx = ±1, the dst-side select code
  depends only on (dx, source slot). It's identical at 2 LAB pairs and 6 dst slots (0, 6, 10, 16, 22, 30) for all 16 source slots
  in both directions, in 1–2 bits of the same frame −12..−2 mux as local lines. 15–16 distinct codes per direction, and only
  3–4 coincide with local-line codes. Table: `li_neighbour.json`. Source-side bits couldn't be isolated (pin routing to Q
  changes ~10 bits in the source LAB even when only the dst slot moves). Not on silicon: that would need source-side
  confidence, which the user chose to keep offline.
- 13:27 **Neighbour table blind check:** 3 new LABs (X28Y5, X6Y12, X20Y21), new dst slot 26, both directions: **94/96 codes predicted**.
  The 2 misses (X20Y21, dx = +1, sources 14 and 16) use the same physical input with a different code, probably a different
  wire Quartus chose. The physical dst input per source slot is fixed (same at 4 LAB pairs) and is recorded in the table.
- 13:31 **Vertical neighbours (dy = ±1, 64 compiles):** the code is identical at two LAB pairs for only 2–3/16 source slots. That's
  general routing chosen per build, so the fixed links are horizontal only, consistent with Cyclone-family "direct link"
  interconnect. `xr:` takes an optional 5th field DY.
- 13:38 Corpus refreshed: 5,996 builds, `corpus.py verify` 5996 identical. `freeze` now skips builds of scratch templates that
  have since been removed (cnt4c_d1, v_romseq_chk7/8). selftest 18/18 PASS.
- 13:47 **FF enable/sync-clear, second try (`ffe2:` design with `dffeas` primitives and C always routed into the LAB): clean result.**
  The first design let Quartus fold the control into the LUT, which is why it looked noisy.
  - **Sync clear:** one bit per register, at frame +11 in the LE's byte column (LE 0..15: 0, −1, −8, −9, −16, −17, −24, −25,
    −38, −39, −46, −47, −54, −55, −62, −63, relative to LE N0's low byte). It's additive: 15/15 combinations. On top of that
    come 4 LAB-wide routing bits that bring C onto the LAB's clear line.
  - **Clock enable:** a per-register select between the LAB's two enable lines (Quartus puts C on one line and VCC on the
    other). It's at frame +11 at bytes −4, −5, −12 (LEs 1–3), −20, −21, −28 (LEs 5–7), and so on. The lowest register of each
    4-LE group is always on line 0, so its bit wasn't observed.
  - Identical at X10Y10, X22Y8 and X30Y20 (16/16 combinations each). Table: `ff_control.json`. Offline only.
- 13:52 **Async clear and sync load (64 + 15 compiles):**
  - **Async clear:** one enable bit per register at frame +10. Bytes for LE 0..15: 3, −4, −5, −12, −13, −20, −21, −28,
    −35, −42, −43, −50, −51, −58, −59, −66. Additive 15/15, identical at 2 LABs.
  - **Sync load:** uses the *same* per-register bit as sync clear (frame +11, 15/15). So that bit enables the LAB's
    synchronous controls, and LAB-wide bits choose clear vs load.
  - **Enable select:** the 12 observed enable-line select bits sit exactly in the async-clear byte columns, one frame
    later, which predicts the 4 unobserved ones (bytes 3, −13, −35, −51).
  - `ff_control.json` updated.
- 13:57 **Combinational vs registered LE output (`ffe2:osel:K`, 32 compiles): entangled.** A parity LUT reads either r[i] or d[i],
  with all FFs kept via a second LUT. The result is deterministic (identical at 2 LABs for all 16 K) but not additive (6/15).
  The changes are in the frame +8/+9 output-select columns seen with the second path, and in the frame −18..−2 input muxes,
  because Quartus reassigns which LE output drives which line per variant. Not decoded today.
- 14:01 Neighbour links: the physical dst input Quartus uses per source slot is now recorded for both directions (always input 0 or 1).
  Forcing a second input with a 3-input dst (`xr3:`, 64 compiles) didn't work: Quartus still gives the link its 0/1 input in
  62/64 builds, and puts the pins on the others. The {2,3} partner is unknown except for 2 builds that used input 3.
- 14:03 **FF control blind test:** 18 random (LAB, kind, K, LE group) cases at 3 new LABs, predictions written before compiling
  (`out/ff_blind_predictions.json`): **16/18**. Both misses were at X19Y22, LEs 12–15, where the byte offset runs off the
  bottom of the frame. Fitting a byte wrap afterwards (byte < 1 → plane + 1, +252/+251, so a threshold of 1, unlike the
  LUT cells' 2) makes it 18/18. The wrap is post hoc, not blind.
- 14:05 Drafted `UPSTREAM_COMMENT_3_DRAFT.md` (M9K, arithmetic, FF controls, neighbour links). **Not posted**, it needs the user's OK.
- 14:07 **Clock select (`ffe2:clk`, 32 compiles):** registers clocked by C instead of B flip exactly the *same* per-register bit as the
  enable-line select (frame +11, bytes −4/−5/−12 for LEs 1–3), at 2 LABs for all 16 combinations. So each register picks
  one of the LAB's two {clock, clock-enable} pairs, as in the Cyclone IV LAB-wide control description. The bit is renamed
  `pair_select` in `ff_control.json`.
- 14:16 **LAB-wide control bits (75 compiles, 5 LABs):** bits that appear at all 5 LABs when a pin drives the register controls:
  - sclr: (+9, −31);
  - aclr: (+6, −31), (+7, −31);
  - enable on pair 0: (−1, −29), (0, −29);
  - registers split over both {clock, enable} pairs: (−8, −31), (+1, −34);
  - all registers moved to another clock: (−4, −36), (−3, −35);
  - sload: 6 bits.

  All are (frame, byte) relative to LE N0, in a control column 29–36 bytes below it. The other 0–14 bits per LAB vary between
  LABs (routing of the pin onto the control line). Recorded as `ff_control.json` → `lab_wide`; meanings inferred, offline only.
- 14:23 **LAB control-line mux, local sources (`ffc:`, 88 compiles):** the control (sclr, aclr, ena, clk) of 4 registers comes from an LE in the same
  LAB at 11 different slots. For sclr and ena, the slot-dependent bits in the control column (bytes −37..−27, frames −14..+11) are
  identical at 2 LABs for 9/11 slots. They form a 5–7-bit code per slot, the same for sclr and ena: a shared control-line
  mux, with separate bits for which control it drives. aclr and clk codes hardly depend on the slot (3–4 distinct), so those
  arrive over another path. The disagreeing slots (12, 14) are LEs whose own LUT inputs sit next to that column. Table:
  `li_control.json`.
- 14:23 The one bit by which the ena and sclr codes differ is (−4, −31) for slots whose local line directly reaches LUT input 0, and (−10, −31)
  for slots reaching input 1 (9/9, against `li_direct.json`). So the LAB control mux is entered from the same two direct line
  groups as LUT inputs 0/1.
- 14:29 **Comb vs registered output, solved (`oreg:S:V`, 52 compiles):** the src LE feeds two LEs in its LAB, one with its LUT output and one
  with its FF output, then the two are swapped. Exactly **2 bits** differ, identical at 2 LABs for all 13 slots. The dst-side codes
  don't change: one dst always uses the direct local line, the other the second path. So each LE has two local outputs, each
  with a comb/reg select in the LE's own plane: **direct line at frame +8, second path at frame +9, 1 = registered**. That's
  why the earlier `osel` test looked tangled: Quartus moved which output carried what. Table: `le_output_select.json`.
- 14:30 **Correction:** a check with both dsts reading the FF (`oreg:S:2`, 13 compiles) gives 0 for both bits at all 13 slots. That falsifies
  my first reading. The consistent one: **1 = combinational, 0 = registered; frame +9 = direct line, frame +8 = second path**. It
  fits V = 0, 1 and 2. `le_output_select.json` is corrected.
- 14:35 **Output-select table:** completed for slots 20 and 28. Blind check at X6Y12 and X28Y5: **24/26** builds differ in exactly the 2
  predicted bits. The direct-line (+9) bit was right in 26/26. In the 2 misses, and for slot 24 between LABs, the second-path
  (+8) bit sits one byte over (0 ↔ 1), so it depends on which of the two second-path lines Quartus uses.
- 14:35 **Source side of neighbour links, partly:** in every cross-LAB build the source's direct-line select (+9) is 0, and exactly one
  of its two +8 output selects is set. So an LE has a local output plus **two general outputs** (byte 0/1 at frame +8). The
  "second path" inside a LAB is one of these looping back. For neighbour links the output is fixed per (direction, slot):
  left and right use opposite outputs, identical over 2 LAB pairs and up to 6 dst slots each (`li_neighbour.json` →
  `src_output_byte`). Whether the link needs further source-side driver bits is still open.
- 14:38 **Neighbour-link driver bits found:** comparing xr builds that differ only in the source slot, removing the LE regions of both sources
  and of the dst leaves 1–2 bits per source slot, in the source LE's plane and byte column, in the routing frames between LAB
  columns. Right links have 2 bits at frames +16..+21, left links 1 bit at frame −22. They're identical at 2 LAB pairs and set
  as predicted in **92/93 builds at 3 other LABs**; the miss is X20Y21 slot 14, the same build where Quartus used another wire
  for the dst code. So a neighbour link appears to be: dst select code + the source's general-output select (+8) + these
  driver bits. All of it is offline; writing it on silicon would need source-side bits, which you chose to keep offline.
  `li_neighbour.json` → `src_driver_bits`.
- 14:41 **2-column hops (dx = 2), first look:** the source-side bits come in pairs in fixed frame groups: +16/+18 (as for right neighbour
  links), +51..+57 and +83..+85 (the routing frames of the next columns over), at bytes near the source row. Which pair is
  used varies with Quartus's wire choice (agreement between 2 LABs in only 4/16 slots). Decoding general routing black-box
  needs either many more builds clustered by wire, or wire names from Quartus's timing reports, as upstream did. The second
  is a methodology change, so I'm leaving it for you to decide.
- 14:50 **I/O periphery decoded (`io:` design, 19 compiles):**
  - Format: frames 1..36 are one stream of 9 logical 255-byte frames, every byte ×4. Each logical frame carries the core CRC
    (0x8005, init 0xFE54) over its first 253 bytes, also ×4: 414/414 blocks in 50 files.
  - Header sum: a logical plane-2 bit at (frame k, byte p) weighs 2^((p + 5 + 4k) mod 8), fitted on 14 variants.
  - `periph.py check`: **15/15 I/O variants rebuilt byte-identical** from io:base.
  - Settings: pull-up and bus hold are one bit each per pin, adjacent bytes (pins A..D, Q). Drive strength and I/O standard
    are a few bits per output. MINIMUM CURRENT = 4 mA, and 8 mA is the default.
  - `vidorlo` vs `vidor` = Q's 6 drive-strength bits only.
  - The header-sum selftest now accounts for I/O changes. selftest 22/22 PASS.
  - Offline only: gate.py still refuses periphery changes.
- 15:10 **Pull-up per pin, all pins (`iopin:`, 252 + 138 compiles, ~17 min):**
  - 138 of 252 BGA positions are legal inputs here. Each has **exactly one** pull-up bit, spread over all 8 planes and all 9
    logical frames.
  - That gave the header weight for every plane: 2^((p + 4k + c_b) mod 8) with c = {0:4, 1:6, 2:5, 3:1, 4:7, 5:5, 6:0, 7:4}.
    One offset per plane fits all 138 pins.
  - `periph.apply` toggles the pull-up byte-identical to Quartus both ways at **138/138** pins. Table: `io_pullup.json`.
- 15:28 **Output pins (`iopinq:`, 252 + 138 compiles, ~17 min):** 139 pins are legal (138 per pass plus the fixed one). Changing
  8 mA → 4 mA flips 6 bits at **fixed offsets from the pin's pull-up bit** (+5, +6, +7, +9, +15, +17 bytes, same plane):
  137/137 predicted. The rule needed for that: byte 0 of each logical periphery frame is unused, so the stream runs
  over bytes 1..252 and then continues in the next frame. Bus hold sits at offset −1. `periph.apply` rebuilds 138/138
  drive changes byte-identical. Tables: `io_drive.json`, `io_tile.json`.
- 15:31 selftest 23/23 PASS (new: I/O tile check over 275 pin probes). Corpus refreshed and verified.
- 15:35 **More I/O tile bits (`iox:PIN:VARIANT`, 29 compiles):** open drain = offset −4 and core-driven output enable (tri-state) = +1 from
  the pull-up bit, same plane, at 9/9 pins each. The tri-state enable also needs ~6 core routing bits. A fast output register
  changes only core-frame bits (13), none in the periphery. `io_tile.json` updated.
- 15:39 **Global clocks (`gclk:PIN`, 48 compiles):** 4 registers clocked from each of the 16 dedicated clock pins, at 3 LABs.
  - 59 bits change with the clock pin, and the LAB's own control column doesn't change at all.
  - **40 global bits:** identical at all 3 LABs, in per-side frame groups (frames 46–47, 956–983, 1026–1053, 1992–1993). The
    pins group by side: E1/E2/M1/M2, M15/M16/E15/E16, A8/B8/A9/B9, T8/R8/T9/R9.
  - **19 regional bits** that move with the LAB: spine frames 487–488 for X10Y10 and 1592–1594 for X22Y8/X30Y20. They are
    12 one-cold bits (6 + 6), 4 one-hot side-select bits and 3 index bits.
  - So clock routing goes pin → side clock control → regional spine select → LAB clock line. Table: `gclk.json`; meanings
    inferred, offline.
- 15:56 **Regional clock model (102 more compiles: every column at Y10, every row at X8, a 7×6 grid; 94 LABs):** the clock-pin-dependent
  bits besides the global ones are:
  - 2 **quadrant** bits: frame 487 for x ≤ 20 or 1592 otherwise; bytes 66/235 for rows ≤ 14, 39/209 for rows ≥ 20.
  - A 4-bit **row clock select** in a spine frame (488 for x ≤ 12, 489 for 14–20, 1593 for 21–29, 1594 for 30–33), at the LAB row's
    LUT byte −62 + {0, 5, 6, 8}, same plane. It uses the LUT byte wrap but with threshold < 1 (as for the FF control bits).

  That fits 93/94 LABs; row 14 (last row above the die centre) has its own layout, recorded as an observed exception. selftest
  now 24 checks, all PASS.
- 15:57 **M9K port-A width code (existing rom2 builds):** a one-hot code in the frames just before the block. ×1, ×2 and ×4 are at
  (−1/−2/−3, −9); ×9 at (−1, −10); ×18 at (−2, −10), also used for 9×512; ×36 sets none. Plus 4 "not ×36" bits. Identical
  at X13_Y10 and X25_Y20 (relative to F[X] and the row byte). `m9k_mode.json`.
- 15:59 M9K width code, blind at X13_Y4 and X25_Y12: **14/14**. The "not ×36" bits were 8/14 as written, because at Y4 the −64 offset
  runs off the frame bottom; with the usual byte wrap it's 28/28 over all 4 sites (wrap added after the check).
- 16:03 **PLL counters (`pll:M:D`, 26 compiles):** all PLL bits are in periphery logical frame 0, plane 1; no core bits change.
  - Model, exact for the 13 builds with f_out ≤ 288 MHz: M = A + B (5-bit fields at bytes 174 and 183), C0 = C1 + C2 (4-bit
    fields at 157 and 166) with an odd flag at 165, N = 2, f = 48·M/(N·C0).
  - Above that (×7..×16), C0's fields are 0 and A/B follow a pattern I haven't explained. Partly decoded: `pll.json`.
- 16:04 12 more PLL builds: A/B are ≥ 6 bits (20:3 → A = B = 40), and N sits near bytes 193..223 (changes for 25:4, 27:4, 20:3,
  15:2). When M/2 is odd the A/B pair carries an offset (A = M/2 − 1, B = M/2 + 2) that I can't explain yet. Raw diffs for all
  37 builds are kept in `pll.json` for later; PLL paused here.
- 16:05 **Embedded multipliers (`mul:MODE`, 6 compiles):** signed vs unsigned changes exactly **2 bits**, one per operand: frame 940,
  plane 7, bytes 203/205 for the 18×18 build and 63/65 for the 9×9 build (Quartus placed them at different sites). No periphery
  bits change. 9-bit mode and input/output registers make Quartus re-place the shift registers (1600–2000 bits), so they need
  pinned placement to separate; not done yet.
- 16:10 **Multipliers pinned (`macm:` with cyclone10lp_mac_mult + mac_out; column X18, DSPOUT slot N2):** the sign bits are
  frame 940, at the row's LUT byte −29 (signa) and −31 (signb), same plane. Fitted at 3 rows, **8/8 blind** at 8 more.
  Register and width modes still drag in DSP-column routing. `dsp.json`.
- 16:15 **`periph.py set`:** writes pull-up, bus hold, drive (4/8 mA) and open drain for any mapped pin without Quartus. It's
  byte-identical to Quartus for pull-up 138/138, drive 137/137 both ways, open drain 8/8, bus hold 3/3, and the CLI matches
  io:q_cur_4. Added the Vidor test pins (T2, P3, R3, T3) to `io_pullup.json`. selftest 25/25 PASS.
- 16:18 Housekeeping: rebuilt the macm builds with the committed generator (a reverted experiment had left builds from a
  different design text). Sign model 11/11 on the rebuilt files. Corpus 7,523 builds, verify all identical.
- 16:22 **Arithmetic-mode bits, second look (existing chain builds, 5 LABs):** outside the LUT cells, only frame −1 bits near each LE
  change, identically at all 5 LABs. One is the carry-in select found earlier, 1 → 0 for N2/N4/N6 and 1 in the chain start.
  The other sits in the column beside it (−1 for even LEs, +2 for odd ones) and goes 1 → 0 for N0, N4 and N6, but stays 1 for
  N2. That's consistent, but I don't understand it yet (a lutc/cin select would be expected to flip in all four).
- 16:23 Vertical links (dy = ±1), source side: output byte and driver bits agree between 2 LABs for only 1/16 slots, with bits in frames
  +13..+22 that vary per build. That's general routing at both ends, unlike the horizontal direct links.
- 16:24 **Periphery format on the EP4CE6 die:**
  - On our own 10CL006 builds, frames 1..24 are 6 logical 210-byte frames, ×4, with the same CRC: 24/24.
  - On upstream's 108 EP4CE6 RBFs (read as data): 107 pass. The one that fails is their hand-built
    `simple_led_iob_bidir_r5.rbf` (IOB_IN/OUT/OE signatures overlaid with loader masks).
  - Upstream maps I/O per pin as cell signatures (e.g. "CLEAN38" OE cells). Those signatures presumably include the ×4
    copies and the CRC-bit changes. XOR-overlaying whole deltas keeps the affine CRC consistent, but masking or cancelling
    cells doesn't, which matches the one failing file.
  - Correction to what I told you earlier: upstream *has* done I/O work. What's new here is the structure (×4 copies,
    logical-frame CRC, header weights, fixed per-pin offsets).
- 16:27 **PLL decoded (8 more compiles):** the low bit of each M field is a flag. A's is "C0 bypassed", B's is "M odd", like
  C0's odd flag. N is a hi/lo pair at 193/202 with odd flag 201 and bypass flag 210. **f = 48·M/(N·C0) reproduces all 46 PLL
  builds** (ratios 1/2..20, N = 1..3, with and without compensation). The asymmetric A/B values were just the flags. Loop
  settings at bytes 219..224 remain undecoded. selftest 26 checks.
- 16:33 **PLL: uniform counter model (19 more compiles, incl. 3 with all five outputs):** seven counters in 18-byte blocks (8-bit
  hi, odd flag, 8-bit lo, bypass flag) at bases N 193, M 175, C0 157, C1 139, C2 121, C3 103, C4 85. It reproduces all 46
  single-output builds and the five-output sets. The "M flag" from earlier is really C0's bypass bit. Quartus picks the
  physical C counter per clk port.
- 16:37 **PLL duty cycle and phase (9 compiles):**
  - Duty: the counter block's first field is the low time and the second the high time (25 % → 9/3, 33 % → 8/4, 75 % → 3/9).
  - Phase (C0): in logical frame 1, a 3-bit VCO tap select (bytes 139..141) and an initial count (bytes 131.., = 1 + whole VCO
    periods). Two more 3-bit groups also move with the tap; not decoded.
  - Loop bits 219..224 depend on M/N in steps (e.g. byte 219 set for M ≥ 14 at N = 1), but no formula yet.
  - `pll.json` updated.

## Silicon tests of the offline classes (2026-11-23, approved by the user: "Go ahead with the board tests")

- 18:04 Gate extended: `gate.check(..., periph_bits=...)` allows declared logical periphery bits (all 4 copies) and the periphery
  CRC bytes, and requires every periphery CRC to be valid. Undeclared or stray periphery bits are still refused (tested).
  New script `newclass_test.py`, vidorlo pins, all-zero control before and after. **15/15 files correct**
  (`out/newclass_20261123_180424.json`):
  - **A, bus hold vs pull-up (periph.py):** each of D1..D4 patched to bus hold in turn. Driven low and released, the patched pin
    stays 0 and driven high it stays 1, while the pulled-up pins and the Quartus base read 1 after release. 5/5 files, every
    pin as predicted.
  - **B, PLL counters (periph.py):** a 26-bit counter on c0, D5 = bit 25, period measured over 12 s.
    - Quartus base 48 MHz → 47.96; Quartus 24 MHz control → 23.98.
    - Patched: M8/C16 → 23.98 (24 predicted); M11/C22 → 23.98 (24); odd C0 = 9 (4/5 + odd flag) → 63.95 (64).
    - Patched: M10/C10 and M13/C13 → 47.96 (48). These show the patched VCO settings (480/624 MHz) lock, but they'd also read
      48 if the patch were ignored. The other three are the discriminating cases.
  - **C, LE output select (core, non-LUT bit):** base D5 = comb ^ reg, 79/79 readings. Flipping the direct-line select to
    registered, or the second-path select to combinational, gives D5 = 0 as predicted, 79/79 each.
- 18:19 **FF control enables on silicon (`ffctl_test.py`): 12/12** (`out/ffctl_20261123_181657.json`). sclr, sload and aclr bases, each
  patched to K = 0, 5 and A, with D5 checked against a simulation, 80/80 readings each. K = 0 (LAB line driven, no register
  enabled) is a configuration Quartus never emits. The subsets are byte-identical to Quartus's own K builds (14/15 offline;
  the exception is K = 0).
- 18:19 **Carry-in select: my reading was wrong.** With the bit set on a1, the counter followed neither "carry-in = 0" nor "= 1", and the
  script stopped. A recording-only rerun of both carry-cut files (a1, a2) fits exactly one model out of 144 tried: with the bit
  set, **the LE's sum uses c = 1 while its carry-out still uses the real carry-in**. So the bit is the `sum_lutc_input` select
  (0 = cin, 1 = datac, which reads 1 when unconnected), not a carry cut. That also explains why chain starts and plain LEs
  have it set. **Blind confirmation:** 3 new patched files (up counter with a3 cut, with a1 + a2 cut, and a random machine with
  a2 cut), predictions written before loading (`out/ffctl_carry_blind_predictions_20261123_181843.json`): **3/3, 360/360
  readings**. Controls held throughout.
- 18:23 **Combined patch demo (`demo_patch.py`, design `demo:X13_Y15`):** one Quartus-placed design (ROM + PLL + pinned LUT), four kinds
  of change without Quartus in one file, gated as a unit:
  - 276 ROM content cells;
  - the LUT mask, CACA → C5CA, input order read from the base;
  - PLL C0 12 → 24;
  - bus hold on D4.

  Predictions were written before loading (`out/demo_predictions_20261123_182229.json`). The Quartus base and the patched file
  both behaved as predicted: ROM/LUT 128/128 readings each; PLL 47.96 → 23.98 MHz; D4 released low reads 1 → 0. Controls held
  (`out/demo_20261123_182321.json`).
- 18:32 Posted the third comment on #3, updated first to today's results (neighbour source bits, silicon results, full PLL model,
  demo): https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3#issuecomment-7108793684 (text in `UPSTREAM_COMMENT_3.md`).
  You confirmed that reading Quartus timing reports is fine. README wording updated; routing between LABs can now use
  wire names from them.
- 18:44 **Remaining board tests (`pending_test.py`):**
  - **Neighbour link: source switched.** The dst in X11Y10 now reads source slot 18 instead of slot 4, using the dst code, the
    dst LUT input, slot 18's general-output select and its two driver bits. All 15 patched cell values match Quartus's own
    slot-18 build; slot 4 stays alive, driving its own unread link. **16/16 combinations as predicted** (base also 16/16).
    This is the first source-side routing patch on silicon.
  - **Row clock select: failed, then fixed.** Copying row 5's select into row 7 over the model's 4 offsets stopped row 7's
    counter (0 MHz); row 5 was unaffected and the controls held. The cause is that row 5's select also uses offset +7, which
    the E1/T8 data never showed. The encodings are c0 = {+5, +7}, c1 = {+5, +8}. Copying the full pattern (2 cells) moved
    row 7's counter **from 23.98 to 47.96 MHz**, as predicted. `gclk.json` corrected.
  - **M9K width code:** contents-only file 64/64. With the ×18 code patched to ×9 the ROM reads ×9 word **2a + 1**, a unique fit
    among 4 hypotheses listed beforehand (64/64): the unconnected extra address LSB reads 1.
  - Logs: `out/pending_20261123_184127.json`, `out/pending_m9k_*.json`, `out/pending_G2_*.json`.

## Small leftovers (2026-11-23, user: "Wait with the routing and do the small leftovers instead")

- 19:34 **The second arithmetic bit, explained (silicon, 4 patched files):** the "other" frame −1 bit (column −1 of even LEs, +2 of odd LEs)
  belongs to the **pair partner's** sum c-input select. Each LE's sum c-input has a 2-bit select: its own bit (found earlier)
  plus this bit in its partner's column. Both 0 means carry-in; either set means datac, which reads 1 when unconnected.
  Evidence:
  - a2's bit 0 → 1 makes a3 toggle every clock (a3's c = 1).
  - a0's bit 0 → 1 fits uniquely "a1's sum c = 1" (1 of 16 hypotheses, 120/120 readings).
  - a1's bit 1 → 0 changes nothing, since it drives a0, a chain start whose sum ignores c.
  - A random machine passed blind (a1 there doesn't depend on c), but the up-counter case was 55/120 under my first
    hypothesis. So the final model is post hoc, not blind.

  It also explains why chain starts and plain LEs have the bit set and the second LE of a chain is the odd one out.
- 19:38 **PLL loop bits (22 compiles with reports kept, `out/pllrpt`):** the fitter report's PLL Summary gives charge pump, loop R/C and
  the VCO post-scale K. **Loop R = 5-bit field at bytes 220..224** (settings 27/24/20/8 match exactly), and **byte 219 = VCO
  post-scale K = 1** (22/22). Charge pump and loop C never vary here, so they stay undecoded. altpll on this family rejects
  explicit loop parameters; only bandwidth_type changes them (LOW → R = 8, with Quartus also re-picking M/N). `pll.json` → `loop`.
- 19:40 **Multiplier modes (16 compiles, shift register pinned):** after keeping only DSP-column bits identical at two sites:
  - 4 bits at frame +1 appear only with input registers, and 2 only with output registers;
  - 4 bits are common to every registered variant (clock into the block);
  - 9×9 mode adds 1 bit;
  - both mixed modes (9×18, 18×9) set the same 9 bits at frame +1, perhaps "zero the narrow operand's upper half".

  Offline candidates only (`dsp.json` → `mode_candidates`). The rest is routing of clocks, unused inputs and the parity tree.
- 19:43 **M9K RAM mode (6 compiles, `rr:SITE:rom|ram`, address counter pinned):** 3 bits just before the block take the RAM value
  at all 3 sites (X13_Y10, X25_Y20, and X13_Y4 with byte wrap), and a 4th at two sites. These may include the write-enable/data
  input selects as well as the mode. Offline candidates in `m9k_mode.json` → `ram_mode_candidates`.
- 19:43 Housekeeping: multiplier sign builds rebuilt with the pinned-input generator (sign model 11/11). Corpus 7,588 builds, verify
  all identical. Rebuild spot checks after the generator edits (pll, gsel, pllcnt, xr2) are byte-identical.
- 20:00 **Board tests of the mode candidates (`dspram_test.py`, `out/dspram_20261123_200014.json`):**
  - **M9K RAM mode confirmed.** The RAM base writes correctly (3 × 512 words). With the 3 candidate bits at their ROM values, the
    design's writes are ignored and the initial contents read back (3 × 512 words correct).
  - **Multiplier 9×9 bit confirmed:** the product splits into two 9×9 products (80/80 clocks; parity can't tell which half is
    where).
  - **Multiplier register bits not confirmed.** With the output-, input- or both-register candidates (plus the 4 clock bits)
    D5 stayed 0 in all three files; mismatches equal the predicted 1s. The registers are in the path but never clock, or are
    held clear: their clock/enable/clear inputs are unrouted in the unregistered base, and unconnected inputs read 1.
    Quartus's registered builds add 70–127 more bits there. Left for the routing work.
  - Controls held throughout.

## Step 1: routing between LABs (2026-11-23)

- 20:44 **Wire labels from timing reports** (`routes.py`): rebuild each design keeping the project, verify the RBF is byte-identical to the
  cached one, run `quartus_sta` with `set_max_delay` from each input to Q and `report_timing -show_routing`, and keep every hop
  (`out/<job>.route.json`). Node names: LE_BUFFER (2 per LE), R4/C4, R24/C16, LOCAL_INTERCONNECT, IO_DATAIN, BLOCK_INPUT_MUX.
- 20:44 **Corpus:** 280 two-LE builds (xr designs, 10 LABs × up to 38 offsets), 14 min.
- 20:44 **Pooled PIP model** (`routemap.py pooled`): each hop becomes a translation-invariant key (from type/index/offset → to
  type/index), with bits relative to the to-node's column frame and row (LUT row-space index, so byte wrap is automatic).
  Candidates are bits present in every instance and in ≤10% of background anchors. 360 keys with ≥3 instances, many with 1–2 bits
  (e.g. R4 → R4 continuation: 1 bit; C16 → R24: a 2-bit pair). **5-fold cross-validation:** about 109 keys per fold with 1–4 bits;
  held-out uses had all predicted bits in **99.5%** (3178/3195); held-out non-uses lacked them in **100.0%** (27640/27643).
  Table: `routing_pips.json`. Not covered yet: I/O (periphery) PIPs, wires in M9K/DSP columns, bundles with > 4 bits. Offline only.
- 22:38 **Corpus grown to 900 builds** (620 more, 30 min, 0 failures). Baseline pooled model: 5-fold CV ~508 keys/fold, 98.9 % / 99.9 %.
  **Fix: anchor at either end of the hop.** Many switches (notably LE_BUFFER drivers) sit at the driving end, and fixed LAB
  offsets aren't fixed frame offsets across M9K/DSP columns. Choosing per key the end that gives a clean 1–4-bit set: **867 of 1,422
  keys mapped** (337 at the from end). 5-fold CV with the anchor chosen on the training folds: **~760 keys/fold, 98.73 % of
  held-out uses complete, 99.64 % of non-uses clean.** `routing_pips.json` updated (867 keys, with anchor).
- 23:38 **Coverage work:** only 36 % of a build's hops had a known key, explaining 38 % of its routing bits. Three fixes:
  - LUT input hops now carry slot and port (`LCCOMB_X_Y_N:datac`);
  - switches into a wire that other sources share are measured against builds where that wire is undriven;
  - LUT-cell positions are removed from candidates (the fixed destination mask had leaked in).

  Result: **1,643 clean keys**; hops with a known key **49 %**, routing bits explained **51 %**, every predicted bit set (in-sample).
  The rest is mostly I/O hops (bits in the periphery) and rare keys. Running: cross-validation of the cleaned model and
  1,000 more corpus builds.
- 00:33 **Corpus 1,900 builds** (1,000 more, 51 min, 0 failures). `routemap.py pooled` now indexes bits by frame and runs in **1 min 44 s**
  instead of 23 min. **2,461 clean keys** (3,175 with ≥ 3 instances). Coverage over 200 sampled builds: hops known 51 %, routing
  bits explained 54 %. **Excluding I/O hops (34 % of all hops, same pins in every build): fabric hops known 76.3 %.**
  - The remaining fabric gaps are mostly keys with **no** candidates: C4/R4 → LAB line, R24 → C16/C4. Example C4 I7 → LAB line
    35: across 142 instances only 50 bits are shared, and those are defaults. Odd rows alone share 204, so the code seems to
    depend on row parity or position along the wire, and the instances cluster in a few rows (corpus bias from the Q path).
  - Next for these: single-net differencing, i.e. design pairs that differ in exactly one hop, as upstream's pass bar
    recommends.
- 00:39 **Cross-validation built in** (`routemap.py cv`, frame-indexed, full model: both anchors, wire-undriven background,
  LUT-cell filter), 4 min 49 s: **~2,245 keys per fold; held-out uses complete 98.92 % (48768/49300), non-uses clean 99.77 %
  (661430/662933).** `routing_pips.json` = 2,461 keys. (An old, slow CV script was stopped; it had used an incomplete model.)
- 00:51 **Die-wide graph + router** (`routegraph.py`): the clean keys instantiated over the die give **2.18 M PIP instances**, and a
  Dijkstra router finds paths between LEs using only known PIPs (row, column, multi-hop and long-wire routes).
- 00:51 **Reroute test files prepared** (`reroute.py plan`; offline, nothing loaded): 8 xr designs on vidorlo pins whose Quartus
  src → dst segment uses only known PIPs. In each, that segment's bits are cleared (those no other hop of the design shares)
  and a different route from the router is set, over nodes no net of the design uses and ending at the same LUT input. All
  pass the gate (exactly the changed cells). Prediction: D5 = ¬parity(D1..D4) for all 16 inputs, as in the Quartus base. This
  is arbitrary routing on silicon, so it waits for the user's OK.
- 07:55 **Reroute board tests (approved): 0/3 rerouted files worked; every Quartus base 16/16.** D5 stuck constant each time; every file
  loaded and configured, and the controls held.
  1. 4-hop route from the source's other output buffer: the hops leaned on rare keys (5–11 instances); the R4 → LAB line hop had
     one doubtful bit.
  2. 7-hop route over well-supported keys (≥ 20 instances); only the Quartus route's last hop cleared.
  3. 2-hop branch off a Quartus-driven C4: C4 I5 → LAB line 21 (one bit) + line 21 → datad (group bit change). Failed too.

  Findings along the way:
  - Cross-validation measures whether predicted bits are present, not whether a key is complete. By training support:
    3–5 instances 91.9 %, 6–10 97.7 %, 11–20 99.3 %, > 20 99.9 %.
  - LUT-input keys now pool across slots of the same parity, anchored at the LE. That gives 184 keys with ≥ 20 instances.
  - Fixed a bug: their "destination undriven" background never matched, so every build counted and the stage-2 bit was
    dropped. Now 2–3 bits per key (group in frames −12..−4, stage 2 at −3/−2, plus the plain-LE bit), matching the
    silicon-proven intra-LAB model.
  - Re-applying Quartus's own last hop flips 0 bits at 8/8 positions.
  - No "clear" bits exist for LAB-line muxes (60 keys). The C4 I5 → line 21 mux really is one bit (45 instances agree,
    background 0 %).

  Still unexplained. Next: single-class unit tests with a known signal (`unithop.py`): T1 switches only the destination's
  LUT-input mux to the LAB line carrying pin A (predicted D5 = ¬D1). Three T1 files are built; the board run was blocked by
  the permission system and needs the user.
- 08:10 **Unit tests on silicon (user: "Run it").**
  - **T1, LAB line → LUT input only: 3/3 PASS** (D5 = ¬D1 at X10Y10, X22Y8, X28Y12). The LE-anchored LUT-input keys work.
  - **T2, + wire → LAB line:** R4 I12 → line 36, R4 I8 → line 34 and C4 I6 → line 34 PASS (16/16). C4 I5 → line 18 (×2), → 33 and
    → 20 FAIL (D5 constant), the same class as the earlier failed 2-hop branch (C4 I5 → line 21).
  - Then **a load failed on an unpatched Quartus base** (exit 1). Stopped per the rules and diagnosed read-only: IDCODE
    0x20f20dd (10CL016) on --detect, bench answers, load average 0.6, no Quartus running. Looks like a transient JTAG
    glitch; logged before any further load.
  - Hypothesis for C4 I5: the co-occurrence trap. In the corpus C4 I5 mostly carries pins via the same upstream R24 → C4 I5
    hop, whose bits may have been absorbed into the C4 I5 → LAB line keys.
- 08:21 **T2 remainder (5 more files): all FAIL**, including R4 I4 → line 18 and C4 I7 → line 9. So it isn't specific to C4 I5. The base
  that failed to load earlier loaded fine this time (the glitch was transient).
  - **T2 total: 3 PASS, 9 FAIL.** The passes have their single LAB-input-mux bit at frame −14/−13 relative to the destination
    LAB; every failure has bits at −19..−15 or +13/+14. Only **6 of 72** well-supported LAB-line keys have bits in −14..−12, so
    most LAB-input-mux keys are suspect. Splitting by row or column phase finds no in-band bits for the failing keys either.
  - Likely cause: the LAB input mux is 2-level, with a C4/R4 tap shared by the LAB's lines plus a per-line select. In the
    corpus the taps are usually active (pins enter every source LAB), so pooling against an "undriven line" background
    can't separate them.
  - Tried single-net differencing by varying only the destination slot (96 builds, 80 routed): Quartus keeps the same LAB
    line for all slots, so it gives no contrast for the LAB input mux.
  - Next: designs that force different lines for the same wire. Occupy LAB lines in the destination LAB with other nets so
    Quartus has to pick another one, then XOR pairs.
- 09:27 **Line-forcing design `xrk:`:** 4 sources in one LAB, each driving its own LE in a destination LAB, so four LAB lines are
  needed there. `routes.py` now parses up to 20 paths per input. Corpus: 4 LAB pairs × 50 random slot seeds, **200/200 routed**,
  10 min. **`limsolve.py`** solves per LAB, exactly (no pooling):
  - select(W, L) = bits in all builds with W → L, none where L is fed otherwise or undriven;
  - tap(W) likewise.

  Selects are 1–3 bits in **frames −19..−12**, so the earlier "−14..−12" band rule was wrong.
- 09:27 **Exact selects on silicon (`limtest.py`):**
  - Base = the corpus build with Q's drive set to 4 mA by periph.py (vidor → vidorlo is only those bits). Patch: set
    select(W, L′) for an unused line L′, clear the old select(W, L), and move the destination LE's input to L′.
  - C4_X15_Y11_I10 → line 27 at X16Y14 (select at frame −18): **4/4 PASS**, bases 16/16.
  - **Negative controls** (old select cleared, nothing else): **4/4 fail as they must** (8–9/16). So the solved selects are
    sufficient and necessary.
  - Only one switch could be tested: in this corpus each wire nearly always enters on the same line (210/210 at 3 LABs).
- 09:27 **Pooled model checked against the exact solves** (pairs seen ≥ 3×): identical 6, missing bits 14, wrong bits 5, extra 1,
  no key 16. Example: R4_X10_I4 and R4_X11_I4 → line 18 at X14Y10 are exact at frames 784 and 785; pooled predicts 786 for both.
  This explains the earlier T2 failures. Pooling the LAB input mux needs a different anchor (the select position depends on
  the wire's own position), or per-position exact solves.
- 10:33 **8-net forcing corpus `xrkn:8`:** 24 destination LABs across the die × 2 source offsets (row, column) × 12 seeds;
  **552/576 routed** (28 min), up to 40 timing paths per input.
- **LAB-input-mux selects repeat with an 8-column period.** `limsolve.py` now contrasts only against builds where the line is
  unused, so a bit shared by all inputs of a line's mux is kept: selects are 1–2 bits in frames −19..−12.
  `limsolve.rule()`, leave-one-out across LABs:

  | Grouping | Exact | Solve missing a shared bit | Differ |
  |---|---|---|---|
  | none | 371 | 66 | 150 |
  | X mod 4 | 440 | 45 | 72 |
  | X mod 8 | **489** | 36 | **5** |

  The pooled model assumed one pattern for every column, which is why it failed.
- **`hopsolve.py`:** exact per-position solve of every hop (752 builds, 13,742 hops, 3 min with an inverted index). Contrast =
  builds where the hop's destination node is unused; LE signatures (bits present exactly when an LE is used) removed.
- **First full inter-LAB reroutes on silicon (`xreroute.py`): 5/5 PASS.**
  - Net s_i → LE_BUFFER → R4 W → line L → d_i moved to a different R4 wire W′ from the same buffer and a different line L′.
    Driver, select and LUT-input bits are all written by us; the old driver and select bits are cleared.
  - Positions: X36Y4 → X39Y4, X26Y4 → X23Y4, X19Y14 → X16Y14. Bases 16/16.
  - Negative controls (old route cleared only): 5/5 fail (8–9/16).
  - The driver bits sit at frames +16/+18 of the source column, and the select at −19..−17 of the destination LAB.
- 11:31 **Die-wide switch model (`switchmodel.py`) from the exact solves**
  - Key = (from type/index, to type/index, offset, column class X mod 8). Anchors: the destination LAB for selects, the source
    LAB for drivers. Consensus = bits in ≥ half of the instances.
  - Drivers need no column class: held-out precision is about the same at period 1 (85%) as at 8 (82%), with 3× the coverage.
  - New corpora: a training extension for column classes 1/2/5 (144 builds) and held-out sets 1 (96 → 72 routed) and 2
    (288/288) at columns absent from training.
  - Held-out 2 precision (all predicted bits set when Quartus uses the hop): selects 713/893, drivers 1245/1514.
    Coverage is still low.
- **Blind reroutes, every routing bit from the model:**
  - Round 1 (held-out 1): 2/3 PASS, both the same switch at X31Y16. The X12Y19 fail was used to hypothesise that M9K-column
    crossings fail.
  - Round 2 (held-out 2, held-out 1 merged into training): **0/8**, at 4 LABs, none crossing an M9K column (so that hypothesis
    doesn't explain it). Bases 16/16, controls fine.
  - Diagnosis at X30Y7: the select bit matches held-out builds exactly. The driver should be the pair (+13,−45)/(+14,−45),
    but the model wrote only (+14). Training solves often miss the +13 partner (agreement 0.45–0.78 on those keys), and the
    consensus drops it. That doesn't explain X4Y5 (2-bit driver and select, still failed).
  - Conclusion: per-position exact bits work on silicon (5/5); the translated model isn't there yet.
- 12:04 **Related-work survey** in RELATED_WORK.md. **README legal notes rewritten**: clauses 2.2.7 and 2.2.8 quoted, EU Software
  Directive Art. 5(3)/8, database right, no raw Quartus outputs committed. `.rcf` use approved by the user, on the same terms as timing reports.
- 12:04 **`.rcf` routing back-annotation works on the 10CL016** (`quartus_cdb --back_annotate=routing`; the help text says
  "Cyclone, Stratix, Stratix GX" only, but it writes a full file). It lists every net's full route in order, plus the logical
  and physical (`route_port`) LUT input: 33 nets per xrkn build, against at most 40 timing paths per input.
- **Also as an input** (`ROUTING_BACK_ANNOTATION_FILE` + `ROUTING_BACK_ANNOTATION_MODE NORMAL`): a hand-edited route is
  either honoured, or rejected with "Error on line N in Routing Constraints File" (Quartus then reroutes that fan-out itself).
  The line number tells which hop is illegal. That makes it a **legality oracle**, and a forced, honoured route differs from
  the base in exactly one net, which gives exact bits. A fit takes about 5 s. Tool: `rcfforce.py` (raw .rcf files stay in scratch).
- **First oracle results** (xrkn:8:-3:0:1 at X17Y22):
  - The two driver hops the die-wide model proposed for LE_BUFFER_X17_Y22_I8 (R4_X14 I22 and I17) are both **illegal**.
  - Scan of R4_X14_Y22 I0..47: that buffer drives only **I18** (Quartus's choice) and **I20**.
  - R4 I20 enters none of the 37 other lines of LAB X14Y22: it probably taps lines in the LABs it passes through.
  - So the blind-round failures come at least partly from wrong driver keys.
- Next: oracle-driven mapping. Enumerate legal driver/select hops per position class with error-line probes, take the bits of
  honoured single-net forces, and rebuild the switch tables from that ground truth.
- 13:12 **Driver row sweep** (`out/rcf_driver_rows.json`, X17, Y8..15, R4_X14 I0..47): buffer I8's legal wires depend on Y mod 4:
  0/2 → {18, 20}, 1 → {21, 27}, 3 → {18, 22} (Y22 agrees). The other buffers' entries are void: the classifier used an
  absolute RCF line number that is only right for net t[0]. Fixed in rcfforce (errors now reported per hop of the net). A
  re-sweep of all buffers for Y8..11 is running.
- Posted the fourth comment on 14sea issue #3 (user-approved): https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3#issuecomment-7131113747
- 13:38 **Corrected driver sweep, all 8 buffers** (`out/rcf_driver_rows2.json`, X17, Y8..11): every buffer's legal R4_X14 set depends
  on the row, and not with period 2 (I14: Y8 {22, 25}, Y10 {24, 26}). A die-wide driver table needs more than
  (buffer, index, offset); the rule is still open.
- **First honoured single-net force** (X17Y15, net t[0]: R4 I22 → line 19 forced to R4 I18 → line 16). 18 bits differ from
  the plain compile, but 8 of them flip whenever routing constraints are on, even with an unchanged route (frames
  126..186, bytes 2–3, plane 7). The identity-forced build is now the diff baseline. The other 10 bits:
  - driver at source frames +13/+14: I22 (13,−10)/(14,−10) → I18 (13,−13)/(14,−14);
  - select at destination frames −18/−17: line 19 (−18,−17)/(−17,−17) → line 16 (−18,−1)/(−17,−1). Both equal the
    exact-solve table entries;
  - the LUT-input mux of d[0] (two bits).
  So the oracle and the exact solves agree. A campaign is running: `oraclemap.py`, X17 Y8..11 (drivers, lines, bits per honoured route).
- 14:27 **Oracle campaign** (X17 Y8..11): 63 legal drivers, 19 honoured routes.
  - **Driver bits are fixed per buffer; the wire index each one reaches rotates with the row.** Each buffer has 2 (I23: 3)
    driver bit-pairs at source frames +13/+14, identical in every row; e.g. I19: A = (13,−42)/(14,−41), B = (13,−45)/(14,−45).
    A reaches R4_X14 I28 at Y8, I24 at Y9, I27 at Y11.
  - **Selects are stable by wire index:** R4 I26 → line 23 is (−19,−42)/(−17,−42) at Y8, Y9 and Y10.
  - Driver legal sets: Y12 = Y8 for all 8 buffers (period 4 in Y). X23Y8 = X17Y10, so the phase also depends on X.
  - **Pre-registered:** X22Y8 (destination X19) equals X17Y9 if the phase is (X+Y) mod 4, or X17Y11 if it is (Y−X) mod 4.
- 14:45 **Prediction confirmed:** X22Y8 = X17Y9, so the driver wiring phase is **(X + Y) mod 4** of the driving LAB (R4, offset −3).
- **switchmodel rebuilt:**
  - drivers classed by (X+Y) mod 4, and partial solves snapped to the buffer's complete pair;
  - LE configuration band (frames −12..+9) excluded from driver bits; select window −26..−13;
  - `routegraph.cell_of` never returns byte 0 (the frame marker): it wraps to the lower plane's top byte.
  - Held-out set 2: drivers precision 87% (1017/1173), specificity 99.3%; selects 86.5%, specificity 99%. Was 78% / 46%
    and 80% / 99%.
- **Blind round 3 (held-out 2, all bits from the model): 2/6 PASS**, the first passes at distinct held-out switches
  (X4Y5 R4 I21 → line 18, X30Y7 R4 I22 → line 19).
  - The RCF oracle honours all 6 routes, and its exact diffs explain every failure:
    - X27Y11 ×2: the plane-boundary wrap (byte 0 plane 4 written for byte 251 plane 5), now fixed;
    - X4Y5 and X30Y7: one bit of the driver pair missing; that buffer never appeared with a complete pair in training.
  - Next: oracle-measured driver pairs for all buffers.
- 14:54 **Model accuracy on held-out set 2:**
  - Driver pairs are now snapped per buffer across wires, into 2-bit patterns only: precision **95.7%** (1123/1173),
    specificity 99.3%.
  - Selects need all instances (n ≤ 3), otherwise 60% agreement: precision **98.4%** (854/868), specificity 99.2%.
  - Held-out set 2 has now been used for tuning, so I compiled a fresh **held-out set 3**: 64/80 built, 4 LABs never used
    before. Blind round 4 planned **0 tests**: 204 old drivers and 233 old selects have no model entry. Coverage, not
    accuracy, is now the limit, because the corpus only contains switches Quartus happened to choose.
- **`drvmap.py`:** complete R4 (offset −3) driver legality with the oracle, all 32 buffers × 4 phases (X17 Y8..11, seeds 1 +
  2730 cover all 16 source slots), about 6,100 probes. Running.
- 16:28 **drvmap done** (X17 Y8..11, 5,860 probes): about 31 legal R4 drivers over the 32 buffers per phase, 0–3 wires per buffer.
- **R4 driver = 2-level mux.** The frame-14 bit row is the physical *track*, shared by every buffer feeding it, at a 4-row
  pitch with about 17 tracks. The frame-13 bit picks the buffer.
  - (phase, track) → wire index: 44/44 known cases consistent. Elimination against the oracle's legality fills 62 entries,
    0 contradictions. 107/120 oracle-legal drivers now have complete bits (`out/r4drv_model.json`, used by switchmodel).
  - Held-out set 3 (fresh positions): drivers **96.4%** precise (347/360), **100%** specific, coverage 360/576.
  - Selects: 100% precise (130/130), but coverage only 130/880, which is why blind round 4 had no candidates.
- **`selmap.py`:** oracle select mapping, forcing every reachable R4 wire onto every free line at one destination LAB per
  class. Started at X14Y10 (class 6).
- 16:35 **selmap at X14Y10:** 245 probes, 5 honoured. Each R4 wire enters only **1–2 of the 38 lines** (I26 → 9, 23; I18 → 16), so the
  select table is sparse.
  - Selects are a 2-level mux, like drivers: inputs of a line fall into groups that share one bit (R4 I31 and I32 into
    line 37 share (−16,−60); C4 I10 is in another group).
  - selmap queued for 7 more column classes (X8, X9, X26, X3, X20, X21, X7 at Y10).
- **`explain.py`** (coverage metric toward a Quartus-free flow): templates/div24 (24-bit counter) has 710 core bits
  differing from the all-zero design.
  - lut 36%, LE-local band 38% (positional, modelled elsewhere), routing priced by the model 0.3%, other 26%.
  - Missing for a blinky: LE_BUFFER → LAB line local feedback, clock into the LAB, R4 at other offsets, R4 → R4.
  - Its .rcf parser pairs resources across fan-out branches (known artefact, to fix).
- 16:38 **RCF branch parser** (`rcfforce.branches`: blank-line branches, `label` / `branch_point` resources).
- **Neighbour links priced in switchmodel** (li_neighbour.json source driver bits). The source LE's frame-8 output-select bit
  is LE mode, not routing: in the counter it caused all 17 false predictions, and it's now excluded.
- **div24 coverage:** lut 36.1%, LE-local 37.9%, routing priced 5.4% (26 hops, 0 false bits), other 20.7% (147 bits).
  - Left: 7 neighbour hops (unmapped slots), 7 R4 → line, 5 LE_BUFFER → R4 (other offsets), the D1 path
    IO_DATAIN → C16 → R4, R4 → R4, and global clock bits.
- 17:03 **selmap, all 8 column classes:** 1,621 probes, 46 honoured routes. 33 oracle-exact selects now override the corpus entries
  in switchmodel. Held-out set 3 select coverage 130 → 158, still 100% precise.
- **Blind round 4 (held-out set 3, X14Y21, fresh position; every routing bit from the model): 2/2 PASS**, negatives fail
  (8/16), bases 16/16, controls fine. The drivers came from the track model (phase (17+21) mod 4 = 2), the select from an
  oracle-mapped entry of class 6, the old route's bits from the model.
  - Blind total so far: 2/3, 0/8, 2/6, 2/2. Only rounds 3–4 use the driver and select fixes: 4/8, and all 4 failures
    were explained by the oracle and fixed.
- 18:30 **div24's unpriced hops, by type:**
  - local feedback LE_BUFFER → own-LAB line (8 hops);
  - left-edge R4 wires (R4_X0 I70..I105);
  - the D1 input path IO_DATAIN → C16 → R4 → line.
- **Local feedback selects don't depend on the column class:** 7/8 multi-class pairs are identical across classes. Each buffer
  reaches 1–2 fixed lines (1 → 15, 3 → 15/30, 7 → 31, 11 → 32, 16 → 34, 20 → 35, 24 → 36, 28 → 37).
- **rcfforce additions:** `rename` and `rewrite` (edit a whole net block, including labels and branch points).
  `route_port` is optional: without it Quartus picks the port and the identity route is still honoured.
- **Measuring local-feedback bits by moving the net to the slot's other buffer: 0/161 honoured,** even with free port
  choice. The other buffer probably has no local-feedback connection, so a different isolation trick is needed: occupy
  the line with another net, or design variants with the same placement.
- 18:46 **Feedback isolation by R4 detour:** the feedback net is routed buffer → R4 → own LAB instead. `rewrite` now names the failing
  resource.
  - Stage 1: 384 probes, 7 legal buffer → R4 drivers (same column). Stage 2: 153 probes, 2 honoured.
  - **I16 → line 34 at X1Y6 = (−16,−36)/(−15,−36)**, equal to the corpus entry in all 7 classes. X1 is a column with no
    corpus entry, so local feedback is confirmed class-independent; the model now uses any class's entry for it.
  - div24 coverage: routing 28 hops priced (5.9%), 0 false bits, other 20.1%.
  - Still unpriced: 7 R4 → line, 5 buffer → R4 (left edge, high indices), 5 local feedback pairs never seen, the D1
    input path, R4 → R4.
- 19:59 **Blinky template `blink24`** (div24 with carry-in and Q input tied to 1: free-running, no input pins). Placed by Quartus at
  X9..X11 Y3. Coverage: lut 37.8%, LE-local 40.5%, routing priced 5.5%, other 16.2%. 14 unpriced hops: R4 dx 0 / −3 / +3
  detours, 6 local feedback, 1 neighbour.
- **Routing repair by RCF** (route the reference build only over priced hops):
  - Same-LAB destinations moved onto the source LE's own local line, one branch per destination, ports left to Quartus:
    **honoured** (s[0]). Labelled local lines are rejected; plain repeated resources are fine.
  - Cross-LAB branches as neighbour links: 0/132 with the net rewritten (Quartus silently drops the branch constraint and
    re-routes over R4), and 0/63 with only that branch changed (every free line of X9 rejected for slot 16's buffers at
    X10Y3). The line those links can reach may be taken by other nets.
  - Next: steer placement instead, so cross-LAB nets are few and use priced hop types, then repair the rest with local lines.
- 20:12 **`blink24p` (hand placement: groups 0–3 in X9Y3, groups 4–7 + lut_out in X10Y3).** Only c[3] crosses LABs, priced by
  its neighbour link.
  - Coverage: lut 38.9%, LE-local 44.8%, routing priced 3.3% (11 hops, 0 false), other 12.9%. **All 22 unpriced branches
    are local feedback** (6 buffer → line pairs).
  - The local-line rewrite is rejected for them: the local line can't reach every LUT port, so 4-input LUTs with several
    same-LAB inputs need local feedback.
  - Exact corpus solves: I15 → 33 = (−16,−27)/(−15,−27) at 9 positions; **I19 → 10 has no select bits** at 36 positions
    (probably the line's default input). I4 → 1, I5 → 17, I8 → 3, I22 → 25 are missing; the R4-detour measurement on
    blink24p is running.
- 20:26 **Blinky output path** LE X10Y3N30 → D5: LE_BUFFER I31 → R4_X7 I31 → C4_X6Y0 I43 → line I1 of the I/O row → BLOCK_INPUT_MUX → pin.
  - Single renames of its C4 or line: 0/102 honoured (a single substitution breaks the chain).
  - The same path appears in 24 corpus builds, whose q LE sits at the same slot. The exact solver had filed the path under
    that LE's signature, so taking the signature minus the LE band gives the path: **8 bits**, all 8 set in blink24p
    (`out/outpath_bits.json`, a fixed bundle for this placement).
- **blink24p coverage:** lut 38.9%, LE-local 44.8%, routing 3.3%, output bundle 0.9%, **other 12.0% (79 bits)**, mostly the
  local-feedback select band of X9/X10, plus clock clusters.
- 21:26 **Process mistake:** at 20:22 I ran the output-path rename scan on blink24p while the feedback detour job was also probing it.
  They shared the same project clones, and the detour run crashed on a corrupted SOF. The 0/102 output-path result is
  unreliable for the same reason.
  - Fix: a failed asm step is now a probe outcome, not an abort, and the clone docstring warns against concurrent scans.
    The detour run was then redone alone.
- **Feedback detours, clean re-run** (blink24p, 852 probes, 34 min, 10 honoured): 8 local-feedback selects measured
  (`out/localfb_oracle_blink.json`):
  - I7 → 31 (−16,−10)/(−15,−10); I11 → 32 (−16,−20)/(−13,−19); I24 → 36 (−16,−52)/(−15,−52); I3 → 30 (−16,−4)/(−13,−3);
  - I15 → 33 (−16,−27)/(−15,−27), equal to the corpus; I3 → 15 (−18,2)/(−17,2), equal to the corpus;
  - I5 → 17 (−18,−6)/(−17,−6); I22 → 25 (−18,−49)/(−17,−50).
- **I4 → line 1 is a zero-bit select:** moving s[2]'s I4 → 1 branch onto its existing I5 → 17 branch (RCF, honoured)
  changes 0 bits, the same as I19 → 10.
- **blink24p coverage: 89.5%** (lut 38.9, LE-local 44.8, routing 4.9 over 20 priced hops, output bundle 0.9). Other 10.5%
  (69 bits): clock (global + row select) and 1 unpriced hop, I8 → 3 at X9.
- 21:28 **49 bits unexplained in all three counter designs:** 47 are set in the all-zero baseline itself. They are that
  design's own D5 driver, cleared by every design that drives D5 (`out/zero_own_bits.json`), so they come from the baseline
  and are not clock bits.
- **blink24p coverage: 96.7% of 658 core bits** (lut 38.9, LE-local 44.8, routing 4.9, output bundle 0.9, baseline's own
  driver 7.1). **22 bits left:** the row clock select (frame 488, 3 bits), I8 → line 3 at X9, a few X9/X10 driver-band
  bits. The 40 periphery bits (E2 input, D5 output) are counted separately.
- 21:30 **Local feedback, second kind:** some buffers feed their LAB lines through the driver track. No select bits; a driver
  pair at frames +13/+14, the same in every phase.
  - 19 → 10 = (13,−43)/(14,−44) at 36 corpus positions (the earlier "zero-bit" reading had only looked in the select
    window); 12 → 5 = (13,−20)/(14,−19).
  - 4 → 1 = (13,−3)/(14,−3) and 8 → 3 = (13,−12)/(14,−11) were read off blink24p and confirmed independently: div24 at X2Y6
    has the pair; corpus builds using these hops, 11/11 and 1/1.
- **blink24p: every routing hop priced** (21 hops, 0 false bits). **98.2% of 658 core bits explained, 12 left:** 1 gclk global
  cell (E2), 3 row clock select cells (gclk formula, row 3), 7 at X10 rows −29..−34 (the LAB-wide control area,
  ff_control lab_wide), and 1 each at X6 −2 / X9 −17.
- 21:51 **LAB clock selects (open):** in the clocked templates, 6 of 8 clocked LABs carry the same 6-bit pattern relative to the LAB:
  (−12,−31), (−11,−31), (−8,−29), (−2,−30), (1,−29), (11,−34). blink24p X9 and blink24 X11 have only (−17,−34) instead.
  Probably two of Quartus's clock-line assignments; what selects one or the other is still open. For our own assembler
  either variant should be a valid choice, but that has to be shown (byte-identical to a Quartus build, or a board test
  with the user's OK).
- 22:29 **Pre-registered:** blinktest.py loads out/asm_blink24p_counter.rbf (byte-identical to Quartus's build; checked again before
  loading). Prediction: D5 at 48e6 / 2^24 = 2.861 Hz (±2%).
- 22:30 **Quartus-free blinky assembled byte-identical** (asm.py):
  - out/asm_blink24p.rbf (placeholder masks) and **out/asm_blink24p_counter.rbf (24-bit counter, Q = s[23]) both equal
    Quartus's builds, all 510,856 bytes**.
  - Built from the all-zero design (own D5 driver cleared) plus models (LUT cells, register bits, output selects, routing
    switches, E2 clock-input entry in io_tile.json) plus measurements from *other* builds at this placement: 109 LUT-input
    codes from 18 variant builds (posmux.py, never the target) and a 52-cell placement bundle (clock selects and similar).
    The 8-bit output-path bundle comes from the corpus.
  - Fixes found on the way:
    - .rcf route_port → lutpos input map C/D/B/A → 0/1/2/3;
    - the own-register feedback is on input 0;
    - odd-LE mux columns sit at low byte + c − 2 (mux1cmap), not 3 − c;
    - LUT inputs must be matched by signal, since the .rcf logical ports are the synthesised netlist's;
    - registers: frame +11 pair select and a frame −1 bit.
  - Limit: the route *choice* is Quartus's back-annotation of the design; the bits come from our tables.
- **Board: blinktest STOPPED on a readback mismatch** (D1..D4 set 0000, read 1111). Cause: my script didn't send the bench's
  "A" (drive) after loading the blinky, so the bench pins stayed tri-stated and read through pull-ups. The load itself
  succeeded and the all-zero control before it held D5 low. Per rule 4: stopped and reported to the user; the board is
  left idle (blinky in SRAM, bench pins tri-stated, nothing on the header). The script is fixed (adds "A") but not re-run.
- 22:38 **Board (user's OK): the assembled blinky runs.** D5 at **2.8619 Hz** from 57 edges (1 kHz polling), predicted 48e6 / 2^24 =
  2.8610 Hz (+0.03%, within the iCLK tolerance). The all-zero control held D5 low before and after. Log
  out/blinktest_20261124_223824.json.
- 23:24 **Own router** (router.py; known switches plus codes measured at the placement): blink24p counter, 99 LUT inputs routed, 4
  differently from Quartus.
  - Quartus with our routing forced: **99/99 branches honoured, 0 errors**. Our assembly equals that build except
    (47,197,4), an RCF-mode artifact: 1 in normal builds and in ours, 0 in forced builds.
  - Router fixes: shared resources (local lines too) must use label / branch_point; neighbour links only for (buffer, dx,
    line) seen in a real route (I30 → 29 is illegal, I31 → 29 legal).
  - vs Quartus's normal build: 12 core cells (X9 LUT-input codes), gate PASS, periphery identical.
  - **Pre-registered:** blinktest --own, D5 at 2.861 Hz. The board run was blocked by the permission classifier; waiting
    for the user (not retried).
- 23:27 **Board (user's OK): the own-routed blinky runs.** D5 at **2.8617 Hz** from 57 edges, predicted 2.8610 Hz. The all-zero
  control held before and after. Log out/blinktest_20261124_232724.json. First file whose bits *and* route choice are
  ours, on a hand placement.
- 23:32 **LUT-input codes are die-wide after all.** With the corrected odd-LE convention (low byte + c − 2), (line, input, LE parity) →
  code conflicts in only 13/135 keys, each one dominant code plus a single outlier. The earlier "position dependence" was
  mostly my convention bug.
  - limux_dw.py: die-wide table from all RCF projects, **excluding every blink24p build**: 127 LAB-line and 55 local-line
    codes.
  - Assembling the blinky with it (asm.py --dw; the placement bundle is barred from the input cells, frames −12..−2):
    **89/89 coded inputs correct, 0 wrong bits.** 10 inputs have keys never seen outside blink24p (20 bits missing).
  - Running: blink24q (the same template at X20/X21 Y12) × 12 variants, to fill those keys from another position.
- 23:38 **Second position** blink24q (X20/X21 Y12) × 12 variants: the die-wide table now has 130 LAB-line and 59 local-line codes.
  The blinky (Quartus's routing) gets 98/99 inputs from it, all correct.
- **Router over die-wide codes** (router.py --dw): 99 LUT inputs, 37 routed differently from Quartus. Quartus with it
  forced: 99/99 honoured, 0 errors.
  - The first assembly differed in 23 bits, all from the placement bundle: it still held Quartus's habitual routing bits.
  - Fixes: the bundle now excludes every model bit of the variants' hops and all output-select cells (336 cells left,
    none of them routing); the second-path select byte is measured per LE (42 cells, out/secondpath_blink24p.json).
  - Now **our die-wide-routed assembly equals Quartus's forced build in every core bit except the RCF-mode bit
    (47,197,4).**
  - vs Quartus's normal build: gate PASS (counts above), periphery identical.
- 23:44 **Timing of the die-wide-routed blinky** (quartus_sta on Quartus's fit with our routing forced; that fit equals our file
  except the RCF-mode bit), 48 MHz on K:
  - setup slack 15.161 / 15.561 / 18.339 ns, hold slack 0.434 / 0.384 / 0.180 ns (slow 85 °C / slow 0 °C / fast 0 °C);
  - Fmax 176.3 MHz at slow 85 °C. All positive.
- **Pre-registered:** blinktest --own-dw, D5 at 2.861 Hz (user's OK, conditional on timing).
- 23:45 **Board: the die-wide-routed blinky runs.** D5 at **2.8615 Hz** from 57 edges, predicted 2.8610 Hz. Controls fine. Log
  out/blinktest_20261124_234503.json.
- 00:27 **Fixed configuration as rules** (clockmodel.py):
  - It is mostly LAB-relative: 120/129 and 145/164 cells identical at X9/X10 Y3 and X20/X21 Y12.
  - Rules: the LAB pattern translated by role; the global E2 clock-tree cells = intersection over E2-clocked designs
    (unclocked ones wrongly dropped clock cells, so they're excluded); the row clock select (offset −1 = 0, +5 = 1, +8 = 1;
    frame 488/489/1593/1594 by column); the quadrant bit (487 / 1592, cell 54,5 = 0). The LAB clock variant goes with the
    LAB's role (first LAB B, second A, at both positions).
  - Select-band cells outside the LAB-control rows (−37..−28) are routing. The output path gets (259,7,7): set in all 24
    corpus builds with this path. The baseline-own list = set in the all-zero design and cleared in 5 unrelated designs
    (46 cells).
- **Blinky assembled with NO measurement from any blink24p build:** LUT-input codes die-wide (excluding blink24p), bundle
  from blink24q plus rules, second-path bytes from blink24q, output path from the corpus.
  - Our routing: **equal to Quartus's forced build except the RCF-mode bit** (ours has the normal-build value);
    periphery identical.
  - It's therefore the same file that ran on the board at 23:45 (D5 2.8615 Hz).
- 00:33 **General output-path bundle** (outpath.py): for an LE driving D5, cells set in all corpus builds with that path. Taken
  as (a) the LE's signature outside its band, plus (b) the cells near the D5 column that aren't set in the all-zero
  design.
  - X10Y3N30: 7 cells; its LE-band cells now come from the models. X28Y9N30: 17 cells along an 11-hop path (24 builds).
  - Fixes: rcfforce.branches now parses pin dests without route_port (the output LUT's branch had been invisible); the
    assembler records LE outputs for branches to pins too.
  - The .rcf also lists the clock tree (GLOBAL_CLK_H → … → LAB_CLK → LAB_CONTROL_MUX), unpriced for now.
  - Blind blinky with the general output path: equal to Quartus's forced build except the RCF-mode bit. Both earlier
    modes still byte-identical.
- 00:37 **Third position, assembled blind:** blink24r (the blinky's slots at X27/X28 Y9), no Quartus build of it used for assembling.
  - Sources: placement from locs.qsf; our router (die-wide codes); the corpus output path for X28Y9N30 (17 cells,
    11 hops); clockmodel from blink24q (row select at frame 1593, quadrant 1592); second-path bytes from blink24q.
  - Check, Quartus with our routing forced (clock routing left free): 100/100 branches honoured. **Our file equals that
    build except the RCF-mode bit**; periphery identical.
  - Fix on the way: driver-band cells (+13..+19) outside the LAB-control rows are routing. The reference's unpriced
    output driver had leaked into the clock bundle.
  - Timing at 48 MHz: setup ≥ +15.16 ns, hold ≥ +0.18 ns, Fmax 176 MHz. vs Quartus's normal build: 213 core cells,
    gate PASS, periphery identical.
  - Board run (blinktest --blind-r, predicted 2.861 Hz) waiting for the user's OK.
- 02:22 **Clock distribution in the .rcf** (K~inputclkctrl, 24 branches, same shape at all three positions):
  GLOBAL_CLK_H X0Y14 I4 → GLOBAL_CLK_V at the spine column (X12; X29 for X27/X28) → SCLK_TO_ROWCLK_BUF (spine, row) →
  LAB_CLK (row clock line) → BLK_CLK_BUF of the LAB, then either straight to the registers' CLK or via BLK_CLK_LIM → a
  LAB line → LAB_CONTROL_MUX.
  - **The LAB clock variants are these two endings:** B = direct (first LAB: X9, X20, X27), A = via a LAB line and the
    control mux (second LAB: X10, X21, X28; its 6 bits are that select plus the control-mux code).
  - Next for the clock model: price these hops instead of translating the LAB pattern. The spine columns match gclk's
    row-select frames (488/489 vs 1593/1594).
- 06:26 **Clock as priced hops** (asm.Asm.clock_hop); the translated LAB pattern is no longer needed:
  - GLOBAL_CLK_H → V: quadrant cell (487 / 1592, 54, 5) cleared.
  - SCLK_TO_ROWCLK_BUF → LAB_CLK_X{0,13,21,30}: row select (frame 488/489/1593/1594 by region; −1 = 0, +5 = 1, +8 = 1).
  - LI I8 → LAB_CONTROL_MUX I1: the 6-cell "variant A".
  - A register clocked directly: LAB cell (−17,−34), plus its LE's frame −1 bytes −1 and 0 (even) or +1 and +2 (odd),
    12/12. Via the control mux: frame −1 bytes −1 and 0 of even LEs only, 8/8.
  - Remaining bundle: 34 global E2 clock-tree cells from other designs.
  - blink24p, blind with priced clock hops: equal to Quartus's forced build except the RCF-mode bit.
- **Third position with our own clock routing** (all 24 registers direct; Quartus had used the control mux for one LAB):
  Quartus with everything forced honoured **125/125 branches**, and **our file equals that build except the RCF-mode
  bit**; periphery identical. File: out/asm_blink24r_blind_clk.rbf.
- 07:01 **Yosys → our place, route, assemble** (ynet.py, ypnr.py):
  - Yosys 0.66 `synth_intel -family cyclone10lp -nodsp -nobram` (the DSP map file is missing from the package): blinky =
    37 lcell_comb + 24 dffeas + 1 $not → 38 LEs.
  - Feasibility-driven placement (slot shuffles until every LE has known input candidates; 138 tries); our router over
    die-wide codes; our clock net; output LE at X10Y3N30 (measured output path).
  - Fixes for netlists other than templates: Quartus names a LUT by its output net and a register's output net by the
    register; the router emits every routed signal; explicit "q" nets.
  - Legality via the RCF oracle: the first run rejected LE_BUFFER_X10_Y3_I3 (local feedback from a combinational LE);
    blacklisted and re-routed → **113/113 branches honoured**.
  - vs Quartus forced to the same netlist, placement and routing: **28 core bits differ**:
    - frame −1 bits that are LAB-wide, not per register (X8/X9: the pair bits on every slot, comb ones too; X10: none,
      other bits on empty slots);
    - frame +8 second-path select byte (no measurement for a new placement);
    - a few feedback selects.
  - The periphery differs (56 bytes) because the baseline configures D1..D4 inputs this netlist lacks.
- 07:05 **Frame −1 occupancy model** (8 probe designs fm1_* in LAB X14Y10, one Quartus compile each):
  - Every placed LE sets a "used" cell; a registered LE also a "register" cell. Even LEs: low byte +0 / +1; odd LEs:
    +1 / +0. A LAB with ≥ 2 LEs in use also sets one cell at LE N24's low byte +0.
  - The earlier per-register "direct clock" and "control mux" frame −1 rules were neighbouring LEs' cells, right only in
    fully packed LABs; they're replaced by this model.
  - Results: blinky exact modes still 0 bits; blind blinky and third position still only the RCF-mode bit; **Yosys
    design 28 → 16 bits**.
- **Yosys design, remaining 16:**
  - the RCF-mode bit;
  - 6 second-path select bits (frame +8 byte 0/1, wrong for 3 LEs; no rule yet);
  - 9 neighbour-link bits: source +15/+16 against li_neighbour's +16/+18, and destination select bits at −17..−14 that
    we don't price.
  - Next: probe designs for those two, like fm1.
- 08:31 **Second-path select byte rule** (16 sp_N* probes, one source LE per slot of X14Y10 → X15Y10): the +8 byte = (LE parity) XOR
  (buffer parity), 16/16. It replaces the per-placement measurement, and both blinky checks still pass.
- **Direct-line select:** +9 byte = LE parity, every table slot. Slot 24 was missing from le_output_select.json and is
  predicted by the rule.
- **Placer** respects the oracle blacklist (LE_BUFFER X10 I3, X9 I20).
- **Yosys blinky: 0 RCF errors, 113/113 honoured; our file differs from Quartus's forced build in 1 bit** (plus the
  RCF-mode bit): (346,194,7), X8 frame +15 at slot 18's row.
  - That cell is also in Quartus's normal build, which uses the same link (I19 → X9 line 23). The probe with that same
    link (sp_N18, X14 → X15) doesn't have it, and forcing line 23 there changes nothing. Open.
  - Periphery differs by 56 bytes (the baseline's D1..D4 inputs, absent from this netlist).
- 09:23 **Open Yosys bit (346,194,7) not resolved by probes:**
  - nbsel.py forced I19 onto each line; only line 23 is legal, so its diffs measure nothing (identity). Probe positions
    also hit an M9K source column (X13): my mistake, the run stopped there.
  - nb2_X* (8 clean probes: source fed by its own register, no input pins, X−1 slot 18 → X, row 3): every one uses
    I19 → line 23. Cells: (−24,−42) is the source register's pair select; (−22,2)/(−20,2) appear in classes 1, 2, 4 and 7
    (not 0, 3), so they're column-dependent. **None reproduces the open cell (X9 −20, row −40).** It depends on
    something about that LE in the Yosys design beyond the link.
  - Parked; the Yosys blinky is 1 bit from Quartus's forced build.
- 10:01 **Wire-to-wire corpus** (xrkn:8 with source and destination 7 columns apart, 10 positions × 10 seeds): 100/100 routed in
  5 min. 980 R4 → R4 hops, against 91 before. Added to limsolve.JOB_FILES; hopsolve: 1,068 builds, 23,053 hops.
  - Exact R4 → R4 solves: 122/246 empty (a chain's hops co-occur); the rest are pairs in frames −22..−17 of the new
    wire's start column, the previous column's driver band. So an R4 → R4 hop is the same driver mux as buffer → R4.
  - r4r4map.py: oracle campaign forcing every R4 index after the first wire of each such net (16 builds, about 6,000
    probes), running.
- 10:11 **Board (user's OK): the third-position blinky runs.** D5 at **2.8611 Hz** from 57 edges, predicted 2.8610 Hz; the all-zero
  control held before and after. Log out/blinktest_20261125_101106.json. This file was assembled with no measurement at
  its own position (X27/X28 Y9), Quartus used only as the check.
- **Policy (user, 2026-11-25):** blinky-type board runs that pass all offline checks are an approved class: byte-identity,
  or equality to the forced build except the RCF-mode bit; timing; gate; periphery identical.
- The R4 → R4 campaign was stopped by Claude Code on low system memory (1/16 builds, 340 probes all "no switch"). Not
  restarted; waiting for the user.
- 10:25 **Hold lifted.** Hand check of r4r4map v1 (340 probes, all "no switch"):
  - Positive control, corpus-seen continuations forced in the same build: 1 honoured (X8 I29 → X5 I33); 2 failed at the
    LAB line, the "no line" class. So the classifier works.
  - The flaw: an R4 continuation starts 3 *or* 4 columns on (X8 → X5 or X4), and v1 only probed the column of Quartus's
    own second wire. v2 probes both columns (96 indices per first wire) with 3 parallel fits; v1 kept as
    out/r4r4map_v1_samecol.json.
- 11:27 **r4r4map v2, first 3 builds** (2,088 probes): 1 honoured, 22 "no line" (the switch exists but the
  second wire doesn't reach that LAB line), the rest no switch.
  - So each R4 continues into about 1–2 of the 96 wires starting 3 or 4 columns on: X8 I29 → X5 I33, X8 I24 → X4 I24,
    X12 I19 → X9 I19, ...
  - The corpus holds 59 (index, dx) keys of observed continuations to fit the pattern against.
- **Mistake (mine):** the stop/restart watcher's pkill killed the watcher too, and my manual resume started while a
  killed run's Quartus was still in build 4's work dir, so the rebuild found no fuzz_top.v. Cleaned up and resumed at
  NPAR=8; the 3 saved builds were unaffected.
- 12:18 **R4 → R4 continuations modelled (r4r4model.py, wired into switchmodel.Model.bits).**
  - r4r4map v2 finished at 8 parallel fits: 8 builds, about 5,600 probes, 1 honoured + 54 "no line"; the switch exists
    for about 1 in 96 candidates.
  - **The target is die-wide:** (index, span 3/4, (X+Y) mod 4) gives exactly one continuation, over 146 keys from 318
    observations (probes plus corpus). Neither X mod 2/4 nor the driver model's track space does this.
  - **Bits:** the new wire's driver mux in the LAB 3 columns back along the travel, frames +13..+15. Buffer → R4 drivers
    use +13/+14, so +15 is the R4-source input. Leave-one-out over positions: 47/50 exact, 2 subsets, 1 differs.
  - In-sample on the 7-column corpus: 574/980 R4 → R4 hops priced, all bits set, none missing. The rest are
    right-going wires (indices 0..16: no bits in that band) and keys without an exact solve.
  - Regression: blink24p exact (0, 0), own-dw = forced build except the RCF-mode bit, third position unchanged.
- 12:21 **Held-out R4 → R4 check** (20 new 7-column builds, positions not in training):
  - First model: left-going 60/60 all bits set, 48 without entry. Right-going 9 correct and 6 with bits missing: their
    entries came from a single exact solve with stray bits of co-occurring hops.
  - Fix: bits common to every instance, and from a single instance only an exact pair. After that, 0 misses held-out
    (54/190 priced) and in-sample (524/980).
  - Coverage is the limit: 49/146 keys have reliable bits. Building 200 more designs (spans 5, 6, 8) for the exact
    solver; the held-out 20 stay out of training.
- 12:38 **R4 → R4: structural rule and cleaner entries.**
  - 200 more corpus builds (spans 5/6/8, 200/200 routed); hopsolve re-run; 275 continuation keys.
  - Rule for left-going span-4: bits relative to the target's track t (r4drv_model). Sources 17–24 give sign +1,
    25–33 sign −1. The pair is (13, t+s)/(14, t+s) for even sources below 25 and odd ones above, else
    (13, t)/(15, t+s). It fits all 43 measured keys and predicts 24 more.
  - Entry rules: an intersection needs instances at ≥2 positions; a pair must sit on adjacent rows; any entry not
    fully set in some training use is dropped (9|3|2 and 9|4|2: (−17,−40) set at 20 positions, clear at X3 Y11).
  - **Held-out (20 builds): 87/190 hops priced (left 73/108, right 14/82), 0 bits missing.** In-sample 0 missing.
  - Right-going needs more (14/82): no structural rule yet (no driver-track table for indices 0–16).
- 12:39 **Right-going R4 → R4 bits depend only on (source index, span)**, not on the target or the phase.
  - Examples: source 6 → target 5 in phases 0 and 2, source 10 → targets 8 and 12, both with the same pair. Probably
    the source's exit switch at its far end, with the phase wiring choosing the landing wire.
  - Pooled per source (sources whose keys disagree left out); 135/275 keys with bits.
  - **Held-out: 113/190 priced (left 73/108, right 40/82), 0 missing;** in-sample 0 missing.
- 12:45 **Board (user's plan): the Yosys-built blinky.**
  - Offline: ycheck --timing on Quartus's forced build (our placement and routing): setup ≥ +16.1 ns, hold ≥ +0.19 ns at
    all 3 corners, PASS; 113/113 branches honoured. The periphery equals the three board-tested blinkies; the gate
    passes both files against Quartus's normal blink24p build.
  - **With cell (346,194,7) set as Quartus sets it: D5 2.8610 Hz, predicted 2.8610, PASS** (log
    out/blinktest_20261125_124229.json). The first Verilog → Yosys → our place/route/assembler design to run, with
    one bit taken from Quartus's forced build.
  - **Our file without that bit: D5 45.776 Hz = 48 MHz / 2^20, FAIL.** The counter's top 4 bits lose a connection, so
    the bit is functional. Controls held before and after both runs (log out/blinktest_20261125_124307.json).
  - The cell sits on net n40 (le30, X8 N18, combinational) → X9 line 23 via buffer I19, feeding 4 LEs. Probes with
    the same link at the same position don't set it: 1/2/4 sinks, pins or constants on the source (nb3_*). It is in
    no other blinky build, so it depends on the Yosys design's context. Each X8 buffer reaches exactly one X9 line,
    so moving links to isolate it isn't possible.
- 12:50 **Found the bit: it belonged to a different link.** X9 N18 → X8 line 9 (buffer I18, dx −1), not n40. Our half (−22,−40)
  was set, the pair's other half (−20,−40) missing.
  - li_neighbour.json's dx −1 source-driver entries list only the frame −22 cell, and its notes say the source side
    was never isolated. nb4 probes (dx −1 from X15Y10, slots 0/2/18/30): every link also sets frame −20 on the same
    byte, 4/4. switchmodel._neighbour adds it.
  - Regression: blink24p exact both modes.
  - **Yosys blinky: core equals Quartus's forced build except the RCF-mode bit;** timing PASS (setup ≥ +16.1 ns, hold
    ≥ +0.19 ns). The file is byte-identical to the diagnostic file that passed.
  - **Board: `make blinky`'s own output, out/ypnr_blink.rbf: D5 2.8608 Hz, predicted 2.8610, PASS**; controls held
    (log out/blinktest_20261125_125003.json).
  - **Goal (A) reached:** Verilog → Yosys → our pack/place/route/assembler → a bitstream that runs on the Vidor.
    Quartus served only as a cross-check and as the source of the tables, which come from oracle measurements.
  - Mistake (mine): the nb4 probe first put its sink on X13, an M9K column (the same slip as this morning's nb
    probes). Rerun at X15/X14.
- 13:14 **Short-span corpus** (spans 2–4, 274/300 routed; hopsolve: 1,525 builds, 60,371 hops):
  - Held-out: R4 → R4 116/190, buffer → R4 97/176 (1 missing), R4 → C4 4/20, but **R4 → LAB line unchanged (29/187)**.
    Its table holds only 145 entries, and no two (R4 index, tap offset) entries share bits for any (line, class), so
    the corpus can't separate these selects.
  - tapmap.py (RCF oracle): for each buffer → R4 → line net, force every other unused line at the same tap. That
    measures selects at any tap offset, in both directions. Running on 10 short-span builds at 8 parallel fits.
- 13:50 **tapmap.py results** (10 short-span builds, 2,368 probes): 54 honoured. Each wire tap reaches about 5 of the
  38 lines.
  - The line fixes the row (line 35 → row −43/−44, 36 → −51/−52, 21 → −25/−26); the frames pick the input.
  - Many (wire, offset, line) keys have the same bits in several classes, but **pooling over classes is unsafe**:
    held-out it gave 8 more right and 3 wrong ((4, +3, 18) agrees in classes 6 and 7, differs in 1). Removed.
  - tapmap results now enter the switch table as exact per-class entries, as selmap's do (78 oracle selects).
  - Corpus R4 → line entries whose bits spread over more than 2 rows are dropped (13, stray bits; (23, 0, 32) caused
    the 2 old held-out misses).
  - **Held-out R4 → line: 31/187 priced, 0 missing.** Coverage needs a structural rule; the key space is about 34
    wires × 5 taps × 5 lines × 8 classes, so exact entries alone won't get there.
