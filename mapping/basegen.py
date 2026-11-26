#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the all-zero baseline from models (long-term goal, user 2026-11-25): no Quartus compile.

Built up rule by rule and checked against Quartus's build (out/lo_quartus_0000.rbf, from make baseline) after each:
  1. every LAB: the cells set relative to its LE N0 in nearly every LAB of the baseline (LAB_PATTERN)
  ... (further rules: special columns, periphery)
Reports, per rule, the core cells it gets right / misses / adds.

  basegen.py
"""
from __future__ import annotations

import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")


def labs():
    for x in range(42):
        if R._col_frame(x) is None:
            continue
        for y in range(1, 29):
            try:
                c0 = lutpos._predict_phys(x, y, 0)
            except (ValueError, KeyError):
                continue
            yield (x, y), min(c[0] for c in c0), min(c[1] for c in c0) + lutpos.PLANE_START[c0[0][2]]


def core_cells(buf, g):
    crc = {32 + f * 255 + 255 - k for f in g.crc_frames for k in (1, 2)}
    return {((i - 32) // 255, (i - 32) % 255, b) for i in range(32 + 37 * 255, len(buf)) if i not in crc
            for b in range(8) if buf[i] >> b & 1}


def main() -> int:
    z = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    g = rbfgeom.infer(z)
    truth = core_cells(z, g)
    L = list(labs())
    cnt = collections.Counter()
    for _xy, f0, l0 in L:
        for f in range(-24, 11):                     # one LAB's own frames and rows (-25 = the west LAB's +10,
            for r in range(-69, 1):                  # row -70 = the LAB below's row 0)
                c = G.cell_of(f0 + f, l0 + r)
                if c and c in truth:
                    cnt[(f, r)] += 1
    pattern = sorted(k for k, n in cnt.items() if n >= 0.5 * len(L))
    gen = set()
    for _xy, f0, l0 in L:
        gen |= {G.cell_of(f0 + f, l0 + r) for f, r in pattern}
    gen.discard(None)
    print(f"rule 1, LAB pattern ({len(pattern)} cells x {len(L)} LABs): right {len(gen & truth)}, missed "
          f"{len(truth - gen)}, extra {len(gen - truth)} of {len(truth)} core cells")
    # where the pattern is wrong: per LAB, cells missing / extra
    bad = collections.Counter()
    for (x, y), f0, l0 in L:
        mine = {G.cell_of(f0 + f, l0 + r) for f, r in pattern}
        miss = len(mine - truth)
        if miss:
            bad[(x, y)] = miss
    print("  LABs where pattern cells are clear in the baseline:", len(bad), sorted(bad.items())[:20])
    print("  pattern:", pattern)
    return 0


if __name__ == "__main__":
    sys.exit(main())
