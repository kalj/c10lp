#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Learn the LAB control mux codes from out/ctlcorpus.json (M3a).

Per (line k, slot j): the cells of the band (frames -12..-2, rows -35..-28 from LE N0) set in every build with that
hop, after peeling the other hop's code in the same build, minus the background set in nearly every build.  Slots 0
and 2 (and 1 and 3) mirror each other in rows (r -> -63 - r); checked on every line seen in both.
Output: out/ctlmux.json {"k|j": [[frame, row], ...], "_background": [...], "_mirror_checked": n}

  ctllearn.py
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "out")
MIRROR = {0: 2, 2: 0, 1: 3, 3: 1}


def main() -> int:
    r = json.load(open(os.path.join(OUT, "ctlcorpus.json")))
    builds = [[((k, j), frozenset(map(tuple, c))) for k, j, c in rows] for rows in r.values() if rows]
    allc = collections.Counter(c for b in builds for c in frozenset.union(*(s for _p, s in b)))
    bg = {c for c, n in allc.items() if n >= 0.9 * len(builds)}
    by = collections.defaultdict(list)
    for b in builds:
        for p, s in b:
            by[p].append(s - bg)
    code = {p: frozenset.intersection(*v) for p, v in by.items()}
    # row -31 holds no line code (it sits between the mirrored row pairs -29/-30 and -33/-34): its cells, e.g.
    # (-12, -31), follow the pin clock's own slot-1 hop and stay as strays in the intersections
    by = {p: [s_ - {c for c in s_ if c[1] == -31} for s_ in v] for p, v in by.items()}
    code = {p: frozenset.intersection(*v) for p, v in by.items()}
    for _ in range(3):                       # peel the other hop's code
        new = {}
        for p in by:
            sets = []
            for b in builds:
                d = dict(b)
                if p not in d:
                    continue
                s = frozenset(c for c in d[p] - bg if c[1] != -31)
                for q in d:
                    if q != p and len(by[q]) >= 3:
                        s = (s - code[q]) | (s & code[q] & code[p])
                    # the pin clock's own code (line 6 -> slot 1, in nearly every ffe2 build) is never kept in another
                    # hop's code: its (-9, -29) stayed in 7|2 and 10|2 (rd118 / rd122: Quartus doesn't set it there)
                    if q == (6, 1) and q != p:
                        s = s - code[q]
                sets.append(s)
            new[p] = frozenset.intersection(*sets)
        code = new
    mir = lambda cs: frozenset((f, -63 - row) for f, row in cs)
    ok = bad = 0
    for (k, j), cs in code.items():
        q = (k, MIRROR[j])
        if q in code and len(by[(k, j)]) >= 2 and len(by[q]) >= 2 and j < MIRROR[j]:
            if mir(cs) == code[q]:
                ok += 1
            else:
                bad += 1
                print(f"  mirror differs: line {k} slot {j} {sorted(cs)} vs slot {q[1]} {sorted(code[q])}")
    out = {f"{k}|{j}": sorted(cs) for (k, j), cs in code.items() if len(by[(k, j)]) >= 2}
    mirrored = []
    for (k, j), cs in code.items():          # mirrored entries where only one slot was seen (at least 2 builds)
        q = f"{k}|{MIRROR[j]}"
        if len(by[(k, j)]) >= 2 and q not in out:
            out[q] = sorted(mir(cs))
            mirrored.append(q)
    n_mir = len(mirrored)
    # a mirrored code gives the cells, not legality: Quartus refused line 6 -> slot 0 (mirrored from 6|2) at X7Y6.
    # Routing uses only the observed pairs; the mirrored ones stay for reference
    out.update({"_background": sorted(bg), "_mirror_checked": [ok, bad], "_mirrored": sorted(mirrored)})
    json.dump(out, open(os.path.join(OUT, "ctlmux.json"), "w"), indent=0)
    print(f"{len(builds)} builds; background {sorted(bg)}; mirror ok {ok}, differs {bad}; "
          f"{sum(1 for k in out if not k.startswith('_'))} (line, slot) codes ({n_mir} by mirror) -> out/ctlmux.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
