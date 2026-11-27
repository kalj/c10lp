#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""nextpnr Himbächel chip database for the 10CL016, from c10lp's validated models only.

Tiles: one LAB tile type per position class (X mod 8 for LAB-line selects, (X+Y) mod 4 for drivers), 32 types;
NULL tiles elsewhere.  A LAB holds 16 LEs, each a LUT4 bel and a DFF bel (z = 2n, 2n+1).  Tile wires:
  LE<n>_IN<i>   physical LUT input i (0..3, lutpos order)   LE<n>_F, LE<n>_Q, LE<n>_D   LUT out, register out / in
  LE<n>_L<j>    the LUT bel's logical input j; pseudo-pips IN<i> -> L<j> let the router choose the permutation
  BUF<b>        LE output buffer b (LE n owns 2n, 2n+1)    LL<n>   local line of LE n    LINE<k>   LAB line 0..37
  NBW<b>/NBE<b> buffer b of the LAB to the west / east (neighbour links)
  R4_<w>_<k>    the R4 wire of index w that starts k columns west of this tile (k < 0: east)
  C4_<w>_<a>_<r>  the C4 wire of index w starting a columns west and r rows from this tile (y here = start row)
  GCLK, CLK     the global clock and the LAB clock (dedicated: routed outside nextpnr)
I/O tiles: the clock driver (X0Y0), IBUF bels for D1..D4 and an OBUF for D5 at their pad tiles, reached over the pin
path library (out/iopaths.json, complete corpus paths whose every hop is priced), hop by hop on PW_<node> wires.
Pips are the hops switchmodel.Model prices at a representative LAB of the class, die-wide LUT-input codes
(limux_dw.json), and the LE-internal connections.  Hops without a model aren't in the database, so nextpnr can only
produce routes our assembler can write.

  c10lp_arch_gen.py NEXTPNR_DIR OUT.bba
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import router  # noqa: E402
import routemap as R  # noqa: E402
import switchmodel as S  # noqa: E402

OUT = os.path.join(HERE, "out")
X, Y = 42, 30
N_LE, N_LINE, N_BUF = 16, 38, 32
# R4 wire indices by direction and the column offsets k (tile - start) where a wire has a tile wire:
# left-going 17..33 (start at driver - 3; taps -1..2; continuation pips at k = 0/-1 of the old wire, 3 of the new);
# right-going 0..16 (start at driver + 1; taps 0..4)
R4_LEFT = range(17, 34)
R4_RIGHT = range(0, 17)
K_LEFT = range(-1, 4)
K_RIGHT = range(-1, 5)
# C4 wires (column wires, 4 rows): C4_<w>_<a>_<r> is the wire of index w starting a columns west (0, 1) and r rows away
# (r = tile row - start row): taps r 0..3 into the LABs of columns cx and cx + 1, drivers at r = -1 and 4 (c4sel.py,
# c4drv.py)
C4_IDX = range(0, 24)
C4_A = (0, 1)
C4_R = range(-1, 5)
_ctl = json.load(open(os.path.join(OUT, "ctlmux.json")))
# LAB lines with a 1-2-cell code into each control slot: 2 = clock enable (ENA), 0 = async clear (ACLR)
CTL_LINES = {s: sorted(int(k.split("|")[0]) for k, v in _ctl.items() if not k.startswith("_") and k.endswith(f"|{s}")
                       and 1 <= len(v) <= 2 and k not in _ctl["_mirrored"]) for s in (0, 2)}   # observed pairs only
IN_PINS = ("N3", "P3", "R3", "T3")       # the Vidor's D1..D4 (xdev.VIDOR_PINS A..D); D5 = PIN_T2 is the output
PAD_TILE = {"N3": (1, 0), "P3": (3, 0), "R3": (3, 0), "T3": (3, 0)}   # IOPAD positions (timing-report routes)
D5_TILE = (6, 0)                         # D5's I/O block (BLOCK_INPUT_MUX_X6_Y0)


def lab_at(x: int, y: int) -> bool:
    try:
        lutpos._predict_phys(x, y, 0)
        return True
    except (ValueError, KeyError):
        return False


