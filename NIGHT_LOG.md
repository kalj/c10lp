# Night run log (started 2026-11-22 ~22:00)

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
