#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Yosys netlist (synth_intel -family cyclone10lp; write_json) -> a netlist for nextpnr-himbaechel's c10lp uarch.

ynet.py packs the design into LEs; each LE becomes a LUT4 cell (and a DFF cell if registered).  LUT pin I[j] is
logical port j (DATAA..DATAD); the router chooses the physical input through the chip database's permutation
pseudo-pips (a register's own output can only reach physical input 0).  Constant inputs stay unconnected (the
assembler writes them into the mask).  The clock comes from a GCLK_DRV cell at X0Y0; the LE driving the output pin
is pinned to the LE with a measured path to D5 (ypnr.OUT_LE).  With --io, ports A..D (D1..D4) become IBUF cells and
Q (D5) an OBUF cell at the I/O tile, and nextpnr places every LE (pin path library, mapping/iopaths.py).
Writes the netlist and a sidecar JSON with each
LUT's physical-input assignment and the design dict, for the converter back to asm.py.

  c10lp_netlist.py NETLIST.json TOP OUT.json [--io [--out-le X,Y,N]]

--out-le pins the output LE to slot N of LAB (X, Y): with the pin path library only some LE buffers reach D5, which
the placer can't see (nextpnr/npnr_flow.py --io tries the library's LEs nearest D5 in turn).
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

INPUTS = {"A": "N3", "B": "P3", "C": "R3", "D": "T3"}     # D1..D4 (xdev.VIDOR_PINS)
PAD = {"N3": (1, 0), "P3": (3, 0), "R3": (3, 0), "T3": (3, 0)}   # their pad tiles (c10lp_arch_gen.PAD_TILE)
RADIUS = 6                                                # LABs (Manhattan) around the output LE for pin-fed LUTs


