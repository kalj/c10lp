#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Full inter-LAB reroute on silicon with exact per-position hop bits (hopsolve.py), no Quartus route reused.

Base: an xrkn build (8 nets s_i -> d_i:dataa between two LABs), Q at 4 mA (periph.py).  For one net whose
Quartus route is  s_i -> LE_BUFFER b -> W -> LAB line L -> d_i:port,  pick W' != W driven by the same b and a
line L' fed by W', both unused in this build, with exact bits for b -> W' and W' -> L' (seen >= 2x, 1..MAX_BITS
bits, not shared with any hop of this build), and the confirmed LUT-input key L' -> d_i:port.
  patched:  clear bits(b -> W), bits(W -> L), d_i's input code; set bits(b -> W'), bits(W' -> L'), LUT key
  negative: clear bits(b -> W) and bits(W -> L) only
Predicted: patched Q = XOR of ~s_i (16/16); negative control wrong.

  xreroute.py plan | blind | board        (blind: held-out builds, all routing bits from switchmodel.py)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import lutpos  # noqa: E402
import mux1cmap  # noqa: E402
import periph  # noqa: E402
import reroute  # noqa: E402
import routegraph as G  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "xreroute")
MAX_BITS = 3
PER_LAB = 2
LE = re.compile(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)")
COLS = set()                                              # logic (LAB) columns; set in plan_blind


def q_of(k, a, b, c, d):
    i = a + 2 * b + 4 * c + 8 * d
    return sum(1 - (int(m, 16) >> i & 1) for m in xdev.XRKN_MASKS[:k]) & 1


def chains(res):
    """Per net: [LCCOMB src, node, ..., LCCOMB dst:port] for routes leaving one LAB for another (Quartus may
    permute the destination's LUT inputs, so the port is whichever it chose)."""
    out = set()
    for hops in res["paths"].values():
        nodes = []
        for loc, elem, typ in hops:
            if typ == "RE":
                nodes.append(loc)
            elif typ == "IC":
                port = elem.rsplit("|", 1)[-1] if "|" in elem else ""
                nodes.append(f"{loc}:{port}" if port else loc)
        les = [k for k, n in enumerate(nodes) if n.startswith("LCCOMB")]
        for a, b in zip(les, les[1:]):
            sa, sb = LE.match(nodes[a]), LE.match(nodes[b])
            if b - a >= 2 and ":" in nodes[b] and ":" not in nodes[a] and sa.groups()[:2] != sb.groups()[:2]:
                out.add(tuple(nodes[a:b + 1]))
    return sorted(out)


