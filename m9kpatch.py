#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write M9K ROM contents on the 10CL016 without Quartus (xdev design "rom:", 9x512, q[0..3] used).

Cell model, fitted on single-bit probes at 12 sites (X13 and X25, rows 1..28):
    frame = F[X] + word // 2                      F = {13: 517, 25: 1185}
    byte  = ROW[Y].byte - 14 - word % 2 - 2*bit   (lutpos.ROW: the LAB row's low LUT byte)
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
F = {13: 517, 25: 1185}
BITS = 4                   # q[0..3]: the bits the rom: design reads (Quartus doesn't store the others)


def cell(site: str, word: int, bit: int) -> tuple[int, int, int]:
    x, y = (int(v) for v in site[1:].split("_Y"))
    low, plane = lutpos.ROW[y]
    byte = low - 14 - word % 2 - 2 * bit
    if byte < 2:                      # same per-byte wrap as LUT cells: top of the frame, plane + 1
        plane += 1
        byte += 251 if plane >= 5 else 252
    return F[x] + word // 2, byte, plane


def header_weight(f: int, p: int, b: int) -> int:
    """Header-sum weight of an M9K content bit.  Same row space L as LAB bits
    (lutpos.header_weight), but the frame enters with the opposite sign: 2^((2L + frame + 7) mod 8)."""
    return 1 << ((2 * (p + lutpos.PLANE_START[b]) + f + 7) % 8)


def name(site: str, spec: str) -> str:
    return xdev.Job("c10_016", f"rom:{site}:{spec}", (0, 0, 0), "vidorlo").name


def write(site: str, words: list[int]) -> tuple[bytes, list]:
    """The rom:SITE:zero base with these contents; returns (bytes, changed cells)."""
    base = xdev.load(OUT, name(site, "zero"))
    if base is None:
        raise SystemExit(f"build {name(site, 'zero')} first")
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    changed = []
    for w, val in enumerate(words):
        for b in range(BITS):
            if val >> b & 1:
                f, p, pl = cell(site, w, b)
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
