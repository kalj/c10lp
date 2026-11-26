#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assemble a bitstream for a placed and routed design from our own tables, without Quartus's RBF.

Inputs: a tpatch template (LUT masks, registers, placement in locs.qsf) and a route description in .rcf form (which
resources each net uses, and each LUT input's physical port).  Every bit comes from a model:
  LUT cells           lutpos (cells per LE, permuted logical -> physical inputs)
  LUT input muxes     li_local_table.json (local line -> input), routing_pips LE-anchored keys (LAB line -> input)
  LE output selects   le_output_select.json (combinational / registered)
  routing hops        switchmodel.Model (drivers, selects, neighbour links, local feedback)
  fixed bundles       out/outpath_bits.json (the output path for this placement), LAB/row/global clock bits
  baseline            out/lo_quartus_0000.rbf (all-zero design) with its own D5 driver cleared (out/zero_own_bits.json)
then CRCs and the header checksum are recomputed.  `compare` diffs the result with Quartus's build of the same design.

  asm.py compare NAME [--counter]      (--counter: the template's functional counter masks; the reference is then
                                       Quartus's build of those masks, compiled with the same pinned placement)
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import lutpos  # noqa: E402
import rcfforce as F  # noqa: E402
import reroute  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
PORTS = ["DATAA", "DATAB", "DATAC", "DATAD"]
# .rcf route_port names -> lutpos physical input numbers (read off tpatch's input orders: 6/6 LUTs consistent)
PHYS = {"DATAC": 0, "DATAD": 1, "DATAB": 2, "DATAA": 3}


def counter_masks(name: str) -> dict:
    """Functional masks for the 3-bit-group counter templates (div24 family): group j has bits 3j..3j+2 with carry-in
    on datab (n) / dataa (cy); n(3j) = a ^ b, n(3j+1) = a ^ (b & c), n(3j+2) = a ^ (b & c & d), cy = a & b & c & d,
    lut_out = a (Q = s[23]).  Minterm i = a + 2b + 4c + 8d."""
    f = {0: lambda a, b, c, d: a ^ b, 1: lambda a, b, c, d: a ^ (b & c), 2: lambda a, b, c, d: a ^ (b & c & d)}
    mask = lambda fn: sum(fn(i & 1, i >> 1 & 1, i >> 2 & 1, i >> 3 & 1) << i for i in range(16))
    out = {}
    for inst, _m in xdev.tpl_luts(name):
        if inst.startswith("cy"):
            out[inst] = mask(lambda a, b, c, d: a & b & c & d)
        elif inst == "lut_out":
            out[inst] = mask(lambda a, b, c, d: a)
        else:
            out[inst] = mask(f[int(inst[1:]) % 3])
    return out


def instances(name: str):
    """instance -> (mask, registered?, {logical port: source net}) from the template's top.v."""
    src = open(os.path.join(xdev.TEMPLATE_DIR, name, "top.v")).read()
    out = {}
    for m in re.finditer(r"lut_mask\(16'h([0-9A-Fa-f]{4})\).*?\)\)\s*\n?\s*(\w+)\s*\((.*?)\);", src, re.S):
        mask, inst, conns = int(m.group(1), 16), m.group(2), m.group(3)
        pins = dict(re.findall(r"\.(data[abcd])\(([^)]*)\)", conns))
        comb = re.search(r"\.combout\(([^)]*)\)", conns).group(1)
        out[inst] = dict(mask=mask, inputs={p.upper(): v.strip() for p, v in pins.items()}, net=comb.strip())
    whole = bool(re.search(r"\bs\s*<=\s*n\s*;", src))          # "always @(posedge K) s <= n;": every n[i] registered
    regs = set(re.findall(r"s\[(\d+)\]\s*<=\s*n\[\1\]", src))
    for inst, d in out.items():
        m = re.match(r"n(\d+)$", inst)
        d["registered"] = bool(m) and (whole or m.group(1) in regs)
        d["q"] = d["net"].replace("n[", "s[") if d["registered"] else None      # the register's output net
    return out


def node_le(node: str):
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)", node)
    return tuple(map(int, m.groups())) if m else None


class Asm:
    def __init__(self):
        self.m = S.Model()
        self._g = None                        # the corpus route graph, built only for the LAB-line fallback below
        self.local = {k: v for k, v in json.load(open(os.path.join(HERE, "data", "li_local_table.json")))["entries"].items()}
        self.osel = json.load(open(os.path.join(HERE, "data", "le_output_select.json")))
        self.set, self.clear = set(), set()
        self.posmux, self.used_posmux = None, 0
        self.dw, self.used_dw = None, 0
        self.second_path = []                      # (table cell, other candidate) of each second-path select
        self.unknown = collections.Counter()

    def lut(self, x, y, n, mask, perm):
        cells = lutpos.predict(x, y, n, perm)
        for i, c in enumerate(cells):
            (self.set if mask >> i & 1 else self.clear).add(c)

    def lut_input(self, src: str, x, y, n, port: str, src_slot=None):
        """The LUT input mux bits for `src` (a LOCAL_LINE or LOCAL_INTERCONNECT node) on .rcf physical port `port`.
        A position-specific code measured from other builds at this LE (posmux.py) takes precedence."""
        if self.dw is not None:
            # die-wide codes (limux_dw.py): (source kind and index, physical input, LE parity)
            kind = "LI" if src.startswith("LOCAL_INTERCONNECT") else "LL"
            e = self.dw.get(f"{kind}|{int(src.rsplit('_I', 1)[1])}|{PHYS[port]}|{(n // 2) % 2}")
            if e is None:
                self.unknown["no die-wide code"] += 1
                return
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            odd = (n // 2) % 2
            self.set |= {(f0 + df, lo + (col - 2 if odd else col), bit) for df, col in e}
            self.used_dw += 1
            return
        key = f"{x}|{y}|{n}|{PHYS[port]}|{src}"
        if self.posmux is not None and key in self.posmux:
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            odd = (n // 2) % 2
            self.set |= {(f0 + df, lo + (col - 2 if odd else col), bit) for df, col in self.posmux[key]}
            self.used_posmux += 1
            return
        if self.posmux is not None:
            self.unknown["no position-specific code"] += 1
        if src.startswith("LOCAL_LINE"):
            e = self.local.get(f"{PHYS[port]},{src_slot}")
            if e is None:
                self.unknown["local line -> input"] += 1
                return
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            odd = (n // 2) % 2
            self.set |= {(f0 + df, lo + (col - 2 if odd else col), bit) for df, col in e}
            return
        if self._g is None:
            self._g = G.Graph(min_inst=20)    # reads the raw corpus: not available in a clone (out/ ships tables only)
        bits = reroute.pip_bits(self._g, src, f"LCCOMB_X{x}_Y{y}_N{n}:{port.lower()}")
        if bits is None:
            self.unknown["LAB line -> input"] += 1
            return
        self.set |= set(bits)

    # Clock distribution (the .rcf's K~inputclkctrl net, the same shape at three positions):
    #   GLOBAL_CLK_H -> GLOBAL_CLK_V_X12 / _X29: the quadrant cell (487 / 1592, byte 54, plane 5) cleared
    #   SCLK_TO_ROWCLK_BUF -> LAB_CLK_X{0,13,21,30}_Y: the row clock select, frame 488 / 489 / 1593 / 1594 by the line's
    #       region, bytes ROW[y].low - 62 + offset on the row's plane: -1 cleared, +5 and +8 set
    #   LOCAL_INTERCONNECT I8 -> LAB_CONTROL_MUX I1: the LAB's clock taken through a LAB line (6 cells, LAB-relative)
    #   a register clocked straight from BLK_CLK_BUF: one cell (-17, -34) relative to the LAB (see assemble)
    ROWSEL_FRAME = {0: 488, 13: 489, 21: 1593, 30: 1594}
    CLK_VIA_LINE = [(-12, -31), (-11, -31), (-8, -29), (-2, -30), (1, -29), (11, -34)]
    CLK_DIRECT = (-17, -34)

    def clock_hop(self, u: str, v: str) -> bool:
        mu = re.match(r"(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$", u)
        mv = re.match(r"(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$", v)
        if not mu or not mv:
            return False
        tu, tv = mu.group(1), mv.group(1)
        xv, yv, iv = int(mv.group(2)), int(mv.group(3)), int(mv.group(4))
        if tu == "GLOBAL_CLK_H" and tv == "GLOBAL_CLK_V":
            self.clear.add((487, 54, 5) if xv <= 20 else (1592, 54, 5))
            return True
        if tu == "SCLK_TO_ROWCLK_BUF" and tv == "LAB_CLK" and xv in self.ROWSEL_FRAME:
            low, plane = lutpos.ROW[yv]
            f = self.ROWSEL_FRAME[xv]
            L = low + lutpos.PLANE_START[plane]          # row index: the offsets can cross into the plane below (row 7)
            self.clear.add(G.cell_of(f, L - 63))
            self.set |= {G.cell_of(f, L - 57), G.cell_of(f, L - 54)}
            return True
        if tu == "LOCAL_INTERCONNECT" and tv == "LAB_CONTROL_MUX" and int(mu.group(4)) == 8 and iv == 1:
            f0, l0 = R._col_frame(xv), R._row_index(yv)
            self.set |= {G.cell_of(f0 + f, l0 + l) for f, l in self.CLK_VIA_LINE}
            return True
        if (tu, tv) in (("GLOBAL_CLK_V", "SCLK_TO_ROWCLK_BUF"), ("LAB_CLK", "BLK_CLK_BUF"), ("BLK_CLK_BUF", "BLK_CLK_LIM"),
                        ("BLK_CLK_LIM", "LOCAL_INTERCONNECT")):
            return True                                  # no bits of their own (seen at three positions)
        return False

    def hop(self, u: str, v: str):
        if self.clock_hop(u, v):
            return
        b = self.m.bits(u, v)
        if b is None:
            self.unknown[f"{u.split('_X')[0]} -> {v.split('_X')[0]}"] += 1
            return
        self.set |= set(b)

    def output_select(self, x, y, n, which):
        """Set the combinational select of LE output `which` ('direct_line' = local line, 'second_path')."""
        c = lutpos._predict_phys(x, y, n)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        if isinstance(which, tuple):
            # second path: the +8 select is at byte (LE parity) XOR (buffer parity) of the LE's low byte (sp probes:
            # 16/16 slots of X14Y10; it explains why buffer parity alone looked random)
            _w, bpar = which
            self.set.add((f0 + 8, lo + (((n // 2) % 2) ^ bpar), bit))
            return
        # direct line: the +9 select at byte (LE parity) of the LE's low byte: every slot in le_output_select.json
        # follows it, and it predicts slot 24's (missing from the table) in the Yosys build
        self.set.add((f0 + self.osel["frames"][which], lo + (n // 2) % 2, bit))


def assemble(name: str, rcf: str, les: dict, posmux: dict | None = None, masks: dict | None = None,
             dw: dict | None = None, insts: dict | None = None):
    """insts: a design dict (ynet.py) instead of the template `name`'s netlist."""
    a = Asm()
    a.posmux = posmux
    a.dw = dw
    insts = insts if insts is not None else instances(name)
    for inst, m in (masks or {}).items():
        insts[inst]["mask"] = m
    by_net = {d["net"]: i for i, d in insts.items()}
    by_src = {d["src"]: i for i, d in insts.items() if d.get("src")}     # instance names (ynet.py designs)
    loc_of = dict(les)
    brs = F.branches(rcf)
    # physical ports per (instance, logical port), and LE outputs in use
    # The .rcf's logical port names are those of Quartus's synthesised netlist, which may differ from the template's;
    # match LUT inputs by signal instead: (instance, signal) -> physical input
    phys, used_out = {}, collections.defaultdict(set)
    for sig, bl in brs.items():
        for path, (dinst, lport, pport) in bl:
            inst = dinst if dinst in insts else by_net.get(dinst) or by_src.get(dinst)
            if inst is None:
                continue
            phys[(inst, sig)] = PHYS.get(pport)
    # LUT cells
    for inst, d in insts.items():
        if inst not in loc_of:
            continue
        x, y, n = loc_of[inst]
        perm = [None] * 4
        for k, lp in enumerate(PORTS):
            sig = d["inputs"].get(lp)
            if sig is not None and phys.get((inst, sig)) is not None:
                perm[k] = phys[(inst, sig)]
            elif d.get("registered") and sig == d["q"]:
                perm[k] = 0                        # the LE's own register output: hard-wired feedback to input 0
        free = [p for p in range(4) if p not in perm]
        perm = tuple(p if p is not None else free.pop(0) for p in perm)
        a.lut(x, y, n, d["mask"], perm)
    # routing and LUT input muxes
    src_slot = {}
    for inst, d in insts.items():
        if inst in loc_of:
            src_slot[d["net"]] = loc_of[inst]
            src_slot[inst] = loc_of[inst]          # a LUT driving a pin is named after its instance in the .rcf
            if d.get("registered"):
                src_slot[d["q"]] = loc_of[inst]
                if d.get("src_reg"):
                    src_slot[d["src_reg"]] = loc_of[inst]      # the register's own name (clock-net destinations)
    for sig, bl in brs.items():
        for path, (dinst, lport, pport) in bl:
            for u, v in zip(path, path[1:]):
                a.hop(u, v)
            s = src_slot.get(sig)
            # which LE output the net uses, for any destination (a LUT, or the pin for the output LUT)
            if path and path[0].startswith("LOCAL_LINE") and s:
                used_out[s].add("direct_line")
            elif path and path[0].startswith("LE_BUFFER") and s:
                used_out[s].add(("second_path", int(path[0].rsplit("_I", 1)[1]) % 2))
            if path and path[-1].startswith("BLK_CLK_BUF") and lport == "CLK":
                mb = re.match(r"BLK_CLK_BUF_X(\d+)_Y(\d+)_", path[-1])
                bx, by = int(mb.group(1)), int(mb.group(2))
                a.set.add(G.cell_of(R._col_frame(bx) + a.CLK_DIRECT[0], R._row_index(by) + a.CLK_DIRECT[1]))
            inst = dinst if dinst in insts else by_net.get(dinst) or by_src.get(dinst)
            if inst is None or not path or pport not in PORTS:
                continue
            x, y, n = loc_of[inst]
            a.lut_input(path[-1], x, y, n, pport, s[2] if s else None)
    for inst, d in insts.items():
        if inst in loc_of and not d.get("registered"):
            for w in used_out.get(loc_of[inst], ()):
                a.output_select(*loc_of[inst], w)
    # registers: the pair select (ff_control.json, frame +11, set for every register in use, offsets per slot relative
    # to LE N0)
    ff = json.load(open(os.path.join(HERE, "data", "ff_control.json")))
    for inst, d in insts.items():
        if inst in loc_of and d.get("registered"):
            x, y, n = loc_of[inst]
            c0 = lutpos._predict_phys(x, y, 0)
            f00, lo0, bit0 = min(v[0] for v in c0), min(v[1] for v in c0), c0[0][2]
            a.set.add((f00 + ff["frame_offset"], lo0 + ff["pair_select_predicted"][n // 2], bit0))
    # Frame -1 occupancy cells (fm1 probes, one LAB, 8 designs): every placed LE sets a "used" cell and a registered
    # LE also a "register" cell, at the LE's low byte +0 / +1 (even LEs) or +1 / +0 (odd LEs).  (A "LAB with two or
    # more LEs" cell at N24's low byte +0 was N24's own used cell: across 59 template builds it is set exactly when
    # N24 is placed, and the nextpnr-placed blinky's X8, with 12 LEs and N24 empty, doesn't have it.)
    per_lab = collections.Counter()
    for inst, d in insts.items():
        if inst not in loc_of:
            continue
        x, y, n = loc_of[inst]
        per_lab[(x, y)] += 1
        c = lutpos._predict_phys(x, y, n)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        odd = (n // 2) % 2
        a.set.add((f0 - 1, lo + (1 if odd else 0), bit))
        if d.get("registered"):
            a.set.add((f0 - 1, lo + (0 if odd else 1), bit))
    return a


def finish(a, name: str, les: dict, outpath_cells: set, placement: dict, sp_meas: dict, dw: bool) -> bytes:
    """Complete an assembly: baseline (all-zero design minus its own D5 driver), output path, second-path selects,
    the fixed-configuration bundle where no model decides, the E2 clock-input periphery entry, CRCs and header."""
    zero = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    zown = {tuple(c) for c in json.load(open(os.path.join(OUT, "zero_own_bits.json")))}
    # LE-relative cells are written as the LE's low byte plus an offset; near a plane boundary that can give byte 1 of
    # a plane where the cell is byte 252 of the plane below, or a byte outside 1..252 (row 7's LEs).  Normalise every
    # cell through the row index (routegraph.cell_of, which knows the boundary rule); interior bytes are unchanged.
    norm = lambda cells: {G.cell_of(f, b + lutpos.PLANE_START[p]) or (f, b, p) for f, b, p in cells}
    a.set, a.clear = norm(a.set), norm(a.clear)
    bundle = set(outpath_cells)
    setb = (a.set | bundle) - a.clear
    decided = a.set | a.clear | bundle | zown
    for c_tab, c_alt in a.second_path:          # resolve each second-path select by measurement
        pick = c_alt if sp_meas.get(c_alt) == 1 and sp_meas.get(c_tab) != 1 else c_tab
        setb.add(pick)
        decided |= {c_tab, c_alt}
        a.clear.add(c_tab if pick == c_alt else c_alt)
    if dw:
        # the bundle must not supply LUT-input codes (frames -12..-2 of the placed LEs)
        mux_region = set()
        for inst, (x, y, n) in les.items():
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            mux_region |= {(f0 + df, lo + k, bit) for df in range(-12, -1) for k in range(-2, 4)}
        decided |= mux_region
    pl_set = {c for c, v in placement.items() if v and c not in decided}
    pl_clr = {c for c, v in placement.items() if not v and c not in decided}
    print(f"  bundle: {len(pl_set)} cells set, {len(pl_clr)} cleared (where no model decides)")
    setb |= pl_set
    data, _ = reroute.flip(zero, ((zown | a.clear | pl_clr) - setb), setb)
    import periph
    return periph.apply(data, [tuple(c) for c in json.load(open(os.path.join(HERE, "data", "io_tile.json")))["clock_input_E2"]["changes"]])


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "compare":
        print(__doc__)
        return 2
    import explain as E
    import tpatch
    name = sys.argv[2]
    func = "--counter" in sys.argv
    masks = counter_masks(name) if func else None
    job = tpatch.job(name, [masks[i] if func else mk for i, mk in xdev.tpl_luts(name)])
    pr = F.Project(job, E.ROOT)
    rcf = pr.base_rcf
    if "--rcf" in sys.argv:                            # route description from a file (e.g. router.py's), not Quartus's
        rcf = open(sys.argv[sys.argv.index("--rcf") + 1]).read()
    t = tpatch.Template(name, partial=True)
    pm = os.path.join(OUT, f"posmux_{name}.json")
    dw = "--dw" in sys.argv                           # die-wide LUT-input codes instead of position-specific ones
    a = assemble(name, rcf, t.les, None if dw else (json.load(open(pm)) if os.path.exists(pm) else None), masks,
                 json.load(open(os.path.join(OUT, "limux_dw.json"))) if dw else None)
    outp = os.path.join(OUT, "outpath_bits.json")
    cells = {tuple(c) for c in json.load(open(outp))}
    if "--outpath" in sys.argv:                         # output path from outpath.py (corpus, general)
        cells = {tuple(c) for c in json.load(open(sys.argv[sys.argv.index("--outpath") + 1]))["cells"]}
    pp = os.path.join(OUT, f"placement_{name}.json")
    if "--bundle" in sys.argv:                          # a bundle from elsewhere, e.g. translated from another position
        pp = sys.argv[sys.argv.index("--bundle") + 1]
    placement = {(f, p, b): v for f, p, b, v in json.load(open(pp))} if os.path.exists(pp) else {}
    spm = os.path.join(OUT, f"secondpath_{name}.json")
    sp_meas = {tuple(c[:3]): c[3] for c in json.load(open(spm))} if os.path.exists(spm) else placement
    data = finish(a, name, t.les, cells, placement, sp_meas, dw)
    ref = pr.base_rbf
    tag = ("_counter" if func else "") + ("_ownroute" if "--rcf" in sys.argv else "") + ("_dw" if dw else "")
    open(os.path.join(OUT, f"asm_{name}{tag}.rbf"), "wb").write(data)
    full = [i for i in range(min(len(data), len(ref))) if data[i] != ref[i]]
    print(f"  whole file: {len(full)} bytes differ from Quartus's build"
          + (f" (first at {full[0]}, frame {(full[0] - 32) // 255})" if full else " (byte-identical)"))
    D = E.core_diff(data, ref)
    on = lambda buf, c: buf[32 + c[0] * 255 + c[1]] >> c[2] & 1
    missing = sorted(c for c in D if on(ref, c))
    extra = sorted(c for c in D if on(data, c))
    print(f"{name}: core bits differing from Quartus's build: {len(D)}  (missing {len(missing)}, extra {len(extra)})")
    print("  not modelled:", dict(a.unknown), f"; position-specific codes used: {a.used_posmux}, die-wide: {a.used_dw}")
    json.dump({"missing": missing, "extra": extra}, open(os.path.join(OUT, f"asm_{name}_diff.json"), "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
