#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test: M9K RAM with initial contents written by m9kpatch.py (design ram:, q[0] read).

Counter a (clock D2, enable D1) addresses a 9x512 single-port RAM; D4 = write enable, D3 = data,
D5 = q[0], read-during-write returns the old data.  Initial contents: random, written only by
the model into the Quartus zero-content base (gate: exactly those M9K cells).  Pass 1 reads all
512 words, pass 2 writes a new random bit everywhere (and reads the old one), pass 3 reads the
new contents back.  Stops at the first wrong reading.

  ramtest.py
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


def main() -> int:
    zero = xdev.Job("c10_016", f"ram:{SITE}:zero", (0, 0, 0), "vidorlo").name
    init = [w & 1 for w in xdev.rom_words("r11")]
    data, cells = M.write(SITE, init, (9, 512), zero, 1)
    errs = gate.check(xdev.load(M.OUT, zero), data, [], extra_cells=cells)
    if errs:
        raise SystemExit(f"gate refused {errs}")
    path = os.path.join(M.OUT, "m9k", "lo_ram_r11.rbf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    print(f"initial contents: {len(cells)} bits written by the model; gate PASS")
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")

    def read(A, B, C, D):
        got, seen = bench.read((A, B, C, D))
        if seen != f"{A}{B}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")

    control = os.path.join(M.OUT, "lo_quartus_0000.rbf")

    def control_ok():
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    control_ok()
    load(path)
    mem, a = list(init), 0
    rnd = random.Random(12)
    newbits = [rnd.randrange(2) for _ in range(512)]
    results = {}
    read(1, 0, 0, 0)
    for name, we in (("read initial", 0), ("write new", 1), ("read back", 0)):
        wrong = None
        for k in range(512):
            c = newbits[a] if we else 0
            read(1, 0, c, we)
            addr = a
            want = mem[addr]                          # read-during-write: old data
            if we:
                mem[addr] = c
            a = (a + 1) % 512
            if read(1, 1, c, we) != want:
                wrong = dict(step=k, addr=addr, want=want)
                break
            read(1, 0, c, we)
        results[name] = wrong
        print(f"  {name:12s}: " + ("PASS (512 words)" if wrong is None else f"FAIL {wrong}"), flush=True)
        if wrong:
            break
    bench.cmd("I")
    control_ok()
    log_path = os.path.join(M.OUT, time.strftime("ramtest_%Y%m%d_%H%M%S.json"))
    json.dump(results, open(log_path, "w"))
    ok = all(v is None for v in results.values()) and len(results) == 3
    print(f"\n{'all 3 passes correct' if ok else 'FAILED'}. Log: {log_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
