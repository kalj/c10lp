# Cyclone 10 LP (MKR Vidor 4000) vs Cyclone_CRAM_Mapper: first-pass toolkit

Scripts for the first steps of extending
[14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper) (studied at
commit `221f790`, 2026-09-30) to the 10CL016 on the Arduino MKR Vidor 4000.
Everything here reads Quartus *output* only.

## What reading the repo and sources changed in the plan

1. **The repo is much further along than the project brief assumes.** It already has C4/R4/R24/LOCAL_INTERCONNECT
   switch models (partial), the carry chain (hardware-verified), M9K init/mode, GCLK, IOB
   directives, a Yosys → nextpnr-generic → FASM → RBF flow (hardware-verified for small
   designs), and a "ζ" path that rebuilds any Quartus RBF byte-for-byte (NEORV32 booted
   Linux from it). Per the README, FFs have **no per-LE enable bit** ("silicon default").
   The open gaps are **C16 (not started)**, 12–13 of 37 R4 I-indices, the M9K/DSP boundary
   columns, and a chipdb routing model too sparse for dense designs.
2. **The 10CL016 is not the die the repo mapped.** Everything in the repo is the
   EP4CE6 ≡ EP4CE10 die (they proved byte-identical RBFs, `fuzz/cross_device_diff.py`).
   Evidence that the 10CL016 is the EP4CE15/EP3C16 die instead:
   - JTAG IDCODE `0x020F20DD` is shared by 10CL016, EP3C16 and EP4CE15, while
     10CL006/10CL010 share `0x020F10DD` with EP4CE6/EP4CE10 (OpenOCD's table; `jtagconfig` output).
   - Intel support, citing the handbook, gives the 10CL010 uncompressed RBF as 2,944,088 bits
     = 368,011 B (= EP4CE6). A forum answer gives ~509 kB for the 10CL016.
   - awtoau/pluribus issue #173 gives EP3C16/EP4CE15 = **510,856 B, 255-byte frames,
     37 periphery + 1966 CRAM frames**. That is exactly 32 + 2003×255 + 59 B, the same
     preamble/frames/postamble layout as the CE6 die.

   So **the repo's absolute offsets (COLUMN_BASE, CRC frame range, header size) will not
   transfer to the Vidor.** What should transfer is the *structure*: XOR-linear LUT
   encoding, ctrl/data pairs one frame apart, the slot/group Y encoding, CRC-16/0x8005 per
   frame. Step 4 becomes "re-derive the constants for a second die", not "check positions match".
3. **The intended shortcut for the Vidor is a 10CL006 board, not a different method.** If
   step 3 confirms 10CL006 ≡ EP4CE6 byte-for-byte, *all* existing repo results apply to
   10CL006/10CL010 boards unchanged (Trenz/QMTech sell them). That is a cheap,
   high-value result for an upstream issue even before any 10CL016 mapping.

## Results so far (2026-11-22, Quartus Lite 21.1.1 Build 850)

Raw output: `report1.txt`. Compiles take ~12 s on both dies (the 20 s guess was pessimistic).

**Control.** Rebuilding the repo's own `build_d1_golden.py` design (X10Y2N0, masks 0000 and
DEAD) gives files **byte-identical** to `results/golden_rbf_modeH/`, although the repo used
21.1.0. 21.1.1 is safe to mix with the repo's corpus.

**Geometry.** 10CL016 = 510,856 B = 32 + 2003 × 255 + 59. CRC-16/0x8005 init 0xFE54 on
frames 37..2002 (1966 frames), frames 0..36 periphery. Exactly as predicted.

**Same die.** 10CL006 ≡ EP4CE6 and 10CL016 ≡ EP4CE15 (F17 and U14 packages). Within each pair
the files differ only in ~314 header/periphery bytes plus a fixed set of 12 CRAM bits that is the same for
every design, including the wire (a family-level setting; same pattern on both dies, different
offsets). LUT cells are absolutely identical within each pair. Package makes no difference;
`ce15u` (I7) differs from `ce15` (C8) only by 7 routing bits, likely the speed grade.

