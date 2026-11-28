#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Corner turns R4 -> C4 and C4 -> R4 from the corpus (the routing gap behind the stress test's unroutable designs).

A turn enters the target wire's driver mux, like an LE buffer does:
  R4 -> C4: the C4 (column cx, start row sy) is driven from row sy - 1 (upward) or sy + 4 (downward), from column cx
            (cells in frames 19..22) or cx + 1 (frames -16..-13) (c4drv.py); the R4 runs along that row.
  C4 -> R4: the R4 (start column sx, row y) is driven from column sx - 1 (right-going, index 0..16) or sx + 3
            (left-going, 17..33), frames 13..22, on row y, which the C4 passes.
Per use, the set cells of that band in the driver LAB (all rows of the LAB); per key the cells set in >= 80% of the
uses (at least 3 uses at 2 positions), at most 2 (a driver is a pair).  Keys:
  R4 -> C4: (R4 index, R4 start - driver column, C4 index, driver column - cx, dy, (X+Y) mod 4 of the driver LAB)
  C4 -> R4: (C4 index, driver row - C4 start row, cx - driver column, R4 index, phase)
Output: out/corner.json {"R4>C4|key": [[frame, row], ...], "C4>R4|key": ...}; cells relative to the driver LAB's
LE N0 (frame, row index), as c4drv.json.

  corner.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import routegraph as G  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
TRAIN = ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json", "xrkn_c4c_jobs.json", "xrkn_c4d_jobs.json", "xrkn_c4e_jobs.json", "xrkn_c4f_jobs.json", "xrkn_w2w_jobs.json",
         "route_corpus_jobs.json")
P = re.compile(r"(R4|C4)_X(\d+)_Y(\d+)_N0_I(\d+)$")


def anchor(x, y):
    try:
        c0 = lutpos._predict_phys(x, y, 0)
    except (ValueError, KeyError):
        return None
    return min(c[0] for c in c0), min(c[1] for c in c0) + lutpos.PLANE_START[c0[0][2]]


def keys(u: str, v: str):
    """[(kind, key, driver LAB, frames)] of a turn: both candidate driver columns of an R4 -> C4 turn (only the true
    one has consistent cells over the uses)."""
    mu, mv = P.match(u), P.match(v)
    if not mu or not mv:
        return []
    if mu[1] == mv[1] == "C4":
        # C4 -> C4: the next C4 (column vx, start vy) is driven from row vy - 1 (upward) or vy + 4 (downward), from
        # column vx (frames 19..22) or vx + 1 (-16..-13); the first C4 (column ux, rows uy..uy+3) passes that row
        ux, uy, ui = int(mu[2]), int(mu[3]), int(mu[4])
        vx, vy, vi = int(mv[2]), int(mv[3]), int(mv[4])
        if uy < 2 or vy < 2:
            return []
        out = []
        for dy in (-1, 4):
            ry = vy + dy                                   # the driver row
            if not 0 <= ry - uy <= 3:
                continue
            for dc, frames in ((0, range(19, 23)), (1, range(-16, -12))):
                dx = vx + dc
                if 0 <= dx - ux <= 1:
                    out.append(("C4>C4", f"{ui}|{ry - uy}|{ux - dx}|{vi}|{dc}|{dy}|{(dx + ry) % 4}", (dx, ry), frames))
        return out
    if mu[1] == mv[1]:
        return []
    ux, uy, ui = int(mu[2]), int(mu[3]), int(mu[4])
    vx, vy, vi = int(mv[2]), int(mv[3]), int(mv[4])
    if mu[1] == "R4":                                   # R4 -> C4: driver row = the R4's row
        dy = vy - uy
        if dy not in (1, -4) or vy < 2:
            return []
        out = []
        for dc, frames in ((0, range(19, 23)), (1, range(-16, -12))):
            dx = vx + dc                                 # driver column
            if -1 <= dx - ux <= 4:                       # the R4 (start ux, 4 columns) reaches the driver column
                out.append(("R4>C4", f"{ui}|{ux - dx}|{vi}|{dc}|{dy}|{(dx + uy) % 4}", (dx, uy), frames))
        return out
    # C4 -> R4: driver column from the R4's direction, row = the R4's row
    dx = vx - 1 if vi < 17 else vx + 3
    if uy < 2 or not 0 <= vy - uy <= 3 or not 0 <= dx - ux <= 1:
        return []
    return [("C4>R4", f"{ui}|{vy - uy}|{ux - dx}|{vi}|{(dx + vy) % 4}", (dx, vy), range(13, 23))]


def uses():
    u = collections.defaultdict(list)
    for jf in TRAIN:
        p = os.path.join(OUT, jf)
        if not os.path.exists(p):
            continue
        for name in json.load(open(p)):
            rp = os.path.join(OUT, name + ".route.json")
            buf = xdev.load(OUT, name)
            if buf is None or not os.path.exists(rp):
                continue
            for a, b in routes.pips(json.load(open(rp))):
                for kind, kk, (dx, dy), frames in keys(a, b):
                    an = anchor(dx, dy)
                    if an is None:
                        continue
                    f0, l0 = an
                    cells = frozenset((f, r) for f in frames for r in range(-69, 1)
                                      if (c := G.cell_of(f0 + f, l0 + r)) and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1)
                    u[f"{kind}|{kk}"].append(((dx, dy), cells))
    return u


def learn(lst, kind):
    if len(lst) < 3 or len({p for p, _s in lst}) < 2:
        return None
    cnt = collections.Counter(c for _p, s in lst for c in s)
    keep = sorted(c for c, n in cnt.items() if n >= 0.8 * len(lst))
    # a C4 driver is a pair (c4drv.py): one cell missed its partner (R4 I11 -> C4 I19 at X12: (492,147,6), Quartus
    # (496,147,6)); an R4 driver input may be one cell (held-out C4 -> R4: 23 right with single cells).  More than
    # two: co-occurring hops' cells
    # C4 -> R4 too: a single cell missed its partner (rd208: (137,59,6) without (139,60,6))
    if len(keep) != 2:
        return None
    return keep


def main() -> int:
    u = uses()
    model = {k: [list(c) for c in m] for k, lst in u.items() if (m := learn(lst, k.split("|")[0]))}
    json.dump(model, open(os.path.join(OUT, "corner.json"), "w"), indent=0)
    kinds = collections.Counter(k.split("|")[0] for k in model)
    print(f"{len(u)} keys, {sum(map(len, u.values()))} uses; {len(model)} with bits {dict(kinds)} -> out/corner.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
