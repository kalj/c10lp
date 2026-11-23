#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test: patch the carry function of an arithmetic chain-start LE (templates/arith2).

In arith2, e0 starts the chain (no carry in) and its sum output is unused, so Quartus stores
only its carry function f(a, b) (cin = 0): f(k) = 1, k = a + 2b, sets physical LUT cells 4k
and 4k+1 (checked on 20 Quartus builds).  Here e0's cells are rewritten for all 16 functions,
e1 passes its carry input to D5, so D5 must equal f(A, B) for every (A, B, C, D).
LUT-only changes on the Quartus base; gate-checked.

  carrytest.py
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import tpatch  # noqa: E402

OUT = os.path.join(HERE, "out")
PASS_C = sum(((m >> 2) & 1) << m for m in range(16))


def enc(f: int) -> int:
    return sum(((f >> k) & 1) * (0b11 << (4 * k)) for k in range(4))


def main() -> int:
    t = tpatch.Template("arith2", partial=True)
    x, y, n = t.les["e0"]
    cells = lutpos._predict_phys(x, y, n)
    base_e1 = t.write({"e1": PASS_C})
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    os.makedirs(os.path.join(OUT, "arith"), exist_ok=True)
    log_path = os.path.join(OUT, time.strftime("carrytest_%Y%m%d_%H%M%S.jsonl"))

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

    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    if any(table(control).values()):
        raise SystemExit("STOP: all-zero control did not hold D5 low")
    print("  control: D5 low, ok")
    ok = 0
    with open(log_path, "w") as log:
        for f in range(16):
            buf = bytearray(base_e1)
            v = lutpatch.header_sum(base_e1)
            want = enc(f)
            for i, (fr, p, b) in enumerate(cells):
                off = 32 + fr * 255 + p
                if (buf[off] >> b & 1) != (want >> i & 1):
                    buf[off] ^= 1 << b
                    v += lutpos.header_weight(fr, p, b) * (1 if buf[off] >> b & 1 else -1)
            lutpatch.patch_crc(buf, rbfgeom.infer(base_e1))
            lutpatch.set_header_sum(buf, v % (1 << 32))
            data = bytes(buf)
            errs = gate.check(t.zero, data, [t.les["e0"], t.les["e1"]])
            if errs:
                raise SystemExit(f"f={f:04b}: gate refused {errs}")
            path = os.path.join(OUT, "arith", f"lo_carry_{f:04b}.rbf")
            open(path, "wb").write(data)
            got = table(path)
            wrong = [ds for ds, v_ in got.items() if v_ != (f >> (ds[0] + 2 * ds[1]) & 1)]
            ok += not wrong
            log.write(json.dumps(dict(f=f, wrong=["".join(map(str, w)) for w in wrong])) + "\n")
            print(f"  carry f(A,B) = {f:04b} (k = A + 2B): " + ("PASS" if not wrong else f"FAIL {len(wrong)}/16"),
                  flush=True)
    if any(table(control).values()):
        print("  control FAILED")
    else:
        print("  control: D5 low, ok")
    print(f"\n{ok}/16 carry functions correct. Log: {log_path}")
    return 0 if ok == 16 else 1


if __name__ == "__main__":
    sys.exit(main())
