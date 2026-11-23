#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map routing switches (PIPs from routes.py) to configuration bits.

Corpus: builds with a route.json (timing-report hops).  For each PIP (from-node -> to-node, exact
coordinates) used in at least MIN_USES builds:
  candidates = bits set in every build that uses the PIP, minus bits set in any build that doesn't.
That leaves the PIP's own select bits (or a bundle, when PIPs always occur together).

  routemap.py stats              corpus size, node types, PIP reuse
  routemap.py exact [MIN_USES]   per-PIP candidate bits (exact coordinates)
  routemap.py pooled             candidate bits per translation-invariant PIP key (from-type/I/dx/dy ->
                                 to-type/I), relative to the to-node's column frame and row (row-space index)
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
NODE = re.compile(r"([A-Z0-9_]+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?$")
FIRST, LAST = 37, 2003


def node(s: str):
    m = NODE.match(s)
    if not m:
        return None
    t, x, y, n, i = m.groups()
    return t, int(x), int(y), int(n), int(i) if i is not None else None


def ones(buf: bytes) -> set[int]:
    """Set bits of the core frames (CRC bytes excluded), as frame * 2040 + byte * 8 + bit."""
    out = set()
    for f in range(FIRST, LAST):
        base = 32 + f * 255
        fr = buf[base:base + 253]
        for p, v in enumerate(fr):
            if v:
                for b in range(8):
                    if v >> b & 1:
                        out.add(f * 2040 + p * 8 + b)
    return out


def corpus():
    jobs = json.load(open(os.path.join(OUT, "route_corpus_jobs.json")))
    items = []
    for name in jobs:
        rp = os.path.join(OUT, name + ".route.json")
        buf = xdev.load(OUT, name)
        if not os.path.exists(rp) or buf is None:
            continue
        items.append((name, routes.pips(json.load(open(rp))), buf))
    return items


def cell(b: int) -> tuple[int, int, int]:
    return b // 2040, (b % 2040) // 8, b % 8


def exact(min_uses: int = 2):
    items = corpus()
    sets = [(name, ps, ones(buf)) for name, ps, buf in items]
    uses = collections.defaultdict(list)
    for k, (_, ps, _) in enumerate(sets):
        for p in ps:
            uses[p].append(k)
    res = {}
    for p, ks in uses.items():
        if len(ks) < min_uses or not (node(p[1]) and node(p[0])):
            continue
        inter = set.intersection(*(sets[k][2] for k in ks))
        others = set().union(*(sets[k][2] for k in range(len(sets)) if k not in ks))
        res[p] = sorted(inter - others)
    return res, len(sets)


def _col_frame(x: int):
    import lutpos
    for y in range(1, 30):
        try:
            return min(f for f, _, _ in lutpos._predict_phys(x, y, 0))
        except ValueError:
            continue
    return None


def _row_index(y: int):
    import lutpos
    if y not in lutpos.ROW:
        return None
    low, plane = lutpos.ROW[y]
    return low + lutpos.PLANE_START[plane]


def rel_ones(buf: bytes):
    """Set bits as (frame, row-space index L = byte + PLANE_START[bit]), the LUT model's linear row space."""
    import lutpos
    out = set()
    for f in range(FIRST, LAST):
        base = 32 + f * 255
        for p, v in enumerate(buf[base:base + 253]):
            if v:
                for b in range(8):
                    if v >> b & 1:
                        out.add((f, p + lutpos.PLANE_START[b]))
    return out


def key(p):
    u, v = node(p[0]), node(p[1])
    if not u or not v:
        return None
    return (u[0], u[4], u[1] - v[1], u[2] - v[2], v[0], v[4]), (v[1], v[2])


def key2(p):
    """key plus both candidate anchors: the to-node's (x, y) and the from-node's (x, y)."""
    u, v = node(p[0]), node(p[1])
    if not u or not v:
        return None
    return (u[0], u[4], u[1] - v[1], u[2] - v[2], v[0], v[4]), {"to": (v[1], v[2]), "from": (u[1], u[2])}


