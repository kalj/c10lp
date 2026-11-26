#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""nextpnr-himbaechel (c10lp uarch) result -> our route description -> asm.py -> RBF.

Reads the routed netlist (--write) and the sidecar of c10lp_netlist.py.  Placement: each LUT4 cell's bel
X<x>Y<y>/LE<n>_LUT is LE slot N = 2n.  Routing: each net's ROUTING attribute lists (wire, pip "tile/DST/SRC",
strength); walking back from every sink gives that sink's path in chip-database wires, translated to our node names:
  BUF<b> -> LE_BUFFER   LL<n> -> LOCAL_LINE   LINE<k> -> LOCAL_INTERCONNECT   NBW/NBE<b> -> the neighbour's LE_BUFFER
  R4_<w>_<k> at column x -> R4 wire of index w starting at column x - k
  C4_<w>_<a>_<r> at (x, y) -> C4 wire of index w starting at (x - a, y - r)
and the permutation pseudo-pip LE<n>_IN<i> -> LE<n>_L<j> gives the physical input i of logical LUT pin j.  The pin
pseudo-pips (c10lp_netlist.py --io) expand into their library paths (out/iopaths.json): an input's from IO_DATAIN to
the LAB line, the output's from the LE buffer to D5's I/O block.  The clock net (GCLK), and the output pin without
--io, are left to ypnr.emit, as in our own flow, which then assembles and writes
out/ypnr_TOP.{rcf,rbf,v} and out/ypnr_TOP_locs.qsf (for flow/ycheck.py --fresh).

  npnr2asm.py ROUTED.json SIDECAR.json TOP
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import asm  # noqa: E402
import rcfforce as F  # noqa: E402
import switchmodel as S  # noqa: E402
import ypnr  # noqa: E402

OUT = os.path.join(HERE, "out")
INV = {v: k for k, v in asm.PHYS.items()}                # physical input -> .rcf port name
TW = re.compile(r"X(\d+)Y(\d+)/([\w-]+)$")


def node(x: int, y: int, w: str):
    """Our node name for chip-database tile wire w at (x, y), or None for LE-internal wires."""
    m = re.match(r"(BUF|NBW|NBE)(\d+)$", w)
    if m:
        dx = {"BUF": 0, "NBW": -1, "NBE": 1}[m[1]]
        return f"LE_BUFFER_X{x + dx}_Y{y}_N0_I{m[2]}"
    m = re.match(r"IL_(\d+)_(\d+)_(\d+)$", w)            # pin path library: a LAB line, a D5-driving buffer
    if m:
        return f"LOCAL_INTERCONNECT_X{m[1]}_Y{m[2]}_N0_I{m[3]}"
    m = re.match(r"OB_(\d+)_(\d+)_(\d+)$", w)
    if m:
        return f"LE_BUFFER_X{m[1]}_Y{m[2]}_N0_I{m[3]}"
    m = re.match(r"LL(\d+)$", w)
    if m:
        return f"LOCAL_LINE_X{x}_Y{y}_N0_I{m[1]}"
    m = re.match(r"LINE(\d+)$", w)
    if m:
        return f"LOCAL_INTERCONNECT_X{x}_Y{y}_N0_I{m[1]}"
    m = re.match(r"R4_(\d+)_(-?\d+)$", w)
    if m:
        return f"R4_X{x - int(m[2])}_Y{y}_N0_I{m[1]}"
    m = re.match(r"C4_(\d+)_(\d+)_(-?\d+)$", w)
    if m:
        return f"C4_X{x - int(m[2])}_Y{y - int(m[3])}_N0_I{m[1]}"
    return None


