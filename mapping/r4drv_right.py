#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Right-going R4 drivers (LE_BUFFER b of LAB (X, Y) -> R4 starting at X + 1): legality and bits.

Legality: drvmap.py --offset 1 (out/drvmap_p1.json): the legal wires depend only on (buffer, (X+Y) mod 4), 32/32
buffers equal at both positions measured per phase.  Bits: a pair at frames +16 and +18 of the source LAB, on a row
near the buffer's that moves with the wire, per (buffer, wire, phase), from the corpus uses of these hops.
Output: out/r4drv_right.json {"legal": {"b|phase": [w, ...]}, "bits": {"b|w|phase": [[frame, row], ...]}}

  r4drv_right.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import lutpos  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
TRAIN = ("xrkn_w2w_jobs.json", "xrkn_w2w2_jobs.json", "xrkn_w2w3_jobs.json", "xrkn_w2w4_jobs.json")   # not the holdout


def main() -> int:
    legal = {}
    by_wire = collections.defaultdict(set)              # (wire, phase) -> buffers that can drive it
    for e in json.load(open(os.path.join(OUT, "drvmap_p1.json"))).values():
        for b, v in e["buffers"].items():
            legal[f"{b}|{e['phase']}"] = sorted(v["legal"])
            for w in v["legal"]:
                by_wire[(w, e["phase"])].add(int(b))
    # Bits from the corpus: every use of a buffer -> right-going R4 hop (timing-report routes of the line-forcing
    # builds).  A cell counts when it is set in at least 80% of a key's uses (3 or more): a strict intersection is
    # emptied by rare positions without the pair (X12Y14, X29Y13, X19Y11 for keys that hold it everywhere else).
    # tapforce probes can't be attributed to a buffer reliably (the frame-16 bit picks between a mux's two buffers).
    import routegraph as G
    import routes
    import xdev
    uses = collections.defaultdict(list)
    for jf in TRAIN:
        for name in json.load(open(os.path.join(OUT, jf))):
            buf = xdev.load(OUT, name)
            if buf is None:
                continue
            for u, v in routes.pips(json.load(open(os.path.join(OUT, name + ".route.json")))):
                mu = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$", u)
                mv = re.match(r"R4_X(\d+)_Y(\d+)_N0_I(\d+)$", v)
                if not (mu and mv) or int(mv[1]) != int(mu[1]) + 1 or mu[2] != mv[2]:
                    continue
                x, y, b = map(int, mu.groups())
                f0, l0 = R._col_frame(x), R._row_index(y)
                if f0 is None:
                    continue
                cells = set()
                for f in (16, 18):
                    for l in range(-70, 6):
                        c = G.cell_of(f0 + f, l0 + l)
                        if c and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1:
                            cells.add((f, l))
                uses[(b, int(mv[3]), (x + y) % 4)].append(cells)
    bits = {}
    for (b, w, ph), lst in sorted(uses.items()):
        if len(lst) < 3:
            continue
        cnt = collections.Counter(c for s in lst for c in s)
        keep = sorted(c for c, n in cnt.items() if n >= 0.8 * len(lst))
        if keep:
            bits[f"{b}|{w}|{ph}"] = [list(c) for c in keep]
    json.dump({"legal": legal, "bits": bits}, open(os.path.join(OUT, "r4drv_right.json"), "w"), indent=0)
    print(f"{len(legal)} (buffer, phase) legality entries, bits for {len(bits)} (buffer, wire, phase) -> out/r4drv_right.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
