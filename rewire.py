#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""First routing change written without Quartus: rewire one LUT input inside a LAB.

Base: Quartus build of xdev design mux4 (pins vidorlo): sources at slots S
(functions of D1..D4) drive the four inputs of dst at slot d, which drives D5.
A rewire switches one physical input of dst from its source to another source
in the same LAB by rewriting only that input's select bits (li_local_table.json):
clear the old (input, source) entry, set the new one.  The dst LUT mask is also
rewritten so D5 shows the rewired input.  gate.py additionally allows exactly
those select bits, and the new select region must equal the table's prediction.

Approved as the one exception to board rule 2 (2026-11-23).

  rewire.py check          offline: base region == table prediction; plan; write + gate files
  rewire.py board          load and test every file, 16 input combinations each
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "rewire")
LOC, D, SRCS = (10, 10, 0), 16, [0, 4, 8, 12]
LONE = None          # --lone: only rewire to (input, source) pairs Quartus used for a lone source
SRC_MASKS = [0x6996, 0x96A5, 0x1E78, 0x7BD2]       # as in xdev.verilog() for mux4
BASE_MASK = 0x3CEC
TABLE = json.load(open(os.path.join(HERE, "li_local_table.json")))
ENTRIES = {tuple(map(int, k.split(","))): [tuple(v) for v in vs] for k, vs in TABLE["entries"].items()}
LO_F, HI_F = TABLE["frames"]


def base_name() -> str:
    return xdev.Job("c10_016", f"mux4:{D}:" + "-".join(map(str, SRCS)), LOC, "vidorlo").name