def klass(x: int, y: int):
    return x % 8, (x + y) % 4


def c4_wires():
    return [(w, a, r) for w in C4_IDX for a in C4_A for r in C4_R]


def r4_wires():
    return [(w, k) for w in R4_LEFT for k in K_LEFT] + [(w, k) for w in R4_RIGHT for k in K_RIGHT]


def representative(labs):
    """A LAB per class, with LAB neighbours on both sides and away from the die edge if possible."""
    rep = {}
    for x, y in sorted(labs, key=lambda p: (abs(p[0] - 20) + abs(p[1] - 14))):
        c = klass(x, y)
        if c not in rep and (x - 1, y) in labs and (x + 1, y) in labs:
            rep[c] = (x, y)
    for x, y in labs:
        rep.setdefault(klass(x, y), (x, y))
    return rep


def tile_pips(m, dw, seen_nb, x, y):
    """(src tile wire, dst tile wire) pips of the LAB tile at (x, y), from the models."""
    nm = lambda t, i, xx=x: f"{t}_X{xx}_Y{y}_N0_I{i}"
    pips = []
    # LE-internal: LUT -> register, LUT / register -> buffers and local line, own register feedback on input 0
    for n in range(N_LE):
        pips += [(f"LE{n}_F", f"LE{n}_D"), (f"LE{n}_Q", f"LE{n}_IN0")]
        # LUT permutation: any physical input can carry any logical LUT input (the assembler permutes the mask)
        pips += [(f"LE{n}_IN{i}", f"LE{n}_L{j}") for i in range(4) for j in range(4)]
        for o in ("F", "Q"):
            pips += [(f"LE{n}_{o}", f"BUF{2 * n}"), (f"LE{n}_{o}", f"BUF{2 * n + 1}"), (f"LE{n}_{o}", f"LL{n}")]
    # LUT-input muxes: die-wide codes per (source, input, LE parity)
    for n in range(N_LE):
        par = n % 2
        for i in range(4):
            pips += [(f"LINE{k}", f"LE{n}_IN{i}") for k in range(N_LINE) if f"LI|{k}|{i}|{par}" in dw]
            # not an LE's own local line into its own LUT: its register's feedback has the hard-wired input 0 (the
            # assembler assumes that path), and its LUT output fed back would be a combinational loop
            pips += [(f"LL{k}", f"LE{n}_IN{i}") for k in range(N_LE) if f"LL|{k}|{i}|{par}" in dw and k != n]
    # local feedback and neighbour links onto this LAB's lines
    for b in range(N_BUF):
        for k in range(N_LINE):
            if m.bits(nm("LE_BUFFER", b), nm("LOCAL_INTERCONNECT", k)) is not None:
                pips.append((f"BUF{b}", f"LINE{k}"))
            # NBW<b>: buffer b of the LAB to the west (link dx = +1); NBE<b>: of the LAB to the east (dx = -1)
            for wname, sx, d in (("NBW", x - 1, 1), ("NBE", x + 1, -1)):
                if (b, d, k) in seen_nb and m.bits(nm("LE_BUFFER", b, sx), nm("LOCAL_INTERCONNECT", k)) is not None:
                    pips.append((f"{wname}{b}", f"LINE{k}"))
    # R4 drivers from this LAB's buffers
    for b in range(N_BUF):
        for v, _bits in m.fanout(nm("LE_BUFFER", b)):
            pv = S.parse(v)
            if pv[0] == "R4" and pv[2] == y:
                k = x - pv[1]
                if (pv[3] in R4_LEFT and k in K_LEFT) or (pv[3] in R4_RIGHT and k in K_RIGHT):
                    pips.append((f"BUF{b}", f"R4_{pv[3]}_{k}"))
    # R4 -> R4 continuations whose switch sits in this LAB, and R4 taps onto this LAB's lines
    import r4r4model as RR
    for w, k in r4_wires():
        u = f"R4_X{x - k}_Y{y}_N0_I{w}"
        for v, _bits in m.fanout(u):
            pv = S.parse(v)
            if pv[0] == "R4":
                if RR.drive_lab(x - k, pv[1]) != x:
                    continue
                k2 = x - pv[1]
                if (pv[3] in R4_LEFT and k2 in K_LEFT) or (pv[3] in R4_RIGHT and k2 in K_RIGHT):
                    pips.append((f"R4_{w}_{k}", f"R4_{pv[3]}_{k2}"))
            elif pv[0] == "LOCAL_INTERCONNECT" and (pv[1], pv[2]) == (x, y):
                pips.append((f"R4_{w}_{k}", f"LINE{pv[3]}"))
    # C4: drivers from this LAB's buffers, taps onto this LAB's lines
    for w, a, r in c4_wires():
        c4 = f"C4_X{x - a}_Y{y - r}_N0_I{w}"
        if r in (-1, 4):
            for b in range(N_BUF):
                if m.bits(nm("LE_BUFFER", b), c4) is not None:
                    pips.append((f"BUF{b}", f"C4_{w}_{a}_{r}"))
        if 0 <= r <= 3:
            for k in range(N_LINE):
                if m.bits(c4, nm("LOCAL_INTERCONNECT", k)) is not None:
                    pips.append((f"C4_{w}_{a}_{r}", f"LINE{k}"))
    # corner turns (mapping/corner.py), in the target wire's driver LAB: R4 -> a C4 driven from this LAB (r = -1 / 4),
    # and a C4 passing this LAB (r = 0..3) -> an R4 driven from this column (right-going k = -1, left-going k = 3)
    for w, k in r4_wires():
        r4 = f"R4_X{x - k}_Y{y}_N0_I{w}"
        for w2, a, r in c4_wires():
            if r in (-1, 4) and m.bits(r4, f"C4_X{x - a}_Y{y - r}_N0_I{w2}") is not None:
                pips.append((f"R4_{w}_{k}", f"C4_{w2}_{a}_{r}"))
    for w2, a, r in c4_wires():
        if 0 <= r <= 3:
            c4 = f"C4_X{x - a}_Y{y - r}_N0_I{w2}"
            for w, k in r4_wires():
                if k == (-1 if w in R4_RIGHT else 3) and m.bits(c4, f"R4_X{x - k}_Y{y}_N0_I{w}") is not None:
                    pips.append((f"C4_{w2}_{a}_{r}", f"R4_{w}_{k}"))
    pips.append(("GCLK", "CLK"))
    return sorted(set(pips))


