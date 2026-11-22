#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Full-speed silicon test of tpatch.py: templates/div24 on the 48 MHz clock.

Variants (all written by tpatch.py, none compiled by Quartus) change both the
counting logic and the D5 output function.  Each has a known D5 frequency at
48 MHz; the test bench polls D5 over serial and fits the frequency from the
edge times.  D1 is the count enable (carry into group 0), so with D1 = 0 the
counter must freeze, except in the "free" variant, which ignores D1.

Timing (quartus_sta on the pinned base, 48 MHz constraint): setup slack
16.8 ns, Fmax 250 MHz (slow 85C model).

  div24test.py write | board
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
import hwtest  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(xdev.HERE, "out")
DIR = os.path.join(OUT, "div24")
F = 48e6
SECONDS = 4.0
TOL = 0.01


def mask(fn) -> int:
    return sum(fn(i & 1, i >> 1 & 1, i >> 2 & 1, i >> 3 & 1) << i for i in range(16))


def counter(low: str, free: bool) -> dict[str, int]:
    """Group LUT masks: binary (or mod-3 in bits 0..1 of group 0); free = ignore D1."""
    M = {}
    for j in range(8):
        b0, b1, b2 = 3 * j, 3 * j + 1, 3 * j + 2
        en = (lambda c: 1) if (free and j == 0) else (lambda c: c)
        if j == 0 and low == "mod3":
            # bits 1..0 count 0 -> 1 -> 2 -> 0; carry out of them when (s1, s0) = 2
            M[f"n{b0}"] = mask(lambda s, c, s1, s2, en=en: (1 - s) * (1 - s1) if en(c) else s)
            M[f"n{b1}"] = mask(lambda s, c, s0, s2, en=en: s0 if en(c) else s)
            M[f"n{b2}"] = mask(lambda s, c, s0, s1, en=en: s ^ (en(c) & s1))
            M["cy0"] = mask(lambda c, s0, s1, s2, en=en: en(c) & s1 & s2)
        else:
            M[f"n{b0}"] = mask(lambda s, c, x, y, en=en: s ^ en(c))
            M[f"n{b1}"] = mask(lambda s, c, s0, y, en=en: s ^ (en(c) & s0))
            M[f"n{b2}"] = mask(lambda s, c, s0, s1, en=en: s ^ (en(c) & s0 & s1))
            if j < 7:
                M[f"cy{j}"] = mask(lambda c, s0, s1, s2, en=en: en(c) & s0 & s1 & s2)
    return M


OUTS = {"s23": mask(lambda a, b, c, d: a), "s21": mask(lambda a, b, c, d: b),
        "s19": mask(lambda a, b, c, d: c)}


def freq(low: str, bit: int) -> float:
    # binary: bit n toggles at F / 2^(n+1); mod-3 low: bits >= 2 form a binary counter at F/3.
    return F / 2 ** (bit + 1) if low == "bin" else (F / 3) / 2 ** (bit - 1)


# name: (low counter, ignore D1?, output bit)
VARIANTS = {
    "bin_s23": ("bin", False, 23), "bin_s21": ("bin", False, 21), "bin_s19": ("bin", False, 19),
    "mod3_s23": ("mod3", False, 23), "mod3_s21": ("mod3", False, 21),
    "free_s21": ("bin", True, 21),
}


def masks(v) -> dict[str, int]:
    low, free, bit = VARIANTS[v]
    M = counter(low, free)
    M["lut_out"] = OUTS[f"s{bit}"]
    return M


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    a = ap.parse_args()
    t = tpatch.Template("div24")
    les = [t.les[i] for i in t.luts]

    if a.cmd == "write":
        os.makedirs(DIR, exist_ok=True)
        for v in VARIANTS:
            open(os.path.join(DIR, f"lo_div24_{v}.rbf"), "wb").write(t.write(masks(v)))
        print(f"{len(VARIANTS)} files written and gated -> {DIR}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    log_path = os.path.join(OUT, time.strftime("div24test_%Y%m%d_%H%M%S.jsonl"))

    def sample(d1: int, seconds: float):
        bench.cmd("S " + f"{d1}111")
        ts, vs = [], []
        end = time.time() + seconds
        while time.time() < end:
            r = bench.cmd("R")                   # "D5=1 D1..4=1111"
            if r.split("=")[2] != f"{d1}111":
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {r}")
            ts.append(time.time())
            vs.append(r[3] == "1")
        edges = [ts[i] for i in range(1, len(vs)) if vs[i] != vs[i - 1]]
        rate = len(ts) / seconds
        if len(edges) < 3:
            return 0.0, len(edges), rate
        # Least-squares slope of edge time vs edge index = half period.
        n = len(edges)
        mx, my = (n - 1) / 2, sum(edges) / n
        slope = sum((i - mx) * (e - my) for i, e in enumerate(edges)) / sum((i - mx) ** 2 for i in range(n))
        return 1 / (2 * slope), n, rate

    ok = fail = 0
    with open(log_path, "w") as log:
        for v, (low, free, bit) in VARIANTS.items():
            path = os.path.join(DIR, f"lo_div24_{v}.rbf")
            errs = gate.check(t.zero, open(path, "rb").read(), les)
            if errs:
                print(f"STOP: {v} fails the gate: {errs}")
                return 1
            bench.cmd("I")
            rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
            if rc:
                print(f"STOP: load of {v} failed (exit {rc})")
                return 1
            bench.cmd("A")
            want = freq(low, bit)
            f1, n1, rate = sample(1, SECONDS)
            f0, n0, _ = sample(0, 2.0)
            bench.cmd("I")
            good1 = abs(f1 - want) / want < TOL
            good0 = (abs(f0 - want) / want < TOL) if free else n0 == 0
            ok += good1 and good0
            fail += not (good1 and good0)
            log.write(json.dumps(dict(variant=v, want_hz=want, got_hz=f1, edges=n1, d1_low_hz=f0,
                                      d1_low_edges=n0, poll_hz=rate)) + "\n")
            log.flush()
            print(f"  {v:9s} D1=1: {f1:8.4f} Hz (expect {want:8.4f}, {n1} edges)  D1=0: "
                  + (f"{f0:.4f} Hz" if free else f"{n0} edges (expect frozen)")
                  + f"  poll {rate:.0f}/s  " + ("PASS" if good1 and good0 else "FAIL"), flush=True)
    print(f"\n{ok}/{ok + fail} variants at the expected frequency. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
