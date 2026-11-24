#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-wide switch tables from the exact per-position solves (out/hopsolve.json).

A hop U -> V becomes a switch type
  (U type, U index, V type, V index, V.x - U.x, V.y - U.y, column class)
anchored at
  - V's LAB for LAB-line selects (V = LOCAL_INTERCONNECT): frames -26..+3 of that LAB;
  - U's LAB for drivers (U = LE_BUFFER): frames -30..+30;
  - V's start otherwise (wire -> wire): frames -30..+30;
with bits relative to the anchor (frame - column frame, row-space index - row index) and the column class =
anchor X mod 8: LAB-line selects repeat with an 8-column period (limsolve.rule, leave-one-out 489 exact / 5 differ).
Bits: those in at least half of the instances (an exact solve can miss a bit the mux shares between its inputs).
Hops into LUT inputs and LUT -> LE_BUFFER are left to their own models (routing_pips, le_output_select).

  switchmodel.py build | check JOBS.json
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
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
NODE = re.compile(r"^(\w+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?$")
PERIOD = {"select": 8, "driver": 1, "wire": 8}       # column-class period per kind (held-out: drivers need none)


def kind(key) -> str:
    return "select" if key[2] == "LOCAL_INTERCONNECT" else "driver" if key[0] == "LE_BUFFER" else "wire"


def parse(n: str):
    m = NODE.match(n.split(":")[0])
    if not m:
        return None
    t, x, y, nn, i = m.groups()
    return t, int(x), int(y), int(i) if i is not None else int(nn)


def typ(u: str, v: str):
    """(key without class, anchor (x, y), frame window) of a hop, or None if it isn't modelled here."""
    pu, pv = parse(u), parse(v)
    if not pu or not pv or pv[0] == "LCCOMB" or pu[0] == "LCCOMB":
        return None
    k = (pu[0], pu[3], pv[0], pv[3], pv[1] - pu[1], pv[2] - pu[2])
    if pv[0] == "LOCAL_INTERCONNECT":
        return k, (pv[1], pv[2]), (-26, 3)
    if pu[0] == "LE_BUFFER":
        return k, (pu[1], pu[2]), (-30, 30)
    return k, (pv[1], pv[2]), (-30, 30)


def anchor(ax, ay):
    f0, l0 = R._col_frame(ax), R._row_index(ay)
    return (f0, l0) if f0 is not None and l0 is not None else None


def build(min_inst: int = 2):
    hs = json.load(open(os.path.join(OUT, "hopsolve.json")))
    inst = collections.defaultdict(list)
    for k, (ny, _nn, bits) in hs.items():
        if ny < 2:
            continue
        u, v = k.split("->")
        t = typ(u, v)
        if not t:
            continue
        key, (ax, ay), (lo, hi) = t
        a = anchor(ax, ay)
        if a is None:
            continue
        rel = frozenset((f - a[0], p + lutpos.PLANE_START[b] - a[1]) for f, p, b in bits
                        if lo <= f - a[0] <= hi and abs(p + lutpos.PLANE_START[b] - a[1]) < 120)
        if rel:
            inst[key + (ax % PERIOD[kind(key)],)].append(rel)
    table = {}
    for key, lst in inst.items():
        if len(lst) < min_inst:
            continue
        cnt = collections.Counter(b for r in lst for b in r)
        bits = sorted(b for b, c in cnt.items() if 2 * c >= len(lst))
        agree = sum(r == frozenset(bits) for r in lst) / len(lst)
        if bits:
            table[repr(key)] = [len(lst), round(agree, 2), bits]
    json.dump(table, open(os.path.join(OUT, "switchmodel.json"), "w"), indent=0)
    return table


class Model:
    def __init__(self, path: str = os.path.join(OUT, "switchmodel.json")):
        import ast
        self.t = {ast.literal_eval(k): v for k, v in json.load(open(path)).items()}
        self.by_from = collections.defaultdict(list)     # (U type, U index, class) -> keys
        for k in self.t:
            self.by_from[(k[0], k[1])].append(k)

    def bits(self, u: str, v: str, min_inst: int = 2):
        """Absolute (frame, byte, plane) bits of hop u -> v, or None if the model has no such switch type."""
        t = typ(u, v)
        if not t:
            return None
        key, (ax, ay), _w = t
        e = self.t.get(key + (ax % PERIOD[kind(key)],))
        a = anchor(ax, ay)
        if not e or e[0] < min_inst or a is None:
            return None
        out = [G.cell_of(a[0] + f, a[1] + l) for f, l in e[2]]
        return None if None in out else out

    def fanout(self, u: str, min_inst: int = 2):
        """Hops u -> v the model knows, as (v, bits)."""
        pu = parse(u)
        if not pu:
            return []
        res = []
        for k in self.by_from.get((pu[0], pu[3]), []):
            _ft, _fi, vt, vi, dx, dy, _c = k
            x, y = pu[1] + dx, pu[2] + dy
            v = f"{vt}_X{x}_Y{y}_N0_I{vi}"
            b = self.bits(u, v, min_inst)
            if b:
                res.append((v, b))
        return res


def check(jobs_file: str):
    """Held-out check: for every modelled hop of each build, are all predicted bits set (uses)?  And for model
    hops from the same U into nodes the build leaves unused, are they all clear (non-uses)?"""
    import routes
    import xdev
    m = Model()
    c = collections.Counter()
    for name in json.load(open(jobs_file)):
        buf = xdev.load(OUT, name)
        hops = routes.pips(json.load(open(os.path.join(OUT, name + ".route.json"))))
        used = {n for h in hops for n in h}
        on = lambda cell: buf[32 + cell[0] * 255 + cell[1]] >> cell[2] & 1
        for u, v in hops:
            t = typ(u, v)
            if not t:
                continue
            kd = kind(t[0])
            b = m.bits(u, v)
            if b is None:
                c[f"{kd}: no type"] += 1
                continue
            c[f"{kd}: use, all bits set" if all(map(on, b)) else f"{kd}: use, bits missing"] += 1
            for v2, b2 in m.fanout(u):
                if v2 not in used and v2 != v:
                    c[f"{kd}: non-use, all clear" if not any(map(on, b2)) else f"{kd}: non-use, some set"] += 1
    for k in sorted(c):
        print(f"  {k:32s} {c[k]}")
    return c


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        t = build()
        kinds = collections.Counter(kind(k) for k in map(eval, t))
        print(f"{len(t)} switch types (with column class):", dict(kinds))
    elif cmd == "check":
        check(sys.argv[2])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
