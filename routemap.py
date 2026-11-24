#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map routing switches (PIPs from routes.py) to configuration bits.

Corpus: builds with a route.json (timing-report hops).  For each PIP (from-node -> to-node, exact
coordinates) used in at least MIN_USES builds:
  candidates = bits set in every build that uses the PIP, minus bits set in any build that doesn't.
That leaves the PIP's own select bits (or a bundle, when PIPs always occur together).

  routemap.py stats              corpus size, node types, PIP reuse
  routemap.py exact [MIN_USES]   per-PIP candidate bits (exact coordinates)
  routemap.py cv                 5-fold cross-validation of the cleaned table
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
NODE = re.compile(r"([A-Z0-9_]+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?(?::(\w+))?$")
FIRST, LAST = 37, 2003


def node(s: str):
    m = NODE.match(s)
    if not m:
        return None
    t, x, y, n, i, port = m.groups()
    if port:                                   # a cell input: the index is "slot.port", e.g. 16.datac
        return t, int(x), int(y), int(n), f"{n}.{port}"
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


def lut_rel():
    """LUT-cell positions of all 16 LEs relative to a LAB's N0 frame and row index (identical for every LAB)."""
    import lutpos
    f0, l0 = _col_frame(10), _row_index(10)
    out = {(f - f0, p + lutpos.PLANE_START[b] - l0) for n in range(0, 32, 2) for f, p, b in lutpos._predict_phys(10, 10, n)}
    for slot in (0, 2):                                       # LE-anchored keys: the LE's own LUT cells, both parities
        f1, l1 = le_anchor(10, 10, slot)
        out |= {(f - f1, p + lutpos.PLANE_START[b] - l1) for f, p, b in lutpos._predict_phys(10, 10, slot)}
    return out


def key(p):
    u, v = node(p[0]), node(p[1])
    if not u or not v:
        return None
    return (u[0], u[4], u[1] - v[1], u[2] - v[2], v[0], v[4]), (v[1], v[2])


