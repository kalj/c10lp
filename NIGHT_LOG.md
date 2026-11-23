# Night run log (started 2026-11-22 ~22:00)

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
  Draft follow-up comment in `UPSTREAM_COMMENT_DRAFT.md` (NOT posted).
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
