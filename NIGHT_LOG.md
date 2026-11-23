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
  38 builds are kept in `pll.json` for later; PLL paused here.
