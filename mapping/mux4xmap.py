#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LUT-input mux selects for sources in *other* LABs (xdev design "mux4x", data only).

Same readout as mux4map.py (dst bytes 0..3, frames -12..-2, odd LEs c -> 3-c),
but the four sources sit in neighbouring LABs, so they arrive on LAB-wide lines
that Quartus allocates.  Questions: is each bit still owned by one physical
input, how many distinct select codes appear per input, and do they overlap the
local-source codes of li_local_table.json?

  mux4xmap.py
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402

MASK = 0x3CEC


def main() -> int:
    import mux4x_plan
    T = json.load(open(os.path.join(HERE, "data", "li_local_table.json")))
    local_codes = {q: {frozenset(map(tuple, v)) for k, v in T["entries"].items() if int(k.split(",")[0]) == q}
                   for q in range(4)}
    for dev, (x, y), pins in mux4x_plan.LABS:
        for d in mux4x_plan.DSTS:
            cells = lutpos._predict_phys(x, y, d)
            f0, lo, bit = min(c[0] for c in cells), min(c[1] for c in cells), cells[0][2]
            flip = (d // 2) % 2
            B = []
            for j in mux4x_plan.jobs():
                if j.dev != dev or j.loc[:2] != (x, y) or not j.design.startswith(f"mux4x:{d}:"):
                    continue
                with open(os.path.join(HERE, "out", j.name + ".rbf"), "rb") as f:
                    buf = f.read()
                on = {c for c in cells if buf[32 + c[0] * 255 + c[1]] >> c[2] & 1}
                hits = [p for p in lutpos.PERMS
                        if {cells[lutpos.permute(i, p)] for i in range(16) if MASK >> i & 1} == on]
                if len(hits) != 1:
                    continue
                srcs = j.design.split(":")[2].split("-")
                src_of = {hits[0][i]: srcs[i] for i in range(4)}
                reg = set()
                for df in range(-12, -1):
                    for c in range(4):
                        dp = c - 2 if flip else c                      # inverse of the column map
                        if buf[32 + (f0 + df) * 255 + lo + dp] >> bit & 1:
                            reg.add((df, c))
                B.append((src_of, reg))
            allb = set().union(*(r for _, r in B))
            owned = collections.defaultdict(set)
            unowned = 0
            for b in allb:
                for q in range(4):
                    by = collections.defaultdict(set)
                    for s, r in B:
                        by[s[q]].add(b in r)
                    if all(len(v) == 1 for v in by.values()):
                        owned[q].add(b)
                        break
                else:
                    unowned += 1
            codes = {q: collections.Counter(frozenset(r & owned[q]) for _, r in B) for q in range(4)}
            print(f"  X{x}Y{y} dst {d:2d}: {len(B)} builds, {len(allb)} bits, {unowned} not owned by one input "
                  f"(source key = LAB offset + slot)")
            for q in range(4):
                cs = codes[q]
                shared = sum(c in local_codes[q] for c in cs)
                print(f"    input {q}: {len(owned[q])} owned bits, {len(cs)} distinct codes, "
                      f"{shared} of them also local-source codes; e.g. {[sorted(c) for c, _ in cs.most_common(3)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
