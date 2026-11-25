#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Solve LAB-input-mux bits exactly per LAB, from the xrk / xrkn line-forcing corpora (out/xrk*_jobs.json).

For each destination LAB, with builds b, the set H_b of (wire W -> LAB line L) hops into that LAB
(timing report), and the set bits S_b in the LAB's frames (column frame - 26 .. + 2):
  select(W, L) = bits set in every build with W -> L, and in no build where L is unused (so bits that L's
                 mux shares between several inputs are kept: a route must set them too)
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
JOB_FILES = ["xrk_jobs.json", "xrkn_jobs.json", "xrkn_holdout_jobs.json", "xrkn_w2w_jobs.json"]   # holdout 1 joined training after blind round 1; w2w: 7-column spans


def parse(name: str):
    """(x, y, dx, dy) of an xrk / xrkn build name: source LAB (x, y), destination (x + dx, y + dy)."""
    m = re.search(r"xrkn?-(?:\d+_)?(-?\d+)_(-?\d+)_(\d+)_X(\d+)Y(\d+)__", name)
    if "xrkn-" in name:
        m = re.search(r"xrkn-\d+_(-?\d+)_(-?\d+)_(\d+)_X(\d+)Y(\d+)__", name)
    dx, dy, _seed, x, y = map(int, m.groups())
    return x, y, dx, dy


def solve():
    jobs = []
    for f in JOB_FILES:
        if os.path.exists(os.path.join(OUT, f)):
            jobs += json.load(open(os.path.join(OUT, f)))
    by_lab = collections.defaultdict(list)
    for name in jobs:
        x, y, dx, dy = parse(name)
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
            # contrast only against builds where L is unused: bits that L's mux shares between its inputs stay in
            no = [s for hb, s in builds if not any(v == L for _u, v in hb)]
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


WIRE = re.compile(r"(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$")


def rule(path: str = os.path.join(OUT, "limsolve.json"), min_seen: int = 2):
    """Group exact selects by switch type (wire type, index, offset to the LAB, line) and test which anchor makes
    the bits agree across LABs: the destination LAB (as stored) or the wire's own column/row."""
    sol = json.load(open(path))
    groups = collections.defaultdict(list)
    for lab, d in sol.items():
        X, Y = int(lab[1:].split("Y")[0]), int(lab.split("Y")[1])
        f0, l0 = R._col_frame(X), R._row_index(Y)
        for k, (cnt, rel) in d["select"].items():
            w, line = k.split("->")
            m = WIRE.match(w)
            if not m or cnt < min_seen or not rel or not line.startswith("LOCAL_INTERCONNECT"):
                continue
            t, wx, wy, wi = m.group(1), *map(int, m.groups()[1:])
            li = int(line.rsplit("_I", 1)[1])
            fw, lw = R._col_frame(wx), R._row_index(wy)
            absb = [(f0 + f, l0 + l) for f, l in rel]
            groups[(t, wi, wx - X, wy - Y, li)].append(dict(
                lab=(X, Y), dst=tuple(sorted(map(tuple, rel))),
                wire=tuple(sorted((f - fw, l - lw) for f, l in absb)) if fw is not None and lw is not None else None))
    stat = collections.Counter()
    for K, lst in sorted(groups.items()):
        if len(lst) < 2:
            continue
        same_d = len({e["dst"] for e in lst}) == 1
        same_w = None not in [e["wire"] for e in lst] and len({e["wire"] for e in lst}) == 1
        stat[("dst" if same_d else "") + ("+wire" if same_w else "") or "neither"] += 1
        if not same_d:
            print(K, [(e["lab"], e["dst"]) for e in lst])
    print("switch types seen at >= 2 LABs, anchor that makes the bits agree:", dict(stat))
    return groups
