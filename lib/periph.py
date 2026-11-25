#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Periphery (I/O) region of the 10CL016 RBF: frames 1..36.

Format, fitted on io: builds (xdev.py):
- The 36 physical frames are one byte stream holding 9 logical frames of 255 bytes, each byte
  stored 4 times in a row (logical byte i = stream bytes 4i..4i+3).
- Each logical frame ends in the same CRC-16 as the core frames (poly 0x8005, init 0xFE54,
  little-endian, over its first 253 bytes), also stored 4 times.
- Header sum: a logical bit (frame k, byte p, plane b) weighs 2^((p + 4k + PLANE_OFFSET[b]) mod 8),
  fitted on pull-up probes at all 138 legal input pins (iopin: design), every plane consistent.

  periph.py check                      rebuild Quartus's I/O variants from their bases, byte for byte
  periph.py set IN OUT PIN KEY=VAL...  change I/O settings of PIN without Quartus:
                                       pullup=0/1, bushold=0/1, opendrain=0/1, drive=4/8 (mA, from 8/4)
Pin positions come from io_pullup.json, the other settings from fixed offsets in io_tile.json.
Not tested on silicon; gate.py refuses periphery changes.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
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


# Per-plane offset of the header-sum exponent, fitted on single-bit pull-up probes at 138 pins.
PLANE_OFFSET = {0: 4, 1: 6, 2: 5, 3: 1, 4: 7, 5: 5, 6: 0, 7: 4}


def header_weight(k: int, p: int, bit: int) -> int:
    return 1 << ((p + 4 * k + PLANE_OFFSET[bit]) % 8)


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


def _tables():
    import json
    pu = json.load(open(os.path.join(HERE, "data", "io_pullup.json")))["pullup"]
    tile = json.load(open(os.path.join(HERE, "data", "io_tile.json")))
    return pu, tile


def tile_cell(pin: str, offset: int) -> tuple[int, int, int]:
    """Logical cell at OFFSET bytes from PIN's pull-up bit; the stream runs over bytes 1..252 of each logical frame."""
    pu, _ = _tables()
    k, p, bit = pu[pin]
    p += offset
    while p > LOGICAL - 3:
        p -= LOGICAL - 3
        k += 1
    while p < 1:
        p += LOGICAL - 3
        k -= 1
    return k, p, bit


def setting(pin: str, key: str, val: int) -> list[tuple[int, int, int, int]]:
    """Logical bit changes (k, p, bit, value) for one I/O setting."""
    _, tile = _tables()
    if key == "pullup":
        return [tile_cell(pin, 0) + (val,)]
    if key == "bushold":                       # Quartus turns the pull-up off with bus hold
        return [tile_cell(pin, -1) + (val,)] + ([tile_cell(pin, 0) + (0,)] if val else [])
    if key == "opendrain":
        return [tile_cell(pin, tile["open_drain"]["offset"]) + (val,)]
    if key == "drive":
        ch = tile["drive_8mA_to_4mA"]["changes"]
        if val not in (4, 8):
            raise ValueError("drive must be 4 or 8")
        return [tile_cell(pin, off) + (v if val == 4 else 1 - v,) for off, v in ch]
    raise ValueError(f"unknown setting {key}")


def set_main(args) -> int:
    src, dst, pin, *kv = args
    data = open(src, "rb").read()
    changes = []
    for item in kv:
        key, val = item.split("=")
        changes += setting(pin, key, int(val))
    out = apply(data, changes)
    open(dst, "wb").write(out)
    print(f"wrote {dst}: {len(changes)} logical periphery bits set for {pin}; CRCs and header sum fixed")
    return 0


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
    if sys.argv[1:2] == ["set"] and len(sys.argv) >= 6:
        sys.exit(set_main(sys.argv[2:]))
    print(__doc__)
