#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board test of the assembled blinky (asm.py): out/asm_blink24p_counter.rbf.

The file is loaded only if it is byte-identical to Quartus's build of the same design (tpatch template blink24p with
the counter masks), i.e. exactly as safe as that Quartus file.  Control: the all-zero design before and after (D5 must
read low).  D5 = s[23] of a 24-bit counter on the 48 MHz iCLK: predicted 48e6 / 2**24 = 2.861 Hz.

  blinktest.py [--own | --own-dw | --blind-r | --yosys | --yosys-qbit]
      --own: our own routing (router.py); --own-dw: our routing over die-wide LUT-input codes only (limux_dw.py);
      --blind-r: the blinky at X27/X28 Y9, assembled with no measurement at its own position
      --yosys: the open flow's file (make blinky: Yosys -> ypnr.py), out/ypnr_blink.rbf
      --yosys-qbit: the same with cell (346,194,7) set as in Quartus's forced build (diagnostic)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hwtest  # noqa: E402

OUT = os.path.join(HERE, "out")
WANT = 48e6 / 2 ** 24


def main() -> int:
    import asm
    import explain as E
    import rcfforce as F
    import tpatch
    import xdev
    name = "blink24r" if "--blind-r" in sys.argv else "blink24p"
    masks = asm.counter_masks(name)
    ref = F.Project(tpatch.job(name, [masks[i] for i, _ in xdev.tpl_luts(name)]), E.ROOT).base_rbf
    yos = "--yosys" in sys.argv or "--yosys-qbit" in sys.argv
    own = "--own" in sys.argv or "--own-dw" in sys.argv or "--blind-r" in sys.argv or yos
    fname = ("ypnr_blink_quartusbit.rbf" if "--yosys-qbit" in sys.argv else "ypnr_blink.rbf" if yos
             else "asm_blink24r_blind.rbf" if "--blind-r" in sys.argv
             else "asm_blink24p_counter_ownroute_dw.rbf" if "--own-dw" in sys.argv
             else "asm_blink24p_counter_ownroute.rbf" if own else "asm_blink24p_counter.rbf")
    ours = open(os.path.join(OUT, fname), "rb").read()
    if own:
        # our own routing (router.py): gate-checked against Quartus's build with exactly the differing cells declared
        import gate
        cells = sorted(E.core_diff(ref, ours))
        errs = gate.check(ref, ours, [], extra_cells=cells)
        if errs:
            raise SystemExit(f"STOP: gate refuses {fname}: {errs}")
        print(f"{fname}: own routing, {len(cells)} core cells differ from Quartus's build, gate PASS; predicted D5 {WANT:.4f} Hz")
    elif ours != ref:
        raise SystemExit("STOP: the assembled file is not byte-identical to Quartus's build; not loading it")
    else:
        print(f"assembled file byte-identical to Quartus's build ({len(ours)} bytes); predicted D5 {WANT:.4f} Hz")
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
    bench.cmd("A")                     # drive D1..D4 again after the load (the bench keeps them tri-stated until "A")
    bench.cmd("S 0000")
    ts, vs = [], []
    end = time.time() + 10
    while time.time() < end:
        r = bench.cmd("R")
        if r.split("=")[2] != "0000":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {r}")
        ts.append(time.time())
        vs.append(r[3] == "1")
    bench.cmd("I")
    edges = [ts[i] for i in range(1, len(vs)) if vs[i] != vs[i - 1]]
    rate = len(ts) / 10
    got = 0.0
    if len(edges) >= 3:
        n = len(edges)
        mx, my = (n - 1) / 2, sum(edges) / n
        slope = sum((i - mx) * (e - my) for i, e in enumerate(edges)) / sum((i - mx) ** 2 for i in range(n))
        got = 1 / (2 * slope)
    ok = abs(got - WANT) / WANT < 0.02
    print(f"  D5: {got:.4f} Hz from {len(edges)} edges (poll rate {rate:.0f}/s); predicted {WANT:.4f} -> {'PASS' if ok else 'FAIL'}")
    control()
    lp = os.path.join(OUT, time.strftime("blinktest_%Y%m%d_%H%M%S.json"))
    json.dump(dict(want_hz=WANT, got_hz=got, edges=len(edges), poll_hz=rate, pass_=ok), open(lp, "w"))
    print(f"Log: {lp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
