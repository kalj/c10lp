#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact LAB line -> LUT input select codes, read from compiled builds.

Each physical LUT input (lutpos numbering) owns a disjoint set of cells in the LE's input-mux region (frames -12..-2,
byte columns 0..3; odd LEs at low byte + column - 2, as mux1cmap.region).  In a build where a LUT input's source is
known (timing-report or .rcf hop LOCAL_INTERCONNECT line -> LCCOMB:port), that input's code is the build's set bits in
its cells.  Collected over the corpus per (line, physical input, LE parity); only codes seen identically everywhere
are kept.  Output: out/limux.json {"line,input,odd": [[frame, column], ...]}

  limux.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import limsolve  # noqa: E402
import lutpos  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
PHYS = {"datac": 0, "datad": 1, "datab": 2, "dataa": 3}       # .rcf / timing-report port -> lutpos input


def input_cells() -> dict[int, set]:
    t = json.load(open(os.path.join(HERE, "li_local_table.json")))["entries"]
    cells = collections.defaultdict(set)
    for k, v in t.items():
        cells[int(k.split(",")[0])] |= {tuple(c) for c in v}
    for i in cells:                                  # complete each input's block (frames x its two columns)
        fr = {f for f, _ in cells[i]}
        cols = {c for _, c in cells[i]}
        cells[i] = {(f, c) for f in fr for c in cols}
    return cells


def code(buf: bytes, x: int, y: int, n: int, cells: set) -> frozenset:
    c = lutpos._predict_phys(x, y, n)
    f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
    odd = (n // 2) % 2
    # odd LEs: byte = low byte + column - 2 (mux1cmap.region; the bits of odd LEs' blinky inputs sit at low -2..+1)
    return frozenset((df, col) for df, col in cells
                     if buf[32 + (f0 + df) * 255 + lo + (col - 2 if odd else col)] >> bit & 1)


def build_rcf(root: str):
    """Same, from the RCF oracle's projects (base.rcf + base.rbf): route_port is the physical port, unambiguously
    (timing-report port names turned out to mix logical and physical ports)."""
    import glob
    import rcfforce as F
    cells = input_cells()
    seen = collections.defaultdict(collections.Counter)
    n_proj = 0
    for work in glob.glob(os.path.join(root, "work", "*")):
        if re.search(r"\.w\d+$", work) or not os.path.exists(os.path.join(work, "base.rcf")):
            continue
        n_proj += 1
        rcf = open(os.path.join(work, "base.rcf")).read()
        buf = open(os.path.join(work, "base.rbf"), "rb").read()
        locs = {}
        for ln in open(os.path.join(work, "fuzz.qsf"), errors="replace"):
            m = re.search(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+) -to \"?([^\"\s]+)", ln)
            if m:
                locs[m.group(4)] = tuple(map(int, m.groups()[:3]))
        for sig, bl in F.branches(rcf).items():
            for path, (dinst, lport, pport) in bl:
                if not path or not path[-1].startswith("LOCAL_INTERCONNECT") or pport.lower() not in PHYS:
                    continue
                d = re.sub(r"\[(\d+)\]", r"\1", dinst)
                loc = locs.get(dinst) or locs.get(d)
                if loc is None:
                    continue
                x, y, n = loc
                li = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", path[-1])
                if (int(li.group(1)), int(li.group(2))) != (x, y):
                    continue
                inp = PHYS[pport.lower()]
                seen[(int(li.group(3)), inp, (n // 2) % 2)][code(buf, x, y, n, cells[inp])] += 1
    return seen, n_proj


def build():
    cells = input_cells()
    names = []
    for f in limsolve.JOB_FILES + ["xrkn_holdout2_jobs.json", "xrkn_holdout3_jobs.json"]:
        if os.path.exists(os.path.join(OUT, f)):
            names += json.load(open(os.path.join(OUT, f)))
    seen = collections.defaultdict(collections.Counter)
    for name in names:
        hops = routes.pips(json.load(open(os.path.join(OUT, name + ".route.json"))))
        buf = None
        for u, v in hops:
            mu = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", u)
            mv = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+):(data[abcd])$", v)
            if not (mu and mv) or mu.groups()[:2] != mv.groups()[:2]:
                continue
            buf = buf or xdev.load(OUT, name)
            x, y, n = map(int, mv.groups()[:3])
            inp = PHYS[mv.group(4)]
            seen[(int(mu.group(3)), inp, (n // 2) % 2)][code(buf, x, y, n, cells[inp])] += 1
    table, stat = {}, collections.Counter()
    for k, c in seen.items():
        if len(c) == 1:
            table[",".join(map(str, k))] = sorted(next(iter(c)))
            stat["consistent"] += 1
        else:
            stat["conflicting"] += 1
    json.dump(table, open(os.path.join(OUT, "limux.json"), "w"), indent=0)
    return table, stat, seen


def main() -> int:
    root = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcf")
    seen, n_proj = build_rcf(root)
    table, stat = {}, collections.Counter()
    for k, c in seen.items():
        if len(c) == 1:
            table[",".join(map(str, k))] = sorted(next(iter(c)))
            stat["consistent"] += 1
        else:
            stat["conflicting"] += 1
    json.dump(table, open(os.path.join(OUT, "limux.json"), "w"), indent=0)
    print(f"{n_proj} RCF projects; {len(seen)} (line, input, parity) keys: {dict(stat)}")
    for k, v in [(k, v) for k, v in seen.items() if len(v) > 1][:5]:
        print("  conflict", k, {tuple(sorted(c)): n for c, n in v.items()})
    return 0


def main_timing() -> int:
    table, stat, seen = build()
    print(f"{len(seen)} (line, input, parity) keys: {dict(stat)}")
    bad = [(k, dict(v)) for k, v in seen.items() if len(v) > 1][:5]
    for k, v in bad:
        print("  conflict", k, {tuple(sorted(c)): n for c, n in v.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
