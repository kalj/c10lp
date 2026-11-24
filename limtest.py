#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blind silicon test of exactly solved LAB-input-mux selects (limsolve.py) on xrk builds.

Base: an xrk build on vidorlo pins (same seed and LABs as the corpus build; its four nets enter the
destination LAB on (wire W_i -> line L_i) and feed d_i).  Patch for one net i: set select(W_i, L')
for an unused line L' (solved from the other corpus builds at this LAB, seen >= 2x), and move d_i's
LUT input from L_i to L' (LE-anchored LUT-input key, confirmed on silicon by unithop T1).
The old line's own select (also solved exactly) is cleared, so only the new line can carry the signal.
Predicted: Q unchanged, = parity of ~s0..~s3 (s masks 6996 8E71 D5A3 3C5A of A..D).

  limtest.py plan | board
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import lutpos  # noqa: E402
import mux1cmap  # noqa: E402
import reroute  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "limtest")
MASKS = [0x6996, 0x8E71, 0xD5A3, 0x3C5A]
NEG_EVERY = 1        # run the negative control (old select cleared, no new line) on every test


def q_of(a, b, c, d):
    i = a + 2 * b + 4 * c + 8 * d
    return sum(1 - (m >> i & 1) for m in MASKS) & 1


def cell_abs(f0, l0, rel):
    return G.cell_of(f0 + rel[0], l0 + rel[1])


def plan(per_lab: int = 4):
    sol = json.load(open(os.path.join(OUT, "limsolve.json")))
    g = G.Graph(min_inst=20)
    os.makedirs(DIR, exist_ok=True)
    jobs = json.load(open(os.path.join(OUT, "xrk_jobs.json")))
    out = []
    for name in jobs:
        m = re.search(r"xrk-(-?\d+)_(-?\d+)_(\d+)_X(\d+)Y(\d+)__", name)
        dx, dy, seed, x, y = map(int, m.groups())
        X, Y = x + dx, y + dy
        lab = sol.get(f"X{X}Y{Y}")
        if not lab or sum(1 for e in out if e["lab"] == [X, Y]) >= per_lab or any(e["job"] == name for e in out):
            continue
        # base: the corpus build itself, with Q's drive set to 4 mA by periph.py (vidor -> vidorlo differ only there)
        import periph
        drive = periph.setting("PIN_T2", "drive", 4)
        vbuild = xdev.load(OUT, name)
        res = json.load(open(os.path.join(OUT, name + ".route.json")))
        hops = routes.pips(res)
        used = {n for h in hops for n in h}
        pre = f"LOCAL_INTERCONNECT_X{X}_Y{Y}_"
        f0, l0 = R._col_frame(X), R._row_index(Y)
        base = periph.apply(vbuild, drive)
        done = False
        for (W, L) in sorted(h for h in hops if h[1].startswith(pre)):
            dsts = [v for u, v in hops if u == L and v.startswith("LCCOMB")]
            if len(dsts) != 1:
                continue
            dst = dsts[0]
            n = int(dst.split("_N")[1].split(":")[0])
            for k, (cnt, rel) in lab["select"].items():
                w2, l2 = k.split("->")
                if w2 != W or l2 == L or l2 in used or cnt < 2 or not rel:
                    continue
                lut = reroute.pip_bits(g, l2, dst)
                if not lut:
                    continue
                sel = [cell_abs(f0, l0, r) for r in rel]
                if any(c is None for c in sel):
                    continue
                c = lutpos._predict_phys(X, Y, n)
                ff0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
                fl = (n // 2) % 2
                old = {(ff0 + df, lo + (col - 2 if fl else col), bit) for df, col in mux1cmap.region(base, X, Y, n)}
                setb = set(sel) | set(lut)
                # also clear the old line's own select, so only the new line can carry the signal
                oldsel = lab["select"].get(f"{W}->{L}")
                if not oldsel or oldsel[0] < 2 or not oldsel[1]:
                    continue
                oldbits = {cell_abs(f0, l0, r) for r in oldsel[1]}
                if None in oldbits or any(not base[32 + c[0] * 255 + c[1]] >> c[2] & 1 for c in oldbits):
                    continue                                 # the solved old select must be set in the base
                data, changed = reroute.flip(base, (old | oldbits) - setb, setb)
                neg, nchanged = reroute.flip(base, oldbits, set())          # negative control: old select cleared only
                pb = [c[:3] for c in drive]
                ok = True
                for d_, ch in ((data, changed), (neg, nchanged), (base, [])):
                    if gate.check(vbuild, d_, [], extra_cells=ch, periph_bits=pb):
                        ok = False
                if not ok:
                    continue
                stem = os.path.join(DIR, f"lo_{name}_{l2.split('_')[-1]}")
                for suffix, d_ in (("base", base), ("patched", data), ("neg", neg)):
                    open(f"{stem}_{suffix}.rbf", "wb").write(d_)
                out.append(dict(job=name, lab=[X, Y], wire=W, old_line=L, new_line=l2, dst=dst, select_seen=cnt,
                                select=rel, base=f"{stem}_base.rbf", patched=f"{stem}_patched.rbf", neg=f"{stem}_neg.rbf",
                                changed=len(changed)))
                print(f"  X{X}Y{Y} {W} : {L.split('_')[-1]} -> {l2.split('_')[-1]} (select {rel}, seen {cnt}x) for {dst}; "
                      f"{len(changed)} cells")
                done = True
                break
            if done:
                break
    json.dump(out, open(os.path.join(DIR, "plan.json"), "w"), indent=1)
    print(len(out), "tests")


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

    def run(path):
        load(path)
        wrong = 0
        for ds in hwtest.COMBOS4:
            got, seen = bench.read(ds)
            if seen != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {seen}")
            wrong += (got == "h") != bool(q_of(*ds))
        bench.cmd("I")
        return wrong

    log = []
    control_ok()
    for e in plan_:
        wb = run(e["base"])
        wp = run(e["patched"])
        wn = run(e["neg"]) if e.get("neg") and NEG_EVERY and len(log) % NEG_EVERY == 0 else None
        log.append(dict(e, wrong_base=wb, wrong_patched=wp, wrong_neg=wn))
        print(f"  X{e['lab'][0]}Y{e['lab'][1]} {e['wire'][:18]:18s} line {e['old_line'].split('_')[-1]:4s}->{e['new_line'].split('_')[-1]:4s}"
              f" base {16 - wb}/16, patched {16 - wp}/16 -> {'PASS' if not wp else 'FAIL'}"
              + (f"; negative control {16 - wn}/16 ({'fails as it must' if wn else 'STILL WORKS: old select not what carried it'})"
                 if wn is not None else ""), flush=True)
        if wb:
            print("STOP: Quartus base not as expected")
            break
    control_ok()
    lp = os.path.join(OUT, time.strftime("limtest_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"Log: {lp}")
    return 0


if __name__ == "__main__":
    {"plan": plan, "board": board}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
