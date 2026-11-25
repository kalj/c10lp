Another update from the 10CL016 (EP4CE15 die) side: inter-LAB routing, plus a method that may be useful to you.

**1. First inter-LAB routes written by our own tools, on silicon.**
We took a net that Quartus routed LUT → LE_BUFFER → R4 → LAB line → LUT, and moved it to a different R4 wire and a
different LAB line, writing all three switches (driver, LAB-line select, LUT-input mux) ourselves. The old route was
cleared. 5/5 worked on the board (16/16 input combinations each). Negative controls, which clear the old route and add
nothing, failed 5/5, so the signal really went the new way. The bits came from an exact per-position solve: for each hop
at each absolute position, the bits set in every build that uses it and in no build that leaves its destination node
unused. Corpus: about 1,000 compiles of an 8-net "line-forcing" design. It puts 8 sources in one LAB and 8 sinks in another,
so Quartus has to use many LAB lines at once.

**2. LAB-line select bits repeat with an 8-column period.** A select is 1–2 bits in frames −19..−12 of the destination
LAB. One of them is shared by all inputs of that line's mux, so a route must set it too. Grouped by X mod 8, the same
switch type has identical bits across LABs. Leave-one-out over 23 LABs: 489 exact and 5 different, against 371 and 150
with no grouping. Our earlier cross-LAB tables had assumed one pattern for every column, which is why they failed.

**3. Driver choices shift with the row, with period 4.** Which R4_X14 wires LE_BUFFER I8 at X17 can drive (oracle below,
all 48 indices probed, 10 rows):

| Y mod 4 | legal wires |
|---|---|
| 0, 2 | I18, I20 |
| 1 | I21, I27 |
| 3 | I18, I22 |

A table keyed only by (buffer, wire index, offset) gets this wrong. That's the main reason our blind, translated reroutes
mostly failed (2/11 so far). We're now mapping the other buffers the same way.

**4. Method: a hand-edited `.rcf` as a legality and bit oracle.** You mentioned `.rcf` back-annotation in your reply on
PR #2. It also works as an *input*, which we found very useful:
- Write the routing of a compiled design with `quartus_cdb fuzz -c fuzz --back_annotate=routing`. It works on Cyclone IV E
  / 10 LP, even though the help text lists only Cyclone, Stratix and Stratix GX. The file lists every net's resources in
  order, e.g. `LE_BUFFER:X17Y22S0I8; R4:X14Y22S0I18; LOCAL_INTERCONNECT:X14Y22S0I16;`, plus the logical and physical
  (`route_port`) LUT input.
- Edit one net's path and refit with `ROUTING_BACK_ANNOTATION_FILE fuzz.rcf` and
  `ROUTING_BACK_ANNOTATION_MODE NORMAL`.
- If a hop doesn't exist, the fitter reports `Error on line N in Routing Constraints File` and reroutes that fan-out itself.
  N identifies the illegal hop, so forcing just "buffer → wire" probes one driver: an error on the wire's line means no
  driver, and an error on the next line means the driver exists.
- If the route is honoured, the new RBF differs from the base in exactly that net.
- A refit takes about 5 s, or about 1 s effective with 6 in parallel. One buffer's whole driver set (48 wires) takes about
  45 s. That's a direct answer instead of waiting for Quartus to happen to pick a wire; in our corpus one wire entered the
  same LAB line in 210 of 210 builds.

This uses only Quartus's documented input and output files, so it fits the clean-room line in your reply on PR #2. We work
the same way: no Quartus binaries or device databases, and no data derived from them.

Smaller notes:
- Another EP4CE6 project has appeared: [Siroco](https://gitlab.com/franlego98/siroco), early-stage. Their CRC is the same
  reflected 0x8005 over the same 208 bytes, but with init 0x2A7F (Quartus 24.1), where our 21.1.1 files fit 0xFE54. So the
  init seems to depend on the Quartus version or options. Worth knowing if you ever compare files across versions.
- Code and results are in [kalj/c10lp](https://github.com/kalj/c10lp): `limsolve.py`, `hopsolve.py`, `xreroute.py` and
  `rcfforce.py`, with the full record in `RESEARCH_LOG.md`.

Happy to compare notes on the C4/R4 families, or to run any of this on the EP4CE6 die (we have the 10CL006 = EP4CE6 die
in our flow too).