def main() -> int:
    routed, side, top = sys.argv[1], sys.argv[2], sys.argv[3]
    sd = json.load(open(side))
    design = sd["design"]
    for i, d in design.items():                         # our netlist names (as ypnr): LUT le<k>, register r_le<k>
        d["src"] = i
        if d["registered"]:
            d["src_reg"] = f"r_{i}"
    mod = next(iter(json.load(open(routed))["modules"].values()))
    les = {}
    for name, c in mod["cells"].items():
        if c["type"] == "LUT4":
            m = re.match(r"X(\d+)Y(\d+)/LE(\d+)_LUT$", c["attributes"]["NEXTPNR_BEL"])
            les[name] = (int(m[1]), int(m[2]), 2 * int(m[3]))
    net_of_bit = {n["bits"][0]: name for name, n in mod["netnames"].items() if n["bits"]}
    lib = json.load(open(os.path.join(OUT, "iopaths.json")))
    model = S.Model()
    in_port = {b[0]: p for p, b in sd["ports"].items() if sd["dirs"][p] == "input"}
    outpath, extra, rname = None, set(), {}
    blocks = collections.defaultdict(list)
    nroutes = 0
    for name, n in mod["netnames"].items():
        r = n.get("attributes", {}).get("ROUTING", "")
        if not r or name == sd["clock"]:
            continue
        parts = r.split(";")
        # keyed by node: a wire spanning tiles (R4, neighbour buffers) appears under different tile-wire names in
        # the pip into it and the pip out of it
        def canon(tw):
            mm = TW.match(tw)
            return node(int(mm[1]), int(mm[2]), mm[3]) or tw
        parent = {}
        for i in range(0, len(parts) - 2, 3):
            wire, pip = parts[i], parts[i + 1]
            if pip:
                t, dst, src = pip.split("/")
                parent[canon(f"{t}/{dst}")] = canon(f"{t}/{src}")
        # sinks: logical LUT pins LE<n>_L<j>
        for wire in parent:
            m = TW.match(wire)
            if m and m[3] == "D5_I":
                # the output pin's pseudo-pip: the library path from this LE buffer to D5's I/O block line
                outpath = lib["output"][parent[wire]] + ["BLOCK_INPUT_MUX_X6_Y0_N0_I10"]
                continue
            if m and m[3] == "ENA":
                # clock enable: ... -> LAB line -> LAB_CONTROL_MUX slot 2 -> every enabled register of this LAB
                x, y = int(m[1]), int(m[2])
                path, w, root = [], parent[wire], None
                while w is not None:
                    if not TW.match(w) and (not path or path[-1] != w):
                        path.append(w)
                    root, w = w, parent.get(w)
                path.reverse()
                pm = re.match(r"X\d+Y\d+/PIN_(\w+)$", root or "")
                if pm:
                    lp = lib["input"][f"PIN_{pm[1]}|{path[0]}"]
                    i0 = next(i for i, nd in enumerate(lp) if nd.startswith("IO_DATAIN"))
                    path = lp[i0:] + path[1:]
                    rname[name] = f"{in_port[name]}~input"
                regs_here = [i for i, (lx, ly, _n) in les.items() if (lx, ly) == (x, y) and design[i]["registered"]]
                if any(not design[i].get("ena") for i in regs_here):
                    raise SystemExit(f"LAB X{x}Y{y}: enabled and free-running registers share the LAB's enable")
                for i in regs_here:
                    blocks[name].append((path + [f"LAB_CONTROL_MUX_X{x}_Y{y}_N0_I2"],
                                         f"\tdest = ( {design[i]['src_reg']}, ENA );"))
                    nroutes += 1
                continue
            lm = re.match(r"LE(\d+)_L(\d+)$", m[3]) if m else None
            if not lm:
                continue
            x, y, le, j = int(m[1]), int(m[2]), int(lm[1]), int(lm[2])
            phys = re.match(r"X\d+Y\d+/LE\d+_IN(\d+)$", parent[wire])
            inp = int(phys[1])
            path, w, root = [], parent.get(parent[wire]), None
            while w is not None:
                if not TW.match(w) and (not path or path[-1] != w):
                    path.append(w)                      # a node name (canon() keeps LE-internal tile wires)
                root, w = w, parent.get(w)
            path.reverse()
            pm = re.match(r"X\d+Y\d+/PIN_(\w+)$", root or "")
            if pm:
                # an input pin's pseudo-pip: the library path from IO_DATAIN (the .rcf's start) to the LAB line.  The
                # IOIBUF -> IO_DATAIN cells of the corpus (X3Y0's pads: 1-2 cells, P3 in 829 builds) are not set in
                # Quartus's build of our routing (its back-annotation has no IO_DATAIN node there): left out
                lp = lib["input"][f"PIN_{pm[1]}|{path[0]}"]
                i0 = next(i for i, nd in enumerate(lp) if nd.startswith("IO_DATAIN"))
                path = lp[i0:] + path[1:]
                rname[name] = f"{in_port[name]}~input"
            inst = next(i for i, (lx, ly, ln) in les.items() if (lx, ly, ln) == (x, y, 2 * le))
            if path and path[-1].startswith(("LOCAL_INTERCONNECT", "LOCAL_LINE")):
                logical = asm.PORTS[j]
                dest = f"\tdest = ( {design[inst]['net']}, {logical} ), route_port = {INV[inp]};"
                blocks[name].append((path, dest))
                nroutes += 1
            elif not path and inp == 0:
                pass                                    # own register feedback: hard-wired, nothing to route
            else:
                raise SystemExit(f"net {name}: unexpected path {path} into {inst} I{inp}")
    # .rcf text with labels and branch points, as router.py writes it
    text = []
    for s, bl in sorted(blocks.items()):
        written, out = [], []
        for path, dest in bl:
            share = max((next((i for i, (a, b) in enumerate(zip(q, path)) if a != b), min(len(q), len(path)))
                         for q in written), default=0)
            t = f"\tbranch_point = Label_{F.rcf_name(path[share - 1])};\n" if share else ""
            t += "".join(f"\tlabel = Label_{F.rcf_name(nd)}, {F.rcf_name(nd)};\n" for nd in path[share:])
            written.append(path)
            out.append(t + dest)
        text.append(f"signal_name = {rname.get(s, s)} {{\n" + "\n\n".join(out) + "\n}")
    # the pin paths are pseudo-pips to nextpnr: their wires must not be used twice
    owner = {}
    for s, bl in blocks.items():
        for path, _ in bl:
            for nd in path:
                if owner.setdefault(nd, s) != s:
                    raise SystemExit(f"{nd} used by nets {owner[nd]} and {s} (a pin path crosses another route)")
    for nd in (outpath or [])[1:]:
        if nd in owner and owner[nd] != sd["out_net"]:
            raise SystemExit(f"{nd}: the D5 path crosses net {owner[nd]}")
    rcf = "\n".join(text) + "\n"
    dw = json.load(open(os.path.join(OUT, "limux_dw.json")))
    a = ypnr.emit(top, design, les, rcf, sd["ports"], sd["dirs"], set(sd["clocks"]), sd["out_net"], dw,
                  outpath=outpath, extra=extra)
    print(f"{len(les)} LEs from nextpnr, {nroutes} LUT-input routes; not modelled: {dict(a.unknown)} -> out/ypnr_{top}.rbf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
