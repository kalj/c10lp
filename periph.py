#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Periphery (I/O) region of the 10CL016 RBF: frames 1..36.

Format, fitted on io: builds (xdev.py):
- The 36 physical frames are one byte stream holding 9 logical frames of 255 bytes, each byte
  stored 4 times in a row (logical byte i = stream bytes 4i..4i+3).
- Each logical frame ends in the same CRC-16 as the core frames (poly 0x8005, init 0xFE54,
  little-endian, over its first 253 bytes), also stored 4 times.
- Header sum: a logical bit (frame k, byte p, plane 2) weighs 2^((p + 5 + 4k) mod 8). Only
  plane 2 has been seen in I/O settings so far, so other planes have no weight model yet.

  periph.py check      rebuild every io: variant from the io:base build, compare byte for byte
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpatch  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

FIRST, NFRAMES, REP = 1, 36, 4
LOGICAL = 255


def _stream_offset(g: rbfgeom.Geometry) -> int:
    return g.preamble + FIRST * g.frame


def logical(buf: bytes, g: rbfgeom.Geometry) -> list[bytes]:
    s = _stream_offset(g)
    stream = buf[s:s + NFRAMES * g.frame]
    data = bytes(stream[i] for i in range(0, len(stream), REP))
    return [data[k * LOGICAL:(k + 1) * LOGICAL] for k in range(len(data) // LOGICAL)]


def header_weight(k: int, p: int, bit: int) -> int:
    if bit != 2:
        raise ValueError("header weight known for plane 2 only")
    return 1 << ((p + 5 + 4 * k) % 8)


def set_bit(buf: bytearray, g: rbfgeom.Geometry, k: int, p: int, bit: int, val: int) -> int:
    """Set logical bit (frame k, byte p, plane bit) in all 4 copies; returns the header-sum delta."""
    base = _stream_offset(g) + REP * (k * LOGICAL + p)
    old = buf[base] >> bit & 1
    if old == val:
        return 0
    for r in range(REP):
        buf[base + r] ^= 1 << bit
    return header_weight(k, p, bit) * (1 if val else -1)


def fix_crc(buf: bytearray, g: rbfgeom.Geometry) -> None:
    for k, blk in enumerate(logical(bytes(buf), g)):
        c = rbfgeom.crc16(blk[:LOGICAL - 2], g.init).to_bytes(2, g.byteorder)
        for j, byte in enumerate(c):
            off = _stream_offset(g) + REP * (k * LOGICAL + LOGICAL - 2 + j)
            buf[off:off + REP] = bytes([byte]) * REP


def apply(base: bytes, changes) -> bytes:
    """changes: iterable of (k, p, bit, val) logical bits.  Fixes the periphery CRCs and the header sum."""
    g = rbfgeom.infer(base)
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    for k, p, bit, val in changes:
        v += set_bit(buf, g, k, p, bit, val)
    fix_crc(buf, g)
    lutpatch.set_header_sum(buf, v % (1 << 32))
    return bytes(buf)


def diff(a: bytes, b: bytes):
    """Logical periphery bits that differ (CRC bytes excluded), as (k, p, bit, value in b)."""
    g = rbfgeom.infer(a)
    la, lb = logical(a, g), logical(b, g)
    return [(k, p, bit, lb[k][p] >> bit & 1) for k in range(len(la)) for p in range(LOGICAL - 2)
            if la[k][p] != lb[k][p] for bit in range(8) if (la[k][p] ^ lb[k][p]) >> bit & 1]


def main() -> int:
    out = os.path.join(HERE, "out")
    base = xdev.load(out, "c10_016__iobase_X10Y10N0__vidor")
    ok = n = 0
    for v in xdev.IO_VARIANTS:
        ref = xdev.load(out, f"c10_016__io{v}_X10Y10N0__vidor")
        if v == "base" or ref is None:
            continue
        got = apply(base, diff(base, ref))
        n += 1
        ok += got == ref
        print(f"  {v:10s}: {'BYTE-IDENTICAL' if got == ref else 'differs'}")
    print(f"{ok}/{n} I/O variants rebuilt byte-identical from the base")
    return 0 if ok == n else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        sys.exit(main())
    print(__doc__)