**LUT at X10Y10N0 on the 10CL016.** One bit per minterm, bit 5 of bytes 222/223 in frames
401..408 (see `lutpatch.py calibrate`). XOR-linear: hold-out masks 4444, 6996 and DEAD are
predicted exactly. Across dies the layout is the same shape (8 frames × 2 bytes × 1 bit) but the
minterm order differs, so constants must be re-mined per die.

**Header checksum (new; the repo treats these bytes as opaque).** Holds on all 103 RBFs here,
both dies, plus the repo's goldens:
- bit 0 of each byte 0x29..0x48 is one bit of a 32-bit value V, LSB first;
- bytes 0x49..0x4A = CRC-16/0x8005, init 0xFFFF, little-endian, over bytes 33..0x48;
- V is an *additive* checksum of the CRAM: on the 10CL016, every set data bit in frames 37..2002
  (CRC bytes and periphery frames excluded) adds `2^((2·L − frame) mod 8)`, where
  `L = byte + PLANE_START[bit]` (bit 7→0, 6→251, 5→502, 4→753, 3→1005, 2→1257, 1→1509, 0→1761),
  the same row space `lutpos.py` uses. With Vidor project settings, V = 133,509 + that sum. Fits 105
  single-bit builds and every whole-file pair tested, including routing changes
  (`lutpos.header_weight`).
- **Same structure on the EP4CE6 die** (210-byte frames): each set data bit in frames 25..1751 adds
  `2^((byte + s[bit] − frame) mod 8)`, with s = bit for bits 0..6 and s = 0 for bit 7. One constant
  per project setup: 26,084 for all 58 repo goldens and our rebuilds of that design, 26,120 for our
  Vidor-pin CE6 builds, and 28,310 for the 10CL006.

**10CL016 LAB grid** (fitter probes, `out/grid_scan*.json`): LAB columns X = 1..40 except
13, 18, 25, 34 (memory/multiplier columns, not yet told apart), rows Y = 1..28, plus a hole at
X1..9 × Y15..19. That is 36 × 28 − 45 = 963 LABs = 15,408 LEs, exactly the datasheet count.

Memory and multiplier columns, confirmed by pinning blocks with the fitter: **X13 and X25 are M9K**
(the wide ~295-frame columns), **X18 and X34 are 18×18 multipliers** (25 frames). 2 × 28 = 56
of each, matching the datasheet. The swapped placement is rejected as illegal.

