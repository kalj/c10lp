#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon tests of the bit classes mapped offline (user-approved 2026-11-23): periphery I/O, PLL
counters, LE output select.  Same rules as every other board test: SRAM loads only, vidorlo
pin set (Q = D5 at minimum drive), all-zero control before and after, gate.py on every file with
exactly the declared cells, stop at the first failed load or readback mismatch.

  A  bus hold vs pull-up on D1..D4 (lut:6996 base; periph.py bushold=1 on one pin at a time):
     drive the pin low, release it (bench disarmed), read it back: pull-up -> 1, bus hold -> 0.
  B  PLL counters (pllcnt:1:1 base: 48 MHz -> 26-bit counter, D5 = bit 25): patch M / C0 in the
     periphery and measure D5's period.  The bench stays disarmed (D1..D4 not driven).
  C  LE output select (oreg:4:0 base): flip the direct-line (+9) or second-path (+8) comb/reg bit
     of the source LE; then D5 = 0 for every input, versus D5 = comb ^ reg in the base.

  newclass_test.py [A] [B] [C]      default: all three
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpos  # noqa: E402
import periph  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "newclass")
PINS = ["PIN_N3", "PIN_P3", "PIN_R3", "PIN_T3"]          # D1..D4
PLL_BASES = {"N": 193, "M": 175, "C0": 157}


def pll_changes(buf: bytes, counts: dict) -> list:
    """Logical periphery changes setting counters to count (even: low = high = count/2; odd: low = count//2,
    high = count - low, odd flag set), bypass off."""
    L = periph.logical(buf, rbfgeom.infer(buf))
    ch = []
    for name, c in counts.items():
        b = PLL_BASES[name]
        low, high = c // 2, c - c // 2
        want = {}
        for i in range(8):
            want[b + i] = low >> i & 1
            want[b + 9 + i] = high >> i & 1
        want[b + 8] = int(low != high)
        want[b + 17] = 0
        ch += [(0, p, 1, v) for p, v in want.items() if (L[0][p] >> 1 & 1) != v]
    return ch


