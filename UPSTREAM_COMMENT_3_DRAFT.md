<!-- DRAFT, not posted. Needs the user's OK before posting on #3. -->

Another update, all on the 10CL016 (MKR Vidor 4000). Everything is in https://github.com/kalj/c10lp,
with `selftest.py` checking each model against the Quartus builds it came from.

**M9K contents.** Each M9K block is 256 rows (one frame each) × 36 positions. The byte
position is anchored to the LAB row's LUT bytes, and every width × depth layout is a fixed
interleave of (word, bit) onto (row, position). The model writes ROM and RAM initial contents
byte-identical to Quartus for all 7 layouts (183 ROM and 6 RAM builds, including the header sum, whose M9K
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
- a select between the LAB's two {clock, clock-enable} pairs (a different clock or a different enable flips the same bit).

They sit in fixed byte columns per LE, are additive over all register combinations, and are
identical at every LAB tried. A blind test at 3 new LABs predicted 16/18 cases, and 18/18 after
adding a byte wrap at the bottom of the frame. Table: `ff_control.json`.

**Neighbour-LAB links (offline).** For a net from an LE to an LE in the horizontally adjacent LAB,
the dst-side select code depends only on the direction and the source slot. It was identical at 2 LAB
pairs and 6 dst slots for all 16 source slots, and predicted 94/96 codes blind at 3 new LABs.
Vertical neighbours and dx = 2 go over general routing, and the code varies per build. Table:
`li_neighbour.json`. I haven't isolated the source-side bits.

**I/O periphery.** Frames 1..36 are not outside the CRC, as I'd assumed earlier. They are one byte
stream of 9 logical 255-byte frames with every byte stored 4 times, and each logical frame ends in
the same CRC-16 as the core frames (414/414 checked). Their header-sum weight is 2^((byte + 4·frame
+ c_plane) mod 8), with one offset per plane (fitted on pull-up probes at all 138 legal input pins).
With that, all 15 Quartus I/O-setting variants (pull-up, bus hold, drive strength, I/O standard)
rebuild byte-identical from one base, and the pull-up bit is located for every legal pin
(`periph.py`, `io_pullup.json`). On the EP4CE6 die it's the same: frames 1..24 are 6 logical
210-byte frames, ×4, with the same CRC (24/24 on my 10CL006 builds, 107/108 of your RBFs). The one
that fails is `simple_led_iob_bidir_r5.rbf`. If I read `build_simple_led_iob_bidir_r5_probe.py`
right, the IOB_IN/OUT/OE signatures are combined with loader masks and overlap cancellation, which
leaves the periphery CRC inconsistent. Overlaying complete deltas would keep it right, since the CRC
is affine. I haven't tested whether the chip checks periphery CRCs, but it might be worth
recomputing them with `periph.py` before flashing.

**LE outputs and control lines (offline).** Each LE has a direct local output plus two general
outputs, each with a comb/registered select bit (frames +9 and +8). Neighbour-LAB links use one of
the general outputs (fixed per direction and slot) plus 1–2 driver bits in the routing frames between
LAB columns. The LAB control-line mux, fed from local LEs, follows the same direct-reach rule as the
LUT inputs.

Still open: general inter-LAB routing (I'd be glad to compare notes if you've looked at the EP4CE6
side), the LAB-wide control-line routing, and the combinational-vs-registered output select.
