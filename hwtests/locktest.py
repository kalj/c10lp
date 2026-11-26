#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board test of the combination lock (examples/lock.v, make npnr-lock): D5 goes high once D1..D4 (A..D) have stepped
through 0001 -> 0011 -> 0111 -> 1111 (DCBA), one pin per step; any other code on the way resets it.  Scripted
sequences of input codes, D5 checked after each step against a model of the lock.

Before loading: gate.py against Quartus's normal build of the same netlist and placement (ycheck --fresh's template)
with exactly the differing core cells declared; flow/ycheck.py has already shown the file equal to Quartus's build
with our routing forced except the RCF-mode bit.  Control: the all-zero design before and after (D5 must read low).
D1..D4 must read back as driven.

  locktest.py
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
TOP = "lock"
CODES = [0b0001, 0b0011, 0b0111, 0b1111]
# (A, B, C, D) steps, each one pin from the last: open, close by leaving, a wrong step, a restart, open again
SEQ = [(0, 0, 0, 0), (1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1), (1, 1, 1, 1), (1, 1, 1, 0), (1, 1, 1, 1),
       (0, 1, 1, 1), (0, 0, 1, 1), (0, 0, 0, 1), (0, 0, 0, 0), (1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 0, 1), (1, 1, 1, 1),
       (0, 1, 1, 1), (0, 0, 1, 1), (0, 0, 0, 1), (0, 0, 0, 0), (1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0), (1, 1, 1, 1)]


def model(seq):
    """The lock's D5 after each step (examples/lock.v)."""
    s, out = 0, []
    for a, b, c, d in seq:
        v = a | b << 1 | c << 2 | d << 3
        if s < 4 and v == CODES[s]:
            s += 1
        elif s == 4 and v != CODES[3]:
            s = 0
        elif s and s < 4 and v != CODES[s - 1]:
            s = 1 if v == CODES[0] else 0
        out.append(int(s == 4))
    return out


def main() -> int:
    import explain as E
    import gate
    import rcfforce as F
    import tpatch
    import xdev
    h = hashlib.sha1((open(os.path.join(OUT, f"ypnr_{TOP}.v")).read()
                      + open(os.path.join(OUT, f"ypnr_{TOP}_locs.qsf")).read()).encode()).hexdigest()[:8]
    tpl = f"ycheck_{TOP}_{h}"
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
    want = model(SEQ)
    for ds, w in zip(SEQ, want):
        d5, seen = bench.read(ds)
        if seen != "".join(map(str, ds)):
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, driven {ds}")
        got = int(d5 == "h")
        bad += got != w
        rows.append(dict(inputs=list(ds), want=w, got=got))
        print(f"  A..D {''.join(map(str, ds))}: D5 {got} want {w}{'' if got == w else '  MISMATCH'}")
    bench.cmd("I")
    ok = bad == 0
    print(f"  lock: {len(SEQ) - bad}/{len(SEQ)} steps right -> {'PASS' if ok else 'FAIL'}")
    control()
    lp = os.path.join(OUT, time.strftime("locktest_%Y%m%d_%H%M%S.json"))
    json.dump(dict(rows=rows, pass_=ok), open(lp, "w"), indent=1)
    print(f"Log: {lp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