def pooled(min_inst: int = 3, fw: int = 40, lw: int = 160, max_bg: float = 0.1):
    """Translation-pooled candidate bits per PIP key, relative to the destination node's column frame and row."""
    import random
    items = corpus()
    data = [(ps, rel_ones(buf)) for _, ps, buf in items]
    inst = collections.defaultdict(list)
    for k, (ps, _) in enumerate(data):
        for p in ps:
            kk = key2(p)
            if kk:
                inst[kk[0]].append((k, kk[1]))
    cf, ri = {}, {}

    def rel(k, anchor):
        x, y = anchor
        if x not in cf:
            cf[x] = _col_frame(x)
        if y not in ri:
            ri[y] = _row_index(y)
        if cf[x] is None or ri[y] is None:
            return None
        f0, l0 = cf[x], ri[y]
        return {(f - f0, l - l0) for f, l in data[k][1] if abs(f - f0) <= fw and abs(l - l0) <= lw}
    rnd = random.Random(1)
    res = {}
    for K, lst0 in inst.items():
        if len(lst0) < min_inst:
            continue
        best = None
        for side in ("to", "from"):                           # the switch may sit at either end of the hop
            lst = [(k, a[side]) for k, a in lst0]
            rels = [r for r in (rel(k, a) for k, a in lst) if r is not None]
            if len(rels) < min_inst:
                continue
            common = set.intersection(*rels)
            used = set(lst)
            bg = []
            for _ in range(40):                               # background: same anchors in builds without this key
                k = rnd.randrange(len(data))
                a = lst[rnd.randrange(len(lst))][1]
                if (k, a) in used:
                    continue
                r = rel(k, a)
                if r is not None:
                    bg.append(r)
            cand = sorted(c for c in common if sum(c in r for r in bg) <= max_bg * max(len(bg), 1))
            score = (1 <= len(cand) <= 4, -len(cand) if cand else -99)
            if best is None or score > best[0]:
                best = (score, side, len(rels), cand)
        if best:
            res[K] = (best[2], best[3], best[1])
    return res


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        items = corpus()
        types = collections.Counter()
        reuse = collections.Counter()
        for _, ps, _ in items:
            for a, b in ps:
                for s in (a, b):
                    n = node(s)
                    types[n[0] if n else s.split("_")[0]] += 1
                reuse[(a, b)] += 1
        print(f"{len(items)} builds; node types: {dict(types.most_common())}")
        print("PIP reuse histogram (uses: count):", sorted(collections.Counter(reuse.values()).items()))
    elif cmd == "pooled":
        res = pooled()
        sizes = collections.Counter(len(v[1]) for v in res.values())
        print(f"{len(res)} PIP keys with >= 3 instances; candidate-set sizes: {sorted(sizes.items())}")
        json.dump({repr(k): v for k, v in res.items()}, open(os.path.join(OUT, "routemap_pooled.json"), "w"))
        anchors = collections.Counter(v[2] for v in res.values() if 1 <= len(v[1]) <= 4)
        print("anchor used by keys with 1-4 bits:", dict(anchors))
        for k, (n, c, side) in sorted(res.items(), key=lambda kv: (len(kv[1][1]) == 0, -kv[1][0]))[:20]:
            print(f"  {k}  n={n} [{side}]: {c}")
    elif cmd == "exact":
        res, n = exact(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
        sizes = collections.Counter(len(v) for v in res.values())
        print(f"{n} builds, {len(res)} PIPs with enough uses; candidate-set sizes: {sorted(sizes.items())}")
        for p, v in sorted(res.items(), key=lambda kv: len(kv[1]))[:25]:
            print(f"  {p[0]:34s} -> {p[1]:34s} {[cell(b) for b in v]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
