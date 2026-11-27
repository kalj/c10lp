#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-wide switch tables from the exact per-position solves (out/hopsolve.json).

A hop U -> V becomes a switch type
  (U type, U index, V type, V index, V.x - U.x, V.y - U.y, column class)
anchored at
  - V's LAB for LAB-line selects (V = LOCAL_INTERCONNECT): frames -26..-13 of that LAB;
  - U's LAB for drivers (U = LE_BUFFER): frames -30..+30 except the LE band -12..+9;
  - V's start otherwise (wire -> wire): frames -30..+30;
with bits relative to the anchor (frame - column frame, row-space index - row index) and the column class =
anchor X mod 8 for LAB-line selects (8-column period: limsolve.rule, leave-one-out 489 exact / 5 differ) and
(X + Y) mod 4 of the driving LAB for drivers (RCF oracle).
Bits: those in at least half of the instances (an exact solve can miss a bit the mux shares between its inputs).
Hops into LUT inputs and LUT -> LE_BUFFER are left to their own models (routing_pips, le_output_select).

  switchmodel.py build | check JOBS.json
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
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
NODE = re.compile(r"^(\w+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?$")
PERIOD = {"select": 8, "driver": 4, "wire": 8}       # class period per kind


def klass(kd: str, ax: int, ay: int) -> int:
    """Position class: LAB-line selects repeat every 8 columns; driver wiring with phase (X + Y) mod 4 of the
    driving LAB (RCF oracle: legal driver sets at X17 Y8..12, X23Y8 = X17Y10, X22Y8 = X17Y9 as predicted)."""
    if kd == "driver":
        return (ax + ay) % PERIOD["driver"]
    return ax % PERIOD[kd]


LE_BAND = (-12, 9)     # frames of an LE's own configuration (input mux, LUT, output select): never driver bits


def kind(key) -> str:
    return "select" if key[2] == "LOCAL_INTERCONNECT" else "driver" if key[0] == "LE_BUFFER" else "wire"


def parse(n: str):
    m = NODE.match(n.split(":")[0])
    if not m:
        return None
    t, x, y, nn, i = m.groups()
    return t, int(x), int(y), int(i) if i is not None else int(nn)


def typ(u: str, v: str):
    """(key without class, anchor (x, y), frame window) of a hop, or None if it isn't modelled here."""
    pu, pv = parse(u), parse(v)
    if not pu or not pv or pv[0] == "LCCOMB" or pu[0] == "LCCOMB":
        return None
    k = (pu[0], pu[3], pv[0], pv[3], pv[1] - pu[1], pv[2] - pu[2])
    if pv[0] == "LOCAL_INTERCONNECT":
        return k, (pv[1], pv[2]), (-26, -13)             # -12 and up: the LAB's LEs' own input-mux codes
    if pu[0] == "LE_BUFFER":
        return k, (pu[1], pu[2]), (-30, 30)
    return k, (pv[1], pv[2]), (-30, 30)


def anchor(ax, ay):
    f0, l0 = R._col_frame(ax), R._row_index(ay)
    return (f0, l0) if f0 is not None and l0 is not None else None


N_BUF_DRV = 32
# a switch is 1-3 cells (a driver pair, a two-level select, a last-tap set); an exact per-position solve (hopsolve.json:
# the cells set in every build using the hop) or an edge C4 entry with more holds co-occurring cells of other hops
# (C4_X3_Y1_I8 -> X4Y4 line 31: 20 cells, 9 of them wrong in the pin design's forced build)
MAX_EXACT = 3


