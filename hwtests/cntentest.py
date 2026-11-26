#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board test of the enable counter (examples/cnt_en.v, make npnr-cnt-en): D5 = bit 23 of a counter on the 48 MHz
iCLK that counts while D1 (A) is high.  Predicted: D1 = 1 -> D5 toggles at 48e6 / 2**24 = 2.861 Hz; D1 = 0 -> D5
holds its value.

Before loading: gate.py against Quartus's normal build of the same netlist and placement (ycheck --fresh's template)
with exactly the differing core cells declared (flow/ycheck.py has shown the file equal to Quartus's build with our
routing forced except the RCF-mode bit).  Control: the all-zero design before and after (D5 must read low).

  cntentest.py
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
TOP = "cnt_en"
WANT = 48e6 / 2 ** 24


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

    def watch(ds, secs):
        bench.cmd("S " + "".join(map(str, ds)))
        ts, vs = [], []
        end = time.time() + secs
        while time.time() < end:
            r = bench.cmd("R")
            if r.split("=")[2] != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {r}")
            ts.append(time.time())
            vs.append(r[3] == "1")
        edges = [ts[i] for i in range(1, len(vs)) if vs[i] != vs[i - 1]]
        hz = 0.0
        if len(edges) >= 3:
            n = len(edges)
            mx, my = (n - 1) / 2, sum(edges) / n
            hz = 1 / (2 * sum((i - mx) * (e - my) for i, e in enumerate(edges)) / sum((i - mx) ** 2 for i in range(n)))
        return hz, len(edges)

    control()
    load(os.path.join(OUT, fname))
    bench.cmd("A")
    on_hz, on_e = watch((1, 0, 0, 0), 10)
    off_hz, off_e = watch((0, 0, 0, 0), 5)
    on2_hz, on2_e = watch((1, 0, 0, 0), 5)
    bench.cmd("I")
    ok = abs(on_hz - WANT) / WANT < 0.02 and off_e == 0 and on2_e >= 3
    print(f"  D1=1: {on_hz:.4f} Hz ({on_e} edges); D1=0: {off_e} edges; D1=1 again: {on2_e} edges; predicted "
          f"{WANT:.4f} Hz / 0 edges -> {'PASS' if ok else 'FAIL'}")
    control()
    lp = os.path.join(OUT, time.strftime("cntentest_%Y%m%d_%H%M%S.json"))
    json.dump(dict(on_hz=on_hz, on_edges=on_e, off_edges=off_e, on2_edges=on2_e, pass_=ok), open(lp, "w"))
    print(f"Log: {lp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
