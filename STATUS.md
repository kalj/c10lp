# Status and plan

Updated 2026-11-28 16:22. Where the toolchain stands, the plan, and what's next. History and reasoning are in
RESEARCH_LOG.md.

## Goals

- **(A) Quartus-free blinky on the Vidor's 10CL016:** done 2026-11-25 (`make blinky`: Verilog → Yosys → our place,
  route and assembler → bitstream → runs on the board).
- **(B) A usable open toolchain for Cyclone 10 LP / Cyclone IV E:** small designs written in Verilog go through
  Yosys → nextpnr → our assembler to a working bitstream, with real I/O, clocking and control signals, without
  Quartus. About **84%** there.

## Status by component

| Component | State | Estimate |
|---|---|---|
| Bitstream format, CRCs, LUTs, LE configuration | decoded; byte-exact assembly of whole designs | ~95% |
| Routing inside a LAB (local lines, LUT inputs, feedback) | die-wide rules, exact | ~95% |
| Horizontal routing (neighbour links, R4) | drivers, continuations, taps; held-out R4 → line 131/187, 0 wrong | ~88% |
| Vertical routing (C4) | drivers, taps, corner turns R4 <-> C4 and C4 -> C4 continuations from 1,700 corpus builds; refusals learned per position | ~76% |
| Long wires (R24, C16) | used inside the pin paths only (exact per-position solves); R24 → R4 structure found | ~10% |
| Clock | global clock to registers in one region, as modelled hops | ~60% |
| I/O | D1..D4 in and D5 out as nextpnr cells, pin paths hop by hop in the database; on the board (pins 16/16, lock 24/24) | ~55% |
| Control signals (clock enable, resets) | enable, async and sync clear through nextpnr, all three on the board; enable + sync clear in one LAB (slot 3) not yet | ~75% |
| Memory and multipliers (M9K, DSP) | M9K contents / layouts / modes decoded and board-tested; M9K routing scoped (M6); not in the flow | ~25% |
| nextpnr integration | Himbächel uarch, chip database from our models, I/O cells, control signals, timing, `make design`; random-design stress test 168/174 exact; learned cross-check corrections | ~88% |
| Timing model | delays per resource type and cell arc from Quartus timing reports (150 projects) in the database; nextpnr estimates 11-16% above Quartus on all four timed designs | ~65% |

## On the board

All predicted 2.861 Hz before loading, all exact against Quartus's build with our placement and routing forced
(except one RCF-mode artifact bit), timing positive, gate PASS.

| Design | Flow | D5 |
|---|---|---|
| blinky, 3 LABs in one row | `make blinky` (Yosys → ypnr → asm) | 2.8608 Hz |
| blinky, 3 LABs in one row | `make npnr-blinky` (Yosys → nextpnr → asm) | 2.8607 Hz |
| blinky spread over X6/X8/X10 (R4 wires) | ypnr `--labs` | 2.8610 Hz |
| blinky over rows 3 and 7, 8 LUTs in row 7 (21 C4 wires) | nextpnr, forced row split | 2.8610 Hz |
| blinky with the output pin as a nextpnr cell (D5 over the pin path library) | `make npnr-blinky-io` | 2.8611 Hz |
| D1..D4 → three registers → D5, Q = (A^B) \| (C&D) | `make npnr-pins` | 16/16 |
| counter with clock enable from D1 (LAB control mux) | `make npnr-cnt-en` | 2.8611 Hz, holds |
| counter with async clear from D1 | `make npnr-cnt-clr` | 2.8607 Hz, held low |
| counter with sync clear from D1 | `make npnr-cnt-sclr` | 2.8613 Hz, held low |
| **combination lock on D1..D4 (M4)** | `make npnr-lock` | 24/24 steps |

(Earlier board runs: template blinkies, own routing, third position; see RESEARCH_LOG.md.)

## Plan

End goal (B): small designs written in Verilog go through Yosys → nextpnr → our assembler to a working bitstream,
with real I/O, clocking and control signals, **without Quartus**. Each milestone ends with a board run (or, where the
board can't show it, a byte-exact check). **Working rule:** each task gets a time box; when it stops producing results
it is parked with a note and the next one starts.

**Done:**
- M1 vertical routing (C4 drivers / taps, corner turns R4 ↔ C4, C4 → C4), M2 I/O as nextpnr cells (D1..D4, D5 over the
  pin path library), M3 register controls (enable, async / sync clear), M4 a second real design (the combination
  lock), M5 timing model (nextpnr 11-16% above Quartus). All on the board; random-design stress test 168/174 exact.
- `make design V=FILE TOP=MODULE`: one command from Verilog to a checked bitstream.

**Next, in order:**
1. **M6: M9K ROM in the flow (current).** Contents, layouts and modes are decoded and board-tested (2026-11-23); the
   routing isn't.
   - (a) Corpus: ROM designs at the M9K sites (columns X13, X25) with the logic in different LABs; from their .rcf
     routes learn wire → M9K line taps, line → PORTAADDR / CLK0 muxes, M4K_BUFFER → line / R4 / C4 drivers.
   - (b) Database: an M9K tile type with a ROM bel (address, clock, data-out pins).
   - (c) Assembler: port muxes, buffers, mode bits, contents (m9kpatch.py).
   - Done when a Verilog design with a ROM (`$readmemh`) goes through `make design` exact against Quartus and reads
     back right on the board (address from D1..D4 / a counter, data on D5).
2. **M7: no Quartus in the build: the baseline from models.** Today `make baseline` compiles the empty design once.
   - Done so far: the LAB default pattern (22 cells, 83% of the core bits, exact).
   - (a) The M9K / multiplier columns' default cells; (b) the edge rows and the left / right edge columns; (c) the
     periphery (the I/O tiles' settings for unused and used pins; needs their meaning, not a copy of the file).
   - Done when `basegen.py` writes a file byte-identical to lo_quartus_0000.rbf, and `make design` uses it.
3. **M8: robust for larger designs, without Quartus at build time.** Today the build can call the Quartus oracle when a
   net doesn't route, and every database rebuild re-routes the named designs.
   - (a) The remaining stress failures (1-2 unroutable, 4 with one unexplained Quartus-only cell); (b) designs with
     30-60 LEs (more corpus where they go, wider regions); (c) freeze the learned corrections so builds are
     reproducible; (d) on-demand probing off by default.
   - Done when 95% of fresh random designs up to 16 registers come out exact on the first build with no Quartus call.
4. **M9: long wires (R24, C16) as database wires** (R24 is an input of the R4 driver mux, frames +16..+18; needs a probe
   campaign: the corpus is pad-centric). Done when a design spread over 10+ columns routes exact.
5. **M10: multipliers (DSP blocks)** in the flow, as M6. Done when a small multiply runs on the board.
6. **M11: more I/O and clocks.** Other header pins and a second clock or the PLL. Offline (exact against Quartus) first;
   on the board it needs an extended test-bench sketch (user decision, 2026-11-26: not now).
7. **Later:** Cyclone IV E (EP4CE6 / EP4CE15, same dies as the 10CL006 / 10CL016).

## Waiting for the user

- (User 2026-11-26: keep the current test-bench sketch, D1..D5; raise it again only when it becomes a real limitation.)

## Running now

designcheck.py on 30 more fresh random designs. Next: scoping M9K memory in the flow.
