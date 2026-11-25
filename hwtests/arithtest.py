#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test: how an arithmetic-mode LUT works (templates/arith2, LUT-only patches of e1).

e0 (fixed, Quartus's bits, placeholder mask 11CC on A, B, D) drives e1's carry input.  e1's
logical inputs are a = C, b = B, c = cin, d = D.
  1. e1 = "pass c": D5 = e0's carry-out; read it over all 16 input combinations.
  2. e1 = random masks: D5 must equal mask[C | B<<1 | cin<<2 | D<<3] with the measured cin.
Every file passes gate.py (only e1's LUT cells differ from the Quartus base).

  arithtest.py board
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import hwtest  # noqa: E402
import tpatch  # noqa: E402

OUT = os.path.join(HERE, "out")
PASS_C = sum(((m >> 2) & 1) << m for m in range(16))          # 0xF0F0


def main() -> int:
    t = tpatch.Template("arith2", partial=True)
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    os.makedirs(os.path.join(OUT, "arith"), exist_ok=True)
    log_path = os.path.join(OUT, time.strftime("arithtest_%Y%m%d_%H%M%S.jsonl"))

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")

    def table(path):
        load(path)
        res = {}
        for ds in hwtest.COMBOS4:
            got, seen = bench.read(ds)
            if seen != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {seen}")
            res[ds] = int(got == "h")
        bench.cmd("I")
        return res

    ctrl = table(os.path.join(OUT, "lo_quartus_0000.rbf"))
    if any(ctrl.values()):
        raise SystemExit("STOP: all-zero control did not hold D5 low")
    print("  control: D5 low, ok")
    with open(log_path, "w") as log:
        p = os.path.join(OUT, "arith", "lo_arith2_passc.rbf")
        open(p, "wb").write(t.write({"e1": PASS_C}))
        cin = table(p)                                       # keyed by (A, B, C, D)
        dep_c = any(cin[(a, b, 0, d)] != cin[(a, b, 1, d)] for a in (0, 1) for b in (0, 1) for d in (0, 1))
        fn = {(a, b, d): cin[(a, b, 0, d)] for a in (0, 1) for b in (0, 1) for d in (0, 1)}
        print(f"  e0 carry-out over (A, B, D): {fn}   depends on C (shouldn't): {dep_c}")
        log.write(json.dumps(dict(test="cout", table={''.join(map(str, k)): v for k, v in fn.items()},
                                  depends_on_C=dep_c)) + "\n")
        rnd = random.Random(31)
        ok = 0
        for k in range(4):
            m = rnd.randrange(1, 0xFFFF)
            p = os.path.join(OUT, "arith", f"lo_arith2_e1_{m:04X}.rbf")
            open(p, "wb").write(t.write({"e1": m}))
            got = table(p)
            wrong = [ds for ds in got if got[ds] != (m >> (ds[2] | ds[1] << 1 | cin[ds] << 2 | ds[3] << 3) & 1)]
            ok += not wrong
            log.write(json.dumps(dict(test="sum", mask=m, wrong=[''.join(map(str, w)) for w in wrong])) + "\n")
            print(f"  e1 mask {m:04X}: " + ("PASS (D5 = mask[C, B, cin, D])" if not wrong else f"FAIL {len(wrong)}/16"))
    ctrl = table(os.path.join(OUT, "lo_quartus_0000.rbf"))
    print("  control: D5 low, ok" if not any(ctrl.values()) else "  control FAILED")
    print(f"\nsum-path masks correct: {ok}/4. Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
