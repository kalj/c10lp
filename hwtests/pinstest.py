#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board test of the pin design (examples/pins.v, make npnr-pins): D1..D4 = A..D in, D5 = Q = (A ^ B) | (C & D),
registered (two clocks of the 48 MHz iCLK later, far below the bench's settling time).

Before loading: gate.py against Quartus's normal build of the same netlist and placement (ycheck --fresh's template)
with exactly the differing core cells declared; flow/ycheck.py has already shown the file equal to Quartus's build
with our routing forced except the RCF-mode bit.  Control: the all-zero design before and after (D5 must read low).
Then all 16 input combinations in Gray order, each read 3 times; D1..D4 must read back as driven.

  pinstest.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import hwtest  # noqa: E402

OUT = os.path.join(HERE, "out")
TOP = "pins"


def want(a, b, c, d):
    return (a ^ b) | (c & d)


def main() -> int:
    import explain as E
    import gate
    import rcfforce as F
    import tpatch
    import xdev
    import ycheck
    tpl, _extra = ycheck.fresh_template(TOP)
    if not os.path.isdir(os.path.join(HERE, "templates", tpl)):
        raise SystemExit(f"STOP: no template {tpl}: run flow/ycheck.py out/{TOP}.json {TOP} --timing --fresh first")
    ref = F.Project(tpatch.job(tpl, [m for _, m in xdev.tpl_luts(tpl)]), E.ROOT).base_rbf
    fname = f"ypnr_{TOP}.rbf"
    ours = open(os.path.join(OUT, fname), "rb").read()
    cells = sorted(E.core_diff(ref, ours))
    errs = gate.check(ref, ours, [], extra_cells=cells)
    if errs:
        raise SystemExit(f"STOP: gate refuses {fname}: {errs}")
    print(f"{fname}: {len(cells)} core cells differ from Quartus's build of the same netlist, gate PASS")
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc}) for {p}")

    def control():
        load(os.path.join(OUT, "lo_quartus_0000.rbf"))
        bench.cmd("A")
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    control()
    load(os.path.join(OUT, fname))
    bench.cmd("A")                     # drive D1..D4 (the bench keeps them tri-stated until "A")
    rows, bad = [], 0
    for ds in hwtest.COMBOS4:
        got = []
        for _ in range(3):
            d5, seen = bench.read(ds)
            if seen != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {seen}, driven {ds}")
            got.append(int(d5 == "h"))
        w = want(*ds)
        bad += any(g != w for g in got)
        rows.append(dict(inputs=list(ds), want=w, got=got))
        print(f"  A..D {''.join(map(str, ds))}: D5 {got} want {w}{'' if all(g == w for g in got) else '  MISMATCH'}")
    bench.cmd("I")
    ok = bad == 0
    print(f"  truth table: {16 - bad}/16 combinations right -> {'PASS' if ok else 'FAIL'}")
    control()
    lp = os.path.join(OUT, time.strftime("pinstest_%Y%m%d_%H%M%S.json"))
    json.dump(dict(rows=rows, pass_=ok), open(lp, "w"), indent=1)
    print(f"Log: {lp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
