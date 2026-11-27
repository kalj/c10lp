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
TRAIN = ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json", "xrkn_c4c_jobs.json", "xrkn_c4d_jobs.json", "xrkn_c4e_jobs.json")
HOP = re.compile(r"C4_X(\d+)_Y(\d+)_N0_I(\d+)$")
LINE = re.compile(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$")


def key(u: str, v: str):
    """(wire index, column offset, row offset, line, X mod 8): a C4 wire also feeds the LAB one column over (C4 at X2
    -> a line of X3), more than half of the corpus uses."""
    mu, mv = HOP.match(u), LINE.match(v)
    if not mu or not mv:
        return None
    # the bottom edge's C4s (start rows 0, 1) are numbered differently (c4drv.py): keyed by their start row
    return (f"{mu[3]}|{int(mv[1]) - int(mu[1])}|{int(mv[2]) - int(mu[2])}|{mv[3]}|{int(mv[1]) % 8}"
            + (f"|e{mu[2]}" if int(mu[2]) < 2 else ""))


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
                # frames -26..-23 are frames +9..+12 of the LAB to the left (35-frame pitch): its LE configuration,
                # which follows that LAB's contents, not this tap (frame -25: set ~25% whatever the line carries)
                for f in list(range(-22, -12)) + [13, 14, 15]:
                    for l in range(-70, 6):
                        c = G.cell_of(f0 + f, l0 + l)
                        if c and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1:
                            cells.add((f, l))
                u[k].append(((x, y), frozenset(cells)))
    return u


# each LAB line's select sits on one row (R4 tap selects: line 35 at -43/-44, ...); the row per line is read off the
# R4 -> line entries of the switch table (out/line_rows.json)
ROWS = {int(k): v for k, v in json.load(open(os.path.join(OUT, "line_rows.json"))).items()}


def learn(lst, line: int, dx: int):
    """Cells set in >= 80% of the uses, near the line's select row (other nets of the same build sink into the same
    LAB, and their selects pass the 80% rule together when the design repeats at many positions)."""
    if len(lst) < 3 or len({p for p, _s in lst}) < 2 or line not in ROWS:
        return None
    # the select's band follows the tap's column: a tap into the wire's own column (dx 0) has it in +13..+15, a tap
    # into the next column (dx 1) in -22..-13 (two-net builds: 320 and 397 uses; 18 with cells in both bands are
    # other nets')
    band = (lambda f: f >= 13) if dx == 0 else (lambda f: f < 0)
    cnt = collections.Counter(c for _p, s in lst for c in s if abs(c[1] - ROWS[line]) <= 1 and band(c[0]))
    keep = sorted(c for c, n in cnt.items() if n >= 0.8 * len(lst))
    # a C4 select can have four cells: a frame -25 pair the line's inputs share, and the input's own pair (e.g. in
    # +13..15 for C4 X8Y4 I8 -> X8Y7 line 11: Quartus set (13,-47)/(14,-48) besides (-25,-47)/(-25,-46)); trimming to
    # the two most frequent kept the shared pair and lost the input
    return keep if 0 < len(keep) <= 4 else None


def main() -> int:
    u = uses(TRAIN)
    model = {k: [list(c) for c in m] for k, lst in u.items()
             if (m := learn(lst, int(k.split("|")[3]), int(k.split("|")[1])))}
    # legality depends on the row phase as well (key (12, 0, 3, class 0): line 13 used at Y mod 4 = 0 and 3, line 14
    # at 2, and forcing 14 at Y mod 4 = 3 is refused): a tap is kept where it was seen at that phase
    legal = sorted({f"{k}|{pos[1] % 4}" for k, lst in u.items() for pos, _c in lst})
    json.dump({"bits": model, "legal": legal}, open(os.path.join(OUT, "c4sel.json"), "w"), indent=0)
    print(f"{len(u)} keys, {sum(map(len, u.values()))} uses; {len(model)} with bits, {len(legal)} legal (key, Y mod 4) "
          f"-> out/c4sel.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