def key2(p):
    """key plus both candidate anchors: the to-node's (x, y) and the from-node's (x, y).  A LUT input (LCCOMB
    "slot.port") is pooled over LE slots of the same parity, anchored at that LE's own LUT position (x, y, slot)."""
    u, v = node(p[0]), node(p[1])
    if not u or not v:
        return None
    if v[0] == "LCCOMB" and isinstance(v[4], str):
        slot, port = v[4].split(".")
        par = "odd" if (int(slot) // 2) % 2 else "even"
        return ((u[0], u[4], u[1] - v[1], u[2] - v[2], "LCCOMB", f"{par}.{port}"),
                {"to": (v[1], v[2], int(slot)), "from": (u[1], u[2])})
    return (u[0], u[4], u[1] - v[1], u[2] - v[2], v[0], v[4]), {"to": (v[1], v[2]), "from": (u[1], u[2])}


def _driven_key(K, anchors):
    """(type, index, x, y) of the hop's destination as recorded in a build's driven set; LE-anchored LUT-input keys
    are pooled ("even.datad"), so their destination is the concrete slot's port."""
    to = anchors["to"]
    if len(to) == 3:
        return K[4], f"{to[2]}.{K[5].split('.', 1)[1]}", to[0], to[1]
    return K[4], K[5], to[0], to[1]


def le_anchor(x: int, y: int, slot: int):
    """(column frame, row-space index of the LE's lowest LUT byte) for an LE-anchored key."""
    import lutpos
    c = lutpos._predict_phys(x, y, slot)
    return min(f for f, _, _ in c), min(p + lutpos.PLANE_START[b] for _, p, b in c)


def pooled(min_inst: int = 3, fw: int = 40, lw: int = 160, max_bg: float = 0.1, train=None, _cache={}):
    """Translation-pooled candidate bits per PIP key, relative to the destination node's column frame and row."""
    import random
    import bisect
    if "data" not in _cache:
        items = corpus()
        data = []
        for _, ps, buf in items:                              # per build: frame -> sorted row-space indices
            byf = collections.defaultdict(list)
            for f, l in rel_ones(buf):
                byf[f].append(l)
            data.append((ps, {f: sorted(v) for f, v in byf.items()}))
        del items
        _cache["data"] = data
    data = _cache["data"]
    use = set(range(len(data))) if train is None else set(train)
    inst = collections.defaultdict(list)
    for k, (ps, _) in enumerate(data):
        if k not in use:
            continue
        for p in ps:
            kk = key2(p)
            if kk:
                inst[kk[0]].append((k, kk[1]))
    cf, ri = {}, {}

    def rel(k, anchor):
        if len(anchor) == 3:                                  # LE-anchored (LUT inputs)
            try:
                f0, l0 = le_anchor(*anchor)
            except ValueError:
                return None
            out = set()
            byf = data[k][1]
            for f in range(f0 - fw, f0 + fw + 1):
                v = byf.get(f)
                if v:
                    for l in v[bisect.bisect_left(v, l0 - lw):bisect.bisect_right(v, l0 + lw)]:
                        out.add((f - f0, l - l0))
            return out
        x, y = anchor
        if x not in cf:
            cf[x] = _col_frame(x)
        if y not in ri:
            ri[y] = _row_index(y)
        if cf[x] is None or ri[y] is None:
            return None
        f0, l0 = cf[x], ri[y]
        out = set()
        byf = data[k][1]
        for f in range(f0 - fw, f0 + fw + 1):
            v = byf.get(f)
            if v:
                for l in v[bisect.bisect_left(v, l0 - lw):bisect.bisect_right(v, l0 + lw)]:
                    out.add((f - f0, l - l0))
        return out
    rnd = random.Random(1)
    # per build: driven to-nodes (type, index, x, y), for the "same wire undriven" background
    driven = []
    for ps, _ in data:
        d = set()
        for p in ps:
            v = node(p[1])
            if v:
                d.add((v[0], v[4], v[1], v[2]))
        driven.append(d)
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
            pool = sorted(use)
            for _ in range(40):                               # background: same anchors in builds without this key
                k = pool[rnd.randrange(len(pool))]
                a = lst[rnd.randrange(len(lst))][1]
                if (k, a) in used:
                    continue
                r = rel(k, a)
                if r is not None:
                    bg.append(r)
            cand = sorted(c for c in common if sum(c in r for r in bg) <= max_bg * max(len(bg), 1))
            if True:                                          # always prefer the "same wire undriven" background,
                # which keeps a mux's group bit (shared with other sources into the same wire)
                # mux bits shared by other sources into the same wire: use builds where that wire is undriven
                bg2 = []
                for k, a0 in lst0[:1] + [lst0[rnd.randrange(len(lst0))] for _ in range(3)]:
                    vk = _driven_key(K, a0)
                    for kk in rnd.sample(pool, min(60, len(pool))):
                        if vk in driven[kk]:
                            continue
                        r = rel(kk, a0[side])
                        if r is not None:
                            bg2.append(r)
                if len(bg2) >= 10:
                    cand = sorted(c for c in common if sum(c in r for r in bg2) <= max_bg * max(len(bg2), 1))
            score = (1 <= len(cand) <= 4, -len(cand) if cand else -99)
            if best is None or score > best[0]:
                best = (score, side, len(rels), cand)
        if best:
            res[K] = (best[2], best[3], best[1])
    pooled.rel, pooled.data = rel, data
    # keys whose bits depend on a position phase: split by row / column parity of the anchor
    lut = lut_rel()
    for K, lst0 in inst.items():
        r0 = res.get(K)
        if len(lst0) < 2 * min_inst or (r0 and 1 <= len([c for c in r0[1] if tuple(c) not in lut]) <= 4):
            continue
        for side in ("to", "from"):
            for ax in (1, 0):                                  # 1: row parity, 0: column parity
                groups = collections.defaultdict(list)
                for k, a in lst0:
                    groups[a[side][ax] % 2].append((k, a[side]))
                if len(groups) < 2 or min(len(g) for g in groups.values()) < min_inst:
                    continue
                sub = {}
                for g, lst in groups.items():
                    rels = [r for r in (rel(k, a) for k, a in lst) if r is not None]
                    if len(rels) < min_inst:
                        break
                    common = set.intersection(*rels)
                    bg = []
                    vk = _driven_key(K, lst0[0][1])
                    for kk in rnd.sample(sorted(use), min(80, len(use))):
                        if vk in driven[kk]:
                            continue
                        r = rel(kk, lst[0][1])
                        if r is not None:
                            bg.append(r)
                    cand = sorted(c for c in common if sum(c in r for r in bg) <= max_bg * max(len(bg), 1)
                                  and c not in lut)
                    if not 1 <= len(cand) <= 4:
                        break
                    sub[g] = (len(rels), cand)
                else:
                    if len(sub) == len(groups):
                        tag = ("ty" if ax else "tx") if side == "to" else ("fy" if ax else "fx")
                        for g, (m, cand) in sub.items():
                            res[K + ((tag, g),)] = (m, cand, side)
                        break
            else:
                continue
            break
    return res


def crossval(folds: int = 5):
    """k-fold CV of the cleaned table: held-out uses (all predicted bits set?) and non-uses (bits absent?)."""
    import random
    lut = lut_rel()
    pooled(train=[])                                          # load the corpus once
    data, n = pooled.data, len(pooled.data)
    idx = list(range(n))
    random.Random(3).shuffle(idx)
    tot = collections.Counter()
    for fi in range(folds):
        test = set(idx[fi::folds])
        res = pooled(train=[k for k in range(n) if k not in test])
        rel = pooled.rel
        table = {K: (side, [tuple(c) for c in cand if tuple(c) not in lut]) for K, (m, cand, side) in res.items()}
        table = {K: v for K, v in table.items() if 1 <= len(v[1]) <= 4}
        users = collections.defaultdict(set)
        for k in test:
            for p in data[k][0]:
                kk = key2(p)
                if kk and kk[0] in table:
                    users[kk[0]].add((k, kk[1][table[kk[0]][0]]))
        anchors = collections.defaultdict(set)
        for k in range(n):
            if k in test:
                continue
            for p in data[k][0]:
                kk = key2(p)
                if kk and kk[0] in table:
                    anchors[kk[0]].add(kk[1][table[kk[0]][0]])
        for K, (side, cand) in table.items():
            nb = res[K][0]
            bucket = "3-5" if nb <= 5 else "6-10" if nb <= 10 else "11-20" if nb <= 20 else ">20"
            for k, a in users[K]:
                r = rel(k, a)
                if r is None:
                    continue
                tot["pos"] += 1
                tot["pos_ok"] += all(c in r for c in cand)
                tot[("pos", bucket)] += 1
                tot[("pos_ok", bucket)] += all(c in r for c in cand)
            al = sorted(anchors[K])
            for k in list(test)[:60]:
                if not al:
                    break
                a = al[k % len(al)]
                if (k, a) in users[K]:
                    continue
                r = rel(k, a)
                if r is None:
                    continue
                tot["neg"] += 1
                tot["neg_clean"] += not all(c in r for c in cand)
                tot[("neg", bucket)] += 1
                tot[("neg_clean", bucket)] += not all(c in r for c in cand)
        tot["keys"] += len(table)
        print(f"  fold {fi}: {len(table)} keys", flush=True)
    print(f"{folds}-fold CV over {n} builds: keys/fold {tot['keys'] / folds:.0f}; held-out uses with all predicted bits "
          f"{tot['pos_ok']}/{tot['pos']} = {tot['pos_ok'] / max(tot['pos'], 1):.2%}; held-out non-uses clean "
          f"{tot['neg_clean']}/{tot['neg']} = {tot['neg_clean'] / max(tot['neg'], 1):.2%}")
    for b in ("3-5", "6-10", "11-20", ">20"):
        print(f"  training instances {b:5s}: uses complete {tot[('pos_ok', b)]}/{tot[('pos', b)]} = "
              f"{tot[('pos_ok', b)] / max(tot[('pos', b)], 1):.1%}; non-uses clean {tot[('neg_clean', b)]}/{tot[('neg', b)]} = "
              f"{tot[('neg_clean', b)] / max(tot[('neg', b)], 1):.1%}")


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
        lut = lut_rel()
        clean = {repr(k): [n, [c for c in cand if tuple(c) not in lut], side] for k, (n, cand, side) in res.items()}
        clean = {k: v for k, v in clean.items() if 1 <= len(v[1]) <= 4}
        json.dump(clean, open(os.path.join(OUT, "routemap_clean.json"), "w"))
        print(f"{len(clean)} keys with 1-4 bits after removing LUT-cell positions -> out/routemap_clean.json")
        anchors = collections.Counter(v[2] for v in res.values() if 1 <= len(v[1]) <= 4)
        print("anchor used by keys with 1-4 bits:", dict(anchors))
        for k, (n, c, side) in sorted(res.items(), key=lambda kv: (len(kv[1][1]) == 0, -kv[1][0]))[:20]:
            print(f"  {k}  n={n} [{side}]: {c}")
    elif cmd == "cv":
        crossval()
    elif cmd == "exact":
        res, n = exact(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
        sizes = collections.Counter(len(v) for v in res.values())
        print(f"{n} builds, {len(res)} PIPs with enough uses; candidate-set sizes: {sorted(sizes.items())}")
        for p, v in sorted(res.items(), key=lambda kv: len(kv[1]))[:25]:
            print(f"  {p[0]:34s} -> {p[1]:34s} {[cell(b) for b in v]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
