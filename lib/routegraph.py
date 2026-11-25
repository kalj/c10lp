#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-wide routing graph from the pooled PIP table, a router over it, and a route writer.

The clean keys of out/routemap_clean.json (routing_pips.json) are instantiated at every position
where both end nodes fall inside the coordinate range seen for their types and the anchor has a
column frame and a row.  Each PIP instance carries its absolute bits (frame, byte, plane).

  routegraph.py stats                         graph size
  routegraph.py route SRC DST                 shortest known-PIP path, e.g.
                                              LCCOMB_X10_Y10_N4  LCCOMB_X14_Y12_N16:datac
"""
from __future__ import annotations

import ast
import collections
import heapq
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import lutpos  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
PLANE_OF = sorted(lutpos.PLANE_START.items(), key=lambda kv: kv[1])     # (plane, start), ascending start


def cell_of(frame: int, L: int):
    """(frame, byte, plane) of a row-space index L = byte + PLANE_START[plane].  Plane starts are 251-252 apart, so an
    index near a boundary has two spellings; byte 0 is the frame marker and never holds configuration, so the cell is
    the one with byte 1..252 (blind reroutes at X27Y11 failed writing byte 0 of plane 4 for byte 251 of plane 5)."""
    for plane, start in reversed(PLANE_OF):
        if L >= start:
            byte = L - start
            if byte == 0:
                continue                                  # use the lower plane's top byte
            return (frame, byte, plane) if 1 <= byte <= 252 else None
    return None


def name(t, x, y, i):
    if isinstance(i, str):                                   # LUT input "slot.port"
        n, port = i.split(".")
        return f"{t}_X{x}_Y{y}_N{n}:{port}"
    if t == "LCCOMB":
        return f"{t}_X{x}_Y{y}_N{i}"
    return f"{t}_X{x}_Y{y}_N0_I{i}"


class Graph:
    def __init__(self, table: str = os.path.join(OUT, "routemap_clean.json"), min_inst: int = 0):
        raw = {ast.literal_eval(k): v for k, v in json.load(open(table)).items()}
        raw = {k: v for k, v in raw.items() if v[0] >= min_inst}      # keep well-supported switch types only
        items = R.corpus()
        rng = collections.defaultdict(lambda: [99, -1, 99, -1])
        for _, ps, _ in items:                               # coordinate range per node type
            for p in ps:
                for s in p:
                    n = R.node(s)
                    if n:
                        r = rng[n[0]]
                        r[0], r[1], r[2], r[3] = min(r[0], n[1]), max(r[1], n[1]), min(r[2], n[2]), max(r[3], n[2])
        self.rng = dict(rng)
        cols = [x for x in range(0, 45) if R._col_frame(x) is not None]
        rows = sorted(lutpos.ROW)
        self.edges = collections.defaultdict(list)           # from-node -> [(to-node, bits)]
        self.npips = 0
        for K, (n, rel, side) in raw.items():
            phase = None
            if len(K) == 7:
                phase = K[6]
                K = K[:6]
            ft, fi, dx, dy, tt, ti = K
            if ft not in self.rng or tt not in self.rng or (ft == "LCCOMB" and tt == "LCCOMB"):
                continue                                     # (LUT input -> its own output is not a switch)
            if tt == "LCCOMB" and isinstance(ti, str):       # LE-anchored LUT-input key: every slot of that parity
                par, port = ti.split(".")
                slots = [n2 for n2 in range(0, 32, 2) if ((n2 // 2) % 2 == 1) == (par == "odd")]
                for x in range(self.rng[tt][0], self.rng[tt][1] + 1):
                    for y in range(self.rng[tt][2], self.rng[tt][3] + 1):
                        fx, fy = x + dx, y + dy
                        for sl in slots:
                            try:
                                f0, l0 = R.le_anchor(x, y, sl) if side == "to" else (R._col_frame(fx), R._row_index(fy))
                            except ValueError:
                                continue
                            if f0 is None or l0 is None:
                                continue
                            bits = [cell_of(f0 + f, l0 + l) for f, l in rel]
                            if any(b is None for b in bits):
                                continue
                            self.edges[name(ft, fx, fy, fi)].append((f"LCCOMB_X{x}_Y{y}_N{sl}:{port}", tuple(bits)))
                            self.npips += 1
                continue
            for x in range(self.rng[tt][0], self.rng[tt][1] + 1):
                fx = x + dx
                if not self.rng[ft][0] <= fx <= self.rng[ft][1]:
                    continue
                for y in range(self.rng[tt][2], self.rng[tt][3] + 1):
                    fy = y + dy
                    if not self.rng[ft][2] <= fy <= self.rng[ft][3]:
                        continue
                    ax, ay = (x, y) if side == "to" else (fx, fy)
                    if phase:
                        tag, g = phase
                        v = {"ty": y, "tx": x, "fy": fy, "fx": fx}[tag]
                        if v % 2 != g:
                            continue
                    if ax not in cols or ay not in rows:
                        continue
                    f0, l0 = R._col_frame(ax), R._row_index(ay)
                    bits = [cell_of(f0 + f, l0 + l) for f, l in rel]
                    if any(b is None for b in bits):
                        continue
                    fname = name(ft, fx, fy, fi)
                    if ft == "LCCOMB" and fi is None:      # LUT output: slot N drives LE_BUFFER N and N + 1
                        if tt != "LE_BUFFER":
                            continue
                        fname = f"LCCOMB_X{fx}_Y{fy}_N{ti - ti % 2}"
                    self.edges[fname].append((name(tt, x, y, ti), tuple(bits)))
                    self.npips += 1

    def route(self, src: str, dst: str, avoid=frozenset(), max_hops: int = 12):
        """Dijkstra by hop count from src to dst, not entering nodes in avoid.  Returns [(from, to, bits)]."""
        dist, prev, pq = {src: 0}, {}, [(0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, 1e9) or d >= max_hops:
                continue
            for v, bits in self.edges.get(u, ()):
                if v in avoid and v != dst:
                    continue
                if d + 1 < dist.get(v, 1e9):
                    dist[v], prev[v] = d + 1, (u, bits)
                    heapq.heappush(pq, (d + 1, v))
        if dst not in prev:
            return None
        path, v = [], dst
        while v != src:
            u, bits = prev[v]
            path.append((u, v, bits))
            v = u
        return path[::-1]


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    g = Graph()
    if cmd == "stats":
        types = collections.Counter(e.split("_X")[0] for e in g.edges)
        print(f"{g.npips} PIP instances out of {len(g.edges)} driving nodes; from-node types: {dict(types.most_common())}")
    elif cmd == "route":
        path = g.route(sys.argv[2], sys.argv[3])
        if not path:
            print("no route with known PIPs")
            return 1
        for u, v, bits in path:
            print(f"  {u:34s} -> {v:36s} {list(bits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
