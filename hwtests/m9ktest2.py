#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test of m9kpatch.py layouts (design rom2:, D5 = parity of the stored word).

For each layout: random contents written only by the model into the Quartus zero-content base
(gate: exactly the model's M9K cells), plus Quartus's own random 36x256 build as a timing
control.  Up to 2,048 clocked steps with a random enable; D5 must equal the parity of
mem[address register].  Controls before each file and at the end; stops at the first wrong reading.

  m9ktest2.py
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

SITE = "X13_Y10"
LAYOUTS = [(36, 256), (1, 8192), (2, 4096), (9, 1024)]


def nm(w, d, spec):
    return xdev.Job("c10_016", f"rom2:{w}x{d}:{SITE}:{spec}", (0, 0, 0), "vidorlo").name


def main() -> int:
    files = [("quartus_36x256_r1", xdev.load(M.OUT, nm(36, 256, "r1")), (36, 256), xdev.rom_words("r1", 36, 256))]
    for w, d in LAYOUTS:
        words = xdev.rom_words("r9", w, d)
        data, cells = M.write(SITE, words, (w, d), nm(w, d, "zero"), w)
        errs = gate.check(xdev.load(M.OUT, nm(w, d, "zero")), data, [], extra_cells=cells)
        if errs:
            raise SystemExit(f"{w}x{d}: gate refused {errs}")
        files.append((f"patched_{w}x{d}_r9", data, (w, d), words))
    print("all patched files pass the gate")
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    os.makedirs(os.path.join(M.OUT, "m9k"), exist_ok=True)
    control = os.path.join(M.OUT, "lo_quartus_0000.rbf")
    log_path = os.path.join(M.OUT, time.strftime("m9ktest2_%Y%m%d_%H%M%S.jsonl"))

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")

    def read(A, B):
        got, seen = bench.read((A, B, 1, 1))
        if seen != f"{A}{B}11":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")

    def control_ok():
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    rnd = random.Random(10)
    ok = 0
    with open(log_path, "w") as log:
        for label, data, (w, d), words in files:
            control_ok()
            path = os.path.join(M.OUT, "m9k", f"lo_{label}.rbf")
            open(path, "wb").write(data)
            load(path)
            a, wrong, steps = 0, None, min(d, 2048)
            read(1, 0)
            for step in range(steps):
                en = 1 if rnd.random() < 0.9 else 0
                read(en, 0)
                addr = a
                a = (a + en) % d
                want = bin(words[addr]).count("1") & 1
                if read(en, 1) != want:                 # after the rising edge
                    wrong = dict(step=step, addr=addr, want=want)
                    break
                read(en, 0)
            bench.cmd("I")
            ok += wrong is None
            log.write(json.dumps(dict(file=label, steps=steps, wrong=wrong)) + "\n")
            log.flush()
            print(f"  {label:20s} " + (f"PASS ({steps} steps)" if wrong is None else f"FAIL {wrong}"), flush=True)
            if wrong:
                print("STOP: first wrong reading")
                break
        control_ok()
    print(f"\n{ok}/{len(files)} files correct. Log: {log_path}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
