#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write M9K ROM contents on the 10CL016 without Quartus (xdev designs "rom:" and "rom2:").

Cell model, fitted on single-bit probes at 12 sites (X13 and X25, rows 1..28) and 7 layouts:
an M9K is 256 rows x 36 positions; LAYOUTS maps (word, bit) -> (row, position) per (width, depth);
    frame = F[X] + row                            F = {13: 517, 25: 1185}
    byte  = ROW[Y].byte - 14 - position           (lutpos.ROW: the LAB row's low LUT byte)
    plane = ROW[Y].bit
Only bits Quartus stores are written: here q[0..3], the ones the design reads.
Header sum: M9K bits weigh 2^((2L + frame + 7) mod 8), with the frame's sign opposite to LAB bits.

  m9kpatch.py check SITE [SITE ...]     compare with Quartus builds of random contents (byte-identical?)
  m9kpatch.py write SITE SPEC -o x.rbf  SPEC as xdev.rom_words ("r<seed>", "w<w>b<b>", "zero")
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
F = {13: 517, 25: 1185}
BITS = 4                   # q[0..3]: the bits the rom: design reads (Quartus doesn't store the others)


# Physical M9K: 256 rows (frames F[X]..F[X]+255) x 36 positions (bytes anchor..anchor-35).
# Each layout (width, depth) maps (word, bit) to (row, position):
LAYOUTS = {
    (36, 256): lambda w, b: (w, 2 * b if b < 18 else 2 * (b - 18) + 1),
    (18, 512): lambda w, b: (w >> 1, 2 * b + (w & 1)),
    (9, 512): lambda w, b: (w >> 1, 2 * b + (w & 1)),
    (9, 1024): lambda w, b: (w >> 2, 2 * b + 18 * (w & 1) + (w >> 1 & 1)),
    (4, 2048): lambda w, b: (w >> 3, 2 * b + 8 * (w & 1) + 18 * (w >> 1 & 1) + (w >> 2 & 1)),
    (2, 4096): lambda w, b: (w >> 4, 2 * b + 4 * (w & 1) + 8 * (w >> 1 & 1) + 18 * (w >> 2 & 1)
                             + (w >> 3 & 1)),
    (1, 8192): lambda w, b: (w >> 5, 2 * (w & 7) + 18 * (w >> 3 & 1) + (w >> 4 & 1)),
}


def cell(site: str, word: int, bit: int, layout=(9, 512)) -> tuple[int, int, int]:
    x, y = (int(v) for v in site[1:].split("_Y"))
    low, plane = lutpos.ROW[y]
    row, pos = LAYOUTS[layout](word, bit)
    byte = low - 14 - pos
    if byte < 2:                      # same per-byte wrap as LUT cells: top of the frame, plane + 1
        plane += 1
        byte += 251 if plane >= 5 else 252
    return F[x] + row, byte, plane


def header_weight(f: int, p: int, b: int) -> int:
    """Header-sum weight of an M9K content bit.  Same row space L as LAB bits
    (lutpos.header_weight), but the frame enters with the opposite sign: 2^((2L + frame + 7) mod 8)."""
    return 1 << ((2 * (p + lutpos.PLANE_START[b]) + f + 7) % 8)


def name(site: str, spec: str) -> str:
    return xdev.Job("c10_016", f"rom:{site}:{spec}", (0, 0, 0), "vidorlo").name


def write(site: str, words: list[int], layout=None, base_name=None, bits=None) -> tuple[bytes, list]:
    """Write ROM contents into a zero-content base (default: the rom:SITE:zero build, 9x512 with
    q[0..3]); returns (bytes, changed cells)."""
    layout = layout or (9, 512)
    bits = BITS if bits is None else bits
    base = xdev.load(OUT, base_name or name(site, "zero"))
    if base is None:
        raise SystemExit(f"build {base_name or name(site, 'zero')} first")
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    changed = []
    for w, val in enumerate(words):
        for b in range(bits):
            if val >> b & 1:
                f, p, pl = cell(site, w, b, layout)
                off = 32 + f * 255 + p
                buf[off] ^= 1 << pl
                v += header_weight(f, p, pl) * (1 if buf[off] >> pl & 1 else -1)
                changed.append((f, p, pl))
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    return bytes(buf), changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "write"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    if a.cmd == "write":
        site, spec = a.args
        data, ch = write(site, xdev.rom_words(spec))
        open(a.output, "wb").write(data)
        print(f"wrote {a.output}: {len(ch)} ROM bits set at M9K {site}")
        return 0
    bad = 0
    for site in a.args:
        for spec in ("r1", "r2"):
            ref = xdev.load(OUT, name(site, spec))
            if ref is None:
                print(f"  {site} {spec}: not built")
                continue
            words = [w & ((1 << BITS) - 1) for w in xdev.rom_words(spec)]
            data, ch = write(site, words)
            same = data == ref
            bad += not same
            nb = sum(x != y for x, y in zip(data, ref))
            print(f"  {site} {spec}: {len(ch)} bits written, " + ("BYTE-IDENTICAL to Quartus" if same
                  else f"{nb} bytes differ"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
