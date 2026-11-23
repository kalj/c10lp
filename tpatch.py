#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fill the LUTs of any Quartus template design without recompiling (10CL016).

A template is templates/NAME/top.v: a netlist of cyclone10lp_lcell_comb
instances (and registers, any wiring) on ports A..D (D1..D4) -> Q (D5).

  tpatch.py init NAME            compile once unplaced, back-annotate every logic
                                 cell to templates/NAME/locs.qsf, then build the
                                 pinned base (masks as written in top.v)
  tpatch.py check NAME [--random K]
                                 K random mask sets compiled by Quartus vs written
                                 by the model
  tpatch.py write NAME --masks inst=XXXX,... -o out.rbf
                                 unnamed instances get 0000; header always fixed

Compiles: 2 for init, K for check (about 12 s each).  Every written file passes
gate.py (differs from the base build only in its LUT cells, CRCs and header).

Each LUT's input order is read from the base build: the base masks must be
asymmetric enough that one order explains them (lutpos.unique_perm_mask).
Patched files keep the base's wiring.  Quartus may wire a different mask set
differently (it re-orders LUT inputs per mask), so `check` reports those builds
as "re-wired by Quartus": not comparable byte for byte, not a model failure.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import random
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(xdev.HERE, "out")
PINS = "vidorlo"
M9K_RE = re.compile(r"set_location_assignment\s+(M9K_X\d+_Y\d+_N\d+)\s+-to\s+\"?altsyncram:(u\d+)\|")
LOC_RE = re.compile(r"set_location_assignment\s+(LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+)\s+-to\s+\"?([^\"\n]+)\"?")


def cell_names(name: str) -> dict[str, list[str]]:
    """Names Quartus may give each LUT instance's cell: the instance, or its combout net."""
    src = open(os.path.join(xdev.TEMPLATE_DIR, name, "top.v")).read()
    res = {}
    for inst, _ in xdev.tpl_luts(name):
        body = re.search(rf"\b{re.escape(inst)}\s*\((.*?)\);", src, re.S)
        net = re.search(r"\.combout\(\s*([^\s)]+)\s*\)", body.group(1)) if body else None
        res[inst] = [inst] + ([net.group(1)] if net else [])
    return res


def job(name: str, masks) -> xdev.Job:
    spec = "asis" if masks is None else "-".join(f"{m:04X}" for m in masks)
    return xdev.Job("c10_016", f"tpl:{name}:{spec}", (0, 0, 0), PINS)


