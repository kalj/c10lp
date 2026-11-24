#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Position-specific LUT-input select codes, measured from Quartus builds of *other* designs at the same LEs.

The general LUT-input tables (li_local_table.json, routing_pips LE-anchored keys) don't hold at every position (LAB-line
codes vary with the LAB; li_local_table matches about 60% of corpus cases).  For a fixed placement, the codes at its LEs
can be measured directly: compile variants of the design with other LUT masks (Quartus then picks other ports and
lines), back-annotate their routing (.rcf), and read each LUT input's code from that input's own cells
(limux.input_cells).  Keyed (X, Y, N, physical input, source node); conflicting samples are dropped.
Output: out/posmux_NAME.json, and out/placement_NAME.json: core cells with the same value in every variant and a
different one in the all-zero design (the placement's fixed configuration), used by asm.py only where no model decides.

  posmux.py NAME VARIANTS.json
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import limux  # noqa: E402
import rcfforce as F  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfvar")


def measure(names: list[str]):
    cells = limux.input_cells()
    seen = collections.defaultdict(collections.Counter)
    for name in names:
        work = os.path.join(ROOT, "work", name)
        rcf = open(os.path.join(work, "base.rcf")).read()
        buf = open(os.path.join(work, "base.rbf"), "rb").read()
        locs = {}
        for ln in open(os.path.join(work, "fuzz.qsf"), errors="replace"):
            m = re.search(r'LCCOMB_X(\d+)_Y(\d+)_N(\d+) -to "?([^"\s]+)', ln)
            if m:
                locs[m.group(4)] = tuple(map(int, m.groups()[:3]))
        for sig, bl in F.branches(rcf).items():
            for path, (d, lp, pp) in bl:
                loc = locs.get(d) or locs.get(re.sub(r"\[(\d+)\]", r"\1", d))
                if not loc or not path or pp.lower() not in limux.PHYS:
                    continue
                inp = limux.PHYS[pp.lower()]
                seen[(*loc, inp, path[-1])][limux.code(buf, *loc, cells[inp])] += 1
    return seen


def constant_bits(names: list[str]):
    """Core cells with the same value in every variant build and a different value in the all-zero design: the
    placement's fixed configuration (clock tree, LAB clock selects, register bits ...), measured from other designs."""
    import explain
    zero = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    bufs = [open(os.path.join(ROOT, "work", n, "base.rbf"), "rb").read() for n in names]
    common = None
    for b in bufs:
        d = {c: b[32 + c[0] * 255 + c[1]] >> c[2] & 1 for c in explain.core_diff(zero, b)}
        common = d if common is None else {c: v for c, v in common.items() if c in d and d[c] == v}
    return common or {}


def main() -> int:
    name, vf = sys.argv[1], sys.argv[2]
    cb = constant_bits(json.load(open(vf)))
    json.dump([[*c, v] for c, v in sorted(cb.items())], open(os.path.join(OUT, f"placement_{name}.json"), "w"))
    print(f"{len(cb)} core cells constant across the variants (and different from the all-zero design)")
    seen = measure(json.load(open(vf)))
    table = {"|".join(map(str, k)): sorted(next(iter(c))) for k, c in seen.items() if len(c) == 1}
    conf = sum(len(c) > 1 for c in seen.values())
    json.dump(table, open(os.path.join(OUT, f"posmux_{name}.json"), "w"), indent=0)
    print(f"{len(seen)} (LE, input, source) keys from {len(json.load(open(vf)))} variant builds: {len(table)} consistent, "
          f"{conf} conflicting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
