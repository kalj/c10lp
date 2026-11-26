# Status and task list

Updated 2026-11-26 14:21. The current state toward the end goals at the top, then what waits for the user, then the
ranked task list. Details and reasoning are in RESEARCH_LOG.md.

## Status

**Goals:** (A) a Quartus-free blinky on the Vidor's 10CL016; (B) a full open toolchain, Verilog → Yosys → place and
route → bitstream, for Cyclone 10 LP / Cyclone IV E.

| Step | Estimate | State |
|---|---|---|
| 1. Routing between LABs | ~74% | local lines, local feedback, neighbour links, R4 drivers/selects and R4 → R4 continuations (die-wide rule; 0 misses held-out, 59% coverage) and R4 → LAB-line taps (per (wire, offset, X mod 8); 0 misses held-out, 70% coverage) priced; C4 hops, multi-hop routing and I/O routing not yet |
| 2. Control and clock routing | ~66% | the global clock as priced hops (spine, row select, LAB clock, control mux); clock enables / clears not yet |
| 3. Database, assembler, blinky | ~80% | asm.py assembles from our tables; the blinky works on silicon at hand-chosen placements, including one with no measurement at its position |
| 4. Yosys / nextpnr | ~40% | two flows run on the board: Yosys → ypnr (our placer and router) and Yosys → nextpnr-himbaechel (c10lp uarch, chip database from our models) → asm.py; one LAB row, fixed clock and output path |

**Overall:** **(A) done** (2026-11-25 12:50): `make blinky` (Verilog → Yosys → our place/route/assembler) runs on the board. About **63%** to (B). 

**On the board** (all predicted 2.861 Hz before loading):

| File | D5 |
|---|---|
| assembled, byte-identical to Quartus's build | 2.8619 Hz |
| our own routing (4 inputs changed) | 2.8617 Hz |
| our routing over die-wide LUT-input codes | 2.8615 Hz |
| third position, no measurement at its own position | 2.8611 Hz |
| Yosys → ypnr with one bit taken from Quartus's forced build (diagnostic) | 2.8610 Hz |
| Yosys → ypnr before the dx −1 driver fix | 45.776 Hz: FAIL, the top 4 counter bits lose a connection |
| **Yosys → ypnr as built (`make blinky`), after the fix** | **2.8608 Hz** |
| **Yosys → nextpnr-himbaechel (c10lp uarch) → npnr2asm → asm (`make npnr-blinky`)** | **2.8607 Hz** |
| nextpnr over two rows (3 and 7): C4 vertical routing, clock in two rows | 2.8615 Hz |

**Running now:** nothing.

## Parked (waiting for the user)



## Next (ranked)

Direction (user, 2026-11-26): A (batched probes, done), then D with B, with C alongside when the data shows structure.

1. **D: nextpnr flow: works end to end** (make npnr-blinky runs on the board). Next:
   - vertical routing (C4): runs on the board (2 LUTs in row 7); taps 180/430 held-out (legality per X mod 8 and
     Y mod 4), drivers 296/321. Denser cross-row designs need more tap coverage (corpus builds at more phases);
   - B: when nextpnr can't route, probe the missing hops (tapforce --job, nbmap) and regenerate, instead of only
     retrying seeds;
   - I/O cells and the clock as database objects instead of fixed paths outside nextpnr.
2. **C, alongside:** a tile-structure model when the data shows it (LAB-line muxes over physical tracks).
3. **Spread blinky's last 2 bits:** the frame-16 half of the right-going driver I17 → wire 6 (80% rule), and an X10
   frame −1 occupancy cell.
4. **C4 wires and I/O routing** (R4 ↔ C4, C4 → line; output paths to any pin).
5. **Control signals** (clock enable, clears) through LAB control lines.
6. **Long term: generate the all-zero baseline from models** (user, 2026-11-25).

## Done recently

- **nextpnr flow:** chip database from our models, c10lp uarch, converter to asm.py; the nextpnr-routed blinky runs on the
  board (2.8607 Hz). Batched oracle (8 probes per fit), neighbour drivers per line, frame −1 rule fixed.
- Repo reorganised: lib/, flow/, mapping/, hwtests/, data/, docs/ (user, 2026-11-25); selftest and `make blinky` unchanged.
- Open flow shipped: derived tables in out/, `make baseline` (one Quartus compile); a fresh clone reproduces the
  board-tested file byte for byte.
- Posted the 5th comment on 14sea issue #3 (open-flow blinky, R4 → R4 rule).
- **Goal (A): the Yosys-built blinky runs on the board** (2.8608 Hz) after fixing dx −1 neighbour-link drivers (a pair
  −22/−20, the table had only −22).
- R4 → R4 continuations (left-going): die-wide key (index, span, (X+Y) mod 4), bits in the driving LAB's +13..+15 band.
- `make blinky` (Yosys → ypnr.py → out/ypnr_blink.rbf) and `make blinky-check` (ycheck.py: Quartus with our placement
  and routing forced, then diff); blinky source in examples/blink.v.
- Board: the third-position blinky (assembled with no measurement at its position), 2.8611 Hz.
- Policy: blinky-type board runs passing all offline checks are an approved class (user, 2026-11-25).
- Yosys → ynet/ypnr place, route (RCF-oracle legality) and assemble; 1 bit from Quartus's forced build.
- Frame −1 occupancy cells, second-path byte (LE parity XOR buffer parity), direct-line byte (LE parity).
- Clock as priced hops; blind assembly at a third position.
