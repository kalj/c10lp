#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check li_local_table.json against Quartus-routed templates (independent of the mux4 data).

For every LUT in templates/*/ whose input comes from an LE in the same LAB (a LUT
combout or a register output), predict that input's select bits from the table
(physical input from tpatch's input order, source = that LE's slot) and check
them in the template's base build.  When all four inputs are such local
sources, the whole select region (bytes 0..3, frames -12..-2) must match exactly.

  limcheck.py
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
import tpatch  # noqa: E402
import xdev  # noqa: E402

PORT = re.compile(r"\.data([abcd])\(\s*([^\s)]+)\s*\)")


def main() -> int:
    T = json.load(open(os.path.join(HERE, "data", "li_local_table.json")))
    lo_f, hi_f = T["frames"]
    table = {tuple(map(int, k.split(","))): {tuple(v) for v in vs} for k, vs in T["entries"].items()}
    stats = collections.Counter()
    for name in sorted(os.listdir(xdev.TEMPLATE_DIR)):
        if not os.path.exists(os.path.join(xdev.TEMPLATE_DIR, name, "locs.qsf")):
            continue
        t = tpatch.Template(name)
        src = open(os.path.join(xdev.TEMPLATE_DIR, name, "top.v")).read()
        locs = open(os.path.join(xdev.TEMPLATE_DIR, name, "locs.qsf")).read()
        where = {inst.strip('"'): (k, int(x), int(y), int(n))
                 for k, x, y, n, inst in tpatch.LOC_RE.findall(locs)}
        for inst in t.luts:
            body = re.search(rf"\b{re.escape(inst)}\s*\((.*?)\);", src, re.S).group(1)
            nets = {p: net for p, net in PORT.findall(body)}
            x, y, d = t.les[inst]
            cells = lutpos._predict_phys(x, y, d)
            f0, lo, bit = min(c[0] for c in cells), min(c[1] for c in cells), cells[0][2]
            flip = (d // 2) % 2
            have = set()
            for df in range(lo_f, hi_f + 1):
                for c in range(4):
                    dp = (3 - c) if flip else c                        # column c -> byte offset
                    dp = (1 - dp) if flip else dp                      # undo the LUT-pair mirror
                    pbyte = lo + dp
                    if 0 <= pbyte < 253 and t.zero[32 + (f0 + df) * 255 + pbyte] >> bit & 1:
                        have.add((df, c))
            want, all_local = set(), True
            for i, port in enumerate("abcd"):
                net = nets.get(port)
                w = where.get(net)
                if w is None or (w[1], w[2]) != (x, y):
                    all_local = False                                  # pin or another LAB
                    continue
                slot = w[3] - 1 if w[0] == "FF" else w[3]
                key = (t.perms[inst][i], slot)
                if key not in table:
                    stats["entry not in table"] += 1
                    all_local = False
                    continue
                kind = ("own LE" if slot == d else "other LE") + (" register" if w[0] == "FF" else " LUT")
                stats[f"local inputs from {kind}"] += 1
                ok = table[key] <= have
                stats[f"  ... {kind}: predicted bits all set"] += ok
                want |= table[key]
            if all_local:
                stats["LUTs with 4 local inputs"] += 1
                stats["  ... whose whole select region matches exactly"] += want == have
        print(f"  {name}: done")
    for k, v in sorted(stats.items(), key=lambda kv: kv[0].replace("  ... ", "").replace(": predicted bits all set", " ~")):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
