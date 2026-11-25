# Task list (ranked)

The working list for runs (see RESEARCH_LOG.md for what was done and why). Top = next. Parked items wait for a
decision by the user and stay listed until answered.

## Parked (waiting for the user)

- **Restart of the R4 → R4 oracle campaign** (r4r4map.py): Claude Code stopped it on low system memory (1/16 builds
  done; all 340 probes "no switch", to be checked by hand on one net first). Proposed: 3 parallel fits instead of 6.

## Next

1. **Wire-to-wire routing (R4 → R4, R4 → C4, C4 → C4).** Needed before nets can span more than one LAB to the side.
   Corpus coverage is thin (91 / 37 / 40 hops), so: an oracle campaign forcing two-hop chains between LABs 4–8 columns
   apart, with driver and select bits isolated from honoured routes. Then the router learns multi-hop paths.
2. **Output paths to D5 from any LE** (C4 → I/O row line → BLOCK_INPUT_MUX), so the output LE can be placed freely;
   today only LEs with a measured corpus path work.
3. **Neighbour-link destination cells per column class** (nb2 probes: (−22,2)/(−20,2) in classes 1, 2, 4, 7): fold into
   the switch model, then re-check the Yosys blinky.
4. **The Yosys blinky's last open bit** (346,194,7): a probe that reproduces the LE's full context (its other outputs).
5. **Yosys blinky board run** (after 3–4 and a timing check; needs an OK).
6. **Control signals** (clock enable, clears) through LAB control lines, for designs beyond plain counters.
7. **A real placer** (simulated annealing over the feasibility check) and a router beyond adjacent LABs.
8. **Database format and the nextpnr Himbächel uarch.**

## Done recently

- Board: the third-position blinky (assembled with no measurement at its position), see RESEARCH_LOG.md.
- Policy: blinky-type board runs passing all offline checks are an approved class (user, 2026-11-25).
- Yosys → ynet/ypnr place, route (RCF-oracle legality) and assemble; 1 bit from Quartus's forced build.
- Frame −1 occupancy cells, second-path byte (LE parity XOR buffer parity), direct-line byte (LE parity).
- Clock as priced hops; blind assembly at a third position.