# Delays (M5): a pip costs the incremental delay of the element it enters, from Quartus's timing reports
# (mapping/delays.py -> out/delays.json, median, slow 1200 mV 85 C); the LUT-input permutation pseudo-pips carry the
# LUT arc of their physical input (datad fastest), so the router's input choice sees it.
PHYS_PORT = {0: "datac", 1: "datad", 2: "datab", 3: "dataa"}       # asm.PHYS, physical input -> port
NOMINAL = {"R4": 300, "C4": 350, "LOCAL_INTERCONNECT": 350, "LOCAL_LINE": 250, "LE_BUFFER": 80, "C16": 300,
           "R24": 400, "LAB_CONTROL_MUX": 300, "BLOCK_INPUT_MUX": 0, "IO": 100}


def pip_class(src: str, dst: str) -> str:
    m = re.match(r"LE\d+_IN(\d+)$", src)
    if m and re.match(r"LE\d+_L\d+$", dst):
        return f"LUT_IN{m[1]}"
    if dst.startswith(("LINE", "IL_")):
        return "LOCAL_INTERCONNECT"
    if dst.startswith("PW_"):
        t = dst[3:].split("_X")[0]
        return t if t in NOMINAL else "IO"
    for pre, c in (("R4_", "R4"), ("C4_", "C4"), ("BUF", "LE_BUFFER"), ("NB", "LE_BUFFER"), ("LL", "LOCAL_LINE"),
                   ("ENA", "LAB_CONTROL_MUX"), ("ACLR", "LAB_CONTROL_MUX"), ("SCLR", "LAB_CONTROL_MUX"),
                   ("D5_I", "BLOCK_INPUT_MUX")):
        if dst.startswith(pre):
            return c
    return ""                                            # LE-internal (LUT input pins, F/Q, clock): no delay


