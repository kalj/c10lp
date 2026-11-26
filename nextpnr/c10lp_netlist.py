#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Yosys netlist (synth_intel -family cyclone10lp; write_json) -> a netlist for nextpnr-himbaechel's c10lp uarch.

ynet.py packs the design into LEs; each LE becomes a LUT4 cell (and a DFF cell if registered).  LUT pin I[j] is
logical port j (DATAA..DATAD); the router chooses the physical input through the chip database's permutation
pseudo-pips (a register's own output can only reach physical input 0).  Constant inputs stay unconnected (the
assembler writes them into the mask).  The clock comes from a GCLK_DRV cell at X0Y0; the LE driving the output pin
is pinned to the LE with a measured path to D5 (ypnr.OUT_LE).  Writes the netlist and a sidecar JSON with each
LUT's physical-input assignment and the design dict, for the converter back to asm.py.

  c10lp_netlist.py NETLIST.json TOP OUT.json
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import asm  # noqa: E402
import ynet  # noqa: E402
import ypnr  # noqa: E402


def main() -> int:
    path, top, out = sys.argv[1], sys.argv[2], sys.argv[3]
    luts, regs, ports, dirs = ynet.read(path, top)
    design, clocks = ynet.pack(luts, regs)
    out_net = ports[[p for p, d in dirs.items() if d == "output"][0]][0]
    clk = sorted(clocks)[0] if clocks else None
    bits = {}
    bit = lambda n: bits.setdefault(n, len(bits) + 2)        # yosys uses 0/1 for constants
    cells, phys_of = {}, {}
    out_x, out_y, out_n = ypnr.OUT_LE
    for inst, d in sorted(design.items()):
        # logical LUT pins in port order; the router picks the physical inputs (pseudo-pips IN<i> -> L<j>)
        conn = {}
        assign = {p: j for j, p in enumerate(asm.PORTS) if p in d["inputs"] and not d["inputs"][p].startswith("1'b")}
        for p, i in assign.items():
            conn[f"I[{i}]"] = [bit(d["inputs"][p])]
        conn["F"] = [bit(d["net"])]
        attrs = {}
        if d["net"] == out_net or (d["registered"] and d["q"] == out_net):
            attrs["BEL"] = f"X{out_x}Y{out_y}/LE{out_n // 2}_LUT"
        cells[inst] = dict(type="LUT4", parameters={"INIT": format(d["mask"], "016b")}, attributes=attrs,
                           port_directions={**{k: "input" for k in conn if k != "F"}, "F": "output"},
                           connections=conn)
        phys_of[inst] = assign
        if d["registered"]:
            # a pinned LUT's register is pinned too (nextpnr doesn't place a pinned cluster root's children)
            fattrs = {"BEL": f"X{out_x}Y{out_y}/LE{out_n // 2}_FF"} if "BEL" in attrs else {}
            cells[f"r_{inst}"] = dict(type="DFF", parameters={}, attributes=fattrs,
                                      port_directions={"D": "input", "CLK": "input", "Q": "output"},
                                      connections={"D": [bit(d["net"])], "CLK": [bit(clk)], "Q": [bit(d["q"])]})
    if clk:
        cells["gclk"] = dict(type="GCLK_DRV", parameters={}, attributes={"BEL": "X0Y0/GCLK_DRV"},
                             port_directions={"O": "output"}, connections={"O": [bit(clk)]})
    netnames = {n: {"bits": [b], "hide_name": 0, "attributes": {}} for n, b in bits.items()}
    json.dump({"creator": "c10lp_netlist.py", "modules": {top: {"attributes": {"top": "00000000000000000000000000000001"},
               "ports": {}, "cells": cells, "netnames": netnames}}}, open(out, "w"), indent=1)
    json.dump({"design": design, "phys": phys_of, "out_net": out_net, "clock": clk, "ports": ports, "dirs": dirs,
               "clocks": sorted(clocks)}, open(out.replace(".json", "_side.json"), "w"), indent=1)
    print(f"{len(design)} LEs ({sum(d['registered'] for d in design.values())} registered) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
