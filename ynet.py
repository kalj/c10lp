#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a Yosys netlist (synth_intel -family cyclone10lp -nodsp -nobram; write_json) and pack it into LEs.

Cells: cyclone10lp_lcell_comb (lut_mask, dataa..datad, combout), dffeas (d, q, clk; ena/clrn/prn/sclr/aload tied
off) and leftover $not (folded into a LUT, mask 5555 on dataa).  An LE is a LUT plus, optionally, the register its
combout drives when that is the LUT's only load.  Nets are named by Yosys bit numbers ("n123"); constants are "1'b0"
and "1'b1".  Output: a design dict in the form asm.py and router.py use for templates:
  {instance: {"mask": int, "inputs": {"DATAA": net, ...}, "net": LUT output net, "registered": bool, "q": reg net}}
plus the clock net, the input and output ports.

  ynet.py NETLIST.json TOP
"""
from __future__ import annotations

import collections
import json
import sys

PORT = {"dataa": "DATAA", "datab": "DATAB", "datac": "DATAC", "datad": "DATAD"}


def bitname(b):
    if b in ("0", "1"):
        return f"1'b{b}"
    return f"n{b}"


def read(path: str, top: str):
    m = json.load(open(path))["modules"][top]
    ports = {name: [bitname(b) for b in p["bits"]] for name, p in m["ports"].items()}
    dirs = {name: p["direction"] for name, p in m["ports"].items()}
    luts, regs = {}, {}
    for name, c in m["cells"].items():
        conn = {k: bitname(v[0]) for k, v in c["connections"].items() if v}
        if c["type"] == "cyclone10lp_lcell_comb":
            mask = c["parameters"]["lut_mask"]
            mask = int(mask, 2) if set(mask) <= {"0", "1"} else int(mask, 16)
            luts[name] = dict(mask=mask, inputs={PORT[k]: v for k, v in conn.items() if k in PORT}, out=conn["combout"])
        elif c["type"] == "$not":
            luts[name] = dict(mask=0x5555, inputs={"DATAA": conn["A"]}, out=conn["Y"])
        elif c["type"] == "dffeas":
            for tie, want in (("ena", "1'b1"), ("clrn", "1'b1"), ("prn", "1'b1"), ("sclr", "1'b0"), ("aload", "1'b0")):
                if conn.get(tie, want) != want:
                    raise SystemExit(f"{name}: {tie} = {conn[tie]} not supported yet")
            regs[name] = dict(d=conn["d"], q=conn["q"], clk=conn["clk"])
        else:
            raise SystemExit(f"cell type {c['type']} not supported yet")
    return luts, regs, ports, dirs


def pack(luts: dict, regs: dict):
    loads = collections.Counter()
    for l in luts.values():
        for v in l["inputs"].values():
            loads[v] += 1
    for r in regs.values():
        loads[r["d"]] += 1
    by_out = {l["out"]: n for n, l in luts.items()}
    design, used_regs = {}, set()
    for i, (name, l) in enumerate(sorted(luts.items())):
        inst = f"le{i}"
        reg = next((rn for rn, r in regs.items() if r["d"] == l["out"] and loads[l["out"]] == 1), None)
        design[inst] = dict(mask=l["mask"], inputs=dict(l["inputs"]), net=l["out"], registered=reg is not None,
                            q=regs[reg]["q"] if reg else None, src=name)
        if reg:
            used_regs.add(reg)
    left = set(regs) - used_regs
    if left:
        raise SystemExit(f"registers without a packable LUT (need a pass-through LUT): {sorted(left)}")
    clocks = {r["clk"] for r in regs.values()}
    return design, clocks


def main() -> int:
    luts, regs, ports, dirs = read(sys.argv[1], sys.argv[2])
    design, clocks = pack(luts, regs)
    print(f"{len(luts)} LUTs, {len(regs)} registers -> {len(design)} LEs ({sum(d['registered'] for d in design.values())} "
          f"with a register); clock nets {clocks}; ports {dirs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
