#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact per-position solve of every routing hop in the line-forcing corpora (xrk / xrkn builds).

For a hop (U -> V) at its absolute position, with builds b, their hops H_b (timing reports, up to 40
paths per input) and their set core bits S_b:
  bits(U -> V) = intersection of S_b over builds with U -> V
                 minus the union of S_b over builds where V is unused (so bits that V's mux shares between its
                 inputs stay; for LUT-input hops: over all builds without U -> V)
                 minus every LUT-cell position (lutpos) and bits farther than WINDOW frames from both ends,
                 and (except for LUT-input hops) minus LE signatures: bits present exactly when an LE is used.
No translation between positions is involved.  Output: out/hopsolve.json
  {"U->V": [n_yes, n_no, [[frame, byte, plane], ...]]}

  hopsolve.py [MIN_NO]
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import limsolve  # noqa: E402
import lutpos  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
PRE, FRAME = 32, 255
WINDOW = 30
POS = re.compile(r"_X(\d+)_Y(\d+)_")


def ones(buf: bytes) -> set[int]:
    """Set core bits as ints frame * 2048 + byte * 8 + plane (CRC bytes 253, 254 excluded)."""
    a = np.frombuffer(buf, dtype=np.uint8, offset=PRE)
    a = a[: len(a) // FRAME * FRAME].reshape(-1, FRAME)[:, :253]
    f, p, b = np.nonzero(np.unpackbits(a[..., None], axis=2, bitorder="little"))
    keep = f >= 37
    return set((f[keep] * 2048 + p[keep] * 8 + b[keep]).tolist())


def lut_cells() -> set[int]:
    out = set()
    for x in range(45):
        for y in range(30):
            for n in range(0, 32, 2):
                try:
                    out |= {f * 2048 + p * 8 + b for f, p, b in lutpos._predict_phys(x, y, n)}
                except ValueError:
                    break
    return out


def frame_of(node: str):
    m = POS.search(node + "_")
    return R._col_frame(int(m.group(1))) if m else None


def solve(min_no: int = 20):
    names = []
    for f in limsolve.JOB_FILES:
        if os.path.exists(os.path.join(OUT, f)):
            names += json.load(open(os.path.join(OUT, f)))
    hops, sets = [], []
    for n in names:
        hops.append(routes.pips(json.load(open(os.path.join(OUT, n + ".route.json")))))
        sets.append(ones(xdev.load(OUT, n)))
    luts = lut_cells()
    nb = len(names)
    builds_with = collections.defaultdict(set)          # bit -> builds that have it
    for i, st in enumerate(sets):
        for c in st:
            builds_with[c].add(i)
    use = collections.defaultdict(set)                   # hop -> builds that use it
    node_use = collections.defaultdict(set)              # node -> builds that use it (as a hop end)
    for i, hb in enumerate(hops):
        for h in hb:
            use[h].add(i)
            for node in h:
                node_use[node.split(":")[0] if node.startswith("LCCOMB") else node].add(i)

    def specific(yes: set, allowed: set):
        """Bits in every build of yes and in no build outside allowed."""
        common = set.intersection(*(sets[i] for i in yes)) - luts
        return {c for c in common if builds_with[c] <= allowed}

    # LE signatures: bits present exactly when an LE is used (its LUT-input codes, output select); not routing
    sig = set()
    for node, yes in node_use.items():
        if node.startswith("LCCOMB") and len(yes) >= 2 and nb - len(yes) >= min_no:
            sig |= specific(yes, yes)
    res = {}
    for (u, v), yes in use.items():
        if u.startswith("LCCOMB") and v.startswith("LCCOMB"):
            continue
        if v.startswith("LCCOMB"):
            allowed = yes                                # LUT-input hop: strict (other lines into the same port vary)
        else:
            allowed = node_use[v]                        # mux select at v: keep bits v's inputs share
        if nb - len(allowed) < min_no:
            continue
        bits = specific(yes, allowed)
        if not v.startswith("LCCOMB"):
            bits -= sig
        fr = [f for f in (frame_of(u), frame_of(v)) if f is not None]
        bits = sorted(c for c in bits if any(abs(c // 2048 - f) <= WINDOW for f in fr))
        res[f"{u}->{v}"] = [len(yes), nb - len(allowed), [[c // 2048, c % 2048 // 8, c % 8] for c in bits]]
    json.dump(res, open(os.path.join(OUT, "hopsolve.json"), "w"), indent=0)
    return res, len(names)


def main() -> int:
    res, nb = solve(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
    kind = collections.defaultdict(collections.Counter)
    for k, (ny, nn, bits) in res.items():
        u, v = k.split("->")
        t = (u.split("_X")[0], v.split("_X")[0])
        kind[t]["seen>=2" if ny >= 2 else "seen 1x"] += 1
        if ny >= 2:
            kind[t][f"{min(len(bits), 4)}{'+' if len(bits) >= 4 else ''} bits"] += 1
    print(f"{nb} builds, {len(res)} hops")
    for t, c in sorted(kind.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {t[0]:>18s} -> {t[1]:18s}", dict(sorted(c.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
