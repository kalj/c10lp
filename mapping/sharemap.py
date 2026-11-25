#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What changes when two LUT inputs select the same local source? (xdev design "mux4d", data only)

dst's ports are (t0, t0, t1, t2): two physical inputs share source 0.  For each build
the actual select region (dst bytes 0..3, frames -12..-2) is compared with the
li_local_table.json prediction (union of each input's entry), grouped by which pair
of physical inputs shares the source.

  sharemap.py
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import mux1cmap  # noqa: E402
import xdev  # noqa: E402


def main() -> int:
    import mux4d_plan
    T = {tuple(map(int, k.split(","))): set(map(tuple, v))
         for k, v in json.load(open(os.path.join(HERE, "data", "li_local_table.json")))["entries"].items()}
    stats = collections.defaultdict(lambda: collections.Counter())
    diffs = collections.defaultdict(collections.Counter)
    for j in mux4d_plan.jobs():
        _, sd, srcs = j.design.split(":")
        d, srcs = int(sd), [int(v) for v in srcs.split("-")]
        x, y, _ = j.loc
        buf = xdev.load(os.path.join(HERE, "out"), j.name)
        perm = mux1cmap.perm_of(buf, x, y, d)
        if perm is None:
            stats["?"]["no unique input order"] += 1
            continue
        src_of = {perm[0]: srcs[0], perm[1]: srcs[0], perm[2]: srcs[1], perm[3]: srcs[2]}
        pair = tuple(sorted((perm[0], perm[1])))
        if not all((p, s) in T for p, s in src_of.items()):
            stats[pair]["entry missing in table"] += 1
            continue
        want = set().union(*(T[(p, s)] for p, s in src_of.items()))
        got = mux1cmap.region(buf, x, y, d)
        if got == want:
            stats[pair]["matches the table"] += 1
        else:
            stats[pair]["differs"] += 1
            diffs[(pair, srcs[0])][(frozenset(got - want), frozenset(want - got))] += 1
    for pair in sorted(stats, key=str):
        print(f"  inputs {pair} share a source: " + ", ".join(f"{k} {v}" for k, v in stats[pair].items()))
    print("\n  differences (extra bits Quartus set, table bits it left out), per shared pair and source:")
    for (pair, s), c in sorted(diffs.items()):
        for (extra, missing), n in c.most_common(2):
            print(f"    inputs {pair}, source {s:2d}: +{sorted(extra)} -{sorted(missing)}  x{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
