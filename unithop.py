#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests of single routing-switch classes on silicon, with a signal known to be present.

Base: xr:NS:0:ND:0 (src and dst LE in the same LAB) on vidorlo pins; dst = ~src via a LOCAL_LINE.
The pins enter that LAB on Quartus-driven LAB lines (LOCAL_INTERCONNECT); pin A's line is read from
the timing report.
  T1  dst's input switched from the local line to pin A's LAB line: clear dst's LUT-input mux bits
      (mux1cmap region of dst), set the LE-anchored LAB line -> LUT input key.  Predicted D5 = ~A.
  T2  drive a free LAB line of that LAB from the wire that brings pin A in (wire -> LAB line key),
      then select it for dst (LAB line -> LUT input key).  Predicted D5 = ~A.

  unithop.py plan | board
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import mux1cmap  # noqa: E402
import reroute  # noqa: E402
import routegraph as G  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "unithop")


def plan():
    g = G.Graph(min_inst=20)
    os.makedirs(DIR, exist_ok=True)
    out = []
    for x, y, ns, nd in ((10, 10, 4, 16), (22, 8, 8, 20), (16, 14, 2, 24), (6, 12, 12, 26), (28, 12, 14, 6), (12, 6, 0, 22)):
        job = xdev.Job("c10_016", f"xr:{ns}:0:{nd}:0", (x, y, 0), "vidorlo")
        res = routes.route(job)
        if res is None:
            continue
        base = xdev.load(OUT, job.name)
        hops = routes.pips(res)
        used = {n for h in hops for n in h}
        nodes = [h for h in res["paths"]["A"] if h[2] in ("RE", "IC")]
        # pin A's LAB line into src, and the wire feeding it
        k = next(i for i, h in enumerate(nodes) if h[0] == f"LCCOMB_X{x}_Y{y}_N{ns}" and h[2] == "IC")
        lineA, wireA = nodes[k - 1][0], nodes[k - 2][0]
        dport = next(h[1].rsplit("|", 1)[1] for h in nodes if h[0] == f"LCCOMB_X{x}_Y{y}_N{nd}" and h[2] == "IC")
        dst = f"LCCOMB_X{x}_Y{y}_N{nd}:{dport}"
        # dst's current LUT-input mux bits (everything set in its mux region: it uses one input)
        import lutpos
        c = lutpos._predict_phys(x, y, nd)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        fl = (nd // 2) % 2
        old = [(f0 + df, lo + (col - 2 if fl else col), bit) for df, col in mux1cmap.region(base, x, y, nd)]
        tests = []
        b1 = reroute.pip_bits(g, lineA, dst)
        if b1:
            tests.append(("T1", [(lineA, dst)], set(b1)))
        if wireA.startswith(("C4", "R4", "C16", "R24")):
            for v, bits in g.edges.get(wireA, ()):
                if v.startswith(f"LOCAL_INTERCONNECT_X{x}_Y{y}_") and v not in used:
                    b2 = reroute.pip_bits(g, v, dst)
                    if b2:
                        tests.append(("T2", [(wireA, v), (v, dst)], set(bits) | set(b2)))
                        break
        for name, path, setb in tests:
            data, changed = reroute.flip(base, set(old) - setb, setb)
            errs = gate.check(base, data, [], extra_cells=changed)
            if errs:
                print(f"  {job.name} {name}: gate {errs}")
                continue
            p = os.path.join(DIR, f"lo_{job.name}_{name}.rbf")
            open(p, "wb").write(data)
            out.append(dict(job=job.name, test=name, path=path, base=os.path.join(OUT, job.name + ".rbf"), patched=p,
                            changed=len(changed)))
            print(f"  {job.name} {name}: {' ; '.join(f'{u} -> {v}' for u, v in path)}  ({len(changed)} cells)")
    json.dump(out, open(os.path.join(DIR, "plan.json"), "w"), indent=1)


def board() -> int:
    import hwtest
    plan_ = json.load(open(os.path.join(DIR, "plan.json")))
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc}) for {p}")
        bench.cmd("A")

    def control_ok():
        load(os.path.join(OUT, "lo_quartus_0000.rbf"))
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    def run(path, want):
        load(path)
        wrong = 0
        for ds in hwtest.COMBOS4:
            got, seen = bench.read(ds)
            if seen != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {seen}")
            wrong += (got == "h") != bool(want(ds))
        bench.cmd("I")
        return wrong

    log = []
    control_ok()
    done = set()
    for e in plan_:
        if e["job"] not in done:
            w = run(e["base"], lambda ds: 1 - (sum(ds) & 1))
            print(f"  {e['job'][9:40]:31s} quartus : {16 - w}/16 (D5 = ~parity)", flush=True)
            log.append(dict(job=e["job"], file="quartus", wrong=w))
            done.add(e["job"])
            if w:
                print("STOP: Quartus base not as expected")
                break
        w = run(e["patched"], lambda ds: 1 - ds[0])
        print(f"  {e['job'][9:40]:31s} {e['test']}      : {16 - w}/16 (D5 = ~D1)  {'PASS' if not w else 'FAIL'}", flush=True)
        log.append(dict(job=e["job"], file=e["test"], path=e["path"], wrong=w))
    control_ok()
    lp = os.path.join(OUT, time.strftime("unithop_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"Log: {lp}")
    return 0


if __name__ == "__main__":
    {"plan": plan, "board": board}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
