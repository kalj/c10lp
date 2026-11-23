#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon tests of flip-flop control enables and the carry-in select (user-approved 2026-11-23).

  F  ffe2:KIND:F base (registers r0..r3 in LEs 0..3 of X10Y10, D_i = LUT_i(A, D), clock B, control C
     on all four; Q = r0 ^ r1 ^ r2 ^ r3 ^ C).  Patched: clear the per-register enable bit
     (ff_control.json: sync enable for sclr/sload, async-clear enable for aclr) of some registers.
     K = 0 (no register enabled, LAB line still driven) is a configuration Quartus never emits;
     the subsets are byte-identical to Quartus's own ffe2:KIND:K builds (checked offline).
     Expected D5 from a simulation of the design with those registers ignoring C.
  K  templates/cnt4c up counter; patched: set one LE's carry-in select (active low) to 1.  Two
     hypotheses (that LE's carry-in reads constant 0 / constant 1) are simulated; the run reports
     which one the board follows.

Same rules as the other board tests: SRAM loads, vidorlo pins, gate.py with exactly the patched
cells, all-zero control before and after, stop at the first failed load or readback mismatch.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cnt4ctest  # noqa: E402
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "ffctl")
LUTS = [lambda a, d: a ^ d, lambda a, d: a & d, lambda a, d: a | d, lambda a, d: 1 - (a ^ d)]   # 6666 8888 EEEE 9999


def flip(base: bytes, cells) -> bytes:
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    for f, p, b in cells:
        off = 32 + f * 255 + p
        buf[off] ^= 1 << b
        v += lutpos.header_weight(f, p, b) * (1 if buf[off] >> b & 1 else -1)
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    return bytes(buf)


def ff_cell(kind: str, i: int):
    t = json.load(open(os.path.join(HERE, "ff_control.json")))
    c0 = lutpos._predict_phys(10, 10, 0)
    f0, lo, bit = min(c[0] for c in c0), min(c[1] for c in c0), c0[0][2]
    col, df = (t["aclr_enable"], 10) if kind == "aclr" else (t["sync_enable"], 11)
    return (f0 + df, lo + col[i], bit)


class FFSim:
    def __init__(self, kind, enabled):
        self.kind, self.en, self.r = kind, enabled, [0] * 4

    def apply(self, a, b, c, d, edge):
        if edge:
            nxt = []
            for i in range(4):
                v = LUTS[i](a, d)
                if self.en[i] and c and self.kind == "sclr":
                    v = 0
                if self.en[i] and c and self.kind == "sload":
                    v = a
                nxt.append(v)
            self.r = nxt
        if self.kind == "aclr":
            self.r = [0 if (self.en[i] and not c) else self.r[i] for i in range(4)]
        return self.r[0] ^ self.r[1] ^ self.r[2] ^ self.r[3] ^ c


