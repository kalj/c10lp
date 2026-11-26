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

1. **M1: vertical routing for normal designs: parked 2026-11-26 19:00** (time box).
   - Works on silicon where rows allow it (rows 3/7, 8 LUTs in the second row).
   - Open: C4 → C4 bits (4 honoured in 12,601 probes, so not in the database); rows next to the die edge (from row 4
     to row 3 needs a C4 starting at row 0). The blinky doesn't need vertical routing when nextpnr chooses freely.
   - Resume when a design needs it, after M2 frees the output LE from X10Y3.
2. **M2: long wires and I/O (current).** The corpus shows I/O runs on long wires: inputs go pin → input buffer →
   IO_DATAIN → C16 → R24 → R4 → LAB line, and the D5 output LE → C4/R4 (C4 → C4, R24, C16) → the I/O block's line →
   BLOCK_INPUT_MUX → output buffer. Held-out today: IO_DATAIN → C16 2 right / 120 wrong, C16 → R24 14/204, the I/O
   block hops not modelled.
   - M2a: R24 and C16 drivers, continuations and taps (corpus learners as for C4, the oracle where they're ambiguous);
     C4 → C4 from M1 comes in here.
   - M2b: the I/O block: IO_DATAIN, BLOCK_INPUT_MUX, input and output buffers, as database cells (pin settings are
     decoded already).
   - Scope on this board: the board rules allow D1..D5 only (D1..D4 driven by the test bench, D5 the output), so M2 means
     the 4 input pads and D5 reached from logic placed anywhere, not general I/O. The pads' own hops come from exact
     per-position solves (IO_DATAIN → C16: 60, → C4: 30, each used in many builds).
   - Done when a design uses D1..D4 as inputs and D5 as output, with nextpnr placing the logic freely (no pinned output
     LE), exact against Quartus and on the board.
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

Nothing in the background: M2a analysis on the existing corpus (no compiles needed yet).
