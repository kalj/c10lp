#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Place, route and assemble a Yosys netlist without Quartus: Verilog -> yosys synth_intel -> this -> RBF.

  1. ynet.py: read and pack into LEs (LUT + its register).
  2. place: rank LEs by the number of register outputs in their logic cone (for a counter: the bit order); the LE whose
     register drives the output pin goes to OUT_LE (an LE with a measured output path to D5, outpath.py); the others
     fill LABS in rank order, 16 LEs per LAB.
  3. route: router.py over die-wide LUT-input codes and priced switches; the clock net by our clock rule
     (global -> spine -> row clock buffer -> the region's LAB clock line -> each LAB's clock buffer -> every register).
  4. assemble: asm.py with the output path (outpath.py) and the global E2 clock-tree cells (clockmodel.py --no-lab).
Writes out/ypnr_TOP.rbf, out/ypnr_TOP.rcf (the route description) and out/ypnr_TOP_locs.qsf (the placement).

  ypnr.py NETLIST.json TOP [--labs X,Y;X,Y;...]     (default X8-X10 Y3; must include the output LE's LAB X10Y3)
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import asm  # noqa: E402
import rcfforce as F  # noqa: E402
import router  # noqa: E402
import ynet  # noqa: E402

OUT = os.path.join(HERE, "out")
LABS = [(8, 3), (9, 3), (10, 3)]                 # default; --labs X,Y;X,Y;... (non-adjacent LABs route over wires)
MULTIHOP = False
OUT_LE = (10, 3, 30)
AVOID = os.path.join(OUT, "ypnr_avoid.json")    # resources the legality oracle (Quartus with our .rcf) rejected


def feasible(design: dict, les: dict, cand) -> bool:
    """Every LE has an assignment of its routed inputs to distinct physical inputs with a known candidate source."""
    import itertools
    for i, d in design.items():
        own = d["registered"] and d["q"] in d["inputs"].values()
        sigs = [s for s in d["inputs"].values() if not s.startswith("1'b") and not (d["registered"] and s == d["q"])]
        opts = [{inp for inp, _src in cand(s, les[i]) if not (own and inp == 0)} for s in sigs]
        if any(not o for o in opts):
            return False
        if not any(len(set(c)) == len(c) for c in itertools.product(*opts)):
            return False
    return True


def candidates(design: dict, les: dict):
    """(input, source) candidates per (signal, destination LE), as router.py builds them."""
    import glob
    import switchmodel as S
    dw = json.load(open(os.path.join(OUT, "limux_dw.json")))
    m = S.Model()
    seen_nb = router.seen_neighbour_pairs() if hasattr(router, "seen_neighbour_pairs") else set()
    cache = {}
    avoid = set(json.load(open(AVOID))) if os.path.exists(AVOID) else set()    # rejected by the legality oracle

    def cand(sig, dloc):
        src = next((les[i] for i, d in design.items() if d["net"] == sig or (d["registered"] and d["q"] == sig)), None)
        if src is None:
            return []
        key = (sig, dloc, src)
        if key in cache:
            return cache[key]
        (sx, sy, sn), (dx, dy, dn) = src, dloc
        par = (dn // 2) % 2
        out = []
        if (sx, sy) == (dx, dy):
            out += [(inp, f"LL{sn // 2}") for inp in range(4) if f"LL|{sn // 2}|{inp}|{par}" in dw]
        if dy == sy and abs(dx - sx) <= 1:
            for b in (sn, sn + 1):
                for li in range(38):
                    if (b, dx - sx, li) in seen_nb and f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}" not in avoid and \
                            m.bits(f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}", f"LOCAL_INTERCONNECT_X{dx}_Y{dy}_N0_I{li}") is not None:
                        out += [(inp, f"LI{li}") for inp in range(4) if f"LI|{li}|{inp}|{par}" in dw]
        if MULTIHOP and dy == sy and (sx, sy) != (dx, dy):
            for b in (sn, sn + 1):
                for pth in router.wire_paths(m, f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}", dx, dy, frozenset(avoid)):
                    li = int(pth[-1].rsplit("_I", 1)[1])
                    out += [(inp, f"LI{li}") for inp in range(4) if f"LI|{li}|{inp}|{par}" in dw]
        cache[key] = out
        return out
    return cand


