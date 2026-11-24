#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Solve LAB-input-mux bits exactly per LAB, from the xrk line-forcing corpus (out/xrk_jobs.json).

For each destination LAB, with builds b, the set H_b of (wire W -> LAB line L) hops into that LAB
(timing report), and the set bits S_b in the LAB's frames (column frame - 26 .. + 2):
  select(W, L) = bits set in every build with W -> L, and in no build where L is fed otherwise or undriven
  tap(W)       = bits set in every build where W enters the LAB (any line), and in no build where it doesn't
Bits are reported relative to the LAB (frame - column frame, row-space index - row index).

  limsolve.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpos  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")


def solve():
    jobs = json.load(open(os.path.join(OUT, "xrk_jobs.json")))
    by_lab = collections.defaultdict(list)
    for name in jobs:
        m = re.search(r"xrk-(-?\d+)_(-?\d+)_(\d+)_X(\d+)Y(\d+)__", name)
        dx, dy, _seed, x, y = map(int, m.groups())
        by_lab[(x + dx, y + dy)].append(name)
    out = {}
    for (X, Y), names in sorted(by_lab.items()):
        f0, l0 = R._col_frame(X), R._row_index(Y)
        pre = f"LOCAL_INTERCONNECT_X{X}_Y{Y}_"
        builds = []
        for n in names:
            res = json.load(open(os.path.join(OUT, n + ".route.json")))
            hops = {(u, v) for u, v in routes.pips(res) if v.startswith(pre)}
            buf = xdev.load(OUT, n)
            s = set()
            for f in range(f0 - 26, f0 + 3):
                base = 32 + f * 255
                for p, val in enumerate(buf[base:base + 253]):
                    if val:
                        for b in range(8):
                            if val >> b & 1:
                                s.add((f - f0, p + lutpos.PLANE_START[b] - l0))
            builds.append((hops, s))
        sel, tap = {}, {}
        pairs = {h for hb, _ in builds for h in hb}
        for W, L in pairs:
            yes = [s for hb, s in builds if (W, L) in hb]
            no = [s for hb, s in builds if (W, L) not in hb and not any(v == L and u == W for u, v in hb)]
            sel[(W, L)] = (len(yes), sorted(set.intersection(*yes) - set().union(*no)))
        for W in {w for w, _ in pairs}:
            yes = [s for hb, s in builds if any(u == W for u, _ in hb)]
            no = [s for hb, s in builds if not any(u == W for u, _ in hb)]
            tap[W] = (len(yes), sorted(set.intersection(*yes) - set().union(*no)) if no else None)
        out[(X, Y)] = dict(builds=len(builds), select=sel, tap=tap)
    return out


def main() -> int:
    res = solve()
    for (X, Y), r in res.items():
        print(f"LAB X{X}Y{Y}: {r['builds']} builds, {len(r['select'])} (wire, line) pairs, {len(r['tap'])} wires")
        sizes = collections.Counter(len(v[1]) for v in r["select"].values() if v[0] >= 2)
        print("   select-bit set sizes (pairs seen >= 2x):", sorted(sizes.items()))
        frames = collections.Counter(f for v in r["select"].values() if v[0] >= 2 for f, _ in v[1])
        print("   frames of select bits:", sorted(frames.items()))
        tf = collections.Counter(f for v in r["tap"].values() if v[1] for f, _ in v[1])
        print("   frames of tap bits:", sorted(tf.items()))
    json.dump({f"X{X}Y{Y}": {"builds": r["builds"],
                            "select": {f"{w}->{l}": v for (w, l), v in r["select"].items()},
                            "tap": {w: v for w, v in r["tap"].items()}} for (X, Y), r in res.items()},
              open(os.path.join(OUT, "limsolve.json"), "w"), indent=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
