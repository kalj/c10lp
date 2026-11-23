#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test: a carry-chain counter (templates/cnt4c) rewritten into other machines.

Arithmetic-LE model (carrytest.py): sum = M[a + 2b + 4cin + 8d], cout = M[a + 2b + 4cin].
LE i: a = s[i], b = A (enable), d = D (held at 1), cin = cout of LE i-1 (0 for LE 0).
LE 0 is a fixed chain start; its cells are written directly with input order (2, 3, 0, 1)
(a -> p2, b -> p3, cin -> p0, d -> p1, as LEs 1 and 2 have).  Variants: up counter (6688/5AA0,
the standard masks the model predicts), down counter (6644/5A50), 4 random machines.  60
clocked steps each, reading s[2] and s[3] (D3 selects); LUT-only, gate-checked.

  cnt4ctest.py [TEMPLATE]     default cnt4c; cnt4c_x22y12 / cnt4c_x30y20 are the same design pinned elsewhere
"""
from __future__ import annotations

import json
import os
import random
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
SEL = sum(((m >> 1 & 1) if m >> 2 & 1 else (m & 1)) << m for m in range(16))   # c ? b : a
A0_ORDER = (2, 3, 0, 1)


def step(ms, s, en, d=1):
    c, n = 0, 0
    for i in range(4):
        idx = (s >> i & 1) + 2 * en + 4 * c
        n |= (ms[i] >> (idx + 8 * d) & 1) << i
        c = ms[i] >> idx & 1
    return n


def write(t, ms) -> bytes:
    base = t.write({"a1": ms[1], "a2": ms[2], "a3": ms[3], "lut_out": SEL})
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    cells = lutpos._predict_phys(*t.les["a0"])
    want = sum((ms[0] >> i & 1) << lutpos.permute(i, A0_ORDER) for i in range(16))
    for i, (fr, p, b) in enumerate(cells):
        off = 32 + fr * 255 + p
        if (buf[off] >> b & 1) != (want >> i & 1):
            buf[off] ^= 1 << b
            v += lutpos.header_weight(fr, p, b) * (1 if buf[off] >> b & 1 else -1)
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    data = bytes(buf)
    errs = gate.check(t.zero, data, [t.les[i] for i in t.luts])
    if errs:
        raise SystemExit(f"gate refused: {errs}")
    return data


def main() -> int:
    tname = sys.argv[1] if len(sys.argv) > 1 else "cnt4c"
    t = tpatch.Template(tname, partial=True)
    rnd = random.Random(44)
    variants = [("up", [0x6688, 0x5AA0, 0x5AA0, 0x5AA0]), ("down", [0x6644, 0x5A50, 0x5A50, 0x5A50])]
    for k in range(4):
        m0 = rnd.randrange(0x10000)
        m0 = sum((m0 >> (i & ~4) & 1) << i for i in range(16))      # LE 0 must ignore input c
        variants.append((f"random{k}", [m0] + [rnd.randrange(0x10000) for _ in range(3)]))
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    os.makedirs(os.path.join(OUT, "arith"), exist_ok=True)
    log_path = os.path.join(OUT, time.strftime(f"cnt4ctest_{tname}_%Y%m%d_%H%M%S.jsonl"))

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
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")

    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    load(control)
    if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
        raise SystemExit("STOP: all-zero control did not hold D5 low")
    bench.cmd("I")
    print("  control: D5 low, ok")
    ok = 0
    with open(log_path, "w") as log:
        for name, ms in variants:
            path = os.path.join(OUT, "arith", f"lo_{tname}_{name}.rbf")
            open(path, "wb").write(write(t, ms))
            load(path)
            s, wrong, seq = 0, [], []
            read(1, 0, 0, 1)
            for k in range(60):
                en = rnd.randrange(2) if name.startswith("random") else (1 if rnd.random() < 0.85 else 0)
                read(en, 0, 0, 1)
                s = step(ms, s, en)
                seq.append(s)
                read(en, 1, 0, 1)                           # rising edge, D held at 1
                for c in (0, 1):
                    if read(en, 1, c, 1) != (s >> (3 if c else 2) & 1):
                        wrong.append(k)
                read(en, 0, 0, 1)
            bench.cmd("I")
            ok += not wrong
            log.write(json.dumps(dict(variant=name, masks=[f"{m:04X}" for m in ms], wrong=wrong[:10])) + "\n")
            print(f"  {name:8s} {' '.join(f'{m:04X}' for m in ms)}: " + ("PASS" if not wrong else
                  f"FAIL at steps {sorted(set(wrong))[:6]}") + f"  (states {seq[:12]} ...)", flush=True)
    load(control)
    print("  control: D5 low, ok" if not any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4) else "  control FAILED")
    bench.cmd("I")
    print(f"\n{ok}/{len(variants)} counter variants correct. Log: {log_path}")
    return 0 if ok == len(variants) else 1


if __name__ == "__main__":
    sys.exit(main())
