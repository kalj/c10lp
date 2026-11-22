# Night run log (started 2026-11-22 ~22:00)

Autonomous session; the board and machine are free for 12–18 h. Rules: board rules from
README (SRAM only, every file gated, D1..D5 only, stop on anything odd), nothing posted,
pushed or deleted, commits local only.

Plan: 1) bigger templates on silicon (multi-LAB, 48 MHz); 2) does the repo's EP4CE6 routing
knowledge transfer to the 10CL016 die; 3) the repo's "canon cell" puzzle vs per-mask input
re-ordering; 4) reliability soak + 300 more silicon LEs; 5) 10CL016 routing pilot (data only).

## Progress
- 22:50 **Block 1a done:** `templates/cnt8` (18 LUTs + 8 registers, Quartus placed it across 2 LABs,
  X3Y2 + X4Y2). 6/6 machines Quartus never compiled were correct on silicon over 80 clocked steps
  each: up counter, up/down counter, shift register, Johnson counter, 2 random 256-state machines
  (`cnt8test.py`, log `out/cnt8test_20261122_225019.jsonl`).
- 22:52 Checked the Vidor's 48 MHz clock pin in Arduino's `vidor_s_pins.qsf`: `iCLK` = PIN_E2 (input
  only). D1..D5 = N3/P3/R3/T3/T2 confirmed again.
- 22:55 **Block 1b done:** `templates/div24`, a 24-bit counter (33 LUTs) on the Vidor's 48 MHz
  clock (PIN_E2, input only). quartus_sta on the pinned base: setup slack 16.8 ns at 48 MHz, Fmax
  250 MHz. 6/6 variants written by tpatch.py ran at the expected D5 frequency, measured by polling
  D5 over serial at ~1870 samples/s: binary counter on bits 23/21/19, a mod-3 low group (3.81 and
  15.25 Hz instead of 2.86 / 11.44 Hz), and a "free" variant that ignores the D1 enable. With D1 = 0
  every counter froze, except "free". All measurements are 0.085% low by the same ratio: the
  SAMD21's "48 MHz" is ~47.96 MHz (`div24test.py`, log `out/div24test_20261122_225445.jsonl`).
- 23:20 **Block 3 done, a clear result for the repo.** Their goldens' "canon cells" are input routing:
  - their design has no `dont_touch`, so a constant mask (0000/FFFF) has no LUT and no input routing;
  - vs mask0000, 6996 and DEAD add identical extra-bit sets at all 14 positions;
  - σ is chosen per mask (0/14 positions have one order for DEAD and 4444).
  With `dont_touch("on")` plus one 0x008A probe at their 14 positions on the EP4CE6 (70 compiles,
  `ce6probe.py`), 4444/DEAD/6996 come out **byte-identical, 42/42**, using their own cell addresses.
  Draft follow-up comment in `UPSTREAM_COMMENT_DRAFT.md` (NOT posted).
