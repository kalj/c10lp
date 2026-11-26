# Status and plan

Updated 2026-11-26 18:53. Where the toolchain stands, the plan, and what's next. History and reasoning are in
RESEARCH_LOG.md.

## Goals

- **(A) Quartus-free blinky on the Vidor's 10CL016:** done 2026-11-25 (`make blinky`: Verilog → Yosys → our place,
  route and assembler → bitstream → runs on the board).
- **(B) A usable open toolchain for Cyclone 10 LP / Cyclone IV E:** small designs written in Verilog go through
  Yosys → nextpnr → our assembler to a working bitstream, with real I/O, clocking and control signals, without
  Quartus. About **65%** there.

## Status by component

| Component | State | Estimate |
|---|---|---|
| Bitstream format, CRCs, LUTs, LE configuration | decoded; byte-exact assembly of whole designs | ~95% |
| Routing inside a LAB (local lines, LUT inputs, feedback) | die-wide rules, exact | ~95% |
| Horizontal routing (neighbour links, R4) | drivers, continuations, taps; held-out R4 → line 131/187, 0 wrong | ~85% |
| Vertical routing (C4) | drivers (legality per buffer and phase), taps 329/430 held-out with 3 wrong; C4 → C4 continuations missing | ~55% |
| Long wires (R24, C16) | not started | 0% |
| Clock | global clock to registers in one region, as modelled hops | ~60% |
| I/O | one fixed output path (D5) and the fixed clock input; pin settings decoded, not in the flow | ~25% |
| Control signals (clock enable, resets) | bits located, not in the flow | ~10% |
| Memory and multipliers (M9K, DSP) | contents and modes mapped, not in the flow | ~20% |
| nextpnr integration | Himbächel uarch, chip database from our models, converter to asm.py, on-demand probing | ~45% |
| Timing model | nominal values in the database; checked with Quartus's analysis | ~5% |

## On the board

All predicted 2.861 Hz before loading, all exact against Quartus's build with our placement and routing forced
(except one RCF-mode artifact bit), timing positive, gate PASS.

| Design | Flow | D5 |
|---|---|---|
| blinky, 3 LABs in one row | `make blinky` (Yosys → ypnr → asm) | 2.8608 Hz |
| blinky, 3 LABs in one row | `make npnr-blinky` (Yosys → nextpnr → asm) | 2.8607 Hz |
| blinky spread over X6/X8/X10 (R4 wires) | ypnr `--labs` | 2.8610 Hz |
| blinky over rows 3 and 7, 8 LUTs in row 7 (21 C4 wires) | nextpnr, forced row split | 2.8610 Hz |

(Earlier board runs: template blinkies, own routing, third position; see RESEARCH_LOG.md.)

## Plan

Direction (user, 2026-11-26): batched probes (A, done), then the nextpnr flow (D) with on-demand probing (B), and
structure models (C) when the data shows them. Milestones in order; each ends with a board run.

**Working rule:** a task gets a time box. If it stops producing results (no new board-passing design, no model that
generalises) within that box, it's parked with a note, and the next milestone starts.

1. **M1: finish vertical routing for normal designs** (time box: this evening).
   - In progress: C4 → C4 continuations (mapping/c4c4map.py). Add what generalises to the database.
   - Done when nextpnr can place a design across 2–3 rows *of its own choosing* (no forced split) and the result is
     exact. The fully alternating split is a stress test, not a goal.
2. **M2: I/O as database cells.** Input and output pins placed and routed by nextpnr instead of the fixed D5 path:
   input buffers → C16/R24/C4 → LAB lines; LE → wires → output pin. Pin settings are decoded already.
   Done when a design uses inputs D1..D4 and drives an output on another header pin, chosen by nextpnr.
3. **M3: control signals.** Clock enable and synchronous/asynchronous clear through the LAB control lines, so Yosys's
   `dffeas` with enables and resets maps directly. Done when a counter with enable and reset runs.
4. **M4: a second real design**, for example a small state machine or a UART transmitter, end to end on the board.
5. **M5: timing model** for nextpnr from Quartus's timing reports (delays per resource type), checked against
   Quartus's analysis.
6. **Later:** long wires (R24, C16); M9K and multipliers in the flow; the all-zero baseline generated from models
   (no Quartus at all, user 2026-11-25); Cyclone IV E (EP4CE6/EP4CE15, same dies).

## Waiting for the user

Nothing.

## Running now

mapping/c4c4map.py: C4 continuations with the batched oracle (30 vertical builds), part of M1.
