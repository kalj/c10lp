#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test of tpatch.py on templates/ring32 (32 state bits, 43 LUTs, 4 LABs).

Every machine is written by tpatch.py from the one pinned base build; none was
compiled by Quartus.  Each step reads D5 for the four (D3, D4) combinations
with the clock low, applies random (D1, D3), clocks D2 and reads again.

  ring32test.py write | board
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
import hwtest  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(xdev.HERE, "out")
DIR = os.path.join(OUT, "ring32")
STEPS = 100


def mask(fn) -> int:
    return sum(fn(i & 1, i >> 1 & 1, i >> 2 & 1, i >> 3 & 1) << i for i in range(16))


def lut(m, a, b, c, d) -> int:
    return m >> (a | b << 1 | c << 2 | d << 3) & 1


def sim_next(M, s, A, C):
    bit = lambda i: s >> (i % 32) & 1
    return sum(lut(M[f"nx{i}"], bit(i), bit(i - 1), bit(i + 11), A if i % 2 == 0 else C) << i
               for i in range(32))


def sim_out(M, s, C, D):
    o = [lut(M[f"ob{j}"], *(s >> (4 * j + k) & 1 for k in range(4))) for j in range(8)]
    p0, p1 = lut(M["pa"], *o[:4]), lut(M["pb"], *o[4:])
    return lut(M["lut_out"], p0, p1, C, D)


PAR = mask(lambda a, b, c, d: a ^ b ^ c ^ d)


def observe(M, rnd=None):
    for j in range(8):
        M.setdefault(f"ob{j}", PAR if rnd is None else rnd.randrange(1, 0xFFFF))
    M.setdefault("pa", PAR if rnd is None else rnd.randrange(1, 0xFFFF))
    M.setdefault("pb", PAR if rnd is None else rnd.randrange(1, 0xFFFF))
    # (C, D): (0,0) p0, (0,1) p1, (1,0) p0^p1, (1,1) p0&p1
    M["lut_out"] = mask(lambda p0, p1, c, d: (p0 & p1 if d else p0 ^ p1) if c else (p1 if d else p0))
    return M


def machines(seed):
    r = random.Random(seed)
    res = {}
    M = {"nx0": mask(lambda s, b, c, x: x)}                     # serial in from D1
    M.update({f"nx{i}": mask(lambda s, b, c, x: b) for i in range(1, 32)})
    res["shift"] = observe(M)
    res["xorring"] = observe({f"nx{i}": mask(lambda s, b, c, x: b ^ (c & x) ^ (i == 0)) for i in range(32)})
    for k in range(2):
        res[f"random{k}"] = observe({f"nx{i}": r.randrange(0x10000) for i in range(32)})
    res["random_obs"] = observe({f"nx{i}": r.randrange(0x10000) for i in range(32)}, rnd=r)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--seed", type=int, default=32)
    a = ap.parse_args()
    t = tpatch.Template("ring32")
    les = [t.les[i] for i in t.luts]
    ms = machines(a.seed)
    if a.cmd == "write":
        os.makedirs(DIR, exist_ok=True)
        for name, M in ms.items():
            open(os.path.join(DIR, f"lo_ring32_{name}.rbf"), "wb").write(t.write(M))
        print(f"{len(ms)} files written and gated -> {DIR}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    rnd = random.Random(a.seed)
    log_path = os.path.join(OUT, time.strftime("ring32test_%Y%m%d_%H%M%S.jsonl"))

    def drive(A, clk, C, D):
        got, seen = bench.read((A, clk, C, D))
        if seen != f"{A}{clk}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {A}{clk}{C}{D}")
        return int(got == "h")

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load of {os.path.basename(path)} failed (exit {rc})")
        bench.cmd("A")

    def control_ok():
        load(os.path.join(OUT, "lo_quartus_0000.rbf"))
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control lo_quartus_0000.rbf: D5 low, ok")

    control_ok()
    ok = fail = 0
    with open(log_path, "w") as log:
        for name, M in ms.items():
            path = os.path.join(DIR, f"lo_ring32_{name}.rbf")
            errs = gate.check(t.zero, open(path, "rb").read(), les)
            if errs:
                print(f"STOP: {name} fails the gate: {errs}")
                return 1
            load(path)
            errors, s, seen = [], 0, {0}
            A_ = C = 1
            for step in range(STEPS):
                for C_, D_ in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    if drive(A_, 0, C_, D_) != sim_out(M, s, C_, D_):
                        errors.append(f"read s={s:08X} C={C_} D={D_} @{step}")
                A_, C = rnd.randrange(2), rnd.randrange(2)
                drive(A_, 0, C, 1)
                s = sim_next(M, s, A_, C)
                seen.add(s)
                if drive(A_, 1, C, 1) != sim_out(M, s, C, 1):
                    errors.append(f"edge -> s={s:08X} @{step}")
                drive(A_, 0, C, 1)
            bench.cmd("I")
            ok += not errors
            fail += bool(errors)
            log.write(json.dumps(dict(machine=name, errors=errors, states=len(seen))) + "\n")
            log.flush()
            print(f"  {name:10s} distinct states {len(seen):3d}: "
                  + ("PASS" if not errors else f"FAIL {errors[:3]}"), flush=True)
    control_ok()
    print(f"\n{ok}/{ok + fail} machines correct over {STEPS} clocked steps. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
