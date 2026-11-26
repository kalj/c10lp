# Status and task list

Updated 2026-11-26 08:43. The current state toward the end goals at the top, then what waits for the user, then the
ranked task list. Details and reasoning are in RESEARCH_LOG.md.

## Status

**Goals:** (A) a Quartus-free blinky on the Vidor's 10CL016; (B) a full open toolchain, Verilog → Yosys → place and
route → bitstream, for Cyclone 10 LP / Cyclone IV E.

| Step | Estimate | State |
|---|---|---|
| 1. Routing between LABs | ~68% | local lines, local feedback, neighbour links, R4 drivers/selects and R4 → R4 continuations (die-wide rule; 0 misses held-out, 59% coverage) and R4 → LAB-line taps (per (wire, offset, X mod 8); 0 misses held-out, 70% coverage) priced; C4 hops, multi-hop routing and I/O routing not yet |
| 2. Control and clock routing | ~66% | the global clock as priced hops (spine, row select, LAB clock, control mux); clock enables / clears not yet |
| 3. Database, assembler, blinky | ~80% | asm.py assembles from our tables; the blinky works on silicon at hand-chosen placements, including one with no measurement at its position |
| 4. Yosys / nextpnr | ~22% | Yosys → ynet/ypnr (pack, place, route, assemble) end to end, running on the board; no nextpnr integration |

**Overall:** **(A) done** (2026-11-25 12:50): `make blinky` (Verilog → Yosys → our place/route/assembler) runs on the board. About **56%** to (B). 

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

**Running now:** nothing (writing the nextpnr chipdb generator, D1).

## Parked (waiting for the user)



## Next (ranked)

Direction (user, 2026-11-26): A (batched probes, done), then D with B, with C alongside when the data shows structure.

1. **D: nextpnr Himbächel uarch for the 10CL016** (nextpnr cloned and built at ../nextpnr, Ninja):
   - D1 chipdb generator (Python, c10lp/nextpnr/): LAB tiles of 16 LEs (LUT4 + DFF bels). Tile types per
     (X mod 8, (X+Y) mod 4), the classes of selects and drivers. Wires: LE inputs/outputs, buffers, local lines,
     38 LAB lines, and R4 wires as nodes over the columns they span (tile wire R4_w_k = the wire of index w starting
     k columns away). Pips only from validated models: die-wide LUT-input codes, local lines, neighbour links, local
     feedback, R4 drivers (left −3, right +1), R4 → R4, R4 → line taps.
   - D2 uarch C++ (himbaechel/uarch/c10lp): pack LUT + register into an LE, validity rules. Clock and the D5 output
     path stay fixed, outside nextpnr (as in ypnr).
   - D3 converter: nextpnr's routed JSON → our route description → asm.py → RBF; cross-check with ycheck --fresh.
   - D4 = B: hops the router lacks are probed with the batched oracle and cached.
2. **C, alongside:** a tile-structure model when the data shows it (LAB-line muxes over physical tracks).
3. **Spread blinky's last 2 bits:** the frame-16 half of the right-going driver I17 → wire 6 (80% rule), and an X10
   frame −1 occupancy cell.
4. **C4 wires and I/O routing** (R4 ↔ C4, C4 → line; output paths to any pin).
5. **Control signals** (clock enable, clears) through LAB control lines.
6. **Long term: generate the all-zero baseline from models** (user, 2026-11-25).

## Done recently

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