def build(min_inst: int = 2):
    hs = json.load(open(os.path.join(OUT, "hopsolve.json")))
    inst = collections.defaultdict(list)
    for k, (ny, _nn, bits) in hs.items():
        if ny < 2:
            continue
        u, v = k.split("->")
        t = typ(u, v)
        if not t:
            continue
        key, (ax, ay), (lo, hi) = t
        a = anchor(ax, ay)
        if a is None:
            continue
        rel = frozenset((f - a[0], p + lutpos.PLANE_START[b] - a[1]) for f, p, b in bits
                        if lo <= f - a[0] <= hi and abs(p + lutpos.PLANE_START[b] - a[1]) < 120
                        and not (kind(key) == "driver" and LE_BAND[0] <= f - a[0] <= LE_BAND[1]))
        if rel:
            inst[key + (klass(kind(key), ax, ay),)].append(rel)
    # A driver is a complete bit pair, but an exact solve often misses one of its bits.  Snap each driver instance
    # to the unique maximal pattern of its (switch type without class) that contains it.
    # A driver's bits belong to the buffer, not to the wire it reaches (that rotates with the phase), so the
    # patterns to snap to are pooled over wires: key (type, buffer, to type, offset).
    drv = lambda key: (key[0], key[1], key[2], key[4], key[5])
    maximal = collections.defaultdict(set)
    for key, lst in inst.items():
        if kind(key) == "driver":
            maximal[drv(key)] |= set(lst)
    for base, pats in maximal.items():
        maximal[base] = {p for p in pats if len(p) == 2}     # a driver is a bit pair (RCF oracle); snap only into pairs
    for key, lst in inst.items():
        if kind(key) == "driver":
            snapped = []
            for r in lst:
                sup = [q for q in maximal[drv(key)] if r <= q]
                snapped.append(sup[0] if len(sup) == 1 and len(r) < 2 else r)
            inst[key] = snapped
    table = {}
    for key, lst in inst.items():
        if len(lst) < min_inst:
            continue
        cnt = collections.Counter(b for r in lst for b in r)
        if kind(key) == "select":
            # few instances let stray bits in at 50%: all instances up to 3, else 60%
            need = len(lst) if len(lst) <= 3 else 0.6 * len(lst)
            bits = sorted(b for b, c in cnt.items() if c >= need)
            # an R4 -> line select's bits sit within two rows (tapmap.py, 78 exact); a wider set holds stray bits of
            # co-occurring hops ((23, 0, 32) class 4: five bits over rows -51..-20, 2 wrong held-out predictions)
            if key[0] == "R4" and bits and max(l for _f, l in bits) - min(l for _f, l in bits) > 2:
                continue
        else:
            bits = sorted(b for b, c in cnt.items() if 2 * c >= len(lst))
            # a driver is a bit pair: a corpus driver entry with more bits holds strays of co-occurring hops
            # (buffer X6 I13 -> R4 X6 I4: five bits, three of them wrong in the spread blinky's forced build)
            if kind(key) == "driver" and len(bits) > 2:
                continue
        agree = sum(r == frozenset(bits) for r in lst) / len(lst)
        if bits:
            table[repr(key)] = [len(lst), round(agree, 2), bits]
    # Exact selects from the RCF oracle (selmap.py): an honoured forced route's diff sets the new select and clears
    # the old one.  They override the corpus consensus for their (wire, line, class).
    sm = os.path.join(OUT, "selmap.json")
    n_or = 0
    for pos, e in (json.load(open(sm)).items() if os.path.exists(sm) else []):
        X, Y = int(pos[1:].split("Y")[0]), int(pos.split("Y")[1])
        a = anchor(X, Y)
        for k, v in e["pairs"].items():
            if v["status"] != "honoured" or not v["bits"]:
                continue
            w, line = k.split("|")
            for val, node in ((1, w), (0, None)):
                rel = sorted((f - a[0], p + lutpos.PLANE_START[b] - a[1]) for f, p, b, x in v["bits"]
                             if x == val and -26 <= f - a[0] <= -13)
                if not rel:
                    continue
                if val == 1:
                    t = typ(w, line)
                else:                                     # the old select: Quartus's route of that net
                    continue
                table[repr(t[0] + (X % PERIOD["select"],))] = [99, 1.0, rel]
                n_or += 1
    # Tap selects sit in the select band, except a wire's tap at its last LAB, which uses the driver band +13..+15
    # (167 honoured tapmap probes with no select-band cell: e.g. R4 I7 -> line 7 at offset 3 sets (13,-28)/(14,-28)).
    # In a tapmap probe only the line changes, and a tapforce probe's new driver sits in another column, so cells in
    # either band are the select.
    in_band = lambda df: -26 <= df <= -13 or 13 <= df <= 15
    # tapmap.py: the same kind of exact selects at any tap of a wire (both directions), keyed per class.  Pooling them
    # over classes is unsafe ((4, +3, 18) agrees in classes 6 and 7 and differs in 1).
    tm = os.path.join(OUT, "tapmap.json")
    # An honoured probe also clears the select of the line Quartus chose for that wire (its 0-valued diff cells): the
    # same kind of exact entry for (w, that line), with the line read from the build's own route (tapmap work dirs).
    import glob
    import rcfforce as F
    orig = {}
    for f in glob.glob(os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcftap", "work", "*", "base.rcf")):
        if re.search(r"\.w\d+$", os.path.dirname(f)):
            continue
        job = os.path.basename(os.path.dirname(f))
        for bl in F.branches(open(f).read()).values():
            for path, _d in bl:
                if len(path) == 3 and path[1].startswith("R4") and path[2].startswith("LOCAL_INTERCONNECT"):
                    orig[(job, path[1])] = path[2]
    n_orig = 0
    for job, out in (json.load(open(tm)).items() if os.path.exists(tm) else []):
        for k, v in out.items():
            if v["status"] != "honoured" or not v["bits"]:
                continue
            w, line = k.split("|")
            L0 = orig.get((job, w))
            if L0:
                pl0 = parse(L0)
                a0 = anchor(pl0[1], pl0[2])
                rel0 = sorted((f - a0[0], p + lutpos.PLANE_START[b] - a0[1]) for f, p, b, x in v["bits"]
                              if x == 0 and in_band(f - a0[0])) if a0 else []
                if rel0:
                    kk = repr(typ(w, L0)[0] + (pl0[1] % PERIOD["select"],))
                    if kk not in table or table[kk][0] != 99:
                        table[kk] = [99, 1.0, rel0]
                        n_orig += 1
            pl = parse(line)
            a = anchor(pl[1], pl[2])
            if a is None:
                continue
            rel = sorted((f - a[0], p + lutpos.PLANE_START[b] - a[1]) for f, p, b, x in v["bits"]
                         if x == 1 and in_band(f - a[0]))
            if rel:
                table[repr(typ(w, line)[0] + (pl[1] % PERIOD["select"],))] = [99, 1.0, rel]
                n_or += 1
    # tapforce.py: wire and line both forced.  The diff also clears the net's old route, so only the set cells in the
    # sink LAB's select band count (the new driver sits in the source LAB, columns to the right).
    tf = os.path.join(OUT, "tapforce.json")
    tf_entries = []
    for out in (json.load(open(tf)).values() if os.path.exists(tf) else []):
        for k, v in out.items():
            if v["status"] != "honoured" or not v["bits"]:
                continue
            w, line = k.split("|")
            pl = parse(line)
            a = anchor(pl[1], pl[2])
            if a is None:
                continue
            rel = sorted((f - a[0], p + lutpos.PLANE_START[b] - a[1]) for f, p, b, x in v["bits"]
                         if x == 1 and in_band(f - a[0]))
            if rel:
                kk = repr(typ(w, line)[0] + (pl[1] % PERIOD["select"],))
                table[kk] = [99, 1.0, rel]
                tf_entries.append((kk, w, a, rel, {(f, p, b) for f, p, b, x in v["bits"] if x == 1}))
                n_or += 1
    table["_oracle_selects"] = n_or
    table["_oracle_selects_orig"] = n_orig
    json.dump(table, open(os.path.join(OUT, "switchmodel.json"), "w"), indent=0)
    # A tapforce probe forces a new wire, so its diff holds the new driver's bits too, and where the driver's band
    # overlaps the sink LAB's (a right-going R4 tapped at its first LAB, driven from the LAB to the left; a source one
    # LAB east driving through the dx -1 pair, which is the sink's +13/+15) they look like selects: 2 of the
    # free-placement blinky's 3 wrong cells against Quartus's forced build.  Drop the cells the model attributes to
    # the probe's driver: a buffer whose modelled bits onto that wire are all set in the probe's diff (a cell has one
    # function).  Any buffer at all would be too broad: (-19, -56) of R4 I13 -> line 12 at offset 0 is a real select.
    m = Model()
    n_drop = 0
    for kk, w, a, rel, setc in tf_entries:
        pw = parse(w)
        drv = set()
        for bx in range(pw[1] - 4, pw[1] + 6):
            for b in range(N_BUF_DRV):
                bits = m.bits(f"LE_BUFFER_X{bx}_Y{pw[2]}_N0_I{b}", w)
                if bits and all((f, by + lutpos.PLANE_START[pb]) in {(f2, b2 + lutpos.PLANE_START[p2]) for f2, b2, p2 in setc}
                                for f, by, pb in bits):
                    drv |= {(f - a[0], by + lutpos.PLANE_START[pb] - a[1]) for f, by, pb in bits}
        keep = sorted(set(map(tuple, rel)) - drv)
        if len(keep) < len(rel) and table[kk][2] == rel:
            n_drop += len(rel) - len(keep)
            if keep:
                table[kk] = [99, 1.0, keep]
            else:
                del table[kk]
    table["_tapforce_driver_cells_dropped"] = n_drop
    json.dump(table, open(os.path.join(OUT, "switchmodel.json"), "w"), indent=0)
    return table


class Model:
    def __init__(self, path: str = os.path.join(OUT, "switchmodel.json")):
        import ast
        self.t = {ast.literal_eval(k): v for k, v in json.load(open(path)).items() if not k.startswith("_")}
        self.by_from = collections.defaultdict(list)     # (U type, U index, class) -> keys
        for k in self.t:
            self.by_from[(k[0], k[1])].append(k)
        # R4 drivers at offset -3 (r4drv_model.json): the frame-14 bit row is the physical track, the frame-13 bit picks
        # the buffer; the wire index a track reaches depends only on the phase (X + Y) mod 4 (RCF oracle, drvmap.py)
        self.nl = None
        self.rr = None                                   # R4 -> R4 continuations (r4r4model.py), loaded on first use
        self.rdrv = None                                 # right-going R4 drivers (r4drv_right.py), loaded on first use
        self.nbdrv = None                                # neighbour-link drivers per (buffer, dx, line), nbmap.py
        self.c4sel = None                                # C4 -> line selects from the corpus, c4sel.py
        self.c4drv = None                                # buffer -> C4 drivers from the corpus, c4drv.py
        self._exact = None                               # exact per-position solves of the input pads' hops
        self._exact_long = None                          # and of long-wire hops (C16, R24)
        self._exact_io = None                            # and of hops into an I/O block's lines (row 0)
        self._exact_edge = None                          # and of hops onto / off the bottom edge's C4s
        self._fix = None                                 # cross-check corrections (hopfix.json)
        self._corner = None                              # R4 <-> C4 turns (corner.json)
        self._memo = {}                                  # bits() per (u, v, min_inst)
        self._lfb_any = None
        # local feedback measured with the RCF oracle (R4 detours, out/localfb_oracle*.json): class-independent, so
        # keyed (buffer, line)
        # Some local feedback runs through the driver track instead of a line select: no select bits, a driver pair at
        # frames +13/+14 (the R4 driver band), the same in every phase.  19 -> 10 and 12 -> 5 from the corpus solves
        # (36 and 3 positions); 4 -> 1 and 8 -> 3 read off blink24p and confirmed independently (div24 at X2Y6, and every
        # corpus build using them: 11/11, 1/1)
        self.lfb = {(19, 10): [(13, -43), (14, -44)], (12, 5): [(13, -20), (14, -19)],
                    (4, 1): [(13, -3), (14, -3)], (8, 3): [(13, -12), (14, -11)]}
        import glob
        for f in glob.glob(os.path.join(OUT, "localfb_oracle*.json")):
            for k, rel in json.load(open(f)).items():
                b, line = k.split("->")
                self.lfb[(int(b.rsplit("_I", 1)[1]), int(line.rsplit("_I", 1)[1]))] = [tuple(r) for r in rel]
        p = os.path.join(OUT, "r4drv_model.json")
        self.r4 = None
        if os.path.exists(p):
            d = json.load(open(p))
            self.r4 = ({int(ph): {int(tr): w for tr, w in m.items()} for ph, m in d["tracks"].items()},
                       {int(b): {int(tr): pr for tr, pr in m.items()} for b, m in d["pairs"].items()})
            for ph, m in self.r4[0].items():
                for b, prs in self.r4[1].items():
                    for tr in prs:
                        if tr in m:
                            k = ("LE_BUFFER", b, "R4", m[tr], -3, 0, ph)
                            if k not in self.by_from[("LE_BUFFER", b)]:
                                self.by_from[("LE_BUFFER", b)].append(k)

    def _r4r4(self, u: str, v: str):
        """R4 u -> R4 v from r4r4model.py: the continuation must be the key's target; bits in the driving LAB's band."""
        import r4r4model as RR
        if self.rr is None:
            p = os.path.join(OUT, "r4r4_model.json")
            self.rr = json.load(open(p)) if os.path.exists(p) else {}
        mu, mv = RR.NODE.match(u), RR.NODE.match(v)
        if not mu or not mv or mu[2] != mv[2]:
            return None
        ax, ay, ai, cx, ci = int(mu[1]), int(mu[2]), int(mu[3]), int(mv[1]), int(mv[3])
        e = self.rr.get(RR.key(ai, ax, ay, cx))
        if e is None or e["c"] != ci or not e["bits"]:
            return None
        a = anchor(RR.drive_lab(ax, cx), ay)
        if a is None:
            return None
        out = [G.cell_of(a[0] + f, a[1] + l) for f, l in e["bits"]]
        return None if None in out else out

    def _neighbour(self, b: int, dx: int, x: int, y: int, line: int | None = None):
        """LE_BUFFER b of LAB (x, y) -> a line of LAB (x + dx, y): the source side of a neighbour-LAB link
        (li_neighbour.json, silicon-verified): driver bits at the column's slot-0 LUT frame + df and the source LE's
        byte + db.  The line index itself isn't in that table."""
        if self.nl is None:
            self.nl = json.load(open(os.path.join(HERE, "data", "li_neighbour.json")))
        slot = b - b % 2
        d = "+1" if dx > 0 else "-1"
        drv = self.nl["src_driver_bits"][d].get(str(slot))
        # measured per (buffer, dx, line) where known (nbmap.py): the driver moves with the line (buffer 14 at dx +1:
        # (16,0)/(18,0) for line 21, the slot table's (19,-2)/(21,-1) for line 33)
        if self.nbdrv is None:
            pn = os.path.join(OUT, "nbdrv.json")
            self.nbdrv = json.load(open(pn)) if os.path.exists(pn) else {}
        meas = self.nbdrv.get(f"{b}|{dx}|{line}") if line is not None else None
        if meas:
            drv = meas
        if drv is None:
            return None
        try:
            c = lutpos._predict_phys(x, y, slot)
            f0 = min(v[0] for v in lutpos._predict_phys(x, y, 0))
        except ValueError:
            return None
        sf0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
        # (the source LE's frame-8 output-select bit is LE configuration: set for a combinational output only)
        # dx -1: the table lists only the frame -22 cell; the driver is a pair with frame -20 on the same byte
        # (nb4 probes at slots 0, 2, 18, 30 from X15Y10: 4/4; without it the Yosys blinky's X9 N18 -> X8 link is
        # open on the board, D5 at 45.8 Hz instead of 2.861)
        if dx < 0:
            drv = list(drv) + [[-20, db] for df, db in drv if df == -22 and [-20, db] not in drv]
        return [(f0 + df, lo + db, bit) for df, db in drv]

    def _r4_driver(self, b: int, w: int, ax: int, ay: int):
        tracks, pairs = self.r4
        inv = {wire: tr for tr, wire in tracks.get((ax + ay) % 4, {}).items()}
        pr = pairs.get(b, {}).get(inv.get(w))
        a = anchor(ax, ay)
        if pr is None or a is None:
            return None
        out = [G.cell_of(a[0] + f, a[1] + l) for f, l in pr]
        return None if None in out else out

    def bits(self, u: str, v: str, min_inst: int = 2):
        """Absolute (frame, byte, plane) bits of hop u -> v, or None if the model has no such switch type."""
        k = (u, v, min_inst)
        if k not in self._memo:
            self._memo[k] = self._bits(u, v, min_inst)
        return self._memo[k]

    def _bits(self, u: str, v: str, min_inst: int = 2):
        # corrections proved by a Quartus cross-check (flow/ycheck.py: Quartus honoured our route, and its build
        # differs from ours in a cell only this hop's entry claims): exact cells for that node pair
        if self._fix is None:
            pf = os.path.join(OUT, "hopfix.json")
            self._fix = {k: v_ for k, v_ in json.load(open(pf)).items() if not k.startswith("_")} if os.path.exists(pf) else {}
        if f"{u}->{v}" in self._fix:
            e = self._fix[f"{u}->{v}"]
            return None if e.get("refused") else [tuple(c) for c in e["cells"]]   # refused by Quartus: no hop
        t = typ(u, v)
        if not t:
            return None
        key, (ax, ay), _w = t
        pv0 = parse(v)
        if pv0 and pv0[2] == 0 and pv0[0] == "LOCAL_INTERCONNECT":
            # a line of an I/O block in row 0 (D5's on the Vidor): fixed positions, so the exact per-position solve
            if self._exact_io is None:
                self._exact_io = {k: v for k, v in json.load(open(os.path.join(OUT, "hopsolve.json"))).items()
                                  if "LOCAL_INTERCONNECT_X" in k.split("->")[1] and "_Y0_" in k.split("->")[1]
                                  and v[0] >= 2 and v[2] and len(v[2]) <= MAX_EXACT}
            e = self._exact_io.get(f"{u}->{v}")
            return [tuple(c) for c in e[2]] if e else None
        if {key[0], key[2]} == {"R4", "C4"}:
            # corner turns: an input of the target wire's driver mux (mapping/corner.py; held-out 37/41 R4 -> C4 and
            # 23/33 C4 -> R4, none wrong; the class table's own entries were wrong 3 times in 15)
            if self._corner is None:
                pc = os.path.join(OUT, "corner.json")
                self._corner = json.load(open(pc)) if os.path.exists(pc) else {}
            import corner as CO
            for kd, kk, (dx, dy), _fr in CO.keys(u, v):      # not `kind`: that is this module's kind()
                e = self._corner.get(f"{kd}|{kk}")
                an = CO.anchor(dx, dy)
                if e and an:
                    out = [G.cell_of(an[0] + f, an[1] + r) for f, r in e]
                    return None if None in out else out
            # no corner entry: fall through (a bottom-edge C4's turn has an exact per-position solve, used by the pin
            # path library; returning None here dropped its cells: rd109 / rd110 / rd119)
        if key[0] in ("C16", "R24") or key[2] in ("C16", "R24"):
            # long wires: on the Vidor's input paths they start next to the fixed pads, so the same hops recur at the
            # same positions; use the exact per-position solve (hopsolve.json) where one exists
            if self._exact_long is None:
                self._exact_long = {k: v for k, v in json.load(open(os.path.join(OUT, "hopsolve.json"))).items()
                                    if ("C16_" in k or "R24_" in k) and v[0] >= 2 and v[2] and len(v[2]) <= MAX_EXACT}
            e = self._exact_long.get(f"{u}->{v}")
            if e:
                return [tuple(c) for c in e[2]]
        if key[0] in ("IO_DATAIN", "IOIBUF"):
            # the input pads sit at fixed positions (D1..D4 on the Vidor): their hops use the exact per-position solve
            # (hopsolve.json), not a class rule (the class table was wrong 120 times in 122 held-out IO_DATAIN -> C16)
            if self._exact is None:
                # an IOIBUF -> IO_DATAIN solve with no bits is the default selection, already in the all-zero baseline
                # (which configures D1..D4 as inputs): priced, nothing to set (pad X1Y0, pin N3)
                self._exact = {k: v for k, v in json.load(open(os.path.join(OUT, "hopsolve.json"))).items()
                               if k.startswith(("IO_DATAIN", "IOIBUF")) and v[0] >= 2 and len(v[2]) <= MAX_EXACT
                               and (v[2] or (k.startswith("IOIBUF") and "->IO_DATAIN" in k))}
            e = self._exact.get(f"{u}->{v}")
            return [tuple(c) for c in e[2]] if e else None
        if key[0] == "R4" and key[2] == "R4" and key[5] == 0:
            return self._r4r4(u, v)
        if key[0] == "LE_BUFFER" and key[2] == "R4" and key[4:6] == (1, 0):
            # right-going drivers (r4drv_right.py): legal per (buffer, phase); a bit pair at frames +16/+18 of the
            # buffer's LAB per (buffer, wire, phase)
            if self.rdrv is None:
                pr = os.path.join(OUT, "r4drv_right.json")
                self.rdrv = json.load(open(pr)) if os.path.exists(pr) else {"legal": {}, "bits": {}}
            ph = (ax + ay) % 4
            if key[3] not in self.rdrv["legal"].get(f"{key[1]}|{ph}", []):
                return None
            e = self.rdrv["bits"].get(f"{key[1]}|{key[3]}|{ph}")
            a = anchor(ax, ay)
            if not e or a is None:
                return None
            out = [G.cell_of(a[0] + f, a[1] + l) for f, l in e]
            return None if None in out else out
        if self.r4 and key[0] == "LE_BUFFER" and key[2] == "R4" and key[4:6] == (-3, 0):
            return self._r4_driver(key[1], key[3], ax, ay)
        if key[0] == "LE_BUFFER" and key[2] == "LOCAL_INTERCONNECT" and key[4:6] == (0, 0) and (key[1], key[3]) in self.lfb:
            a = anchor(ax, ay)
            out = [G.cell_of(a[0] + f, a[1] + l) for f, l in self.lfb[(key[1], key[3])]]
            return None if None in out else out
        if key[0] == "LE_BUFFER" and key[2] == "LOCAL_INTERCONNECT" and key[4] in (-1, 1) and key[5] == 0:
            return self._neighbour(key[1], key[4], ax - key[4], ay, key[3])
        e = self.t.get(key + (klass(kind(key), ax, ay),))
        if e is None and key[0] == "LE_BUFFER" and key[2] == "LOCAL_INTERCONNECT" and key[4:6] == (0, 0):
            # local feedback (an LE buffer onto a line of its own LAB) is the same in every column class: 7/8 pairs
            # seen in several classes agree, and an RCF measurement at X1 (no corpus entry) equals all 7 classes
            if self._lfb_any is None:                     # first entry per class-less key, indexed once
                self._lfb_any = {}
                for k, tv in self.t.items():                # not v: that is this hop's sink
                    if tv[0] >= 2:
                        self._lfb_any.setdefault(k[:6], tv)
            e = self._lfb_any.get(key)
        if key[0] == "LE_BUFFER" and key[2] == "C4":
            # C4 drivers from the corpus (c4drv.py): per (buffer, wire, dx, dy, (X+Y) mod 4), a pair on the buffer's
            # row (held-out 295/297 priced hops all set, against the table's 140/140 with half the coverage)
            if self.c4drv is None:
                pc = os.path.join(OUT, "c4drv.json")
                self.c4drv = json.load(open(pc)) if os.path.exists(pc) else {}
            sy = parse(v)[2]
            c = self.c4drv.get(f"{key[1]}|{key[3]}|{key[4]}|{key[5]}|{(ax + ay) % 4}" + (f"|e{sy}" if sy < 2 else ""))
            if c and sy < 2 and len(c) > MAX_EXACT:
                c = None
            if c:
                e = [99, 1.0, c]
        if key[0] == "C4" and key[2] == "LOCAL_INTERCONNECT":
            # C4 taps from the corpus (c4sel.py): per (wire, column offset, row offset, line, X mod 8), the cells near
            # the line's select row set in >= 80% of the uses.  Preferred over the corpus table, whose C4 selects keep
            # stray bits of other nets (held-out: c4sel 1 wrong in 79, the table 6 in 44).
            if self.c4sel is None:
                pc = os.path.join(OUT, "c4sel.json")
                self.c4sel = json.load(open(pc)) if os.path.exists(pc) else {}
            if "bits" in self.c4sel and not isinstance(self.c4sel.get("legal"), set):
                self.c4sel["legal"] = set(self.c4sel.get("legal", []))
            sy = parse(u)[2]
            k5 = f"{key[1]}|{key[4]}|{key[5]}|{key[3]}|{ax % 8}" + (f"|e{sy}" if sy < 2 else "")
            # bits per X mod 8, legality per (X mod 8, Y mod 4) of the sink LAB (c4sel.py)
            c = self.c4sel["bits"].get(k5) if f"{k5}|{ay % 4}" in self.c4sel["legal"] else None
            if c and sy < 2 and len(c) > MAX_EXACT:
                c = None
            # c4sel, else an oracle-measured entry (tapforce.py, count 99); not the corpus table's own C4 selects
            # (wrong 6 times in 50 held-out)
            e = [99, 1.0, c] if c else (e if e and e[0] == 99 else None)
        a = anchor(ax, ay)
        if not e or e[0] < min_inst or a is None:
            if any(p_ and p_[0] == "C4" and p_[2] < 2 for p_ in (parse(u), parse(v))):
                # the bottom edge's C4s, numbered differently from mid-die: else the exact per-position solve
                if self._exact_edge is None:
                    self._exact_edge = {k: v_ for k, v_ in json.load(open(os.path.join(OUT, "hopsolve.json"))).items()
                                        if re.search(r"C4_X\d+_Y[01]_", k) and v_[0] >= 2 and v_[2]
                                        and len(v_[2]) <= MAX_EXACT}
                x = self._exact_edge.get(f"{u}->{v}")
                return [tuple(c) for c in x[2]] if x else None
            return None
        out = [G.cell_of(a[0] + f, a[1] + l) for f, l in e[2]]
        return None if None in out else out

    def fanout(self, u: str, min_inst: int = 2):
        """Hops u -> v the model knows, as (v, bits)."""
        pu = parse(u)
        if not pu:
            return []
        res = []
        for k in self.by_from.get((pu[0], pu[3]), []):
            _ft, _fi, vt, vi, dx, dy, c = k
            if self.r4 and k[0] == "LE_BUFFER" and vt == "R4" and (dx, dy) == (-3, 0) and c != (pu[1] + pu[2]) % 4:
                continue                                     # R4 driver entries are per phase
            x, y = pu[1] + dx, pu[2] + dy
            v = f"{vt}_X{x}_Y{y}_N0_I{vi}"
            b = self.bits(u, v, min_inst)
            if b:
                res.append((v, b))
        if pu[0] == "LE_BUFFER":
            # right-going drivers: the wires legal for (buffer, phase), starting one column right
            if self.rdrv is None:
                self.bits(u, f"R4_X{pu[1] + 1}_Y{pu[2]}_N0_I0")        # loads the table
            for w in self.rdrv["legal"].get(f"{pu[3]}|{(pu[1] + pu[2]) % 4}", []):
                v = f"R4_X{pu[1] + 1}_Y{pu[2]}_N0_I{w}"
                b = self.bits(u, v, min_inst)
                if b:
                    res.append((v, b))
        if pu[0] == "R4":
            # R4 -> R4 continuations (r4r4model.py): the key's one target, 3 or 4 columns on in the wire's direction
            import r4r4model as RR
            if self.rr is None:
                self._r4r4(u, u)                         # loads the table
            step = -1 if pu[3] >= 17 else 1
            for span in (3, 4):
                e = self.rr.get(RR.key(pu[3], pu[1], pu[2], pu[1] + step * span))
                if e and e["bits"]:
                    v = f"R4_X{pu[1] + step * span}_Y{pu[2]}_N0_I{e['c']}"
                    b = self.bits(u, v, min_inst)
                    if b:
                        res.append((v, b))
        return res


def check(jobs_file: str):
    """Held-out check: for every modelled hop of each build, are all predicted bits set (uses)?  And for model
    hops from the same U into nodes the build leaves unused, are they all clear (non-uses)?"""
    import routes
    import xdev
    m = Model()
    c = collections.Counter()
    for name in json.load(open(jobs_file)):
        buf = xdev.load(OUT, name)
        hops = routes.pips(json.load(open(os.path.join(OUT, name + ".route.json"))))
        used = {n for h in hops for n in h}
        on = lambda cell: buf[32 + cell[0] * 255 + cell[1]] >> cell[2] & 1
        for u, v in hops:
            t = typ(u, v)
            if not t:
                continue
            kd = kind(t[0])
            b = m.bits(u, v)
            if b is None:
                c[f"{kd}: no type"] += 1
                continue
            c[f"{kd}: use, all bits set" if all(map(on, b)) else f"{kd}: use, bits missing"] += 1
            for v2, b2 in m.fanout(u):
                if v2 not in used and v2 != v:
                    c[f"{kd}: non-use, all clear" if not any(map(on, b2)) else f"{kd}: non-use, some set"] += 1
    for k in sorted(c):
        print(f"  {k:32s} {c[k]}")
    return c


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        t = build()
        kinds = collections.Counter(kind(eval(k)) for k in t if not k.startswith("_"))
        print(f"{len(t)} switch types (with column class):", dict(kinds))
    elif cmd == "check":
        check(sys.argv[2])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