**LUT position model** (`lutpos.py`): predicts the 16 cells of any LE from per-column frame
bases, per-row (byte, bit) and an N offset. The *minterm order* within those cells is relative
to the LE's physical inputs, and Quartus routes A..D to them in a placement-dependent order
(6 different permutations seen; it's stable across masks at one LE). So:
- symmetric masks (0000, FFFF, 6996, …) can be written at any LE from only its mask-0000 build;
- asymmetric masks need one probe compile of mask `0x008A` (minterms a, a&b, a&b&c) at that LE,
  which fixes the permutation. `lutpatch.py --model` reads it automatically and refuses
  asymmetric masks without it.

`lutpos.py --check` explains every build in `out/` (317 builds at 156 LEs, 16 input
permutations seen). My first "blind" test used 6996, which can't detect permutations. The
single-minterm builds caught it. Stress test (2026-11-22): 54 new LEs next to the M9K and multiplier
columns, around the X1..9 × Y15..19 hole and on the die edges, each with 0000, the 0x008A probe and a
random asymmetric mask. 0 mismatches.

`lutpatch.py write --fix-header` (with a sweep, or `--model` using the rule) gives output
**byte-identical** to Quartus: 149 builds at 150+ LEs (incl. 54 random asymmetric masks at
unseen LEs), from just the mask-0000 build (+ the 0x008A
probe for asymmetric masks). Run `python3 selftest.py` (~30 s, no Quartus) to re-check everything. Without the flag the header
keeps mask 0000's values (6–9 bytes differ). Loading that file tests whether the chip checks V.

## Files

| File | What it does | Tested here |
|---|---|---|
| `rbfgeom.py` | Infers frame size, CRC init and CRC-covered frames from any uncompressed RBF (solves the init over GF(2) from one frame); region-aware diff across devices | On the repo's EP4CE6 golden RBFs it independently recovers 1752×210 B, init 0xFE54, CRC frames 25..1751, which matches the repo. Synthetic 210/255/298-byte-frame dies pass |
| `xdev.py` | Quartus campaign driver: `parts`, `plan`, `build`, `sweep`, `report`. Caches RBFs, records timings, prints estimates | Project generation plus a stub Quartus; report/control path checked against repo goldens. **Not yet run with real Quartus** |
| `lutpatch.py` | Calibrates the LUT codec at one LE from a 17-compile sweep, verifies XOR-linearity against other masks, writes any mask and re-patches CRCs with the inferred init | On a synthetic 255-byte-frame die: verify MATCH, written RBF has 0 data-bit diffs vs the "Quartus" one, CRCs valid |
| `lutpos.py` | 10CL016 LUT position model: (X,Y,N) → 16 (frame, byte, bit) cells; `--check` against all builds | 124/124 builds match |
| `selftest.py` | Re-checks every result above against cached builds, no Quartus | 10/10 PASS |
| `hwtest.py` | Guided first hardware test: loads the `lo_*` files to SRAM, logs your D5 readings | dry run only |
| `UPSTREAM_ISSUE_DRAFT.md` | Draft issue for 14sea/Cyclone_CRAM_Mapper. **Not posted** | — |
| `vidor_pack.py` | RBF → bit-reversed `app.h` array for Arduino's flash route; `--check-ttf` to confirm the .ttf/.rbf relationship | Logic only |

Python 3.10+, no dependencies. `QUARTUS_BIN` defaults to `~/intelFPGA_lite/21.1/quartus/bin`.
Use **21.1 (Lite)** if you can, because the repo's whole corpus is Quartus 21.1. A different
version may change the bitstream. The control builds will tell you either way.

## Run order on your machine

```bash
python3 xdev.py parts                    # confirm part names (EP4CE15U14?? etc.)
python3 xdev.py plan                     # 18 compiles, ~3 min estimated at 2 parallel
python3 xdev.py build --jobs 2
python3 xdev.py report --repo ~/src/Cyclone_CRAM_Mapper > report1.txt
python3 rbfgeom.py info out/c10_016__wire__vidor.rbf
```

What `report` answers:
- **Control:** whether your CE6 rebuild of the repo's `X10_Y2_N0` 0000/DEAD pair has
  the same LUT cells as the repo's golden files (and whether it is byte-identical).
- **Geometry:** whether 10CL016 really is 510,856 B / 255-byte frames, and its CRC init.
- **Same die?:** `ce6` vs `c10_006` and `ce15` vs `c10_016` (and `ce15u`, same U256 package)
  diffs, split into header / CRAM / CRC regions. Package differences (F256 vs U256)
  should only show up in I/O bits, if they show up at all.
- **LUT bits:** the 0000→FFFF / 0000→8888 pair-diffs in (frame, byte-in-frame, bit)
  coordinates, compared across devices, both absolute and as a relative shape.

If `ce15` vs `c10_016` is byte-identical (or differs only in the header), the Cyclone IV
side of Quartus becomes a second view of your chip (the same trick the repo used with CE10).

Then the 10CL016 LUT calibration:
```bash
python3 xdev.py sweep --device c10_016 --loc 10,10,0 --dry-run   # 17 compiles
python3 xdev.py sweep --device c10_016 --loc 10,10,0
python3 lutpatch.py calibrate --device c10_016 --loc 10,10,0
python3 lutpatch.py verify    --device c10_016 --loc 10,10,0   # vs FFFF, 8888
python3 lutpatch.py write     --device c10_016 --loc 10,10,0 --mask 6996 -o x6996.rbf
```
X=10/Y=10 is a guess at a legal LAB on the 10CL016. If the fitter rejects it, change `--loc`.
Mapping the 10CL016 LAB grid (the repo's jailbreak probe) is a natural next script once
we've seen the first real compile times.

**Time estimates.** The repo measured 9–10 s per compile on the CE6 die. I assumed ~20 s
for the 10CL016 until real numbers exist; `plan` and `build` replace the assumption with
the median of your own compiles. Step 3 (18 compiles) is about 3 min. The sweep (17) is
about 3 min. For scale, the repo's 12,000-compile route factory would be ~33 h at 2 parallel.
I'll estimate each campaign before you run it.

## Loading bitstreams on the Vidor

The SAMD21 is wired to the FPGA's JTAG pins. The board's JTAG header is not fitted.

**Route A (recommended for fuzzing): SRAM over JTAG via a USB-Blaster emulator on the SAMD21.**
Volatile, fast, no flash wear, and power-cycling restores the Arduino image from flash.
0. Already in place on this machine: `openFPGALoader` (knows IDCODE 0x020f20dd) and its udev
   rules for `09fb:6001` (group `plugdev`, which you're in). Still missing: the SAMD core and the
   library. Install them with
   `arduino-cli core install arduino:samd && arduino-cli lib install USBBlaster`, then
   `arduino-cli lib examples USBBlaster` shows the example sketch path to compile/upload with
   `-b arduino:samd:mkrvidor4000`.
1. Arduino IDE → Library Manager → **USBBlaster** (Arduino's emulator for the MKR Vidor 4000,
   shipped precompiled). Upload its example sketch. The forum release notes say it needed
   SAMD core 1.6.25. If a newer core fails, try that version.
   Open-source alternative: [sameer/usbd-blaster](https://github.com/sameer/usbd-blaster)
   (Rust, last updated 2020, flashed with `bossac` after a double-tap reset).
2. On Linux the board should enumerate as `09fb:6001`. Add a udev rule for it.
3. `openFPGALoader -c usb-blaster --detect` should report IDCODE `0x020f20dd`.
   (The repo needed a source-built openFPGALoader for the CE6 IDCODE. The 10CL016's is
   probably known already, since openFPGALoader supports a QMTech 10CL016 board.)
4. `openFPGALoader -c usb-blaster out/c10_016__lut8888_X10Y10N0__vidor.rbf`
   (`quartus_pgm -m jtag -o "p;file.sof"` also works through the emulator).
5. To go back to normal Arduino use: double-tap reset, then upload any sketch.

**Route B: Arduino's flash route** (for persistent demos only). Arduino embeds the
bit-reversed bitstream in the sketch's `.fpga_bitstream` section. The bootloader sends it over
JTAG to the boot image in the FPGA, which writes it to the QSPI user area after the 512 kB
boot image. Use `vidor_pack.py` for patched RBFs, but run `--check-ttf` against one Quartus
build first.

**First hardware test.** You need a USB cable, a multimeter (D5 to GND) *or* an LED with a 330 Ω
series resistor from D5 to GND, and a jumper wire or two. D1/D2 have weak pull-ups, so leaving them
unconnected = 1 and a jumper to GND = 0. Expect D5 = D1 AND D2: 3.3 V with nothing connected, 0 V when
either one is grounded. D3/D4 don't matter. Never connect D5 to anything but the meter/LED.

These test files drive D5 at the I/O standard's **minimum current strength** (pin variant
`vidorlo`), to limit the current if the SAMD21 ever drove the same pin.

**Easiest: `python3 hwtest.py`.** It checks the USB-Blaster and IDCODE, loads each file into SRAM
only (never flash), asks what D5 reads for the four D1/D2 combinations and logs the answers to
`out/hwtest_<time>.jsonl`. `python3 hwtest.py --check` runs only the preflight checks. It follows
this order:
1. `out/lo_quartus_8888.rbf` (Quartus's own build). This tests the setup.
2. `out/lo_quartus_0000.rbf` (Quartus, constant 0). D5 must read low. An unconfigured FPGA leaves D5
   floating with a weak pull-up, which a meter also reads as high, so this low reading proves the
   chip is really configured.
3. `out/lo_x8888.rbf` (patched from mask 0000, header checksum stale). This tests whether the chip
   checks the header.
4. If 3 works: `out/lo_x8888_X30Y20N12.rbf` (patched by the position model at a far-away LE, stale
   header). This tests `lutpos.py` on silicon.
   If 3 fails: `out/lo_x8888_hdr.rbf` (header fixed; byte-identical to 1).

## Hazards (read before flashing)

- **Every MKR header pin is also a SAMD21 GPIO.** The test designs drive only D5 (`PIN_T2`).
  Checked 2026-11-22: the D1–D5 ↔ N3/P3/R3/T3/T2 mapping matches Arduino's
  `VidorFPGA/constraints/MKRVIDOR4000/vidor_s_pins.qsf`. All unused FPGA pins are tri-stated
  inputs with weak pull-ups (Quartus default; see the `.pin` report). The USBBlaster example sketch
  has no pinMode/digitalWrite on header pins, but its JTAG code is a precompiled library and
  couldn't be read.
  Make sure the loaded SAMD21 firmware leaves D1–D5 as inputs, and put a ≥330 Ω resistor in
  series with any LED or meter. Don't flash designs that drive other Vidor pins (HDMI,
  SDRAM, flash, NINA, SAM_INT) until you've checked what's on the other end.
- **Only flash LUT-mask patches at first.** Repo lesson: hand-built routing bits caused
  driver contention and protective resets on silicon. Keep routing patches gold-anchored
  (byte-identical to a Quartus build) until a model is proven.
- A Quartus RBF plus Quartus's `.sof` can always be loaded through Route A as a known-good
  recovery. Power-cycling also reloads Arduino's image from flash.

## Legal notes (I'm not a lawyer)

- The Quartus Prime Lite licence (25.1std, as quoted in pluribus #165) forbids decompiling or
  reverse-engineering *the software* "except as otherwise permitted by applicable law".
  Nothing here touches Quartus binaries or databases. It only compiles designs and diffs the
  output files, the same black-box method the CRAM mapper uses.
- In the EU (you're in Sweden), Software Directive 2009/24/EC Art. 5(3) lets a licensed user
  observe, study or test a program's functioning while running it, and Art. 8 voids contract
  terms contrary to it. That supports black-box fuzzing. It does not cover disassembling
  Quartus or decoding its device-database files, so stay out of those.
- The same licence has a clause against publishing benchmark/test results of the software
  without permission (2.2.8, flagged but unexamined in pluribus #165). Our results describe
  the device's bitstream, not Quartus's performance, but read the clause in your installed
  licence before publishing.
- Don't commit RBF/SOF blobs to the PR. Commit scripts and derived facts. The repo itself says
  redistribution of its blobs "remains subject to Altera/Intel's original terms".

## Suggested contribution sequence (draft, nothing sent)

1. Issue: "Cross-die results: 10CL006 vs EP4CE6, 10CL016 vs EP4CE15" with the `report`
   output, IDCODE/size evidence and the 255-byte-frame geometry, asking whether the author
   wants multi-die support upstream (the repo hard-codes `DEVICE`, sizes and CRC frame
   ranges in `config.py` / `bitstream.py`).
2. Only then: PR adding a device-geometry abstraction (`rbfgeom.py`-style inference) plus
   Vidor loading docs. Mapping work on the 10CL016 (LUT constants first) goes in after the
   author agrees on structure.
3. Gap to offer: **C16** is the one wire class with zero coverage, and the method should
   carry over between dies. Coordinate with the author before starting, because they appear to be active
   (commits through 2026-09-30).