def main() -> int:
    which = set(sys.argv[1:]) or {"A", "B", "C"}
    os.makedirs(DIR, exist_ok=True)
    files = []          # (test, label, path, info)

    def add(test, label, base_name, data, periph_bits=(), extra=()):
        base = xdev.load(OUT, base_name)
        errs = gate.check(base, data, [], extra_cells=extra, periph_bits=periph_bits)
        if errs:
            raise SystemExit(f"{label}: gate refused: {errs}")
        path = os.path.join(DIR, f"lo_{label}.rbf")
        open(path, "wb").write(data)
        return path

    if "A" in which:
        bn = "c10_016__lut6996_X10Y10N0__vidorlo"
        base = xdev.load(OUT, bn)
        files.append(("A", "A_base", os.path.join(OUT, bn + ".rbf"), None))
        for i, pin in enumerate(PINS):
            ch = periph.setting(pin, "bushold", 1)
            files.append(("A", f"A_bushold_D{i + 1}", add("A", f"A_bushold_D{i + 1}", bn, periph.apply(base, ch),
                                                         periph_bits=[c[:3] for c in ch]), i))
    if "B" in which:
        bn = "c10_016__pllcnt11_X0Y0N0__vidorlo"
        base = xdev.load(OUT, bn)
        files.append(("B", "B_base_48MHz", os.path.join(OUT, bn + ".rbf"), 48.0))
        files.append(("B", "B_quartus_24MHz", os.path.join(OUT, "c10_016__pllcnt12_X0Y0N0__vidorlo.rbf"), 24.0))
        for label, counts in (("M10_C10", {"M": 10, "C0": 10}), ("M13_C13", {"M": 13, "C0": 13}),
                              ("M8_C16", {"M": 8, "C0": 16}), ("M11_C22", {"M": 11, "C0": 22}),
                              ("M12_C9", {"M": 12, "C0": 9})):
            ch = pll_changes(base, counts)
            f = 48.0 * counts["M"] / counts["C0"]
            files.append(("B", f"B_{label}", add("B", f"B_{label}", bn, periph.apply(base, ch),
                                                 periph_bits=[c[:3] for c in ch]), f))
    if "C" in which:
        bn = "c10_016__oreg-4-0_X10Y10__vidorlo"
        base = xdev.load(OUT, bn)
        c = lutpos._predict_phys(10, 10, 4)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        files.append(("C", "C_base", os.path.join(OUT, bn + ".rbf"), "comb^reg"))
        for label, df, want in (("C_direct_reg", 9, 0), ("C_second_comb", 8, 1)):
            buf = bytearray(base)
            cell = (f0 + df, lo, bit)
            off = 32 + cell[0] * 255 + cell[1]
            assert (buf[off] >> bit & 1) != want
            buf[off] ^= 1 << bit
            import lutpatch
            v = lutpatch.header_sum(base) + lutpos.header_weight(*cell) * (1 if want else -1)
            lutpatch.patch_crc(buf, rbfgeom.infer(base))
            lutpatch.set_header_sum(buf, v % (1 << 32))
            files.append(("C", label, add("C", label, bn, bytes(buf), extra=[cell]), "zero"))
    print(f"{len(files)} files, all patched ones pass the gate")

    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    control = os.path.join(OUT, "lo_quartus_0000.rbf")

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc}) for {path}")

    def control_ok():
        load(control)
        bench.cmd("A")
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    def rd():
        r = bench.cmd("R")
        return int(r[3]), r.split("=")[2]

    log = []
    ok_all = True
    control_ok()
    for test, label, path, info in files:
        load(path)
        if test == "A":
            res = {}
            for i in range(4):
                seen = []
                for lvl in (0, 1, 0, 1, 0):
                    bench.cmd("A")
                    bench.read(tuple(lvl if j == i else 1 for j in range(4)))
                    bench.cmd("I")
                    time.sleep(0.01)
                    seen.append(int(rd()[1][i]))
                res[f"D{i + 1}"] = seen
            want = {f"D{i + 1}": ([0, 1, 0, 1, 0] if info == i else [1, 1, 1, 1, 1]) for i in range(4)}
            ok = res == want
            print(f"  {label:18s}: released levels {res} -> {'PASS' if ok else 'FAIL, expected ' + str(want)}", flush=True)
        elif test == "B":
            t0 = time.time()
            prev, edges = rd()[0], []
            while time.time() - t0 < 12.0:
                v = rd()[0]
                if v != prev:
                    edges.append(time.time())
                    prev = v
            if len(edges) >= 3:
                half = (edges[-1] - edges[0]) / (len(edges) - 1)
                f = 2 ** 25 / half / 1e6
            else:
                f = None
            ok = f is not None and abs(f - info) / info < 0.05
            print(f"  {label:18s}: predicted {info:6.2f} MHz, measured "
                  f"{('%.2f' % f) if f else 'n/a'} MHz ({len(edges)} edges) -> {'PASS' if ok else 'FAIL'}", flush=True)
            res = dict(pred=info, measured=f, edges=len(edges))
        else:
            rnd = random.Random(7)
            bench.cmd("A")
            q = None
            wrong = 0
            n = 0
            for step in range(40):
                a, cc, d = rnd.randrange(2), rnd.randrange(2), rnd.randrange(2)
                for clk in (0, 1):
                    got, seen = bench.read((a, clk, cc, d))
                    if seen != f"{a}{clk}{cc}{d}":
                        bench.cmd("I")
                        raise SystemExit(f"STOP: D1..D4 read back {seen}")
                    comb = a ^ cc ^ d
                    if clk == 1:
                        q = comb
                    if q is None:
                        continue
                    want = (comb ^ q) if info == "comb^reg" else 0
                    n += 1
                    wrong += (got == "h") != bool(want)
                bench.read((a, 0, cc, d))
            bench.cmd("I")
            ok = wrong == 0
            print(f"  {label:18s}: {n} readings, {wrong} wrong (expect D5 = {info}) -> {'PASS' if ok else 'FAIL'}", flush=True)
            res = dict(readings=n, wrong=wrong)
        bench.cmd("I")
        log.append(dict(test=test, file=label, ok=ok, result=res))
        ok_all &= ok
        if not ok:
            print("STOP: first wrong result")
            break
    control_ok()
    path = os.path.join(OUT, time.strftime("newclass_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(path, "w"), indent=1)
    print(f"\n{sum(e['ok'] for e in log)}/{len(log)} files correct. Log: {path}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
