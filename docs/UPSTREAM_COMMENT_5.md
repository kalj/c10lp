Update from the 10CL016 (EP4CE15 die) side: a blinky from Verilog to silicon without Quartus in the build path.

**1. Verilog → Yosys → our own place, route and assembler → a running bitstream.**
The design is a 24-bit counter on the Vidor's 48 MHz clock, bit 23 on a pin. Yosys (`synth_intel -family cyclone10lp`)
gives 37 LUTs and 24 registers. Our tools pack them into 38 LEs, place them in three LABs, route all 86 LUT inputs and the
clock, and write the bitstream from our tables, starting from an all-zero design. On the board the pin toggles at
2.8608 Hz, against 48 MHz / 2²⁴ = 2.8610 Hz predicted.

Quartus isn't in the build path. We use it to derive the tables (compiles, timing reports and `.rcf` route files) and to
cross-check. Quartus fits the same netlist with our placement and routing forced: no RCF errors, 113/113 branches
honoured. Our file equals that build in every core bit except one RCF-mode artifact. Timing on our routing passes at all
corners (setup ≥ +16 ns, hold ≥ +0.19 ns).

One bit was missing at first, and the board showed it. The pin ran at 48 MHz / 2²⁰: the counter's top 4 bits had lost
a connection. It was half of a neighbour-LAB driver for links going left (dx −1). Our table had only the frame −22 cell,
and the driver is a pair: frame −22 plus frame −20 on the same byte, 4/4 slots in new probes. With that added, the open
flow's file is the one that ran.

**2. R4 → R4 continuations follow a die-wide rule.**
An R4 continues into a wire starting 3 or 4 columns on, and there are very few choices: one of about 96 candidates per
wire in our oracle probes. The target depends only on (wire index, span, (X+Y) mod 4), the same phase as the R4 drivers
in my last comment. That held for 146 keys from 318 observations without a conflict. The switch bits sit in the driver
band of the LAB that drives the new wire:
- Left-going: frames +13..+15 of the LAB 3 columns back. The bits sit at the target's track row, and the source index
  picks the input (frame 14 or 15) and a ±1 row offset.
- Right-going: frames −19..−17 of the new wire's start column. Those bits depend only on the source wire and the span.

On 20 held-out builds, the model predicted 113 of 190 R4 → R4 hops, with 0 wrong. The rest are keys we haven't seen
yet.

**3. Not done yet.**
- Selects from R4 wires onto LAB lines at taps along the wire. Each tap reaches about 5 of the 38 lines, and they don't
  pool across column classes.
- C4 wires, and I/O routing beyond one measured output path.
- A general placer. Today it fills three fixed LABs.

Code and the full record are in [kalj/c10lp](https://github.com/kalj/c10lp): `make blinky`, `ypnr.py`, `asm.py`,
`r4r4model.py`, `RESEARCH_LOG.md`. The derived tables are not in the repo yet, so a clone still needs Quartus to rebuild
them first.

If it's useful, I'm happy to run the same rule-finding on the EP4CE6 die.
