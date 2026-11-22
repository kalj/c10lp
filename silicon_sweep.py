#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon check of the lutpos.py position model at many random LEs.

For each LE: Quartus builds mask 0000 and the 0x008A probe (pins vidorlo), the
model writes a random asymmetric mask Quartus never compiled, gate.py checks it
is gold-anchored, then (with --board) it is loaded to SRAM and all 16 D1..D4
combinations are compared with the mask via sketch/VidorTestBench.

  silicon_sweep.py plan  [--count 100] [--seed S]   list LEs, estimate time
  silicon_sweep.py build [--jobs 2]                  compile what is missing
  silicon_sweep.py write                             model files + gate
  silicon_sweep.py board [--port /dev/ttyACM0]       load and test (stops on trouble)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
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
SWEEP = os.path.join(OUT, "sweep")
PINS = "vidorlo"
CONTROL_EVERY = 25          # re-load the Quartus all-zero control this often


def plan(count: int, seed: int) -> list[tuple[tuple[int, int, int], int]]:
    r = random.Random(seed)
    labs = [(x, y) for x in lutpos.LAB_X for y in range(1, 29) if (x, y) not in lutpos.HOLE]
    res = []
    for x, y in r.sample(labs, count):
        n = 2 * r.randrange(16)
        while True:
            m = r.randrange(1, 0xFFFF)
            if any(sum((m >> lutpos.permute(i, p) & 1) << i for i in range(16)) != m
                   for p in lutpos.PERMS):
                break
        res.append(((x, y, n), m))
    return res


def fname(loc, m) -> str:
    return f"lo_sweep_X{loc[0]}Y{loc[1]}N{loc[2]}_{m:04X}.rbf"


def jobs(items) -> list[xdev.Job]:
    return [xdev.Job("c10_016", d, loc, PINS)
            for loc, _ in items for d in ("lut:0000", f"lut:{lutpos.PROBE_MASK:04X}")]


def lut(m: int, ds) -> int:
    return m >> sum(d << k for k, d in enumerate(ds)) & 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "build", "write", "board"])
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--port", default="/dev/ttyACM0")
    a = ap.parse_args()
    items = plan(a.count, a.seed)
    js = jobs(items)

    if a.cmd == "plan":
        for loc, m in items:
            print(f"  X{loc[0]}Y{loc[1]}N{loc[2]}  mask {m:04X}")
        print(xdev.estimate(js, OUT, a.jobs))
        print(f"board: ~{len(items) * 7.5 / 60:.0f} min ({len(items)} loads x ~7.5 s)")
        return 0

    if a.cmd == "build":
        print(xdev.estimate(js, OUT, a.jobs), flush=True)
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            res = list(ex.map(lambda j: xdev.build_one(j, OUT, False), js))
        bad = [(m["job"], m.get("error")) for m in res if not m["ok"]]
        print(f"{sum(not m.get('cached') for m in res)} compiled, failed: {bad}")
        return 1 if bad else 0

    if a.cmd == "write":
        os.makedirs(SWEEP, exist_ok=True)
        bad = 0
        for loc, m in items:
            c = lutpatch.Codec(OUT, "c10_016", loc, model=True, pins=PINS)
            new = c.write(m, fix_header=True)
            errs = gate.check(c.zero, new, [loc])
            if errs:
                bad += 1
                print(f"  {fname(loc, m)}: GATE FAIL {errs}")
                continue
            open(os.path.join(SWEEP, fname(loc, m)), "wb").write(new)
        print(f"{len(items) - bad}/{len(items)} files written and gated -> {SWEEP}")
        return 1 if bad else 0

    # board
    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    log_path = os.path.join(OUT, time.strftime("sweep_%Y%m%d_%H%M%S.jsonl"))
    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    tests = []
    for i, it in enumerate(items):
        if i % CONTROL_EVERY == 0:
            tests.append(("control", control, 0))
        tests.append((it[0], os.path.join(SWEEP, fname(*it)), it[1]))
    tests.append(("control", control, 0))
    ok = fail = 0
    with open(log_path, "w") as log:
        for loc, path, m in tests:
            if loc != "control":
                # Re-gate right before loading: the file on disk is what gets loaded.
                tmpl = xdev.load(OUT, lutpatch.name("c10_016", 0, loc, PINS))
                errs = gate.check(tmpl, open(path, "rb").read(), [loc])
                if errs:
                    print(f"STOP: {os.path.basename(path)} fails the gate: {errs}")
                    return 1
            bench.cmd("I")
            rc, txt = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
            if rc:
                bench.cmd("I")
                print(f"STOP: load of {os.path.basename(path)} failed (exit {rc}): "
                      + " | ".join(txt.strip().splitlines()[-3:]))
                return 1
            bench.cmd("A")
            wrong = []
            for ds in hwtest.COMBOS4:
                got, seen = bench.read(ds)
                if seen != "".join(map(str, ds)):
                    bench.cmd("I")
                    print(f"STOP: D1..D4 read back {seen} while driving {ds}: another driver")
                    return 1
                if (got == "h") != bool(lut(m, ds)):
                    wrong.append("".join(map(str, ds)))
            bench.cmd("I")
            name = os.path.basename(path)
            log.write(json.dumps(dict(file=name, loc=loc, mask=m, wrong=wrong)) + "\n")
            log.flush()
            if loc == "control":
                if wrong:
                    print(f"STOP: all-zero control did not hold D5 low at {wrong}")
                    return 1
                print(f"  control {name}: D5 low for all 16, ok")
                continue
            ok += not wrong
            fail += bool(wrong)
            print(f"  X{loc[0]}Y{loc[1]}N{loc[2]:<2d} {m:04X}: "
                  + ("PASS" if not wrong else f"FAIL at D1..D4 = {wrong}"), flush=True)
    print(f"\n{ok}/{ok + fail} LEs correct on silicon. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