def place(design: dict, out_net: str, tries: int = 400, seed: int = 1):
    """Rank-ordered placement, then random slot shuffles within each LAB until every LE is feasible."""
    import random
    les = place_ranked(design, out_net)
    rnd = random.Random(seed)
    for t in range(tries):
        if feasible(design, les, candidates(design, les)):
            return les, t
        by_lab = collections.defaultdict(list)
        for i, loc in les.items():
            if loc != OUT_LE:
                by_lab[loc[:2]].append(i)
        new = dict(les)
        for lab, insts in by_lab.items():
            slots = [les[i] for i in insts] + [(*lab, n) for n in range(0, 32, 2)
                                               if (*lab, n) not in les.values() and (*lab, n) != OUT_LE]
            rnd.shuffle(slots)
            for i, sl in zip(insts, slots):
                new[i] = sl
        les = new
    raise SystemExit("no feasible placement found")


def place_ranked(design: dict, out_net: str):
    driver = {d["q"] if d["registered"] else d["net"]: i for i, d in design.items()}
    cone = {}

    def regs_in(net, seen):
        i = driver.get(net)
        if i is None or net in seen:
            return set()
        seen.add(net)
        d = design[i]
        out = {d["q"]} if d["registered"] and net == d["q"] else set()
        for v in d["inputs"].values():
            out |= regs_in(v, seen)
        return out

    for i, d in design.items():
        cone[i] = len(set().union(*(regs_in(v, set()) for v in d["inputs"].values())) | ({d["q"]} if d["registered"] else set()))
    out_le = driver[out_net]
    order = sorted((i for i in design if i != out_le), key=lambda i: (cone[i], i))
    slots = [(x, y, n) for x, y in LABS for n in range(0, 32, 2) if (x, y, n) != OUT_LE]
    if len(order) > len(slots):
        raise SystemExit(f"{len(design)} LEs don't fit in {len(LABS)} LABs")
    les = dict(zip(order, slots))
    les[out_le] = OUT_LE
    return les


def clock_block(design: dict, les: dict) -> str:
    labs = sorted({les[i][:2] for i, d in design.items() if d["registered"]})
    region = lambda x: 0 if x <= 12 else 13 if x <= 20 else 21 if x <= 29 else 30
    spine = lambda x: 12 if x <= 20 else 29
    (x0, y0) = labs[0]
    if len({region(x) for x, _ in labs}) != 1 or len({y for _, y in labs}) != 1:
        raise SystemExit("registers in more than one LAB clock line: not supported yet")
    lc = f"LAB_CLK:X{region(x0)}Y{y0}S0I5"
    parts, first = [], True
    head = (f"\tCLKBUF_OUT:X0Y14S32I0;\n\tGLOBAL_CLK_H:X0Y14S0I4;\n\tGLOBAL_CLK_V:X{spine(x0)}Y0S0I4;\n"
            f"\tSCLK_TO_ROWCLK_BUF:X{spine(x0)}Y{y0}S0I14;\n\tlabel = Label_{lc}, {lc};\n")
    for (x, y) in labs:
        bb = f"BLK_CLK_BUF:X{x}Y{y}S0I5"
        regs = sorted(d["src_reg"] for i, d in design.items() if d["registered"] and les[i][:2] == (x, y))
        for k, r in enumerate(regs):
            if k == 0:
                parts.append(("" if first else f"\tbranch_point = Label_{lc};\n") + f"\tlabel = Label_{bb}, {bb};\n\tdest = ( {r}, CLK );")
                first = False
            else:
                parts.append(f"\tbranch_point = Label_{bb};\n\tdest = ( {r}, CLK );")
    parts[0] = head + parts[0]
    return "signal_name = K~inputclkctrl {\n" + "\n\n".join(parts) + "\n}\n"


