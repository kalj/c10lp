<!-- DRAFT, not posted. Needs the user's OK before posting on #3. -->

Another update, all on the 10CL016 (MKR Vidor 4000). Everything is in https://github.com/kalj/c10lp,
with `selftest.py` checking each model against the Quartus builds it came from.

**M9K contents.** Each M9K block is 256 rows (one frame each) × 36 positions. The byte
position is anchored to the LAB row's LUT bytes, and every width × depth layout is a fixed
interleave of (word, bit) onto (row, position). The model writes ROM and RAM initial contents
byte-identical to Quartus for all 7 layouts (183 builds, including the header sum, whose M9K
term has the frame with the opposite sign to LAB bits). Quartus only stores the bits the design
reads. On silicon, patched ROM contents read back correctly. A RAM with patched initial contents
read back all 512 words, then the design wrote new data through its own port and read that back
too.

**Arithmetic mode.** The LE stores one 16-bit mask M:
- sum = M[a + 2b + 4·cin + 8d];
- cout = M[a + 2b + 4·cin], the d = 0 half, so datad must be 1 for the sum;
- with the sum unused, only the d = 0 half is stored, in a different cell order;
- a chain start stores f(a + 2b) twice.

A 4-bit carry-chain counter, with its four arithmetic LEs rewritten as up, down and 4 random
machines, ran correctly on silicon at three LABs (18/18). The carry-in select is one active-low bit
per LE, in the frame before the LUT (offline only).

**Flip-flop controls (offline).** Per register, there are:
- a sync clear/load enable at frame +11 (the same bit for both; LAB-wide bits choose which);
- an async-clear enable at frame +10;
- a clock-enable line select, choosing between the LAB's two enable lines.

They sit in fixed byte columns per LE, are additive over all register combinations, and are
identical at every LAB tried. A blind test at 3 new LABs predicted 16/18 cases, and 18/18 after
adding a byte wrap at the bottom of the frame. Table: `ff_control.json`.

**Neighbour-LAB links (offline).** For a net from an LE to an LE in the horizontally adjacent LAB,
the dst-side select code depends only on the direction and the source slot. It was identical at 2 LAB
pairs and 6 dst slots for all 16 source slots, and predicted 94/96 codes blind at 3 new LABs.
Vertical neighbours and dx = 2 go over general routing, and the code varies per build. Table:
`li_neighbour.json`. I haven't isolated the source-side bits.

Still open: general inter-LAB routing (I'd be glad to compare notes if you've looked at the EP4CE6
side), the LAB-wide control-line routing, and the combinational-vs-registered output select.
