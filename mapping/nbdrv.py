#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neighbour-link driver bits (LE_BUFFER b of LAB (X, Y) -> LAB line L of LAB (X +/- 1, Y)) per (buffer, dx, line).

li_neighbour.json gives one pattern per source slot, but the driver moves with the line: buffer I14 -> X10 line 21
(the nextpnr-routed blinky) is (16, 0)/(18, 0) of the source LE, where the slot-14 entry says (19, -2)/(21, -1).
From every corpus use of such a hop (timing-report routes): the cells in frames +13..+22 of the source LAB, within
4 bytes of the source LE's low byte on its plane, set in at least 80% of a key's uses (3 or more).  Builds at a
fifth of the positions are held out to test.
Output: out/nbdrv.json {"b|dx|line": [[frame, byte offset], ...]}

  nbdrv.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
LISTS = ("route_corpus_jobs.json", "xrk_jobs.json", "xrkn_jobs.json", "xrkn_holdout_jobs.json", "xrkn_holdout2_jobs.json",
         "xrkn_holdout3_jobs.json", "xrkn_w2w_jobs.json", "xrkn_w2w2_jobs.json", "xrkn_w2w3_jobs.json")


def uses():
    u = collections.defaultdict(list)                   # key -> [(position, cells)]
    for jf in LISTS:
        p = os.path.join(OUT, jf)
        for name in (json.load(open(p)) if os.path.exists(p) else []):
            rp = os.path.join(OUT, name + ".route.json")
            buf = xdev.load(OUT, name)
            if buf is None or not os.path.exists(rp):
                continue
            for a, b in routes.pips(json.load(open(rp))):
                ma = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$", a)
                mb = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", b)
                if not (ma and mb) or ma[2] != mb[2] or abs(int(mb[1]) - int(ma[1])) != 1:
                    continue
                x, y, bb = map(int, ma.groups())
                try:
                    c0 = lutpos._predict_phys(x, y, bb - bb % 2)
                    f0 = min(v[0] for v in lutpos._predict_phys(x, y, 0))
                except (ValueError, KeyError):
                    continue
                lo, bit = min(v[1] for v in c0), c0[0][2]
                cells = frozenset((df, db) for df in range(13, 23) for db in range(-4, 5)
                                  if 0 < lo + db < 253 and buf[32 + (f0 + df) * 255 + lo + db] >> bit & 1)
                u[(bb, int(mb[1]) - x, int(mb[3]))].append(((x, y), cells))
    return u


def learn(lst):
    if len(lst) < 3:
        return None
    cnt = collections.Counter(c for _p, s in lst for c in s)
    keep = sorted(c for c, n in cnt.items() if n >= 0.8 * len(lst))
    return keep or None


def main() -> int:
    u = uses()
    held = lambda pos: hash(pos) % 5 == 0
    c = collections.Counter()
    for k, lst in u.items():
        tr = [e for e in lst if not held(e[0])]
        m = learn(tr)
        for pos, s in lst:
            if held(pos):
                c["no entry" if not m else "all set" if set(map(tuple, m)) <= s else "missing"] += 1
    print(f"{len(u)} keys, {sum(map(len, u.values()))} uses; held-out positions: {dict(c)}")
    model = {f"{b}|{dx}|{li}": [list(x) for x in m] for (b, dx, li), lst in u.items() if (m := learn(lst))}
    json.dump(model, open(os.path.join(OUT, "nbdrv.json"), "w"), indent=0)
    print(f"{len(model)} entries -> out/nbdrv.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
