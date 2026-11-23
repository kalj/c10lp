#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-load safety gate for patched 10CL016 bitstreams.

A patched file may differ from its Quartus template only in
  - the LUT cells of the LEs it declares (lutpos.py positions),
  - frame CRC bytes (frames 37..2002), which must all be valid,
  - the header sum bits (bit 0 of 0x29..0x48) and header CRC (0x49..0x4A).
Anything else (routing, I/O, periphery) means the file is not gold-anchored
and must not be loaded.

  gate.py TEMPLATE.rbf CANDIDATE.rbf X,Y,N [X,Y,N ...]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402

SIZE = 510_856


def check(template: bytes, cand: bytes, les, extra_cells=()) -> list[str]:
    """Problems found; empty means safe to load.  extra_cells: (frame, byte, bit) cells that may also
    differ (the select bits of an approved single-input rewire, rewire.py); empty by default."""
    if len(template) != SIZE or len(cand) != SIZE:
        return [f"size {len(cand)} / template {len(template)}, expected {SIZE}"]
    g = rbfgeom.infer(template)
    gc = rbfgeom.infer(cand)
    errs = []
    if gc.crc_frames != g.crc_frames or gc.frame != 255:
        errs.append(f"frame CRCs: {len(gc.crc_frames)} valid, template {len(g.crc_frames)}")
    allowed: set[tuple[int, int]] = set()
    for x, y, n in les:
        for f, p, b in lutpos._predict_phys(x, y, n):
            allowed.add((g.preamble + f * g.frame + p, b))
    for f, p, b in extra_cells:
        allowed.add((g.preamble + f * g.frame + p, b))
    crc_bytes = {g.preamble + f * g.frame + g.frame - k for f in g.crc_frames for k in (1, 2)}
    bad = []
    for i, (a, c) in enumerate(zip(template, cand)):
        d = a ^ c
        if not d or i in crc_bytes:
            continue
        if lutpatch.HDR_SUM <= i < lutpatch.HDR_SUM + 32 and d == 1:
            continue
        if lutpatch.HDR_CRC <= i < lutpatch.HDR_CRC + 2:
            continue
        for b in range(8):
            if d >> b & 1 and (i, b) not in allowed:
                bad.append((i, b))
    if bad:
        errs.append(f"{len(bad)} bits differ outside the declared LUT cells, e.g. "
                    + ", ".join(f"0x{i:05X}.{b}" for i, b in bad[:5]))
    hc = rbfgeom.crc16(cand[33:lutpatch.HDR_CRC], 0xFFFF).to_bytes(2, "little")
    if cand[lutpatch.HDR_CRC:lutpatch.HDR_CRC + 2] != hc:
        errs.append("header CRC (0x49..0x4A) invalid")
    return errs


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    t, c = (open(p, "rb").read() for p in sys.argv[1:3])
    les = [tuple(int(v) for v in s.split(",")) for s in sys.argv[3:]]
    errs = check(t, c, les)
    print("GATE PASS" if not errs else "GATE FAIL: " + "; ".join(errs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
