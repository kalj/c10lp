#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-side bits of the "second path" (an LE output used by a non-direct LUT input), from the
mux4 builds (data only).  For each source slot s: bits in s's own LE window (frame offset from the
LAB's first LUT frame, byte column in s's LE, odd LEs mapped c -> 3-c... as lutpos byte mirror)
that are on in every build using s through a non-direct input and off in every build using s only
directly.  Writes li_second_path.json (entries agreeing at both 10CL016 LABs).

  secondpath.py
"""
from __future__ import annotations

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402
import mux1cmap  # noqa: E402
import xdev  # noqa: E402


def main() -> int:
    import mux4_plan
    direct = {int(k): set(v) for k, v in json.load(open(os.path.join(HERE, "data", "li_direct.json"))).items()}
    per_lab = collections.defaultdict(lambda: collections.defaultdict(lambda: ([], [])))
    for j in mux4_plan.jobs(full=True):
        if j.dev != "c10_016":
            continue
        _, sd, srcs = j.design.split(":")
        d, srcs = int(sd), [int(v) for v in srcs.split("-")]
        x, y, _ = j.loc
        buf = xdev.load(os.path.join(HERE, "out"), j.name)
        perm = mux1cmap.perm_of(buf, x, y, d)
        if perm is None:
            continue
        f0 = min(f for f, _, _ in lutpos._predict_phys(x, y, 0))
        for i, s in enumerate(srcs):
            cells = lutpos._predict_phys(x, y, s)
            lo, b, fl = min(p for _, p, _ in cells), cells[0][2], (s // 2) % 2
            win = {(df, col) for df in range(-20, 30) for col in range(-2, 6)
                   if 2 <= lo + (col - 2 if fl else col) < 253
                   and buf[32 + (f0 + df) * 255 + lo + (col - 2 if fl else col)] >> b & 1}
            indirect = any(srcs[k] == s and perm[k] not in direct[s] for k in range(4))
            per_lab[(x, y)][s][0 if indirect else 1].append(win)
    sigs = {}
    for lab, by_s in per_lab.items():
        for s, (on, off) in by_s.items():
            if on and off:
                sigs.setdefault(s, {})[lab] = set.intersection(*on) - set.union(*off)
    out = {}
    for s in sorted(sigs):
        labs = list(sigs[s].values())
        same = len(labs) == 2 and labs[0] == labs[1]
        print(f"  source {s:2d}: " + "  ".join(f"X{l[0]}Y{l[1]} {sorted(v)}" for l, v in sigs[s].items())
              + ("  SAME" if same else ""))
        if same:
            out[str(s)] = sorted(labs[0])
    json.dump({"about": "Source-LE bits that turn on when that LE's output is used by a non-direct LUT input "
                        "(the second path). Key: source slot -> [[frame offset from the LAB's first LUT frame, "
                        "byte column in the source LE], ...]. Agreeing at X10Y10 and X22Y8.",
               "entries": out}, open(os.path.join(HERE, "data", "li_second_path.json"), "w"), indent=1)
    print(f"{len(out)} source slots with the same signature at both LABs -> li_second_path.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
