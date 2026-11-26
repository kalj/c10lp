#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame -1 LE cells vs how the LE's outputs are used (templates/fm1v_*).

One LE at X9Y3 slot N (6 = odd, 8 = even) with a LUT (always) and optionally its register; its combinational output
and/or register output feed sinks to the left (X8), to the right (X10) or in its own LAB (local line).  Each Quartus
build's own route file says which buffer / local line carries which signal; the LE's frame -1 cells (low byte -2..+3
on its plane) are read against that.
Output: printed table; out/fm1map.json {variant: {"N": n, "uses": ..., "cells": [...]}}

  fm1map.py
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import explain as E  # noqa: E402
import lutpos  # noqa: E402
import rcfforce as F  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
T = os.path.join(HERE, "templates")
# (comb sinks, reg sinks): L = LAB X8, R = LAB X10, S = same LAB X9 (local line); registered if reg sinks or "reg"
VARIANTS = {
    "cR": ("R", ""), "cL": ("L", ""), "cS": ("S", ""),
    "rR": ("", "R"), "rL": ("", "L"), "rS": ("", "S"), "rLR": ("", "LR"),
    "cR_rL": ("R", "L"), "cL_rR": ("L", "R"), "cS_rR": ("S", "R"), "cR_rS": ("R", "S"),
    "cLR": ("LR", ""), "reg_unused_cR": ("R", "-"),
    # own feedback: the register drives its own LUT (hard-wired input), as in every counter bit
    "fb": ("", "F"), "fb_rR": ("", "FR"), "fb_rS": ("", "FS"), "fb_rLR": ("", "FLR"), "fb_cR": ("R", "F"),
}
SINK = {"L": (8, 0), "R": (10, 0), "S": (9, 20)}


def make(name, n, comb, reg):
    d = os.path.join(T, name)
    os.makedirs(d, exist_ok=True)
    registered = bool(reg)
    v = [f"// fm1map probe: LE X9Y3 N{n}; combinational output to {comb or 'nothing'}, register to {reg or 'nothing'}",
         "module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);",
         "  wire t; reg s;" if registered else "  wire t;",
         f"  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) le (.dataa(A), "
         f".datab(B), .datac(C), .datad({'s' if 'F' in reg else 'D'}), .combout(t));"]
    if registered:
        v.append("  always @(posedge K) s <= t;")
    outs, locs = [], [f'set_location_assignment LCCOMB_X9_Y3_N{n} -to "le"']
    if registered:
        locs.append(f'set_location_assignment FF_X9_Y3_N{n + 1} -to "s"')
    k = 0
    for sig, where in (("t", comb), ("s", reg if reg != "-" else "")):
        for wch in where:
            if wch == "F":
                continue                                # own feedback: datad above
            x, sn = SINK[wch]
            v.append(f"  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) "
                     f"k{k} (.dataa({sig}), .combout(o{k}));")
            v.insert(2, f"  wire o{k};")
            locs.append(f'set_location_assignment LCCOMB_X{x}_Y3_N{sn + 2 * (k % 4)} -to "k{k}"')
            outs.append(f"o{k}")
            k += 1
    if reg == "-":                                      # registered but the register output unused outside: keep it
        v.append("  wire unused_s = s;")
    v.append(f"  assign Q = {' ^ '.join(outs) if outs else 't'};")
    v.append("endmodule")
    open(os.path.join(d, "top.v"), "w").write("\n".join(v) + "\n")
    open(os.path.join(d, "locs.qsf"), "w").write("\n".join(locs) + "\n")
    open(os.path.join(d, "extra.qsf"), "w").write(open(os.path.join(T, "blink24p", "extra.qsf")).read())


def main() -> int:
    jobs = []
    for n in (6, 8):
        for vname, (comb, reg) in VARIANTS.items():
            name = f"fm1v_N{n}_{vname}"
            make(name, n, comb, reg)
            jobs.append((name, n))

    def run(j):
        name, n = j
        try:
            pr = F.Project(tpatch.job(name, [m for _, m in xdev.tpl_luts(name)]), E.ROOT)
        except SystemExit as e:
            return name, n, None, str(e)
        return name, n, pr, None
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(run, jobs))
    out = {}
    for name, n, pr, err in res:
        if err:
            print(f"{name}: {err}")
            continue
        br = F.branches(pr.base_rcf)
        uses = {}
        for sig in ("t", "s"):
            for p, dd in br.get(sig, []):
                if p:
                    uses.setdefault(sig, set()).add(p[0].split("_N0_")[0].split("_X")[0] + ":" + p[0].rsplit("_I", 1)[1])
        c = lutpos._predict_phys(9, 3, n)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        cells = [pr.base_rbf[32 + (f0 - 1) * 255 + lo + d] >> bit & 1 for d in range(-2, 4)]
        out[name] = {"N": n, "uses": {k: sorted(v) for k, v in uses.items()}, "cells": cells}
        print(f"{name:20s} frame-1 lo-2..lo+3 {cells}  comb t -> {sorted(uses.get('t', []))}  reg s -> {sorted(uses.get('s', []))}")
    json.dump(out, open(os.path.join(OUT, "fm1map.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
