# Status and task list

Updated 2026-11-25 16:21. The current state toward the end goals at the top, then what waits for the user, then the
ranked task list. Details and reasoning are in RESEARCH_LOG.md.

## Status

**Goals:** (A) a Quartus-free blinky on the Vidor's 10CL016; (B) a full open toolchain, Verilog → Yosys → place and
route → bitstream, for Cyclone 10 LP / Cyclone IV E.

| Step | Estimate | State |
|---|---|---|
| 1. Routing between LABs | ~60% | local lines, local feedback, neighbour links, R4 drivers/selects and R4 → R4 continuations (die-wide rule; 0 misses held-out, 59% coverage: left 68%, right 49%) priced; C4 hops, multi-hop routing and I/O routing not yet |
| 2. Control and clock routing | ~66% | the global clock as priced hops (spine, row select, LAB clock, control mux); clock enables / clears not yet |
| 3. Database, assembler, blinky | ~80% | asm.py assembles from our tables; the blinky works on silicon at hand-chosen placements, including one with no measurement at its position |
| 4. Yosys / nextpnr | ~20% | Yosys → ynet/ypnr (pack, place, route, assemble) end to end, running on the board; no nextpnr integration |

**Overall:** **(A) done** (2026-11-25 12:50): `make blinky` (Verilog → Yosys → our place/route/assembler) runs on the board. About **53%** to (B). 

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

**Running now:** tapmap.py round 4 on the remaining 134 short-span builds (new keys only; 8 parallel fits, ~2–3 h).

## Parked (waiting for the user)



## Next (ranked)

1. **Wire-to-wire routing.** R4 → R4 modelled both ways (r4r4model.py; held-out 113/190 priced, 0 missing). Left:
   coverage of R4 → LAB line (30/187 held-out), buffer → R4 (87/176), R4 ↔ C4, then multi-hop search in the router
   and a held-out board design spanning several columns.
2. **Output paths to D5 from any LE** (C4 → I/O row line → BLOCK_INPUT_MUX), so the output LE can be placed freely;
   today only LEs with a measured corpus path work.
3. **Neighbour-link destination cells per column class** (nb2 probes: (−22,2)/(−20,2) in classes 1, 2, 4, 7): fold into
   the switch model, then re-check the Yosys blinky.
6. **Control signals** (clock enable, clears) through LAB control lines, for designs beyond plain counters.
7. **A real placer** (simulated annealing over the feasibility check) and a router beyond adjacent LABs.
8. **Database format and the nextpnr Himbächel uarch.**
9. **Long term: generate the all-zero baseline from models** (periphery defaults, I/O tile defaults, core settings:
   27,703 nonzero bytes), so the flow needs no Quartus at all (user, 2026-11-25).

## Done recently

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
