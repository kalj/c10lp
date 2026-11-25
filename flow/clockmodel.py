#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed configuration of a placement (clock tree, LAB clock selects, register controls), built from rules and from
measurements at *other* placements; it replaces the measured placement bundle (posmux.py) for a new placement.

  LAB-relative pattern   the fixed cells of a reference placement relative to its LABs (frame - column frame,
                         row-space index - row index), translated onto the new LABs with the same roles; the routing
                         bands (frames -26..-13, +13..+19) are left out (they follow the route choice)
  global E2 clock tree   cells outside every LAB, with the same value in the builds of other E2-clocked designs and a
                         different one in the all-zero design (their intersection)
  row clock select       per LAB row: offsets -1 = 0, +5 = 1, +8 = 1 on the row's LUT plane, bytes ROW.low - 62 + offset,
                         frame 488 (x <= 12), 489 (x <= 20), 1593 (x <= 29), 1594 (gclk.json regional_model)
  quadrant               (487, 54, 5) = 0 for x <= 20, (1592, 54, 5) = 0 beyond
Output: a bundle file in placement_NAME.json format.

  clockmodel.py NEW_NAME REF_NAME 'X,Y X,Y' 'X,Y X,Y' DESIGN [DESIGN ...]
      new LABs, reference LABs (same roles, same order), other E2-clocked template builds for the global set
      (only designs clocked from E2: unclocked ones would drop real clock-tree cells from the intersection)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import explain  # noqa: E402
import lutpos  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
NO_LAB = "--no-lab" in sys.argv          # only the global clock-tree cells: LAB clocking comes from priced clock hops


def row_select_frame(x: int) -> int:
    return 488 if x <= 12 else 489 if x <= 20 else 1593 if x <= 29 else 1594


def lab_of(f: int, labs):
    k = min(range(len(labs)), key=lambda i: abs(R._col_frame(labs[i][0]) - f))
    return k if abs(R._col_frame(labs[k][0]) - f) <= 40 else None


def build(ref_bundle: list, ref_labs, new_labs, global_bufs: list[bytes]):
    zero = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    out = {}
    for f, p, b, v in ([] if NO_LAB else ref_bundle):   # LAB-relative pattern, translated
        k = lab_of(f, ref_labs)
        if k is None:
            continue
        fo = f - R._col_frame(ref_labs[k][0])
        l = p + lutpos.PLANE_START[b] - R._row_index(ref_labs[k][1])
        if (-26 <= fo <= -13 or 13 <= fo <= 19) and not -37 <= l <= -28:
            continue        # select / driver band outside the LAB-control rows: routing (the clock-variant bit sits at
                            # row -34; an unpriced output driver of the reference leaked at +13/+14 otherwise)
        c = G.cell_of(R._col_frame(new_labs[k][0]) + fo, R._row_index(new_labs[k][1]) + l)
        if c:
            out[c] = v
    common = None                                       # global E2 clock tree: common to other clocked designs
    for buf in global_bufs:
        d = {c: buf[32 + c[0] * 255 + c[1]] >> c[2] & 1 for c in explain.core_diff(zero, buf)}
        common = d if common is None else {c: v for c, v in common.items() if d.get(c) == v}
    allabs = list(ref_labs) + list(new_labs)
    for c, v in (common or {}).items():
        if c[0] not in (487, 488, 489, 1592, 1593, 1594) and lab_of(c[0], allabs) is None:
            out[c] = v
    for x, y in ([] if NO_LAB else new_labs):           # row clock select and quadrant (with --no-lab: clock hops)
        low, plane = lutpos.ROW[y]
        for off, v in ((-1, 0), (5, 1), (8, 1)):
            out[(row_select_frame(x), low - 62 + off, plane)] = v
        out[(487, 54, 5) if x <= 20 else (1592, 54, 5)] = 0
    return out


def main() -> int:
    import tpatch
    import xdev
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    new, ref, nl, rl = args[:4]
    designs = args[4:]
    new_labs = [tuple(map(int, s.split(","))) for s in nl.split()]
    ref_labs = [tuple(map(int, s.split(","))) for s in rl.split()]
    ref_bundle = [tuple(x) for x in json.load(open(os.path.join(OUT, f"placement_{ref}.json")))]
    # a design is a template name (its placeholder-mask build) or a path to any E2-clocked RBF
    bufs = [open(d, "rb").read() if os.path.exists(d) else xdev.load(OUT, tpatch.job(d, [m for _, m in xdev.tpl_luts(d)]).name)
            for d in designs]
    out = build(ref_bundle, ref_labs, new_labs, [b for b in bufs if b])
    p = os.path.join(OUT, f"clockmodel_{new}_from_{ref}{'_global' if NO_LAB else ''}.json")
    json.dump([[*c, v] for c, v in sorted(out.items())], open(p, "w"))
    print(f"{len(out)} cells for {new} from {ref} and {len([b for b in bufs if b])} other clocked builds -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
