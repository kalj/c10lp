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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
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
    return out


def node_le(node: str):
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)", node)
    return tuple(map(int, m.groups())) if m else None


class Asm:
    def __init__(self):
        self.m = S.Model()
        self.g = G.Graph(min_inst=20)
        self.local = {k: v for k, v in json.load(open(os.path.join(HERE, "li_local_table.json")))["entries"].items()}
        self.osel = json.load(open(os.path.join(HERE, "le_output_select.json")))
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
        bits = reroute.pip_bits(self.g, src, f"LCCOMB_X{x}_Y{y}_N{n}:{port.lower()}")
        if bits is None:
            self.unknown["LAB line -> input"] += 1
            return
        self.set |= set(bits)

    def hop(self, u: str, v: str):
        b = self.m.bits(u, v)
        if b is None:
            self.unknown[f"{u.split('_X')[0]} -> {v.split('_X')[0]}"] += 1
            return
        self.set |= set(b)

    def output_select(self, x, y, n, which: str):
        """Set the combinational select of LE output `which` ('direct_line' = local line, 'second_path')."""
        e = self.osel["bytes"].get(str(n))
        if e is None:
            self.unknown["output select slot"] += 1
            return
        c = lutpos._predict_phys(x, y, n)
        f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        k = 1 if which == "direct_line" else 0
        if which == "second_path":
            # the +8 select sits at byte 0 or 1 depending on the second-path line (le_output_select.json about; buffer
            # parity doesn't decide it: 279/158/99/70 over the RCF projects): keep both candidates, resolved later
            self.second_path.append(((f0 + 8, lo + e[k], bit), (f0 + 8, lo + (1 - e[k]), bit)))
            return
        self.set.add((f0 + self.osel["frames"][which], lo + e[k], bit))


def assemble(name: str, rcf: str, les: dict, posmux: dict | None = None, masks: dict | None = None,
             dw: dict | None = None):
    import tpatch  # noqa: F401  (template helpers)
    a = Asm()
    a.posmux = posmux
    a.dw = dw
    insts = instances(name)
    for inst, m in (masks or {}).items():
        insts[inst]["mask"] = m
    by_net = {d["net"]: i for i, d in insts.items()}
    loc_of = dict(les)
    brs = F.branches(rcf)
    # physical ports per (instance, logical port), and LE outputs in use
    # The .rcf's logical port names are those of Quartus's synthesised netlist, which may differ from the template's;
    # match LUT inputs by signal instead: (instance, signal) -> physical input
    phys, used_out = {}, collections.defaultdict(set)
    for sig, bl in brs.items():
        for path, (dinst, lport, pport) in bl:
            inst = dinst if dinst in insts else by_net.get(dinst)
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
            elif d.get("registered") and sig == d["net"].replace("n[", "s["):
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
                src_slot[d["net"].replace("n[", "s[")] = loc_of[inst]
    for sig, bl in brs.items():
        for path, (dinst, lport, pport) in bl:
            for u, v in zip(path, path[1:]):
                a.hop(u, v)
            inst = dinst if dinst in insts else by_net.get(dinst)
            if inst is None or not path or pport not in PORTS:
                continue
            x, y, n = loc_of[inst]
            s = src_slot.get(sig)
            a.lut_input(path[-1], x, y, n, pport, s[2] if s else None)
            if path[0].startswith("LOCAL_LINE") and s:
                used_out[s].add("direct_line")
            elif path[0].startswith("LE_BUFFER") and s:
                used_out[s].add("second_path")
    for inst, d in insts.items():
        if inst in loc_of and not d.get("registered"):
            for w in used_out.get(loc_of[inst], ()):
                a.output_select(*loc_of[inst], w)
    # registers: the pair select (ff_control.json, frame +11, set for every register in use, offsets per slot relative
    # to LE N0) and the register's own bit at frame -1 (low byte +1 for even LEs, +0 for odd: 24/24 in blink24p)
    ff = json.load(open(os.path.join(HERE, "ff_control.json")))
    for inst, d in insts.items():
        if inst in loc_of and d.get("registered"):
            x, y, n = loc_of[inst]
            c0 = lutpos._predict_phys(x, y, 0)
            f00, lo0, bit0 = min(v[0] for v in c0), min(v[1] for v in c0), c0[0][2]
            a.set.add((f00 + ff["frame_offset"], lo0 + ff["pair_select_predicted"][n // 2], bit0))
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            a.set.add((f0 - 1, lo + (0 if (n // 2) % 2 else 1), bit))
    return a


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
    zero = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    zown = {tuple(c) for c in json.load(open(os.path.join(OUT, "zero_own_bits.json")))}
    bundle = {tuple(c) for c in json.load(open(os.path.join(OUT, "outpath_bits.json")))}
    setb = (a.set | bundle) - a.clear
    # placement bundle (posmux.py): fixed configuration measured from other builds at this placement, only where no
    # model of ours decides the cell
    pp = os.path.join(OUT, f"placement_{name}.json")
    decided = a.set | a.clear | bundle | zown
    placement = {(f, p, b): v for f, p, b, v in json.load(open(pp))} if os.path.exists(pp) else {}
    spm = os.path.join(OUT, f"secondpath_{name}.json")       # measured byte of each LE's second-path select
    sp_meas = {tuple(c[:3]): c[3] for c in json.load(open(spm))} if os.path.exists(spm) else placement
    for c_tab, c_alt in a.second_path:          # resolve each second-path select by the placement measurement
        pick = c_alt if sp_meas.get(c_alt) == 1 and sp_meas.get(c_tab) != 1 else c_tab
        setb.add(pick)
        decided |= {c_tab, c_alt}
        a.clear.add(c_tab if pick == c_alt else c_alt)
    if dw:
        # die-wide test: the placement bundle must not supply LUT-input codes (frames -12..-2 of the placed LEs, their
        # byte columns): those must come from the die-wide table or stay unset
        mux_region = set()
        for inst, (x, y, n) in t.les.items():
            c = lutpos._predict_phys(x, y, n)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            mux_region |= {(f0 + df, lo + k, bit) for df in range(-12, -1) for k in range(-2, 4)}
        decided |= mux_region
    pl_set = {c for c, v in placement.items() if v and c not in decided}
    pl_clr = {c for c, v in placement.items() if not v and c not in decided}
    print(f"  placement bundle: {len(pl_set)} cells set, {len(pl_clr)} cleared (measured from other builds, no model decides them)")
    setb |= pl_set
    data, _ = reroute.flip(zero, ((zown | a.clear | pl_clr) - setb), setb)
    # periphery: pin E2 as clock input (io_tile.json clock_input_E2), written with periph.apply (x4 copies, CRC, header)
    import periph
    data = periph.apply(data, [tuple(c) for c in json.load(open(os.path.join(HERE, "io_tile.json")))["clock_input_E2"]["changes"]])
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
