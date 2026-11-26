#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Buffer -> C4 drivers from corpus uses, per (buffer, wire, dx, dy, (X+Y) mod 4).

The switch table's buffer -> C4 entries show the structure: a driver is a bit pair on the buffer's row, at frames
+19/+21..22 of the source LAB for a C4 in the same column (dx 0) and -16/-13..-15 for one in the column to the left
(dx -1), for wires starting one row up (dy +1) or four down (dy -4).  For every use of such a hop in the vertical-span
builds, the cells set in those frames within 8 rows of the buffer's LE are collected; a cell counts when it is set in
at least 80% of a key's uses (3 or more, at 2 or more positions); a driver keeps one cell per frame band, the most
frequent.
Output: out/c4drv.json {"b|w|dx|dy|phase": [[frame, row], ...]} (relative to the source LAB)

  c4drv.py
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
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
TRAIN = ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json", "xrkn_c4c_jobs.json", "xrkn_c4d_jobs.json")
BUF = re.compile(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$")
C4 = re.compile(r"C4_X(\d+)_Y(\d+)_N0_I(\d+)$")
FRAMES = {0: (19, 20, 21, 22), -1: (-16, -15, -14, -13)}


def key(u, v):
    mu, mv = BUF.match(u), C4.match(v)
    if not mu or not mv:
        return None
    x, y, b = map(int, mu.groups())
    dx, dy = int(mv[1]) - x, int(mv[2]) - y
    if dx not in FRAMES:
        return None
    # the bottom edge's C4s (start rows 0, 1) are numbered differently (48.. at row 1; row 0's low indices collide with
    # mid-die ones): keyed by their start row
    return f"{b}|{mv[3]}|{dx}|{dy}|{(x + y) % 4}" + (f"|e{mv[2]}" if int(mv[2]) < 2 else "")


def uses(lists):
    u = collections.defaultdict(list)
    for jf in lists:
        for name in json.load(open(os.path.join(OUT, jf))):
            buf = xdev.load(OUT, name)
            if buf is None:
                continue
            for a, b in routes.pips(json.load(open(os.path.join(OUT, name + ".route.json")))):
                k = key(a, b)
                if not k:
                    continue
                mu = BUF.match(a)
                x, y, bb = map(int, mu.groups())
                f0, l0 = R._col_frame(x), R._row_index(y)
                try:
                    c0 = lutpos._predict_phys(x, y, bb - bb % 2)
                except (ValueError, KeyError):
                    continue
                lerow = min(v[1] for v in c0) + lutpos.PLANE_START[c0[0][2]] - l0
                cells = set()
                for f in FRAMES[int(k.split("|")[2])]:
                    for l in range(lerow - 8, lerow + 9):
                        c = G.cell_of(f0 + f, l0 + l)
                        if c and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1:
                            cells.add((f, l))
                u[k].append(((x, y), frozenset(cells)))
    return u


def learn(lst):
    if len(lst) < 3 or len({p for p, _s in lst}) < 2:
        return None
    cnt = collections.Counter(c for _p, s in lst for c in s)
    keep = [c for c, n in cnt.items() if n >= 0.8 * len(lst)]
    if not keep:
        return None
    lo, hi = min(f for f, _l in keep), max(f for f, _l in keep)
    first = max((c for c in keep if c[0] == lo), key=lambda c: cnt[c])
    if hi != lo:
        second = max((c for c in keep if c[0] != lo), key=lambda c: cnt[c])
    else:
        # a driver is a pair: with no partner at 80%, the most frequent cell of the other frames if at 50%, else no
        # entry (single-cell entries missed their partner: buffer 12 -> C4 I15 lacked (21, -15), buffer 4 -> C4 I12
        # lacked (21, 1), both set in Quartus's builds of our routing)
        rest = [c for c, n in cnt.items() if c[0] != lo and n >= 0.5 * len(lst)]
        if not rest:
            return None
        second = max(rest, key=lambda c: cnt[c])
    return sorted([first, second])


def main() -> int:
    u = uses(TRAIN)
    model = {k: [list(c) for c in m] for k, lst in u.items() if (m := learn(lst))}
    json.dump(model, open(os.path.join(OUT, "c4drv.json"), "w"), indent=0)
    print(f"{len(u)} keys, {sum(map(len, u.values()))} uses; {len(model)} with bits -> out/c4drv.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