def init(name: str) -> int:
    luts = xdev.tpl_luts(name)
    first = job(name, None)
    m = xdev.build_one(first, OUT, True)
    if not m["ok"]:
        raise SystemExit(f"compile failed: {m.get('error')}")
    work = os.path.join(OUT, "work", first.name)
    if not os.path.isdir(work):
        raise SystemExit(f"{work} is gone (cached build?); delete {first.name}.* and rerun init")
    r = subprocess.run([xdev.tool("quartus_cdb"), "fuzz", "--back_annotate=lc"], cwd=work,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("back-annotation failed:\n" + (r.stdout + r.stderr)[-800:])
    raw = open(os.path.join(work, "fuzz.qsf"), errors="replace").read().splitlines()
    lines = [ln.strip() for ln in raw if LOC_RE.search(ln)]
    m9k = sorted({f'set_location_assignment {m.group(1)} -to "{m.group(2)}"'
                  for m in (M9K_RE.search(ln) for ln in raw) if m})
    locs = {LOC_RE.search(ln).group(5): ln for ln in lines}
    missing = [i for i, names in cell_names(name).items() if not any(n in locs for n in names)]
    if missing:
        raise SystemExit(f"no back-annotated LCCOMB for {missing}; got {sorted(locs)}")
    with open(os.path.join(xdev.TEMPLATE_DIR, name, "locs.qsf"), "w") as f:
        f.write("# Back-annotated by tpatch.py init (quartus_cdb --back_annotate=lc)\n")
        f.write("\n".join(sorted(set(lines)) + m9k) + "\n")
    print(f"{len(lines)} cells pinned: " + ", ".join(sorted(locs)))
    weak = [i for i, m in luts if not lutpos.unique_perm_mask(m)]
    if weak:
        raise SystemExit(f"placeholder masks of {weak} don't identify the input order; use "
                         "asymmetric ones (lutpos.unique_perm_mask)")
    r = xdev.build_one(job(name, [m for _, m in luts]), OUT, False)
    if not r["ok"]:
        raise SystemExit(f"pinned base build failed: {r.get('error')}")
    Template(name).report()
    return 0


class Template:
    def __init__(self, name: str, partial: bool = False):
        self.name = name
        self.luts = [i for i, _ in xdev.tpl_luts(name)]
        self.les = {}
        locs = open(os.path.join(xdev.TEMPLATE_DIR, name, "locs.qsf")).read()
        cells = {inst: (int(x), int(y), int(n)) for kind, x, y, n, inst in LOC_RE.findall(locs)
                 if kind == "LCCOMB"}
        for inst, names in cell_names(name).items():
            self.les[inst] = next(cells[n] for n in names if n in cells)
        # The base is the template with its masks as written (all-0000 can let Quartus
        # optimise registers away), pinned to the back-annotated placement.
        self.base = dict(xdev.tpl_luts(name))
        self.zero = xdev.load(OUT, job(name, [self.base[i] for i in self.luts]).name)
        if self.zero is None:
            raise SystemExit(f"run `tpatch.py init {name}` first")
        self.g = rbfgeom.infer(self.zero)
        self.perms, self.fixed = {}, set()
        for inst in self.luts:
            loc = self.les[inst]
            on = {c for c in lutpos._predict_phys(*loc)
                  if self.zero[self.g.preamble + c[0] * self.g.frame + c[1]] >> c[2] & 1}
            hits = lutpos.perms_for_mask(on, *loc, self.base[inst])
            if len(hits) != 1:
                if not partial:
                    raise SystemExit(f"{inst} at {loc}: base build matches {len(hits)} input orders")
                self.fixed.add(inst)          # keeps Quartus's bits; can't be rewritten
                continue
            self.perms[inst] = hits[0]

    def report(self) -> None:
        for inst in self.luts:
            x, y, n = self.les[inst]
            print(f"  {inst:12s} X{x}Y{y}N{n:<2d} input order {self.perms[inst]}")
        print("input orders read from the base build: each unique")

    def write(self, masks: dict[str, int]) -> bytes:
        buf = bytearray(self.zero)
        v = lutpatch.header_sum(self.zero)
        for inst in self.luts:
            if inst in self.fixed:
                if masks.get(inst, self.base[inst]) != self.base[inst]:
                    raise SystemExit(f"{inst} is fixed (input order unknown); can't change its mask")
                continue
            flip = masks.get(inst, 0) ^ self.base[inst]
            cells = lutpos.predict(*self.les[inst], self.perms[inst])
            for i, (f, p, b) in enumerate(cells):
                if flip >> i & 1:
                    off = self.g.preamble + f * self.g.frame + p
                    w = lutpos.header_weight(f, p, b)
                    v += -w if buf[off] >> b & 1 else w      # clearing a bit removes its weight
                    buf[off] ^= 1 << b
        lutpatch.patch_crc(buf, self.g)
        lutpatch.set_header_sum(buf, v % (1 << 32))
        new = bytes(buf)
        errs = gate.check(self.zero, new, list(self.les[i] for i in self.luts if i not in self.fixed))
        if errs:
            raise SystemExit(f"gate refused the written file: {errs}")
        return new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "check", "write"])
    ap.add_argument("name")
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--masks", default="")
    ap.add_argument("-o", "--output")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()

    if a.cmd == "init":
        return init(a.name)
    t = Template(a.name)
    if a.cmd == "write":
        masks = {}
        for kv in filter(None, a.masks.split(",")):
            k, v = kv.split("=")
            if k not in t.luts:
                raise SystemExit(f"unknown LUT {k}; template has {t.luts}")
            masks[k] = int(v, 16)
        if not a.output:
            raise SystemExit("write needs -o")
        open(a.output, "wb").write(t.write(masks))
        print(f"wrote {a.output} (gate PASS)")
        return 0

    t.report()
    r = random.Random(a.seed)
    sets = [[r.randrange(1, 0xFFFF) for _ in t.luts] for _ in range(a.random)]
    js = [job(a.name, s) for s in sets]
    if js:
        print(xdev.estimate(js, OUT, a.jobs), flush=True)
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda j: xdev.build_one(j, OUT, False), js))
    bad = 0
    for s, j in zip(sets, js):
        ref = xdev.load(OUT, j.name)
        new = t.write(dict(zip(t.luts, s)))
        if ref == new:
            verdict = "BYTE-IDENTICAL"
        elif gate.check(t.zero, ref, [t.les[i] for i in t.luts]):
            # Not comparable byte for byte; its LUT cells must still fit the model.
            fit = all(lutpos.perms_for_mask(
                {c for c in lutpos._predict_phys(*t.les[i])
                 if ref[t.g.preamble + c[0] * t.g.frame + c[1]] >> c[2] & 1}, *t.les[i], m)
                for i, m in zip(t.luts, s))
            verdict = ("re-wired by Quartus; its LUT cells fit the model" if fit else
                       "re-wired by Quartus and its LUT cells do NOT fit the model")
            bad += not fit
        else:
            verdict = "DIFFERS in the LUT cells -- model failure"
            bad += 1
        print(f"  {'-'.join(f'{m:04X}' for m in s)}: {verdict}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
