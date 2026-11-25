#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test: patch the carry function of an arithmetic chain-start LE (templates/arith2).

In arith2, e0 starts the chain (no carry in) and its sum output is unused, so Quartus stores
only its carry function f(a, b) (cin = 0): f(k) = 1, k = a + 2b, sets physical LUT cells 4k
and 4k+1 (checked on 20 Quartus builds).  Here e0's cells are rewritten for all 16 functions,
e1 passes its carry input to D5, so D5 must equal f(A, B) for every (A, B, C, D).
LUT-only changes on the Quartus base; gate-checked.

  carrytest.py            chain start, all 16 functions (templates/arith2)
  carrytest.py chain3     middle LE too: D5 = g(C, B, f(A, B)) (templates/arith3)
  carrytest.py both       an LE using sum and carry: the unified model (templates/arith3b)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import tpatch  # noqa: E402

OUT = os.path.join(HERE, "out")
PASS_C = sum(((m >> 2) & 1) << m for m in range(16))


def enc(f: int) -> int:
    """Chain-start carry f(a, b), k = a + 2b: cells 4k and 4k+1."""
    return sum(((f >> k) & 1) * (0b11 << (4 * k)) for k in range(4))


def enc3(g: int) -> int:
    """Middle-of-chain carry g(a, b, cin), j = a + 2b + 4cin: cell 4(j mod 4) + j div 4."""
    return sum(((g >> j) & 1) << (4 * (j & 3) + (j >> 2)) for j in range(8))


def set_cells(buf: bytearray, cells, pattern: int, v: int) -> int:
    for i, (fr, p, b) in enumerate(cells):
        off = 32 + fr * 255 + p
        if (buf[off] >> b & 1) != (pattern >> i & 1):
            buf[off] ^= 1 << b
            v += lutpos.header_weight(fr, p, b) * (1 if buf[off] >> b & 1 else -1)
    return v


def chain3(n_files: int = 12, seed: int = 3) -> int:
    """templates/arith3: e0 carry f(A, B), e1 carry g(C, B, cin), e2 passes its carry: D5 = g(C, B, f(A, B))."""
    import random
    t = tpatch.Template("arith3", partial=True)
    base = t.write({"e2": PASS_C})
    x, y, _ = t.les["e2"]
    c0, c1 = lutpos._predict_phys(x, y, 0), lutpos._predict_phys(x, y, 2)
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    log_path = os.path.join(OUT, time.strftime("carry3_%Y%m%d_%H%M%S.jsonl"))
    rnd = random.Random(seed)

    def table(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")
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
        for k in range(n_files):
            f, g = rnd.randrange(16), rnd.randrange(256)
            buf = bytearray(base)
            v = set_cells(buf, c0, enc(f), lutpatch.header_sum(base))
            v = set_cells(buf, c1, enc3(g), v)
            lutpatch.patch_crc(buf, rbfgeom.infer(base))
            lutpatch.set_header_sum(buf, v % (1 << 32))
            data = bytes(buf)
            errs = gate.check(t.zero, data, [t.les[i] for i in ("e0", "e1", "e2")])
            if errs:
                raise SystemExit(f"gate refused: {errs}")
            path = os.path.join(OUT, "arith", f"lo_carry3_{f:04b}_{g:08b}.rbf")
            open(path, "wb").write(data)
            got = table(path)
            want = lambda A, B, C, D: g >> (C + 2 * B + 4 * (f >> (A + 2 * B) & 1)) & 1   # noqa: E731
            wrong = [ds for ds, val in got.items() if val != want(*ds)]
            ok += not wrong
            log.write(json.dumps(dict(f=f, g=g, wrong=["".join(map(str, w)) for w in wrong])) + "\n")
            print(f"  f = {f:04b}, g = {g:08b}: " + ("PASS" if not wrong else f"FAIL {len(wrong)}/16"), flush=True)
    print("  control: D5 low, ok" if not any(table(control).values()) else "  control FAILED")
    print(f"\n{ok}/{n_files} two-stage carry chains correct. Log: {log_path}")
    return 0 if ok == n_files else 1


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


def both(n_masks: int = 6, seed: int = 4) -> int:
    """templates/arith3b: e1 uses sum and carry.  Model: sum = M[a + 2b + 4cin + 8d],
    cout = M[a + 2b + 4cin] (d = 0 half).  Readout 1: x passes e1's sum; readout 2: x passes e2,
    which passes its carry in, i.e. e1's cout.  e0's carry f(A, B) feeds e1's cin."""
    import random
    t = tpatch.Template("arith3b", partial=True)
    x0, y0, n0 = t.les["e0"]
    c0 = lutpos._predict_phys(x0, y0, n0)
    rnd = random.Random(seed)
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    log_path = os.path.join(OUT, time.strftime("carryboth_%Y%m%d_%H%M%S.jsonl"))

    def table(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")
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
    pass_a = sum((m & 1) << m for m in range(16))            # x: logical a = y1 (e1's sum)
    pass_b = sum((m >> 1 & 1) << m for m in range(16))       # x: logical b = q2
    ok = n = 0
    with open(log_path, "w") as log:
        for k in range(n_masks):
            f, M = rnd.randrange(16), rnd.randrange(1, 0xFFFF)
            for readout, masks in (("sum", {"e1": M, "x": pass_a}), ("cout", {"e1": M, "e2": PASS_C, "x": pass_b})):
                base = t.write(masks)
                buf = bytearray(base)
                v = set_cells(buf, c0, enc(f), lutpatch.header_sum(base))
                lutpatch.patch_crc(buf, rbfgeom.infer(base))
                lutpatch.set_header_sum(buf, v % (1 << 32))
                data = bytes(buf)
                errs = gate.check(t.zero, data, [t.les[i] for i in t.luts])
                if errs:
                    raise SystemExit(f"gate refused: {errs}")
                path = os.path.join(OUT, "arith", f"lo_both_{readout}_{f:04b}_{M:04X}.rbf")
                open(path, "wb").write(data)
                got = table(path)

                def want(A, B, C, D):
                    cin = f >> (A + 2 * B) & 1
                    return M >> (C + 2 * B + 4 * cin + (8 * D if readout == "sum" else 0)) & 1
                wrong = [ds for ds, val in got.items() if val != want(*ds)]
                n += 1
                ok += not wrong
                log.write(json.dumps(dict(f=f, M=M, readout=readout,
                                          wrong=["".join(map(str, w)) for w in wrong])) + "\n")
                print(f"  f = {f:04b}, M = {M:04X}, {readout:4s}: " + ("PASS" if not wrong else f"FAIL {len(wrong)}/16"),
                      flush=True)
    print("  control: D5 low, ok" if not any(table(control).values()) else "  control FAILED")
    print(f"\n{ok}/{n} readouts match the model. Log: {log_path}")
    return 0 if ok == n else 1


if __name__ == "__main__":
    arg = sys.argv[1:]
    sys.exit(chain3() if arg == ["chain3"] else both() if arg == ["both"] else main())
