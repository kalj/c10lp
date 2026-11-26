#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4 -> LAB-line select bits from corpus uses (the oracle can't isolate them: a C4 tap reaches about one line, the
one Quartus already uses, so c4map.py's line probes come back "no select" and clear nothing).

For every use of a C4 w -> LAB line L hop in the vertical-span builds (xrkn_c4_jobs.json, timing-report routes), the
cells set in the sink LAB's select bands (frames -26..-13 and +13..+15, rows within 70 of the LAB's row index) are
collected per key (wire index, column offset, row offset, line, X mod 8).  A cell counts when it is within 2 rows of the
line's select row and set in at least 80% of a key's uses, with at least 3 uses at 2 or more positions; an entry has
1 to 3 cells.
Output: out/c4sel.json {"bits": {"w|dx|dy|line|class": [[frame, row], ...]} (relative to the sink LAB),
"legal": ["w|dx|dy|line|class|Y mod 4", ...]}, used by
switchmodel.Model for C4 -> LOCAL_INTERCONNECT hops without a corpus-table entry.

  c4sel.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
TRAIN = ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json")
HOP = re.compile(r"C4_X(\d+)_Y(\d+)_N0_I(\d+)$")
LINE = re.compile(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$")


def key(u: str, v: str):
    """(wire index, column offset, row offset, line, X mod 8): a C4 wire also feeds the LAB one column over (C4 at X2
    -> a line of X3), more than half of the corpus uses."""
    mu, mv = HOP.match(u), LINE.match(v)
    if not mu or not mv:
        return None
    return f"{mu[3]}|{int(mv[1]) - int(mu[1])}|{int(mv[2]) - int(mu[2])}|{mv[3]}|{int(mv[1]) % 8}"


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
                mv = LINE.match(b)
                x, y = int(mv[1]), int(mv[2])
                f0, l0 = R._col_frame(x), R._row_index(y)
                if f0 is None or l0 is None:
                    continue
                cells = set()
                for f in list(range(-26, -12)) + [13, 14, 15]:
                    for l in range(-70, 6):
                        c = G.cell_of(f0 + f, l0 + l)
                        if c and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1:
                            cells.add((f, l))
                u[k].append(((x, y), frozenset(cells)))
    return u


# each LAB line's select sits on one row (R4 tap selects: line 35 at -43/-44, ...); the row per line is read off the
# R4 -> line entries of the switch table (out/line_rows.json)
ROWS = {int(k): v for k, v in json.load(open(os.path.join(OUT, "line_rows.json"))).items()}


def learn(lst, line: int):
    """Cells set in >= 80% of the uses, near the line's select row (other nets of the same build sink into the same
    LAB, and their selects pass the 80% rule together when the design repeats at many positions)."""
    if len(lst) < 3 or len({p for p, _s in lst}) < 2 or line not in ROWS:
        return None
    cnt = collections.Counter(c for _p, s in lst for c in s if abs(c[1] - ROWS[line]) <= 2)
    keep = sorted(c for c, n in cnt.items() if n >= 0.8 * len(lst))
    return keep if 0 < len(keep) <= 3 else None


def main() -> int:
    u = uses(TRAIN)
    model = {k: [list(c) for c in m] for k, lst in u.items() if (m := learn(lst, int(k.split("|")[3])))}
    # legality depends on the row phase as well (key (12, 0, 3, class 0): line 13 used at Y mod 4 = 0 and 3, line 14
    # at 2, and forcing 14 at Y mod 4 = 3 is refused): a tap is kept where it was seen at that phase
    legal = sorted({f"{k}|{pos[1] % 4}" for k, lst in u.items() for pos, _c in lst})
    json.dump({"bits": model, "legal": legal}, open(os.path.join(OUT, "c4sel.json"), "w"), indent=0)
    print(f"{len(u)} keys, {sum(map(len, u.values()))} uses; {len(model)} with bits, {len(legal)} legal (key, Y mod 4) "
          f"-> out/c4sel.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
