#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replace a Quartus route between two LEs with one from routegraph.py (prepare + offline checks).

For an xr: build on the vidorlo pins: read all its routes (routes.py), require every hop of the
src -> dst route to be a known PIP, remove that route's bits (the ones no other hop of the design
also sets), route src -> the same dst input over nodes no net of the design uses, and set those
bits.  Gate-checked with exactly the changed cells.

  reroute.py plan          pick designs, build them, write out/reroute/*.rbf + a plan json (no board)
  reroute.py board         run the plan: each Quartus base, then its rerouted file (approved by the user 2026-11-24)
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "reroute")


def pip_bits(g, u, v):
    for vv, bits in g.edges.get(u, ()):
        if vv == v:
            return bits
    return None


def flip(base, clear, setb):
    buf = bytearray(base)
    hs = lutpatch.header_sum(base)
    changed = []
    for cells, val in ((clear, 0), (setb, 1)):
        for f, p, b in cells:
            off = 32 + f * 255 + p
            if (buf[off] >> b & 1) != val:
                buf[off] ^= 1 << b
                hs += lutpos.header_weight(f, p, b) * (1 if val else -1)
                changed.append((f, p, b))
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, hs % (1 << 32))
    return bytes(buf), changed


MIN_INST = 20          # switch types with fewer corpus instances are not trusted on silicon
BRANCH = 2             # 0: route from the source LE; N: branch off the Quartus route with at most N new hops


def plan(n_want: int = 8):
    g = G.Graph(min_inst=MIN_INST)
    os.makedirs(DIR, exist_ok=True)
    cands = [(28, 12, 14, -4, 0, 2), (10, 22, 10, 1, -3, 8)]
    cp = os.path.join(DIR, "candidates.json")              # corpus designs whose src -> dst hops are all known
    if os.path.exists(cp):
        cands += [tuple(c[:6]) for c in json.load(open(cp))]
    out = []
    for x, y, ns, dx, dy, nd in cands:
        job = xdev.Job("c10_016", f"xr:{ns}:{dx}:{nd}:{dy}", (x, y, 0), "vidorlo")
        res = routes.route(job)
        if res is None:
            continue
        hops = routes.pips(res)
        src = f"LCCOMB_X{x}_Y{y}_N{ns}"
        # the src -> dst segment of path A (all paths share it)
        nodes = []
        for loc, elem, typ in res["paths"]["A"]:
            if typ == "RE":
                nodes.append(loc)
            elif typ == "IC" and "|" in elem:
                nodes.append(f"{loc}:{elem.rsplit('|', 1)[-1]}")
        i0 = nodes.index(src)
        j = next(k for k in range(i0 + 1, len(nodes)) if nodes[k].startswith(f"LCCOMB_X{x + dx}_Y{y + dy}_N{nd}:"))
        seg = list(zip(nodes[i0:j], nodes[i0 + 1:j + 1]))
        dst = nodes[j]
        # only the last hop (LAB line -> LUT input) of the Quartus route is removed; the rest stays, driving a line
        # nothing selects any more
        last = seg[-1]
        lb = pip_bits(g, *last)
        if lb is None:
            print(f"  skip {job.name}: last hop {last} not a trusted PIP")
            continue
        seg_bits = [lb]
        used = {n for h in hops for n in h}
        other_bits = set()
        for u, v in hops - {seg[-1]}:                       # every other hop's bits stay (incl. the old route's)
            b = pip_bits(g, u, v)
            if b:
                other_bits |= set(b)
        if BRANCH:                                          # branch off a wire the Quartus route already drives
            new = None
            qline = seg[-1][0]                                # Quartus's LAB line into dst: must not be reused
            for w in [v for _, v in seg[:-1] if v != qline][::-1]:   # latest wire first: fewest new hops
                cand = g.route(w, dst, avoid=frozenset((used | {qline}) - {w, dst}), max_hops=BRANCH)
                if cand and (new is None or len(cand) < len(new)):
                    new = cand
            if not new:
                print(f"  skip {job.name}: no {BRANCH}-hop branch")
                continue
        else:
            new = g.route(src, dst, avoid=frozenset(used - {src, dst}))
        if not new:
            print(f"  skip {job.name}: no alternative route")
            continue
        clear = {c for b in seg_bits for c in b} - other_bits - {c for _, _, b in new for c in b}
        setb = {c for _, _, b in new for c in b}
        base = xdev.load(OUT, job.name)
        absent_now = [c for c in clear if not base[32 + c[0] * 255 + c[1]] >> c[2] & 1]
        if absent_now:
            print(f"  skip {job.name}: {len(absent_now)} predicted bits of the Quartus route are not set in the build")
            continue
        data, changed = flip(base, clear, setb)
        errs = gate.check(base, data, [], extra_cells=changed)
        if errs:
            print(f"  skip {job.name}: gate {errs}")
            continue
        path = os.path.join(DIR, f"lo_{job.name}_rerouted.rbf")
        open(path, "wb").write(data)
        out.append(dict(job=job.name, base=os.path.join(OUT, job.name + ".rbf"), patched=path, quartus_seg=seg,
                        new_seg=[(u, v) for u, v, _ in new], cleared=len(clear), set=len(setb), changed=len(changed)))
        print(f"  {job.name}: Quartus {' -> '.join(v for _, v in seg)}\n      ours    {' -> '.join(v for _, v, _ in new)}"
              f"\n      cleared {len(clear)} bits, set {len(setb)}, gate PASS")
        if len(out) >= n_want:
            break
    json.dump(out, open(os.path.join(DIR, "plan.json"), "w"), indent=1)
    return out




def board() -> int:
    """Run plan.json on the board: each Quartus base, then its rerouted file; D5 must be ~parity(D1..D4)."""
    import time
    import hwtest
    plan = json.load(open(os.path.join(DIR, "plan.json")))
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

    log, ok_all = [], True
    control_ok()
    for e in plan:
        for label, path in (("quartus", e["base"]), ("rerouted", e["patched"])):
            load(path)
            wrong = 0
            for ds in hwtest.COMBOS4:
                got, seen = bench.read(ds)
                if seen != "".join(map(str, ds)):
                    bench.cmd("I")
                    raise SystemExit(f"STOP: D1..D4 read back {seen}")
                want = 1 - (sum(ds) & 1)
                wrong += (got == "h") != bool(want)
            bench.cmd("I")
            ok = wrong == 0
            ok_all &= ok
            log.append(dict(job=e["job"], file=label, wrong=wrong))
            print(f"  {e['job'][9:]:40s} {label:9s}: {16 - wrong}/16 as predicted -> {'PASS' if ok else 'FAIL'}", flush=True)
            if not ok:
                print("STOP: first wrong result")
                control_ok()
                json.dump(log, open(os.path.join(OUT, time.strftime("reroute_%Y%m%d_%H%M%S.json")), "w"), indent=1)
                return 1
    control_ok()
    lp = os.path.join(OUT, time.strftime("reroute_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"\n{sum(1 for r in log if not r['wrong'])}/{len(log)} files as predicted. Log: {lp}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["plan"]:
        plan()
    elif sys.argv[1:] == ["board"]:
        sys.exit(board())
    else:
        print(__doc__)