def main() -> int:
    os.makedirs(DIR, exist_ok=True)
    files = []
    for kind in ("sclr", "sload", "aclr"):
        bn = f"c10_016__ffe2-{kind}-F_X10Y10__vidorlo"
        base = xdev.load(OUT, bn)
        files.append(("F", f"{kind}_K=F", os.path.join(OUT, bn + ".rbf"), (kind, [1, 1, 1, 1])))
        for k in (0x0, 0x5, 0xA):
            en = [k >> i & 1 for i in range(4)]
            cells = [ff_cell(kind, i) for i in range(4) if not en[i]]
            data = flip(base, cells)
            errs = gate.check(base, data, [], extra_cells=cells)
            if errs:
                raise SystemExit(f"{kind} K={k:X}: gate refused {errs}")
            path = os.path.join(DIR, f"lo_{kind}_K{k:X}.rbf")
            open(path, "wb").write(data)
            files.append(("F", f"{kind}_K={k:X}", path, (kind, en)))
    t = tpatch.Template("cnt4c", partial=True)
    up = [0x6688, 0x5AA0, 0x5AA0, 0x5AA0]
    base = cnt4ctest.write(t, up)
    path = os.path.join(DIR, "lo_cnt4c_up.rbf")
    open(path, "wb").write(base)
    files.append(("K", "carry_base", path, None))
    for le in ("a1", "a2"):
        x, y, n = t.les[le]
        c = lutpos._predict_phys(x, y, n)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        cell = (f0 - 1, lo + (1 if (n // 2) % 2 else 0), bit)
        assert not base[32 + cell[0] * 255 + cell[1]] >> bit & 1
        data = flip(base, [cell])
        errs = gate.check(t.zero, data, [t.les[i] for i in t.luts], extra_cells=[cell])
        if errs:
            raise SystemExit(f"carry {le}: gate refused {errs}")
        path = os.path.join(DIR, f"lo_cnt4c_up_cin_off_{le}.rbf")
        open(path, "wb").write(data)
        files.append(("K", f"carry_cut_{le}", path, int(le[1])))
    print(f"{len(files)} files, all patched ones pass the gate")

    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    control = os.path.join(OUT, "lo_quartus_0000.rbf")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc}) for {p}")
        bench.cmd("A")

    def read(A, B, C, D):
        got, seen = bench.read((A, B, C, D))
        if seen != f"{A}{B}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")

    def control_ok():
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    def step_forced(ms, s, en, forced_le, forced_c, d=1):
        c, nxt = 0, 0
        for i in range(4):
            if i == forced_le:
                c = forced_c
            idx = (s >> i & 1) + 2 * en + 4 * c
            nxt |= (ms[i] >> (idx + 8 * d) & 1) << i
            c = ms[i] >> idx & 1
        return nxt

    log, ok_all = [], True
    control_ok()
    for test, label, path, info in files:
        load(path)
        rnd = random.Random(31)
        if test == "F":
            kind, en = info
            sim = FFSim(kind, en)
            idle = 1 if kind == "aclr" else 0
            read(0, 0, idle, 0)
            read(0, 1, idle, 0)
            sim.apply(0, 1, idle, 0, True)
            read(0, 0, idle, 0)
            wrong = n = 0
            for _ in range(40):
                a, c, d = rnd.randrange(2), rnd.randrange(2), rnd.randrange(2)
                want = sim.apply(a, 0, c, d, False)
                n += 1
                wrong += read(a, 0, c, d) != want
                want = sim.apply(a, 1, c, d, True)
                n += 1
                wrong += read(a, 1, c, d) != want
                read(a, 0, c, d)
            ok = wrong == 0
            res = dict(readings=n, wrong=wrong, enabled=en)
            print(f"  {label:12s} enabled {en}: {n} readings, {wrong} wrong -> {'PASS' if ok else 'FAIL'}", flush=True)
        else:
            hyps = {"plain": (None, 0)} if info is None else {"cin=0": (info, 0), "cin=1": (info, 1)}
            st = {h: 0 for h in hyps}
            fails = {h: 0 for h in hyps}
            read(1, 0, 0, 1)
            for _ in range(60):
                e = 1 if rnd.random() < 0.85 else 0
                read(e, 0, 0, 1)
                for h, (le, cv) in hyps.items():
                    st[h] = step_forced(up, st[h], e, le, cv) if le is not None else cnt4ctest.step(up, st[h], e)
                read(e, 1, 0, 1)
                for c in (0, 1):
                    got = read(e, 1, c, 1)
                    for h in hyps:
                        fails[h] += got != (st[h] >> (3 if c else 2) & 1)
                read(e, 0, 0, 1)
            matching = [h for h in hyps if fails[h] == 0]
            ok = len(matching) == 1
            res = dict(mismatches=fails, follows=matching)
            print(f"  {label:12s}: mismatches per hypothesis {fails} -> "
                  + (f"follows {matching[0]}" if ok else "no unique hypothesis") + (" PASS" if ok else " FAIL"), flush=True)
        bench.cmd("I")
        log.append(dict(test=test, file=label, ok=ok, result=res))
        ok_all &= ok
        if not ok:
            print("STOP: first wrong result")
            break
    control_ok()
    lp = os.path.join(OUT, time.strftime("ffctl_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"\n{sum(e['ok'] for e in log)}/{len(log)} files correct. Log: {lp}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