def main() -> int:
    args = sys.argv[1:]
    io = "--io" in args
    out_le = tuple(map(int, args[args.index("--out-le") + 1].split(","))) if "--out-le" in args else None
    path, top, out = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--out-le")][:3]
    luts, regs, ports, dirs = ynet.read(path, top)
    design, clocks = ynet.pack(luts, regs)
    out_net = ports[[p for p, d in dirs.items() if d == "output"][0]][0]
    clk = sorted(clocks)[0] if clocks else None
    bits = {}
    bit = lambda n: bits.setdefault(n, len(bits) + 2)        # yosys uses 0/1 for constants
    cells, phys_of, pinned = {}, {}, set()
    out_x, out_y, out_n = out_le or ypnr.OUT_LE
    for inst, d in sorted(design.items()):
        # logical LUT pins in port order; the router picks the physical inputs (pseudo-pips IN<i> -> L<j>)
        conn = {}
        assign = {p: j for j, p in enumerate(asm.PORTS) if p in d["inputs"] and not d["inputs"][p].startswith("1'b")}
        for p, i in assign.items():
            conn[f"I[{i}]"] = [bit(d["inputs"][p])]
        conn["F"] = [bit(d["net"])]
        attrs = {}
        if (not io or out_le) and (d["net"] == out_net or (d["registered"] and d["q"] == out_net)):
            attrs["BEL"] = f"X{out_x}Y{out_y}/LE{out_n // 2}_LUT"
            pinned.add(inst)
        cells[inst] = dict(type="LUT4", parameters={"INIT": format(d["mask"], "016b")}, attributes=attrs,
                           port_directions={**{k: "input" for k in conn if k != "F"}, "F": "output"},
                           connections=conn)
        phys_of[inst] = assign
        if d["registered"]:
            # a pinned LUT's register is pinned too (nextpnr doesn't place a pinned cluster root's children)
            fattrs = {"BEL": f"X{out_x}Y{out_y}/LE{out_n // 2}_FF"} if "BEL" in attrs else {}
            conn_r = {"D": [bit(d["net"])], "CLK": [bit(clk)], "Q": [bit(d["q"])]}
            if d.get("ena"):
                conn_r["EN"] = [bit(d["ena"])]      # LAB-wide ENA wire (LAB_CONTROL_MUX slot 2)
            cells[f"r_{inst}"] = dict(type="DFF", parameters={}, attributes=fattrs,
                                      port_directions={**{k: "input" for k in conn_r if k != "Q"}, "Q": "output"},
                                      connections=conn_r)
    if clk:
        cells["gclk"] = dict(type="GCLK_DRV", parameters={}, attributes={"BEL": "X0Y0/GCLK_DRV"},
                             port_directions={"O": "output"}, connections={"O": [bit(clk)]})
    if io:
        for p, d_ in dirs.items():
            if d_ == "input" and ports[p][0] not in clocks:
                pin = INPUTS.get(p)
                if pin is None:
                    raise SystemExit(f"input {p}: the Vidor test inputs are A..D (D1..D4)")
                cells[f"ibuf_{p}"] = dict(type="IBUF", parameters={}, attributes={"BEL": f"X{PAD[pin][0]}Y{PAD[pin][1]}/IBUF_{pin}"},
                                          port_directions={"O": "output"}, connections={"O": [bit(ports[p][0])]})
            elif d_ == "output":
                if p != "Q":
                    raise SystemExit(f"output {p}: the Vidor test output is Q (D5)")
                cells["obuf_Q"] = dict(type="OBUF", parameters={}, attributes={"BEL": "X6Y0/OBUF_D5"},
                                       port_directions={"I": "input"}, connections={"I": [bit(out_net)]})
    regions = {}
    if io:
        # a LUT fed by input pins can only sit where the pin path library reaches from all of them: those LABs within
        # RADIUS of the output LE (nextpnr/region_row.py's C10LP_CELL_REGIONS; nextpnr chooses among them)
        import re
        lib = json.load(open(os.path.join(HERE, "out", "iopaths.json")))["input"]
        ctl = json.load(open(os.path.join(HERE, "out", "ctlmux.json")))
        ena_lines = {int(k.split("|")[0]) for k, v in ctl.items() if not k.startswith("_") and k.endswith("|2")
                     and 1 <= len(v) <= 2}                 # as c10lp_arch_gen.ENA_LINES
        reach, reach_ena = {}, {}
        for k in lib:
            pin, line = k.split("|")
            mm = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)", line)
            reach.setdefault(pin[4:], set()).add((int(mm[1]), int(mm[2])))
            if int(mm[3]) in ena_lines:
                reach_ena.setdefault(pin[4:], set()).add((int(mm[1]), int(mm[2])))
        pin_of = {ports[p][0]: INPUTS[p] for p, d_ in dirs.items() if d_ == "input" and p in INPUTS}
        groups = {}
        for inst, d in sorted(design.items()):
            pins = {pin_of[n] for n in d["inputs"].values() if n in pin_of}
            en_pin = pin_of.get(d.get("ena"))              # an enable from a pin: its line must feed ENA
            if not (pins or en_pin) or (out_le and inst in pinned):
                continue
            labs = set.intersection(*([reach.get(p, set()) for p in pins] + ([reach_ena.get(en_pin, set())] if en_pin
                                                                              else [])))
            pins |= {en_pin} if en_pin else set()
            if not labs:
                raise SystemExit(f"{inst}: no LAB reached from all of {sorted(pins)} in the pin path library")
            # a LAB above the output LE reaches it over a downward C4, driven from its row L and starting at L - 4,
            # which the database lacks below row 2 (the bottom edge's C4s)
            ok = {l for l in labs if (l[1] <= out_y or l[1] - 4 >= 2)
                  and abs(l[0] - out_x) + abs(l[1] - out_y) <= RADIUS}
            if not ok:
                raise SystemExit(f"{inst}: no LAB within {RADIUS} of the output LE reached from all of {sorted(pins)}")
            regions[inst] = sorted(ok)
            groups.setdefault((tuple(sorted(pins)), tuple(sorted(ok))), []).append(inst)
        # cells with the same pins share their nearest LABs: enough for the group (16 LEs a LAB) and one more, so a
        # counter with a pin enable stays in a few LABs instead of spreading over every reachable one
        for (_p, ok), insts in groups.items():
            near = sorted(ok, key=lambda l: (abs(l[0] - out_x) + abs(l[1] - out_y), l))[:-(-len(insts) // 16) + 1]
            for inst in insts:
                regions[inst] = [list(l) for l in near]
        json.dump(regions, open(out.replace(".json", "_regions.json"), "w"), indent=1)
    netnames = {n: {"bits": [b], "hide_name": 0, "attributes": {}} for n, b in bits.items()}
    json.dump({"creator": "c10lp_netlist.py", "modules": {top: {"attributes": {"top": "00000000000000000000000000000001"},
               "ports": {}, "cells": cells, "netnames": netnames}}}, open(out, "w"), indent=1)
    json.dump({"design": design, "phys": phys_of, "out_net": out_net, "clock": clk, "ports": ports, "dirs": dirs,
               "clocks": sorted(clocks), "io": io}, open(out.replace(".json", "_side.json"), "w"), indent=1)
    print(f"{len(design)} LEs ({sum(d['registered'] for d in design.values())} registered) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