def delays():
    # checked against Quartus's analysis of the same placement and routing (slow 85 C): the lock 4.23 ns vs 3.81 ns,
    # the enable counter 5.81 vs 5.02 ns (nextpnr 11-16% pessimistic).  C10LP_TIMING=0: nominal values
    p = os.path.join(OUT, "delays.json")
    d = json.load(open(p)) if os.path.exists(p) and os.environ.get("C10LP_TIMING", "1") == "1" else {}
    re_ = {k: int(round(v[1] * 1000)) for k, v in d.get("RE", {}).items()}
    cell = {k: int(round(v[1] * 1000)) for k, v in d.get("CELL", {}).items()}
    out = {c: re_.get(c, NOMINAL[c]) for c in NOMINAL}
    for i, port in PHYS_PORT.items():
        # the LUT arc plus the LUT's output element (CUDA_LCELL_COMB, "LCCOMB" in the reports, 25 ps)
        out[f"LUT_IN{i}"] = cell.get(f"LCCOMB:{port}->combout", 400) + re_.get("LCCOMB", 0)
    return out, d


def main() -> int:
    npnr, bba = sys.argv[1], sys.argv[2]
    sys.path.append(os.path.join(npnr, "himbaechel"))
    from himbaechel_dbgen.chip import Chip, NodeWire, PinType
    m = S.Model()
    dw = json.load(open(os.path.join(OUT, "limux_dw.json")))
    seen_nb = router.seen_neighbour_pairs()
    labs = {(x, y) for x in range(X) for y in range(Y) if R._col_frame(x) is not None and lab_at(x, y)}
    rep = representative(labs)
    ch = Chip("c10lp", "10CL016", X, Y)
    ch.strs.read_constids(os.path.join(os.path.dirname(os.path.abspath(__file__)), "uarch", "constids.inc"))
    npips = 0
    def make_lab_wires(tt):
        """A LAB tile type's wires and bels (16 LUT4 + DFF bels, buffers, lines, R4 / C4 tile wires, clock, controls)."""
        for n in range(N_LE):
            for i in range(4):
                tt.create_wire(f"LE{n}_IN{i}", "LUT_INPUT")
                tt.create_wire(f"LE{n}_L{i}", "LUT_PIN")
            for o, t in (("F", "LUT_OUT"), ("Q", "FF_OUT"), ("D", "FF_DATA")):
                tt.create_wire(f"LE{n}_{o}", t)
            tt.create_wire(f"LL{n}", "LOCAL_LINE")
        for b in range(N_BUF):
            tt.create_wire(f"BUF{b}", "LE_BUFFER")
            tt.create_wire(f"NBW{b}", "NEIGHBOUR")
            tt.create_wire(f"NBE{b}", "NEIGHBOUR")
        for k in range(N_LINE):
            tt.create_wire(f"LINE{k}", "LAB_LINE")
        for w, k in r4_wires():
            tt.create_wire(f"R4_{w}_{k}", "R4")
        for w, a, r in c4_wires():
            tt.create_wire(f"C4_{w}_{a}_{r}", "C4")
        tt.create_wire("GCLK", "GCLK")
        tt.create_wire("CLK", "LAB_CLK")
        tt.create_wire("ENA", "LAB_ENA")
        tt.create_wire("ACLR", "LAB_ACLR")
        tt.create_wire("SCLR", "LAB_SCLR")
        for n in range(N_LE):
            lut = tt.create_bel(f"LE{n}_LUT", "LUT4", z=2 * n)
            for i in range(4):
                tt.add_bel_pin(lut, f"I[{i}]", f"LE{n}_L{i}", PinType.INPUT)
            tt.add_bel_pin(lut, "F", f"LE{n}_F", PinType.OUTPUT)
            ff = tt.create_bel(f"LE{n}_FF", "DFF", z=2 * n + 1)
            tt.add_bel_pin(ff, "D", f"LE{n}_D", PinType.INPUT)
            tt.add_bel_pin(ff, "CLK", "CLK", PinType.INPUT)
            tt.add_bel_pin(ff, "EN", "ENA", PinType.INPUT)
            tt.add_bel_pin(ff, "CLRN", "ACLR", PinType.INPUT)
            tt.add_bel_pin(ff, "SCLR", "SCLR", PinType.INPUT)
            tt.add_bel_pin(ff, "Q", f"LE{n}_Q", PinType.OUTPUT)

    for c, (rx, ry) in sorted(rep.items()):
        tt = ch.create_tile_type(f"LAB_{c[0]}_{c[1]}")
        make_lab_wires(tt)
        pips = tile_pips(m, dw, seen_nb, rx, ry)
        # clock enable: LAB line k -> the LAB's ENA (LAB_CONTROL_MUX slot 2), die-wide codes (mapping/ctllearn.py)
        pips += [(f"LINE{k}", w) for k in CTL_LINES[2] for w in ("ENA", "SCLR")] + [(f"LINE{k}", "ACLR")
                                                                                   for k in CTL_LINES[0]]
        for s, d in pips:
            tt.create_pip(s, d, timing_class=pip_class(s, d))
        npips += len(pips)
        print(f"  LAB class {c}: representative X{rx}Y{ry}, {len(pips)} pips", flush=True)
    ch.create_tile_type("NULL")
    # I/O: the clock driver at X0Y0, and the Vidor's test pins at their pad tiles: D1 (N3) at X1Y0, D2..D4 (P3, R3, T3)
    # at X3Y0, D5 (T2) at X6Y0 (its I/O block).  The pins are reached through the pin path library
    # (mapping/iopaths.py): complete corpus paths, PIN_<pin> -> ... -> IL_<x>_<y>_<k> (a wire joined to LINE<k> of LAB
    # (x, y)) and LE buffer -> ... -> D5_I, hop by hop (below).
    lib = json.load(open(os.path.join(OUT, "iopaths.json")))
    gtile = ch.create_tile_type("IO_CLK")
    gtile.create_wire("GCLK", "GCLK")
    clk = gtile.create_bel("GCLK_DRV", "GCLK_DRV", z=0)
    gtile.add_bel_pin(clk, "O", "GCLK", PinType.OUTPUT)
    il = collections.defaultdict(list)                  # (x, y, k) -> [(pad tile, IL wire)]
    ob = {}                                             # (x, y, b) -> OB wire (in D5's tile)
    tiles = {}
    for pad in sorted({PAD_TILE[p] for p in IN_PINS} | {D5_TILE}):
        tiles[pad] = ch.create_tile_type(f"IO_X{pad[0]}Y{pad[1]}")
    for z, pin in enumerate(IN_PINS):
        t = tiles[PAD_TILE[pin]]
        t.create_wire(f"PIN_{pin}", "IO_PIN")
        bb = t.create_bel(f"IBUF_{pin}", "IBUF", z=1 + z)
        t.add_bel_pin(bb, "O", f"PIN_{pin}", PinType.OUTPUT)
    t5 = tiles[D5_TILE]
    t5.create_wire("D5_I", "IO_PIN")
    bb = t5.create_bel("OBUF_D5", "OBUF", z=8)
    t5.add_bel_pin(bb, "I", "D5_I", PinType.INPUT)
    # each library path hop by hop over PW_<node> wires (a wire per inner node, in the tile of the pad it starts from;
    # the same node in two pad tiles, or an R4 / C4 / LE buffer the database already has, is one node), so the router
    # sees every wire a pin path uses and can't use it twice (pseudo-pips hid them: the lock's D and B paths shared
    # C16_X2_Y1_I5)
    pips = collections.defaultdict(set)
    pw = collections.defaultdict(set)                   # node name -> pad tiles holding a PW wire for it
    n_in = n_out = 0
    for key, path in lib["input"].items():
        pin, line = key.split("|")
        pin = pin[4:]
        mm = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", line)
        lx, ly, k = map(int, mm.groups())
        if (lx, ly) not in labs or pin not in IN_PINS:
            continue
        pad, w = PAD_TILE[pin], f"IL_{lx}_{ly}_{k}"
        if (pad, w) not in il[(lx, ly, k)]:
            il[(lx, ly, k)].append((pad, w))
        chain = [f"PIN_{pin}"] + [f"PW_{nd}" for nd in path[:-1]] + [w]
        for nd in path[:-1]:
            pw[nd].add(pad)
        pips[pad] |= set(zip(chain, chain[1:]))
        n_in += 1
    for buf, path in lib["output"].items():
        mm = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$", buf)
        bx, by, b_ = map(int, mm.groups())
        if (bx, by) not in labs:
            continue
        ob[(bx, by, b_)] = f"PW_{buf}"
        chain = [f"PW_{nd}" for nd in path] + ["D5_I"]
        for nd in path:
            pw[nd].add(D5_TILE)
        pips[D5_TILE] |= set(zip(chain, chain[1:]))
        n_out += 1
    for pad, t in tiles.items():
        for w in sorted({w for v in il.values() for p_, w in v if p_ == pad}
                        | {f"PW_{nd}" for nd, pads in pw.items() if pad in pads}):
            t.create_wire(w, "IO_PATH")
        for s_, d_ in sorted(pips[pad]):
            t.create_pip(s_, d_, timing_class=pip_class(s_, d_))
    # PW wires that join a database node (R4, C4, LE buffer: added to those nodes below) or span pad tiles
    pw_extra = collections.defaultdict(list)            # node name -> [NodeWire] to add
    for nd, pads in pw.items():
        pw_extra[nd] = [NodeWire(*pad, f"PW_{nd}") for pad in sorted(pads)]
    print(f"  I/O: {n_in} input paths to {len(il)} LAB lines, {n_out} LE buffers to D5, "
          f"{sum(len(v) for v in pips.values())} hop pips over {len(pw)} wires", flush=True)
    # LABs near a hop Quartus refused (hopfix.json "refused", from a cross-check) get their own tile type with pips
    # computed at their own position, so the refused hop is gone there and nowhere else in their class
    own = {}
    fix = json.load(open(os.path.join(OUT, "hopfix.json"))) if os.path.exists(os.path.join(OUT, "hopfix.json")) else {}
    near = set()
    for k, e in fix.items():
        if k.startswith("_") or not e.get("refused"):
            continue
        for nd in k.split("->"):
            pn = S.parse(nd)
            if pn:
                near |= {(pn[1] + dx, pn[2] + dy) for dx in range(-4, 5) for dy in range(-5, 6)}
    for x, y in sorted(near & labs):
        c = klass(x, y)
        tt = ch.create_tile_type(f"LAB_{c[0]}_{c[1]}_X{x}Y{y}")
        make_lab_wires(tt)
        pips = tile_pips(m, dw, seen_nb, x, y)
        pips += [(f"LINE{k}", w) for k in CTL_LINES[2] for w in ("ENA", "SCLR")] + [(f"LINE{k}", "ACLR")
                                                                                   for k in CTL_LINES[0]]
        for s_, d_ in pips:
            tt.create_pip(s_, d_, timing_class=pip_class(s_, d_))
        own[(x, y)] = f"LAB_{c[0]}_{c[1]}_X{x}Y{y}"
    if own:
        print(f"  {len(own)} LABs with their own tile type (near {sum(1 for e in fix.values() if isinstance(e, dict) and e.get('refused'))} refused hops)", flush=True)
    for x in range(X):
        for y in range(Y):
            ch.set_tile_type(x, y, own[(x, y)] if (x, y) in own else f"LAB_{klass(x, y)[0]}_{klass(x, y)[1]}" if (x, y) in labs
                             else "IO_CLK" if (x, y) == (0, 0) else f"IO_X{x}Y{y}" if (x, y) in tiles else "NULL")
    # nodes: R4 wires over the LAB tiles they span; neighbour buffers; the global clock
    for y in range(Y):
        for s in range(-4, X + 4):
            for w in list(R4_LEFT) + list(R4_RIGHT):
                ks = K_LEFT if w in R4_LEFT else K_RIGHT
                members = [NodeWire(s + k, y, f"R4_{w}_{k}") for k in ks if (s + k, y) in labs]
                members += pw_extra.pop(f"R4_X{s}_Y{y}_N0_I{w}", []) if len(members) > 1 else []
                if len(members) > 1:
                    ch.add_node(members)
        for cx in range(-1, X):
            # only C4s that run within the LAB rows (2..28): pips onto an edge wire then lead nowhere, since the pips
            # are per tile type and learnt mid-die (one starting at row 0 was refused by Quartus from X8Y4; onto those
            # starting at row 1 the corpus drives indices 48/49 from row 5, not the mid-die 0..25, and Quartus refused
            # 7 of our row-1 hops)
            if not 2 <= y <= 25:
                continue
            for w in C4_IDX:
                members = [NodeWire(cx + a, y + r, f"C4_{w}_{a}_{r}") for a in C4_A for r in C4_R
                           if (cx + a, y + r) in labs]
                members += pw_extra.pop(f"C4_X{cx}_Y{y}_N0_I{w}", []) if len(members) > 1 else []
                if len(members) > 1:
                    ch.add_node(members)
        for x in range(X):
            if (x, y) not in labs:
                continue
            for k in range(N_LINE):
                if (x, y, k) in il:
                    ch.add_node([NodeWire(x, y, f"LINE{k}")] + [NodeWire(*pad, w) for pad, w in il[(x, y, k)]])
            for b in range(N_BUF):
                members = [NodeWire(x, y, f"BUF{b}")]
                members += pw_extra.pop(f"LE_BUFFER_X{x}_Y{y}_N0_I{b}", [])
                if (x + 1, y) in labs:
                    members.append(NodeWire(x + 1, y, f"NBW{b}"))
                if (x - 1, y) in labs:
                    members.append(NodeWire(x - 1, y, f"NBE{b}"))
                if len(members) > 1:
                    ch.add_node(members)
    for nd, members in pw_extra.items():               # pin-path wires the database has no node for
        if len(members) > 1:
            ch.add_node(members)
    ch.add_node([NodeWire(0, 0, "GCLK")] + [NodeWire(x, y, "GCLK") for x, y in sorted(labs)])
    # nominal timing (one speed grade) so nextpnr's timing-driven placement runs; real numbers can come from
    # Quartus's timing reports later.  Our designs are checked with Quartus's own analysis (ycheck --timing).
    from himbaechel_dbgen.chip import TimingValue, ClockEdge
    tmg = ch.set_speed_grades(["DEFAULT"])
    dly, raw = delays()
    for c, v in dly.items():
        ch.timing.set_pip_class("DEFAULT", c, TimingValue(v))
    lut = ch.timing.add_cell_variant("DEFAULT", "LUT4")
    for i in range(4):
        lut.add_comb_arc(f"I[{i}]", "F", TimingValue(0))   # the arc's delay sits on the LUT_IN<i> pseudo-pip
    dff = ch.timing.add_cell_variant("DEFAULT", "DFF")
    # register arcs from the reports: clock -> q = uTco plus the register's output element (CUDA_FF, "FF" RE); the
    # data and enable inputs' arcs (CELL rows after the d / ena pin, keyed by pin) as setup.  The enable was untimed
    # before: the lock's worst path (Quartus) ends at a register's ena with a 0.795 ns arc
    ps = lambda v: TimingValue(int(round(v * 1000)))
    cellv = lambda k, dflt: raw.get("CELL", {}).get(k, [0, dflt])[1]
    tco = raw.get("uTco", {}).get("FF:", [0, 0.3])[1] + raw.get("RE", {}).get("FF", [0, 0])[1]
    dff.add_setup_hold("CLK", "D", ClockEdge.RISING, ps(cellv("FF:d", 0.2)), TimingValue(50))
    dff.add_setup_hold("CLK", "EN", ClockEdge.RISING, ps(cellv("FF:ena", 0.8)), TimingValue(50))
    dff.add_setup_hold("CLK", "SCLR", ClockEdge.RISING, ps(cellv("FF:sclr", 0.8)), TimingValue(50))
    dff.add_clock_out("CLK", "Q", ClockEdge.RISING, ps(tco))
    ch.write_bba(bba)
    print(f"{len(labs)} LAB tiles, {len(rep)} tile types, {npips} pips over the types -> {bba}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
