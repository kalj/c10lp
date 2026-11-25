#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test of tpatch.py on templates/cnt8 (8 state bits, 18 LUTs, 2 LABs).

Machines are given as the 18 LUT functions; a netlist simulator mirrors the
template (see templates/cnt8/top.v).  Each step the test bench reads D5 for
all four (D1, D4) combinations with the clock low (no edge), then applies
random (D1, D3, D4), clocks D2 and reads D5 again.  None of the machines was
compiled by Quartus: each is written by tpatch.py from the one pinned base.

  cnt8test.py write | board
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import hwtest  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(xdev.HERE, "out")
DIR = os.path.join(OUT, "cnt8")
STEPS = 80


def mask(fn) -> int:
    return sum(fn(i & 1, i >> 1 & 1, i >> 2 & 1, i >> 3 & 1) << i for i in range(16))


def lut(m: int, a, b, c, d) -> int:
    return m >> (a | b << 1 | c << 2 | d << 3) & 1


def sim_next(M, s: int, A: int, C: int, D: int) -> int:
    bit = lambda i: s >> i & 1
    k, n = C, 0
    for i in range(8):
        prev = bit(7) if i == 0 else bit(i - 1)
        n |= lut(M[f"nx{i}"], bit(i), prev, k, A) << i
        if i < 7:
            k = lut(M[f"ch{i}"], bit(i), k, A, D)
    return n


def sim_out(M, s: int, A: int, D: int) -> int:
    e0 = lut(M["elo"], s & 1, s >> 1 & 1, s >> 2 & 1, s >> 3 & 1)
    e1 = lut(M["ehi"], s >> 4 & 1, s >> 5 & 1, s >> 6 & 1, s >> 7 & 1)
    return lut(M["lut_out"], e0, e1, A, D)


def observe(M) -> dict:
    # D5: (A, D) = (0, 0) -> e0, (0, 1) -> e1, (1, x) -> e0 ^ e1
    M["lut_out"] = mask(lambda e0, e1, a, d: (e0 ^ e1) if a else (e1 if d else e0))
    return M


def machines(seed: int) -> dict[str, dict]:
    res = {}
    z = lambda *_: 0
    # Up counter, enable = D3 (carry in).  e0 = parity of the low nibble, e1 = s7 ^ s5.
    M = {f"nx{i}": mask(lambda s, p, k, a: s ^ k) for i in range(8)}
    M.update({f"ch{i}": mask(lambda s, k, a, d: s & k) for i in range(7)})
    M["elo"] = mask(lambda a, b, c, d: a ^ b ^ c ^ d)
    M["ehi"] = mask(lambda a, b, c, d: d ^ b)
    res["counter"] = observe(M)
    # Up/down counter: D3 = enable, D4 = 1 counts down (borrow chain).
    M = {f"nx{i}": mask(lambda s, p, k, a: s ^ k) for i in range(8)}
    M.update({f"ch{i}": mask(lambda s, k, a, d: k & (1 - s if d else s)) for i in range(7)})
    M["elo"] = mask(lambda a, b, c, d: a ^ (c & d))
    M["ehi"] = mask(lambda a, b, c, d: d ^ (a | b))
    res["updown"] = observe(M)
    # Shift register: D1 = shift enable, D3 = serial in.
    M = {"nx0": mask(lambda s, p, k, a: k if a else s)}
    M.update({f"nx{i}": mask(lambda s, p, k, a: p if a else s) for i in range(1, 8)})
    M.update({f"ch{i}": mask(z) for i in range(7)})
    M["elo"] = mask(lambda a, b, c, d: d ^ a)
    M["ehi"] = mask(lambda a, b, c, d: d)
    res["shift"] = observe(M)
    # Johnson counter (twisted ring), advances while D1 = 1: 16 states from 0.
    M = {"nx0": mask(lambda s, p, k, a: (1 - p) if a else s)}
    M.update({f"nx{i}": mask(lambda s, p, k, a: p if a else s) for i in range(1, 8)})
    M.update({f"ch{i}": mask(z) for i in range(7)})
    M["elo"] = mask(lambda a, b, c, d: a ^ c)
    M["ehi"] = mask(lambda a, b, c, d: b ^ d)
    res["johnson"] = observe(M)
    r = random.Random(seed)
    for k in range(2):
        names = [f"nx{i}" for i in range(8)] + [f"ch{i}" for i in range(7)] + ["elo", "ehi"]
        M = {nm: r.randrange(0x10000) for nm in names}
        res[f"random{k}"] = observe(M)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    t = tpatch.Template("cnt8")
    les = [t.les[i] for i in t.luts]
    ms = machines(a.seed)

    if a.cmd == "write":
        os.makedirs(DIR, exist_ok=True)
        for name, M in ms.items():
            open(os.path.join(DIR, f"lo_cnt8_{name}.rbf"), "wb").write(t.write(M))
        print(f"{len(ms)} files written and gated -> {DIR}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    rnd = random.Random(a.seed)
    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    log_path = os.path.join(OUT, time.strftime("cnt8test_%Y%m%d_%H%M%S.jsonl"))

    def drive(A, clk, C, D) -> int:
        got, seen = bench.read((A, clk, C, D))
        if seen != f"{A}{clk}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {A}{clk}{C}{D}")
        return int(got == "h")

    def load(path) -> None:
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load of {os.path.basename(path)} failed (exit {rc})")
        bench.cmd("A")

    def control_ok() -> None:
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control lo_quartus_0000.rbf: D5 low, ok")

    control_ok()
    ok = fail = 0
    with open(log_path, "w") as log:
        for name, M in ms.items():
            path = os.path.join(DIR, f"lo_cnt8_{name}.rbf")
            errs = gate.check(t.zero, open(path, "rb").read(), les)
            if errs:
                print(f"STOP: {name} fails the gate: {errs}")
                return 1
            load(path)
            errors, s, seen = [], 0, {0}
            C = D = 1
            for step in range(STEPS):
                for A_, D_ in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    if drive(A_, 0, C, D_) != sim_out(M, s, A_, D_):
                        errors.append(f"read s={s:02X} A={A_} D={D_} @{step}")
                A_, C, D = rnd.randrange(2), rnd.choice((0, 1, 1)), rnd.randrange(2)
                drive(A_, 0, C, D)
                s = sim_next(M, s, A_, C, D)
                seen.add(s)
                if drive(A_, 1, C, D) != sim_out(M, s, A_, D):
                    errors.append(f"edge -> s={s:02X} @{step}")
                drive(A_, 0, C, D)
            bench.cmd("I")
            ok += not errors
            fail += bool(errors)
            log.write(json.dumps(dict(machine=name, errors=errors, states=len(seen))) + "\n")
            log.flush()
            print(f"  {name:8s} distinct states {len(seen):3d}: "
                  + ("PASS" if not errors else f"FAIL {errors[:4]}"), flush=True)
    control_ok()
    print(f"\n{ok}/{ok + fail} machines correct over {STEPS} clocked steps. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