def plan():
    hs = {tuple(k.split("->")): v for k, v in json.load(open(os.path.join(OUT, "hopsolve.json"))).items()}
    good = {h: [tuple(c) for c in v[2]] for h, v in hs.items() if v[0] >= 2 and 1 <= len(v[2]) <= MAX_BITS}
    g = G.Graph(min_inst=20)
    os.makedirs(DIR, exist_ok=True)
    drive = periph.setting("PIN_T2", "drive", 4)
    out, per = [], {}
    for name in json.load(open(os.path.join(OUT, "xrkn_jobs.json"))):
        k = int(name.split("xrkn-")[1].split("_")[0])
        res = json.load(open(os.path.join(OUT, name + ".route.json")))
        hops = routes.pips(res)
        used = {n for h in hops for n in h}
        held = set()                                     # exact bits of every hop of this build
        for h in hops:
            held |= set(good.get(h, []))
        for ch in chains(res):
            if len(ch) != 5 or not ch[1].startswith("LE_BUFFER") or not ch[3].startswith("LOCAL_INTERCONNECT"):
                continue
            s, b, W, L, dst = ch
            lab = LE.match(dst).groups()[:2]
            if per.get(lab, 0) >= PER_LAB:
                continue
            old = good.get((b, W), []) + good.get((W, L), [])
            if not good.get((b, W)) or not good.get((W, L)):
                continue
            vbuild = xdev.load(OUT, name)
            if any(not vbuild[32 + f * 255 + p] >> bt & 1 for f, p, bt in old):
                continue
            others = set()
            for h in hops:
                if h not in ((b, W), (W, L)):
                    others |= set(good.get(h, []))
            if set(old) & others:
                continue                                 # old bits shared with another hop: can't clear them
            for (u, W2), bw in good.items():
                if u != b or W2 == W or W2 in used:
                    continue
                for (u2, L2), sel in good.items():
                    if u2 != W2 or L2 in used or not L2.startswith(f"LOCAL_INTERCONNECT_X{lab[0]}_Y{lab[1]}_"):
                        continue
                    lut = reroute.pip_bits(g, L2, dst)
                    new = set(bw) | set(sel)
                    if not lut or new & (held | others) or any(vbuild[32 + f * 255 + p] >> bt & 1 for f, p, bt in new):
                        continue
                    X, Y, n = map(int, LE.match(dst).groups())
                    c = lutpos._predict_phys(X, Y, n)
                    ff0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
                    fl = (n // 2) % 2
                    base = periph.apply(vbuild, drive)
                    code = {(ff0 + df, lo + (col - 2 if fl else col), bit) for df, col in mux1cmap.region(base, X, Y, n)}
                    setb = new | set(lut)
                    data, ch1 = reroute.flip(base, (set(old) | code) - setb, setb)
                    neg, ch2 = reroute.flip(base, set(old), set())
                    pb = [c[:3] for c in drive]
                    if any(gate.check(vbuild, d_, [], extra_cells=cc, periph_bits=pb)
                           for d_, cc in ((data, ch1), (neg, ch2), (base, []))):
                        continue
                    stem = os.path.join(DIR, f"lo_{name}_{W2.split('_N0_')[0]}_{L2.split('_')[-1]}")
                    for suf, d_ in (("base", base), ("patched", data), ("neg", neg)):
                        open(f"{stem}_{suf}.rbf", "wb").write(d_)
                    out.append(dict(job=name, k=k, net=list(ch), new=[b, W2, L2, dst], driver=list(bw), select=list(sel),
                                    lut=list(lut), seen=[hs[(b, W2)][0], hs[(W2, L2)][0]], changed=len(ch1),
                                    base=f"{stem}_base.rbf", patched=f"{stem}_patched.rbf", neg=f"{stem}_neg.rbf"))
                    per[lab] = per.get(lab, 0) + 1
                    print(f"  {name}: {W} -> {L.split('_')[-1]}  becomes  {W2} -> {L2.split('_')[-1]}  ({len(ch1)} cells)", flush=True)
                    break
                else:
                    continue
                break
    json.dump(out, open(os.path.join(DIR, "plan.json"), "w"), indent=1)
    print(len(out), "tests")


def plan_blind(jobs: str = "xrkn_holdout_jobs.json", per_lab: int = 2, max_tests: int = 16):
    """Like plan(), on held-out builds (positions absent from the training corpus), with every routing bit
    (old and new driver and select) predicted by the die-wide model (switchmodel.py), none solved at that position.
    Quartus's own route must be predicted exactly first (all old bits set), else the net is skipped."""
    import routemap
    import switchmodel
    COLS.update(x for x in range(45) if routemap._col_frame(x) is not None)
    m = switchmodel.Model()
    g = G.Graph(min_inst=20)
    os.makedirs(DIR, exist_ok=True)
    drive = periph.setting("PIN_T2", "drive", 4)
    out, per = [], {}
    for name in json.load(open(os.path.join(OUT, jobs))):
        if len(out) >= max_tests:
            break
        k = int(name.split("xrkn-")[1].split("_")[0])
        res = json.load(open(os.path.join(OUT, name + ".route.json")))
        hops = routes.pips(res)
        used = {n for h in hops for n in h}
        vbuild = xdev.load(OUT, name)
        on = lambda c: vbuild[32 + c[0] * 255 + c[1]] >> c[2] & 1
        held = set()
        for h in hops:
            held |= set(m.bits(*h) or [])
        for ch in chains(res):
            if len(ch) != 5 or not ch[1].startswith("LE_BUFFER") or not ch[3].startswith("LOCAL_INTERCONNECT"):
                continue
            s_, b, W, L, dst = ch
            lab = LE.match(dst).groups()[:2]
            if per.get(lab, 0) >= per_lab:
                continue
            bo, so = m.bits(b, W), m.bits(W, L)
            if not bo or not so or not all(map(on, bo + so)):
                continue
            old = set(bo) | set(so)
            others = set()
            for h in hops:
                if h not in ((b, W), (W, L)):
                    others |= set(m.bits(*h) or [])
            if old & others:
                continue
            done = False
            for W2, bw in m.fanout(b):
                if W2 == W or W2 in used or not W2.startswith(("R4", "C4")):
                    continue
                for L2, sel in m.fanout(W2):
                    if L2 in used or not L2.startswith(f"LOCAL_INTERCONNECT_X{lab[0]}_Y{lab[1]}_"):
                        continue
                    lut = reroute.pip_bits(g, L2, dst)
                    new = set(bw) | set(sel)
                    if not lut or new & (held | others) or any(map(on, new)):
                        continue
                    X, Y, n = map(int, LE.match(dst).groups())
                    c = lutpos._predict_phys(X, Y, n)
                    ff0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
                    fl = (n // 2) % 2
                    base = periph.apply(vbuild, drive)
                    code = {(ff0 + df, lo + (col - 2 if fl else col), bit) for df, col in mux1cmap.region(base, X, Y, n)}
                    setb = new | set(lut)
                    data, ch1 = reroute.flip(base, (old | code) - setb, setb)
                    neg, ch2 = reroute.flip(base, old, set())
                    pb = [c[:3] for c in drive]
                    if any(gate.check(vbuild, d_, [], extra_cells=cc, periph_bits=pb)
                           for d_, cc in ((data, ch1), (neg, ch2), (base, []))):
                        continue
                    stem = os.path.join(DIR, f"blind_{name}_{W2.split('_N0_')[0]}_{L2.split('_')[-1]}")
                    for suf, d_ in (("base", base), ("patched", data), ("neg", neg)):
                        open(f"{stem}_{suf}.rbf", "wb").write(d_)
                    out.append(dict(job=name, k=k, net=list(ch), new=[b, W2, L2, dst], driver=list(bw), select=list(sel),
                                    lut=list(lut), old=sorted(old), changed=len(ch1), blind=True,
                                    base=f"{stem}_base.rbf", patched=f"{stem}_patched.rbf", neg=f"{stem}_neg.rbf"))
                    per[lab] = per.get(lab, 0) + 1
                    xs = [int(re.search(r"_X(\d+)_", n_).group(1)) for n_ in (s_, W2, dst)]
                    holes = [x for x in range(min(xs), max(xs) + 1) if x not in COLS]
                    out[-1]["predicted"] = "FAIL?" if holes else "PASS"     # hypothesis: crossing M9K/DSP columns breaks
                    out[-1]["holes"] = holes
                    print(f"  {name}: {W} -> {L.split('_')[-1]}  becomes  {W2} -> {L2.split('_')[-1]}  ({len(ch1)} cells)"
                          f"  predicted {out[-1]['predicted']}{' (crosses X' + str(holes) + ')' if holes else ''}", flush=True)
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

    def run(path, k):
        load(path)
        wrong = 0
        for ds in hwtest.COMBOS4:
            got, seen = bench.read(ds)
            if seen != "".join(map(str, ds)):
                bench.cmd("I")
                raise SystemExit(f"STOP: D1..D4 read back {seen}")
            wrong += (got == "h") != bool(q_of(k, *ds))
        bench.cmd("I")
        return wrong

    log = []
    control_ok()
    for e in plan_:
        wb, wp, wn = run(e["base"], e["k"]), run(e["patched"], e["k"]), run(e["neg"], e["k"])
        log.append(dict(e, wrong_base=wb, wrong_patched=wp, wrong_neg=wn))
        print(f"  {e['net'][2]} -> {e['net'][3].split('_')[-1]}  =>  {e['new'][1]} -> {e['new'][2].split('_')[-1]}"
              f"{' [predicted ' + e['predicted'] + ']' if 'predicted' in e else ''}: "
              f"base {16 - wb}/16, patched {16 - wp}/16 {'PASS' if not wp else 'FAIL'}, negative {16 - wn}/16", flush=True)
        if wb:
            print("STOP: base not as expected")
            break
    control_ok()
    lp = os.path.join(OUT, time.strftime("xreroute_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"Log: {lp}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "blind":
        plan_blind(sys.argv[2])
    else:
        {"plan": plan, "blind": plan_blind, "board": board}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
