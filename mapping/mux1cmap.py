#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Clean single-input LUT-input select codes from xdev design "mux1c" (data only).

One local source (slot a) on one dst input; the other three dst inputs are tied
to constants.  dst's mask reveals which physical input p carries the source, so
dst's select region (bytes 0..3, frames -12..-2, odd LEs c -> 3-c) is the code
for (p, a), plus whatever the constant tie-offs need.  Writes li_single.json:
only (input, source) pairs Quartus actually used for a lone source.

  mux1cmap.py
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
import xdev  # noqa: E402


def region(buf, x, y, d):
    cells = lutpos._predict_phys(x, y, d)
    f0, lo, bit = min(c[0] for c in cells), min(c[1] for c in cells), cells[0][2]
    flip = (d // 2) % 2
    return {(df, c) for df in range(-12, -1) for c in range(4)
            if buf[32 + (f0 + df) * 255 + lo + (c - 2 if flip else c)] >> bit & 1}


def perm_of(buf, x, y, d, mask=0x3CEC):
    cells = lutpos._predict_phys(x, y, d)
    on = {c for c in cells if buf[32 + c[0] * 255 + c[1]] >> c[2] & 1}
    hits = [p for p in lutpos.PERMS if {cells[lutpos.permute(i, p)] for i in range(16) if mask >> i & 1} == on]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    import mux1c_plan
    codes = collections.defaultdict(collections.Counter)
    groups = collections.defaultdict(list)        # (LAB, d, perm) -> [(p, a, region)]
    for j in mux1c_plan.jobs():
        _, sd, sa, k = j.design.split(":")
        d, a, k = int(sd), int(sa), int(k)
        x, y, _ = j.loc
        buf = xdev.load(os.path.join(HERE, "out"), j.name)
        perm = perm_of(buf, x, y, d)
        if perm is None:
            continue
        r = frozenset(region(buf, x, y, d))
        codes[(perm[k], a)][r] += 1
        groups[((x, y), d, perm)].append((perm[k], a, r))
    clean = {}
    for key, c in sorted(codes.items()):
        top, n = c.most_common(1)[0]
        tot = sum(c.values())
        flag = "" if n == tot else f"  ({tot - n} builds differ: {[sorted(v) for v in c if v != top][:2]})"
        print(f"  input {key[0]} src {key[1]:2d}: {sorted(top)}  in {n}/{tot} builds{flag}")
        if n == tot:
            clean[key] = sorted(top)
    print(f"{len(clean)} (input, source) pairs with one consistent region; {len(codes) - len(clean)} vary")
    # Decompose: within builds that share the constant layout (same LAB, dst slot, input order), what
    # every source has in common is the constants' code; the rest is the local input's own code.
    own = collections.defaultdict(collections.Counter)
    for _, rows in groups.items():
        if len({a for _, a, _ in rows}) < 3:
            continue
        common = frozenset.intersection(*(r for _, _, r in rows))
        for p, a, r in rows:
            own[(p, a)][r - common] += 1
    clean = {}
    for key, c in sorted(own.items()):
        top, n = c.most_common(1)[0]
        if n == sum(c.values()):
            clean[key] = sorted(top)
    print(f"own codes (region minus the constants' common part): {len(clean)} consistent pairs")
    with open(os.path.join(HERE, "data", "li_single.json"), "w") as f:
        json.dump({"about": "Single-input LUT-input select codes from mux1c builds (other dst inputs tied to "
                            "constants). Key 'input,source_slot' -> [[frame, column], ...] in dst coordinates "
                            "as li_local_table.json. Only pairs Quartus used for a lone local source, with one "
                            "code in every build.",
                   "entries": {f"{p},{s}": v for (p, s), v in clean.items()}}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
