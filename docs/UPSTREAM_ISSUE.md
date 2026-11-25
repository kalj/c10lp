<!-- Posted 2026-11-22 as https://github.com/14sea/Cyclone_CRAM_Mapper/issues/3. This is the text as posted. -->

# Cross-die results: 10CL006 ≡ EP4CE6, 10CL016 ≡ EP4CE15, plus the header checksum at 0x29/0x49

Hi! I've been using your mapper as the basis for looking at the Cyclone 10 LP 10CL016 on an
Arduino MKR Vidor 4000. Some results seem useful upstream, so I'm sharing them before writing any
code for the repo. All of this is black-box: compile tiny designs, diff the uncompressed RBFs.

Setup: Quartus Prime Lite **21.1.1** Build 850. Your `scripts/handoff_modeh/build_d1_golden.py`
design for X10Y2N0 masks 0000 and DEAD rebuilds **byte-identical** to
`results/golden_rbf_modeH/` under 21.1.1, so 21.1.0 vs 21.1.1 doesn't seem to matter.

## 1. 10CL006/10CL010 are the EP4CE6/EP4CE10 die

10CL006YU256C8G vs EP4CE6F17C8, same designs (wire, LUT masks 0000/FFFF/8888 at X10Y10N0):
same size (368,011 B), same geometry (1752 × 210, CRC init 0xFE54, frames 25..1751). The files
differ only in header/periphery bytes and a fixed set of 12 CRAM bits that's identical for every
design (a family setting, I assume). LUT cells are absolutely identical. So your existing
results should apply unchanged to 10CL006/10CL010 boards.

## 2. 10CL016 is the EP4CE15 (EP3C16) die

10CL016YU256C8G vs EP4CE15F17C8 and EP4CE15U14I7: 510,856 B = 32 + 2003 × 255 + 59, CRC-16/0x8005
init 0xFE54 over frames 37..2002 (37 periphery frames), the same layout as CE6 with different
constants. Same kind of differences as in (1): header/periphery plus a fixed 12-bit family set.

The LUT model carries over structurally. Fitted from ~130 builds; it now explains all 317 LUT builds at 156 LEs, including
54 LEs added afterwards as a stress test (next to M9K/multiplier columns, around the hole, die edges):
- LAB columns X ∈ 1..40 \ {13, 18, 25, 34}, rows Y ∈ 1..28, a hole at X1..9 × Y15..19:
  36 × 28 − 45 = 963 LABs = 15,408 LEs.
- LUT = 8 consecutive frames × 2 adjacent bytes × 1 bit. Frame base steps 35 per LAB column, with
  wider gaps at the non-LAB columns and +4 between X29 and X30.
- Y sets (byte, bit) in steps of 70 bytes "down the frame", wrapping into bit−1 (bits 7..0).
- N shifts the byte pair by −2 within an LE pair, −8 per pair, and an extra −6 after LE 7. Odd LEs
  (N/2 odd) swap the two bytes in the minterm order.
- XOR-linear; single-minterm sweep and hold-out masks 4444/6996/DEAD match exactly.
- The minterm order is relative to the *physical* LUT inputs, and Quartus picks a per-placement
  input permutation (16 seen). One probe compile (mask 0x008A = a, a&b, a&b&c) identifies it.
- Memory/multiplier columns: M9K at X13/X25, 18×18 multipliers at X18/X34 (56 of each).

## 3. Header bytes 0x29..0x34 and 0x49..0x4A decoded

`results/rbf_safe_byte_ranges.md` treats these as opaque per-build bytes. On every RBF I have
(740+ so far, both dies, all five part numbers, including your goldens):
- **bit 0 of each byte 0x29..0x48** is one bit of a 32-bit value V, LSB first (the other bits of
  those bytes stay fixed for a given device and project settings);
- **bytes 0x49..0x4A = CRC-16/0x8005 (reflected), init 0xFFFF, little-endian, over bytes
  33..0x48**;
- V is an **additive** checksum of the CRAM: on the 10CL016, each set data bit in frames 37..2002
  (not CRC bytes, not periphery) adds `2^((2·L − frame) mod 8)` with carries, where
  `L = byte + plane_start[bit]` (bit 7→0, 6→251, 5→502, 4→753, 3→1005, 2→1257, 1→1509, 0→1761).
  It fits 105 single-bit builds and whole-file pairs including routing changes.
- **On the CE6 die** (your chip) it's `2^((byte + s[bit] − frame) mod 8)` over frames 25..1751
  (data bytes only), with s = bit for bits 0..6 and s = 0 for bit 7. All 58 files in
  `results/golden_rbf_modeH/` give the same constant (V − Σ = 26,084), so the delta form lets
  any patched RBF carry a correct header, instead of excluding these bytes.

With that, patched LUT RBFs come out byte-identical to Quartus, header included (149 builds at
150+ LEs, including random asymmetric masks at LEs the model had never seen). Your silicon results
suggest the EP4CE6 doesn't check V, and the 10CL016 doesn't either (see 4).

## 4. Silicon results (MKR Vidor 4000, SRAM over JTAG)

Loading uses Arduino's USBBlaster library on the board's SAMD21, plus openFPGALoader. The header
pins are shared between the SAMD21 and the FPGA, so the test designs drive only D5, at minimum
current strength. A small sketch, the USBBlaster example plus a serial test bench, drives D1..D4
and reads D5, so every file is checked over all 16 input combinations without jumpers. Before
each load, a gate checks that the file differs from its Quartus template only in LUT cells, frame
CRCs and the header sum/CRC. Results:

- **The header sum is not checked.** A mask-0000 build patched to 0x8888 with V left stale works
  as a&b.
- **The position model works on silicon.** 100 random LEs (35/36 LAB columns, all 28 rows, all 16
  N, including die edges and LEs next to the M9K/multiplier columns). Each got a random asymmetric
  mask written only from the model plus the 0x008A probe permutation, never compiled by Quartus.
  **100/100 correct, 1600/1600 readings.** A Quartus all-zero control, reloaded every 25 files,
  held D5 low each time.
- **Multi-LUT patching works.** A 5-LUT template spread across the die: 4 first-level LUTs on
  D1..D4 feeding a final LUT. From the all-0000 and all-0x008A builds alone (same routing, 0 bits
  differ outside the LUT cells), all five LUTs can be rewritten. This reproduced 3 random Quartus
  mask sets byte for byte, and two mask sets Quartus never compiled ("at least two inputs high",
  4-input parity) are correct on silicon, 16/16 each.

## Question

Your `config.py` / `bitstream.py` hard-code the CE6 geometry. Would you be interested in
multi-die support upstream (e.g. a small geometry abstraction inferred from the RBF itself, plus
the 10CL016 LUT model and Vidor loading notes)? Or would you rather keep the repo CE6-only, with
this living in a fork? I also have a flip-flop pilot (one per-LE bit that tracks FF use), not yet
tested on silicon. I'm also happy to look at C16 later if that's useful, after checking with you.

Scripts (no blobs) are at https://github.com/kalj/c10lp: `selftest.py` re-checks every result above
from cached builds. I've kept RBF/SOF files out per the licence note in your README.
