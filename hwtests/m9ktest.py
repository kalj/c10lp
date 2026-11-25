#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test of m9kpatch.py: ROM contents written without Quartus (approved 2026-11-23).

Design rom: (xdev.py): a 9-bit counter a (clock D2, enable D1) addresses a 9x512 M9K ROM; the
M9K registers the address on the clock edge, so after an edge q = mem[a as it was before the
edge].  D5 = q[0..3] selected by (D3, D4).  For each file: the all-zero control first, then 520
clocked steps with a random enable, reading q[0..3] after every edge.  Stops at the first wrong
reading.  Every file must pass gate.py with exactly the model's M9K cells allowed.

  m9ktest.py board
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
import m9kpatch as M  # noqa: E402
import xdev  # noqa: E402

SITE = "X13_Y15"
STEPS = 520


def files():
    """(label, bytes, words): Quartus's own r1 (timing control), then two patched contents."""
    res = []
    q = xdev.load(M.OUT, M.name(SITE, "r1"))
    res.append(("quartus_r1", q, [w & 15 for w in xdev.rom_words("r1")]))
    for label, words in (("patched_r7", [w & 15 for w in xdev.rom_words("r7")]),
                         ("patched_count", [w & 15 for w in range(512)])):
        data, _ = M.write(SITE, words)
        res.append((label, data, words))
    return res


def main() -> int:
    base = xdev.load(M.OUT, M.name(SITE, "zero"))
    fs = files()
    for label, data, words in fs:                       # gate every file before touching the board
        _, cells = M.write(SITE, words)
        errs = gate.check(base, data, [], extra_cells=cells)
        if errs:
            raise SystemExit(f"{label}: gate refused: {errs}")
        if label.startswith("quartus") and data != M.write(SITE, words)[0]:
            raise SystemExit("model doesn't reproduce the Quartus control file")
    print("all files pass the gate (only the model's M9K content cells differ from the base)")

    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    os.makedirs(os.path.join(M.OUT, "m9k"), exist_ok=True)
    control = os.path.join(M.OUT, "lo_quartus_0000.rbf")
    log_path = os.path.join(M.OUT, time.strftime("m9ktest_%Y%m%d_%H%M%S.jsonl"))

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")

    def read(A, B, C, D):
        got, seen = bench.read((A, B, C, D))
        if seen != f"{A}{B}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {A}{B}{C}{D}")
        return int(got == "h")

    def control_ok():
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    rnd = random.Random(9)
    ok = 0
    with open(log_path, "w") as log:
        for label, data, words in fs:
            control_ok()
            path = os.path.join(M.OUT, "m9k", f"lo_{label}.rbf")
            open(path, "wb").write(data)
            load(path)
            a = 0
            wrong = None
            read(1, 0, 0, 0)
            for step in range(STEPS):
                en = 1 if rnd.random() < 0.8 else 0
                read(en, 0, 0, 0)
                read(en, 1, 0, 0)                       # rising edge: M9K samples a, then a += en
                addr = a
                a = (a + en) % 512
                for c in (0, 1):
                    for d in (0, 1):
                        bit = 2 * c + d
                        want = words[addr] >> bit & 1
                        if read(en, 1, c, d) != want:
                            wrong = dict(step=step, addr=addr, bit=bit, want=want)
                            break
                    if wrong:
                        break
                read(en, 0, 0, 0)
                if wrong:
                    break
            bench.cmd("I")
            ok += wrong is None
            log.write(json.dumps(dict(file=label, wrong=wrong, steps=STEPS)) + "\n")
            log.flush()
            print(f"  {label:14s} " + (f"PASS ({STEPS} steps, {STEPS * 4} readings)" if wrong is None
                                       else f"FAIL {wrong}"), flush=True)
            if wrong:
                print("STOP: first wrong reading")
                break
        control_ok()
    print(f"\n{ok}/{len(fs)} files correct. Log: {log_path}")
    return 0 if ok == len(fs) else 1


if __name__ == "__main__":
    sys.exit(main())
