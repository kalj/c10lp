#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Output-path bundle from an LE to the D5 pin, measured from corpus builds (other designs) whose LUT at that LE drives D5.

The path's hops always co-occur with that LE in the corpus, so the exact hop solver files their bits under the LE's
signature.  Here: cells set in every build where the LE drives D5 by this path,
  (a) and in no build without that path, outside the LE's own LAB band (its signature minus LE configuration), plus
  (b) near the D5 I/O column (frames 240..320) and not set in the all-zero design (cells that other paths into D5 share,
      which (a) removes; e.g. (259,7,7) for the blinky's output).
Output: out/outpath_X_Y_N.json, a list of (frame, byte, plane)

  outpath.py X Y N
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import hopsolve as H  # noqa: E402
import limsolve as L  # noqa: E402
import routemap as R  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
FILES = L.JOB_FILES + ["xrkn_holdout2_jobs.json", "xrkn_holdout3_jobs.json"]


def measure(x: int, y: int, n: int):
    names = []
    for f in FILES:
        if os.path.exists(os.path.join(OUT, f)):
            names += json.load(open(os.path.join(OUT, f)))
    le = f"LCCOMB_X{x}_Y{y}_N{n}"
    tails, sets = collections.Counter(), {}
    path_of = {}
    for nm in names:
        r = json.load(open(os.path.join(OUT, nm + ".route.json")))
        for p in r["paths"].values():
            nodes = [h[0] for h in p if h[2] in ("RE", "IC")]
            if le in nodes and nodes[-1].startswith(("IOOBUF", "IOPAD")) or (le in nodes and "BLOCK_INPUT_MUX" in "".join(nodes)):
                i = nodes.index(le)
                path_of[nm] = tuple(v for v in nodes[i + 1:] if not v.startswith(("IOOBUF", "IOPAD")))
                break
        sets[nm] = H.ones(xdev.load(OUT, nm))
    if not path_of:
        return None, None
    path = collections.Counter(path_of.values()).most_common(1)[0][0]
    yes = [sets[nm] for nm, p in path_of.items() if p == path]
    no = [sets[nm] for nm in names if path_of.get(nm) != path]
    zero = H.ones(open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read())
    common = set.intersection(*yes)
    f0, l0 = R._col_frame(x), R._row_index(y)
    dec = lambda c: (c // 2048, c % 2048 // 8, c % 8)
    specific = common - set().union(*no) - H.lut_cells()
    a = {dec(c) for c in specific if abs(c // 2048 - f0) > 12}
    b = {dec(c) for c in common - zero if 240 <= c // 2048 <= 320}
    return sorted(a | b), dict(path=list(path), builds=len(yes))


def main() -> int:
    x, y, n = map(int, sys.argv[1:4])
    cells, info = measure(x, y, n)
    if cells is None:
        print("no corpus build drives D5 from that LE")
        return 1
    json.dump(dict(cells=cells, **info), open(os.path.join(OUT, f"outpath_{x}_{y}_{n}.json"), "w"))
    print(f"LE X{x}Y{y}N{n} -> D5: {len(cells)} cells from {info['builds']} corpus builds; path {' -> '.join(info['path'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
