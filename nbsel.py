#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Destination-side selects of neighbour links (LE_BUFFER of LAB X-1 -> a line of LAB X), per column class X mod 8.

Probe design (templates/nb_*): one combinational LE at slot 18 of LAB (X-1, 10) drives a sink LE in LAB (X, 10).  For
each line L the link may reach (seen pairs for buffer I19 at dx +1), the link is forced onto L with the RCF oracle;
the diff against the identity build, restricted to LAB X's select band (frames -26..-13) outside the source's driver
pair, gives that line's destination select cells.  Output: out/nbsel.json {"class": {"line": [[frame, row], ...]}}

  nbsel.py
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpos  # noqa: E402
import rcfforce as F  # noqa: E402
import router  # noqa: E402
import routemap as R  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfnb")
T = os.path.join(HERE, "templates")
SLOT, BUF = 18, 19
# one destination LAB per column class (x and x - 1 logic columns), row 10
DSTS = [8, 9, 10, 11, 12, 21, 14, 15]


def make(X: int) -> str:
    name = f"nb_X{X}"
    d = os.path.join(T, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "top.v"), "w").write(f"""// nbsel probe: neighbour link LE_BUFFER X{X - 1} I{BUF} -> a line of LAB X{X} (destination selects per column class)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk (.dataa(t), .combout(u));
  assign Q = u;
endmodule
""")
    open(os.path.join(d, "extra.qsf"), "w").write(open(os.path.join(T, "blink24p", "extra.qsf")).read())
    open(os.path.join(d, "locs.qsf"), "w").write(f'set_location_assignment LCCOMB_X{X - 1}_Y10_N{SLOT} -to "src"\n'
                                               f'set_location_assignment LCCOMB_X{X}_Y10_N0 -to "snk"\n')
    return name


def main() -> int:
    res = json.load(open(os.path.join(OUT, "nbsel.json"))) if os.path.exists(os.path.join(OUT, "nbsel.json")) else {}
    seen = router.seen_neighbour_pairs()
    lines = sorted(li for b, dx, li in seen if b == BUF and dx == 1)
    for X in DSTS:
        cls = str(X % 8)
        if cls in res:
            continue
        name = make(X)
        pr = F.Project(tpatch.job(name, [m for _, m in xdev.tpl_luts(name)]), ROOT)
        br = F.branches(pr.base_rcf)["t"][0][0]
        if not br or not br[0].startswith(f"LE_BUFFER_X{X - 1}_Y10_N0_I{BUF}"):
            print(f"X{X}: Quartus used {br[:2]}, not buffer I{BUF}; skipped", flush=True)
            continue
        old = br[1]
        f0, l0 = R._col_frame(X), R._row_index(10)
        out = {}
        for li in lines:
            L = f"LOCAL_INTERCONNECT_X{X}_Y10_N0_I{li}"
            fn = lambda blk, L=L: re.sub(r", route_port = \w+;", ";", blk).replace(F.rcf_name(old), F.rcf_name(L))
            ok, data, msg = pr.rewrite("t", fn, L)
            if not ok:
                continue
            d = F.xor_cells(pr.ident_rbf, data)
            sel = sorted((f - f0, p + lutpos.PLANE_START[b] - l0, v) for f, p, b, v in d if -26 <= f - f0 <= -13)
            out[str(li)] = sel
        res[cls] = dict(X=X, base_line=int(old.rsplit("_I", 1)[1]), lines=out)
        json.dump(res, open(os.path.join(OUT, "nbsel.json"), "w"), indent=0)
        print(f"X{X} (class {cls}): {len(out)} lines honoured, base line {old.rsplit('_I', 1)[1]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