def write_netlist(design: dict, ports: dict, dirs: dict, clocks: set, path: str):
    """The packed design as a WYSIWYG netlist (module fuzz_top), so Quartus sees exactly our LEs: one lcell_comb per LE
    (dont_touch) and one dffeas per register, nets as wires.  Used only for the check build."""
    v = lambda n: n                                   # net names as in the routing description
    port_net = {p: bits[0] for p, bits in ports.items()}
    L = ["module fuzz_top(" + ", ".join(f"{dirs[p]} wire {p}" for p in ports) + ");"]
    nets = set()
    for d in design.values():
        nets |= {x for x in d["inputs"].values() if not x.startswith("1'b")} | {d["net"]} | ({d["q"]} if d["q"] else set())
    nets |= set(clocks)
    L += [f"  wire {v(n)};" for n in sorted(nets)]
    for p, n in port_net.items():
        L.append(f"  assign {v(n)} = {p};" if dirs[p] == "input" else f"  assign {p} = {v(n)};")
    clk = next(iter(clocks))
    for i, d in sorted(design.items()):
        conns = ", ".join(f".{p.lower()}({v(x)})" for p, x in sorted(d["inputs"].items()))
        L.append(f"  cyclone10lp_lcell_comb #(.lut_mask(16'h{d['mask']:04X}), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))"
                 f" {i} ({conns}, .combout({v(d['net'])}));")
        if d["registered"]:
            L.append(f"  dffeas {d['src_reg']} (.d({v(d['net'])}), .clk({v(clk)}), .q({v(d['q'])}), .ena(1'b1), .clrn(1'b1),"
                     " .prn(1'b1), .sclr(1'b0), .aload(1'b0), .asdata(1'b0), .sload(1'b0));")
    L.append("endmodule")
    open(path, "w").write("\n".join(L) + "\n")


def main() -> int:
    global LABS, MULTIHOP
    path, top = sys.argv[1], sys.argv[2]
    if "--labs" in sys.argv:
        LABS = [tuple(map(int, t.split(","))) for t in sys.argv[sys.argv.index("--labs") + 1].split(";")]
        if OUT_LE[:2] not in LABS:
            raise SystemExit(f"--labs must include the output LE's LAB {OUT_LE[:2]}")
        xs = sorted(x for x, _ in LABS)
        MULTIHOP = any(b - a > 1 for a, b in zip(xs, xs[1:]))
    luts, regs, ports, dirs = ynet.read(path, top)
    design, clocks = ynet.pack(luts, regs)
    for i, d in design.items():                       # our netlist names: LUT le<k>, register r_le<k>
        d["src"] = i
        if d["registered"]:
            d["src_reg"] = f"r_{i}"
    out_ports = [p for p, dr in dirs.items() if dr == "output"]
    out_net = ports[out_ports[0]][0]
    dw = json.load(open(os.path.join(OUT, "limux_dw.json")))
    avoid = set(json.load(open(AVOID))) if os.path.exists(AVOID) else set()
    # a feasible placement (every input has a candidate) can still fail to route when signals compete for one wire:
    # then another placement (multi-hop only; the default flow keeps its one placement)
    for seed in range(1, 41 if MULTIHOP else 2):
        les, tries = place(design, out_net, seed=seed)
        print(f"placement feasible after {tries} shuffles (seed {seed})")
        rcf, choice = router.route(top, les, "", None, dw, insts=design, avoid=avoid, multihop=MULTIHOP)
        if rcf is not None:
            break
    if rcf is None:
        raise SystemExit("no routing with known switches and die-wide codes")
    op = json.load(open(os.path.join(OUT, "outpath_%d_%d_%d.json" % OUT_LE)))
    path_ = [p for p in op["path"] if not p.startswith("LCCOMB")]
    rcf += ("signal_name = %s {\n" % out_net) + "".join(f"\t{F.rcf_name(n)};\n" for n in path_) + "\tdest = ( Q~output, I );\n}\n"
    rcf += clock_block(design, les)
    open(os.path.join(OUT, f"ypnr_{top}.rcf"), "w").write(rcf)
    a = asm.assemble(top, rcf, les, None, None, dw, insts=design)
    cells = {tuple(c) for c in op["cells"]}
    glob_ = {(f, p, b): v for f, p, b, v in json.load(open(os.path.join(OUT, "clockmodel_blink24p_from_blink24q_global.json")))}
    data = asm.finish(a, top, les, cells, glob_, {}, True)
    open(os.path.join(OUT, f"ypnr_{top}.rbf"), "wb").write(data)
    write_netlist(design, ports, dirs, clocks, os.path.join(OUT, f"ypnr_{top}.v"))
    with open(os.path.join(OUT, f"ypnr_{top}_locs.qsf"), "w") as f:
        for i, (x, y, n) in sorted(les.items(), key=lambda kv: kv[1]):
            d = design[i]
            f.write(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to "{d["src"]}"\n')
            if d["registered"]:
                f.write(f'set_location_assignment FF_X{x}_Y{y}_N{n + 1} -to "{d["src_reg"]}"\n')
    print(f"{len(design)} LEs placed in {len(LABS)} LABs; {len(choice)} LUT inputs routed; not modelled: {dict(a.unknown)}; "
          f"die-wide codes used: {a.used_dw} -> out/ypnr_{top}.rbf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
