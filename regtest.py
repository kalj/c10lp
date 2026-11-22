#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Clocked silicon test: a patched LUT feeding a register (xdev "reg:" design).

Template (Quartus): LUT at X,Y,N with inputs a=D1, b=D3, c=D4, d=register
state; the register (FF at N+1, power-up low) is clocked by D2 and drives D5.
So next_state = mask(a, b, c, state): any 3-input state machine with 1 bit
of state.  The LUT is rewritten from the reg:0000 template and the reg:008A
probe; gate.py checks every file before loading.

For each file, the test bench (sketch/VidorTestBench) checks:
  - D5 = 0 right after loading (power-up low);
  - before each clock edge, D5 still holds the old state (inputs changed, no edge);
  - after each rising edge on D2, D5 = mask(a, b, c, old state).

  regtest.py write          build model files into out/reg/ and gate them
  regtest.py board          load and test (stops on trouble, like silicon_sweep.py)
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
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(xdev.HERE, "out")
REG = os.path.join(OUT, "reg")
PINS = "vidorlo"
LOCS = [(10, 10, 0), (30, 20, 12)]
STEPS = 40


def mask_of(fn) -> int:
    return sum(fn(i & 1, i >> 1 & 1, i >> 2 & 1, i >> 3 & 1) << i for i in range(16))


# Functions Quartus never compiled: (name, next(a, b, c, state)).
FUNCS = [
    ("toggle", lambda a, b, c, s: s ^ a),                 # T flip-flop on D1
    ("dff", lambda a, b, c, s: a),                        # plain D flip-flop from D1
    ("setreset", lambda a, b, c, s: b | (s & (1 - c))),   # D3 sets, D4 resets, else hold
    ("maj", lambda a, b, c, s: int(a + b + s >= 2)),      # majority of D1, D3, state
]


def name(m: int, loc) -> str:
    return xdev.Job("c10_016", f"reg:{m:04X}", loc, PINS).name


def files() -> list[tuple[str, str, int, tuple]]:
    """(label, path, mask, loc): Quartus's own random-mask builds, then model files."""
    res = []
    for loc in LOCS:
        for f in sorted(os.listdir(OUT)):
            if f.startswith("c10_016__reg") and f.endswith(f"_X{loc[0]}Y{loc[1]}N{loc[2]}__{PINS}.rbf"):
                m = int(f[12:16], 16)
                if m not in (0, lutpos.PROBE_MASK):
                    res.append((f"quartus {m:04X}", os.path.join(OUT, f), m, loc))
        for fname, fn in FUNCS:
            m = mask_of(fn)
            res.append((f"model {fname} ({m:04X})",
                        os.path.join(REG, f"lo_reg_{fname}_X{loc[0]}Y{loc[1]}N{loc[2]}.rbf"), m, loc))
    return res


def codec(loc) -> lutpatch.Codec:
    # The reg: template has a single LUT, so the LUT codec works on it directly.
    c = lutpatch.Codec.__new__(lutpatch.Codec)
    c.zero = xdev.load(OUT, name(0, loc))
    probe = xdev.load(OUT, name(lutpos.PROBE_MASK, loc))
    if c.zero is None or probe is None:
        raise SystemExit(f"build reg:0000 and reg:008A at {loc} first")
    import rbfgeom
    c.g = rbfgeom.infer(c.zero)
    cs = set(xdev.cells(c.zero, probe, c.g))
    if cs - set(lutpos._predict_phys(*loc)):
        raise SystemExit(f"reg probe at {loc} changed bits outside the LUT")
    c.perm = lutpos.perm_from_probe(cs, *loc)
    c.delta, c.hweight = [], []
    for f, p, b in lutpos.predict(*loc, c.perm):
        c.delta.append({(c.g.preamble + f * c.g.frame + p, b)})
        c.hweight.append(lutpos.header_weight(f, p, b))
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--seed", type=int, default=4000)
    a = ap.parse_args()

    if a.cmd == "write":
        os.makedirs(REG, exist_ok=True)
        for loc in LOCS:
            c = codec(loc)
            for fname, fn in FUNCS:
                m = mask_of(fn)
                new = c.write(m, fix_header=True)
                errs = gate.check(c.zero, new, [loc])
                if errs:
                    raise SystemExit(f"{fname} at {loc}: GATE FAIL {errs}")
                open(os.path.join(REG, f"lo_reg_{fname}_X{loc[0]}Y{loc[1]}N{loc[2]}.rbf"),
                     "wb").write(new)
            # The model must also reproduce Quartus's own random-mask builds exactly.
            for label, path, m, l2 in files():
                if l2 == loc and label.startswith("quartus"):
                    same = c.write(m, fix_header=True) == open(path, "rb").read()
                    print(f"  {loc} {label}: model {'BYTE-IDENTICAL' if same else 'DIFFERS'}")
        print(f"model files written and gated -> {REG}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    rnd = random.Random(a.seed)
    log_path = os.path.join(OUT, time.strftime("regtest_%Y%m%d_%H%M%S.jsonl"))
    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    tests = [("control", control, 0, None)] + files() + [("control", control, 0, None)]
    ok = fail = 0

    def drive(a_, clk, b, c_):
        got, seen = bench.read((a_, clk, b, c_))
        if seen != f"{a_}{clk}{b}{c_}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {a_}{clk}{b}{c_}")
        return int(got == "h")

    with open(log_path, "w") as log:
        for label, path, m, loc in tests:
            if loc is not None:
                tmpl = xdev.load(OUT, name(0, loc))
                errs = gate.check(tmpl, open(path, "rb").read(), [loc])
                if errs:
                    print(f"STOP: {os.path.basename(path)} fails the gate: {errs}")
                    return 1
            bench.cmd("I")
            rc, txt = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
            if rc:
                print(f"STOP: load of {os.path.basename(path)} failed (exit {rc})")
                return 1
            bench.cmd("A")                                   # all pins high, no edge
            if label == "control":
                wrong = [ds for ds in hwtest.COMBOS4 if bench.read(ds)[0] == "h"]
                bench.cmd("I")
                if wrong:
                    print(f"STOP: all-zero control did not hold D5 low")
                    return 1
                print("  control lo_quartus_0000.rbf: D5 low, ok")
                continue
            errors = []
            state = 0
            a_, b, c_ = 1, 1, 1
            if drive(a_, 0, b, c_) != state:              # clock low first; power-up low
                errors.append("power-up")
            for step in range(STEPS):
                a_, b, c_ = rnd.randrange(2), rnd.randrange(2), rnd.randrange(2)
                if drive(a_, 0, b, c_) != state:
                    errors.append(f"hold@{step}")
                nxt = m >> (a_ | b << 1 | c_ << 2 | state << 3) & 1
                if drive(a_, 1, b, c_) != nxt:            # rising edge on D2
                    errors.append(f"edge@{step}")
                state = nxt
                drive(a_, 0, b, c_)
            bench.cmd("I")
            ok += not errors
            fail += bool(errors)
            log.write(json.dumps(dict(label=label, file=os.path.basename(path), loc=loc,
                                      mask=m, errors=errors)) + "\n")
            log.flush()
            print(f"  X{loc[0]}Y{loc[1]}N{loc[2]:<2d} {label:24s} "
                  + ("PASS" if not errors else f"FAIL {errors[:6]}"), flush=True)
    print(f"\n{ok}/{ok + fail} files correct over {STEPS} clocked steps each. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
