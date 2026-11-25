#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-wide LUT-input select codes, from every RCF project's routing and RBF.

Key: (source kind and index, physical input, LE parity), where the source is a LAB line (LI k) or a local line
(LL k, from the LE at slot 2k of the same LAB).  The code is the build's set bits in that input's own cells
(limux.input_cells, odd LEs at low byte + column - 2).  With that convention the codes are position-independent: of
135 LAB-line keys only 13 conflict, each as one dominant code plus a single outlier sample.  Kept: the majority code
with >= 3 samples and >= 90% of them, or 1-2 samples that agree.  Output: out/limux_dw.json {"LI|line|input|parity": [[frame, col], ...]}

  limux_dw.py
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import limux  # noqa: E402
import rcfforce as F  # noqa: E402

OUT = os.path.join(HERE, "out")


def samples(exclude: str | None = None):
    cells = limux.input_cells()
    out = []
    for root in ("rcf", "rcfvar"):
        for work in glob.glob(os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", root, "work", "*")):
            if re.search(r"\.w\d+$", work) or not os.path.exists(os.path.join(work, "base.rcf")):
                continue
            if exclude and exclude in os.path.basename(work):
                continue
            rcf = open(os.path.join(work, "base.rcf")).read()
            buf = open(os.path.join(work, "base.rbf"), "rb").read()
            locs = {}
            for ln in open(os.path.join(work, "fuzz.qsf"), errors="replace"):
                m = re.search(r'LCCOMB_X(\d+)_Y(\d+)_N(\d+) -to "?([^"\s]+)', ln)
                if m:
                    locs[m.group(4)] = tuple(map(int, m.groups()[:3]))
            for sig, bl in F.branches(rcf).items():
                for path, (d, lp, pp) in bl:
                    if not path or pp.lower() not in limux.PHYS:
                        continue
                    kind = "LI" if path[-1].startswith("LOCAL_INTERCONNECT") else "LL" if path[-1].startswith("LOCAL_LINE") else None
                    loc = locs.get(d) or locs.get(re.sub(r"\[(\d+)\]", r"\1", d))
                    if not kind or not loc:
                        continue
                    inp = limux.PHYS[pp.lower()]
                    key = f"{kind}|{int(path[-1].rsplit('_I', 1)[1])}|{inp}|{(loc[2] // 2) % 2}"
                    out.append((key, limux.code(buf, *loc, cells[inp])))
    return out


def build(exclude: str | None = None, path: str = os.path.join(OUT, "limux_dw.json")):
    g = collections.defaultdict(collections.Counter)
    for k, c in samples(exclude):
        g[k][c] += 1
    table, stat = {}, collections.Counter()
    for k, c in g.items():
        code, n = c.most_common(1)[0]
        tot = sum(c.values())
        if (tot >= 3 and n >= 0.9 * tot) or (tot < 3 and n == tot):     # small keys: unanimous
            table[k] = sorted(code)
            stat[k.split("|")[0] + " kept"] += 1
        else:
            stat[k.split("|")[0] + " dropped"] += 1
    json.dump(table, open(path, "w"), indent=0)
    return table, stat


def main() -> int:
    ex = sys.argv[sys.argv.index("--exclude") + 1] if "--exclude" in sys.argv else None
    table, stat = build(ex)
    print(f"die-wide LUT-input codes{' (excluding ' + ex + ')' if ex else ''}: {dict(stat)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