class Dst:
    def __init__(self, buf: bytes):
        x, y, _ = LOC
        self.cells = lutpos._predict_phys(x, y, D)
        self.f0 = min(c[0] for c in self.cells)
        self.lo = min(c[1] for c in self.cells)
        self.bit = self.cells[0][2]
        self.flip = (D // 2) % 2
        on = {c for c in self.cells if buf[32 + c[0] * 255 + c[1]] >> c[2] & 1}
        hits = [p for p in lutpos.PERMS
                if {self.cells[lutpos.permute(i, p)] for i in range(16) if BASE_MASK >> i & 1} == on]
        if len(hits) != 1:
            raise SystemExit("base build: dst input order not identified")
        self.perm = hits[0]                                   # logical input i -> physical perm[i]

    def cell(self, df: int, col: int) -> tuple[int, int, int]:
        """(frame, byte, bit) of a dst-relative select bit (frame offset, byte column)."""
        dp = col - 2 if self.flip else col
        return (self.f0 + df, self.lo + dp, self.bit)

    def region(self, buf: bytes) -> set:
        return {(df, c) for df in range(LO_F, HI_F + 1) for c in range(4)
                if buf[32 + (self.f0 + df) * 255 + self.lo + (c - 2 if self.flip else c)] >> self.bit & 1}


def predict(assign: dict[int, int]) -> set:
    """Table prediction of the select region for {physical input: source slot}."""
    return set().union(*(set(ENTRIES[(p, s)]) for p, s in assign.items()))


def flip_bit(buf: bytearray, cell, v: list) -> None:
    f, p, b = cell
    off = 32 + f * 255 + p
    w = lutpos.header_weight(f, p, b)
    v[0] += -w if buf[off] >> b & 1 else w
    buf[off] ^= 1 << b


def make(base: bytes, dst: Dst, lut_mask: int, rewires: dict[int, int]) -> tuple[bytes, set]:
    """Rewrite dst's mask, and move physical input p to source slot rewires[p]."""
    buf = bytearray(base)
    v = [lutpatch.header_sum(base)]
    cur = {dst.perm[i]: SRCS[i] for i in range(4)}
    extra = set()
    for p, s_new in rewires.items():
        old, new = set(ENTRIES[(p, cur[p])]), set(ENTRIES[(p, s_new)])
        for rel in old ^ new:
            c = dst.cell(*rel)
            flip_bit(buf, c, v)
            extra.add(c)
        cur[p] = s_new
    flip = BASE_MASK ^ lut_mask
    for i, c in enumerate(lutpos.predict(*LOC[:2], D, dst.perm)):
        if flip >> i & 1:
            flip_bit(buf, c, v)
    g = rbfgeom.infer(base)
    lutpatch.patch_crc(buf, g)
    lutpatch.set_header_sum(buf, v[0] % (1 << 32))
    new = bytes(buf)
    if dst.region(new) != predict(cur):
        raise SystemExit("rewired select region is not what the table predicts")
    return new, extra


def expected(lut_mask: int, dst: Dst, rewires: dict[int, int], ds) -> int:
    """D5 for pins ds = (D1..D4): sources compute their masks of (A, B, C, D)."""
    idx = sum(v << k for k, v in enumerate(ds))
    src_val = {s: SRC_MASKS[k] >> idx & 1 for k, s in enumerate(SRCS)}
    cur = {dst.perm[i]: SRCS[i] for i in range(4)}
    cur.update(rewires)
    # logical input i sits on physical input perm[i]
    lut_in = sum(src_val[cur[dst.perm[i]]] << i for i in range(4))
    return lut_mask >> lut_in & 1


def plan(dst: Dst):
    """(name, dst mask, rewires).  Mask PASS_i passes logical input i straight to D5."""
    pass_i = lambda i: sum(((m >> i) & 1) << m for m in range(16))   # noqa: E731
    p0 = dst.perm[0]                                       # physical input of logical 0 (source 0)
    cur = {dst.perm[i]: SRCS[i] for i in range(4)}
    res = [("quartus_base", BASE_MASK, {}), ("lut_only_pass0", pass_i(0), {})]
    ok = lambda p, s: (p, s) in ENTRIES and (LONE is None or (p, s) in LONE)   # noqa: E731
    if LONE is not None:
        for i in range(4):
            p = dst.perm[i]
            for s in SRCS:
                if s != cur[p] and ok(p, s) and (p, cur[p]) in ENTRIES:
                    res.append((f"rewire_in{p}_to_src{s}", pass_i(i), {p: s}))
        return res
    for s in SRCS[1:]:
        if (p0, s) in ENTRIES:
            res.append((f"rewire_in{p0}_to_src{s}", pass_i(0), {p0: s}))
    # Every other single rewire the table covers (each physical input to each other source).
    for i in range(1, 4):
        p = dst.perm[i]
        for s in SRCS:
            if s != cur[p] and (p, s) in ENTRIES:
                res.append((f"rewire_in{p}_to_src{s}", pass_i(i), {p: s}))
    # Swaps: two inputs exchange sources, so no source is shared by two inputs.
    for i in range(4):
        for k in range(i + 1, 4):
            p, q = dst.perm[i], dst.perm[k]
            if (p, cur[q]) in ENTRIES and (q, cur[p]) in ENTRIES:
                # D5 = input i AND NOT input k: asymmetric, so an unswapped wiring gives a different D5
                m = sum((((v >> i) & ~(v >> k)) & 1) << v for v in range(16))
                res.append((f"swap_in{p}_in{q}", m, {p: cur[q], q: cur[p]}))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "board"])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--srcs", default="0-4-8-12", help="base source slots, e.g. 2-10-18-24")
    ap.add_argument("--lone", action="store_true",
                    help="only rewires to (input, source) pairs in li_lone_pairs.json")
    a = ap.parse_args()
    global SRCS, DIR, LONE
    SRCS = [int(v) for v in a.srcs.split("-")]
    if SRCS != [0, 4, 8, 12]:
        DIR = os.path.join(OUT, "rewire_" + a.srcs)
    if a.lone:
        LONE = {tuple(p) for p in json.load(open(os.path.join(HERE, "li_lone_pairs.json")))}
    base = xdev.load(OUT, base_name())
    if base is None:
        raise SystemExit(f"build {base_name()} first")
    dst = Dst(base)
    cur = {dst.perm[i]: SRCS[i] for i in range(4)}
    files = []
    os.makedirs(DIR, exist_ok=True)
    for name, mask, rw in plan(dst):
        new, extra = make(base, dst, mask, rw)
        les = [(LOC[0], LOC[1], D)]
        errs = gate.check(base, new, les, extra_cells=extra)
        if errs:
            raise SystemExit(f"{name}: GATE FAIL {errs}")
        path = os.path.join(DIR, f"lo_{name}.rbf")
        if name == "quartus_base":
            new = base
        open(path, "wb").write(new)
        files.append((name, path, mask, rw, extra))
    if a.cmd == "check":
        print(f"base input order {dst.perm}; physical input -> source: {cur}")
        print(f"base select region == table prediction: {dst.region(base) == predict(cur)}")
        for name, _, mask, rw, extra in files:
            table = "".join(str(expected(mask, dst, rw, ds)) for ds in hwtest.COMBOS4)
            print(f"  {name:22s} mask {mask:04X} rewires {rw} select bits changed {len(extra)}  D5 over "
                  f"the 16 combos: {table}")
        return 0

    bench = hwtest.Bench(a.port)
    bench.cmd("I")
    log_path = os.path.join(OUT, time.strftime(f"rewire_{a.srcs}_%Y%m%d_%H%M%S.jsonl"))
    control = os.path.join(OUT, "lo_quartus_0000.rbf")
    ok = fail = 0
    with open(log_path, "w") as log:
        for name, path, mask, rw, extra in [("control", control, 0, {}, set())] + files + \
                [("control", control, 0, {}, set())]:
            if name != "control":
                errs = gate.check(base, open(path, "rb").read(), [(LOC[0], LOC[1], D)], extra_cells=extra)
                if errs:
                    print(f"STOP: {name} fails the gate: {errs}")
                    return 1
            bench.cmd("I")
            rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
            if rc:
                print(f"STOP: load of {name} failed (exit {rc})")
                return 1
            bench.cmd("A")
            wrong = []
            for ds in hwtest.COMBOS4:
                got, seen = bench.read(ds)
                if seen != "".join(map(str, ds)):
                    bench.cmd("I")
                    print(f"STOP: D1..D4 read back {seen}, drove {ds}")
                    return 1
                want = 0 if name == "control" else expected(mask, dst, rw, ds)
                if (got == "h") != bool(want):
                    wrong.append("".join(map(str, ds)))
            bench.cmd("I")
            if name == "control":
                if wrong:
                    print("STOP: all-zero control did not hold D5 low")
                    return 1
                print("  control lo_quartus_0000.rbf: D5 low, ok")
                continue
            ok += not wrong
            fail += bool(wrong)
            log.write(json.dumps(dict(file=name, mask=mask, rewires=rw, wrong=wrong)) + "\n")
            print(f"  {name:22s} " + ("PASS" if not wrong else f"FAIL at {wrong}"), flush=True)
    print(f"\n{ok}/{ok + fail} files correct. Log: {log_path}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
