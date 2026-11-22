#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon test of tpatch.py: 8-state machines written into templates/fsm3.

State s = s0 + 2*s1 + 4*s2 (power-up 0), input a = D1, clock D2 (rising edge),
output D5 = out(s, D3).  Every machine below is written by tpatch.py from the
one pinned base build; Quartus never compiled any of them.  Each step the
test bench reads D5 with D3 = 0 and D3 = 1, clocks, and compares everything
with a simulation.

  fsmtest.py write        write + gate the files into out/fsm/
  fsmtest.py board        load and test (stops on trouble)
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
FSM = os.path.join(OUT, "fsm")
STEPS = 60


def gray(v): return v ^ (v >> 1)


def ungray(g):
    v = 0
    while g:
        v ^= g
        g >>= 1
    return v


def detect_1011(s, a):
    # Moore detector for 1011 (overlapping); states 0..4, 4 = just seen 1011.
    return {(0, 0): 0, (0, 1): 1, (1, 0): 2, (1, 1): 1, (2, 0): 0, (2, 1): 3,
            (3, 0): 2, (3, 1): 4, (4, 0): 2, (4, 1): 1}.get((s, a), 0)


# name: (next(s, a) -> s', out(s, c) -> bit)
MACHINES = {
    "counter": (lambda s, a: (s + a) % 8,                 # count while D1 = 1
                lambda s, c: (s >> 2 if c else s) & 1),     # D3 picks bit 2 or bit 0
    "graydir": (lambda s, a: gray((ungray(s) + (1 if a else 7)) % 8),   # D1 = up/down
                lambda s, c: ((s >> 2) ^ (s >> 1) if c else s) & 1),
    "lfsr": (lambda s, a: (((s << 1) | (1 ^ (s >> 2) ^ (s >> 1) & 1)) & 7) if a else s,
             lambda s, c: (s if c else s >> 2) & 1),        # XNOR LFSR, period 7 from 0
    "det1011": (detect_1011, lambda s, c: int(s == 4) ^ c),
}


def masks_for(nxt, out) -> dict[str, int]:
    m = {"next0": 0, "next1": 0, "next2": 0, "lut_out": 0}
    for i in range(16):
        a, s = i & 1, i >> 1
        for b in range(3):
            m[f"next{b}"] |= (nxt(s, a) >> b & 1) << i
        s, c = i & 7, i >> 3
        m["lut_out"] |= out(s, c) << i
    return m


def all_machines(seed: int):
    res = dict(MACHINES)
    r = random.Random(seed)
    for k in range(2):
        table = [[r.randrange(8) for _ in range(2)] for _ in range(8)]
        outs = [r.randrange(16) for _ in range(8)]
        res[f"random{k}"] = (lambda s, a, t=table: t[s][a],
                             lambda s, c, o=outs: o[s] >> c & 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--seed", type=int, default=8)
    a = ap.parse_args()
    t = tpatch.Template("fsm3")
    les = [t.les[i] for i in t.luts]
    ms = all_machines(a.seed)

    if a.cmd == "write":
        os.makedirs(FSM, exist_ok=True)
        for name, (nxt, out) in ms.items():
            m = masks_for(nxt, out)
            open(os.path.join(FSM, f"lo_fsm3_{name}.rbf"), "wb").write(t.write(m))
            print(f"  {name:8s} " + " ".join(f"{k}={v:04X}" for k, v in m.items()))
        print(f"{len(ms)} files written and gated -> {FSM}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    rnd = random.Random(a.seed)
    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    log_path = os.path.join(OUT, time.strftime("fsmtest_%Y%m%d_%H%M%S.jsonl"))
    ok = fail = 0

    def drive(a_, clk, c, d=1) -> int:
        got, seen = bench.read((a_, clk, c, d))
        if seen != f"{a_}{clk}{c}{d}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {a_}{clk}{c}{d}")
        return int(got == "h")

    def load(path) -> None:
        bench.cmd("I")
        rc, txt = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
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
    with open(log_path, "w") as log:
        for name, (nxt, out) in ms.items():
            path = os.path.join(FSM, f"lo_fsm3_{name}.rbf")
            errs = gate.check(t.zero, open(path, "rb").read(), les)
            if errs:
                print(f"STOP: {name} fails the gate: {errs}")
                return 1
            load(path)
            errors, s, visited = [], 0, {0}
            for step in range(STEPS):
                a_ = rnd.randrange(2) if not name.startswith("det") else rnd.choice((0, 1, 1))
                for c in (0, 1):
                    if drive(a_, 0, c) != out(s, c):
                        errors.append(f"out(s={s},c={c})@{step}")
                s = nxt(s, a_)
                visited.add(s)
                if drive(a_, 1, 1) != out(s, 1):              # rising edge on D2
                    errors.append(f"edge->s={s}@{step}")
                drive(a_, 0, 1)
            bench.cmd("I")
            ok += not errors
            fail += bool(errors)
            log.write(json.dumps(dict(machine=name, errors=errors, visited=sorted(visited))) + "\n")
            log.flush()
            print(f"  {name:8s} states visited {len(visited)}/8: "
                  + ("PASS" if not errors else f"FAIL {errors[:5]}"), flush=True)
    control_ok()
    print(f"\n{ok}/{ok + fail} machines correct over {STEPS} clocked steps. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
