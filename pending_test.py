#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon tests of the last offline classes (user-approved 2026-11-23: "Do the rest of the pending
board tests").  Same rules as the other board tests: SRAM loads, vidorlo pins, gate.py with exactly
the patched cells, all-zero control before and after, predictions written before loading, stop at
the first failed load or readback mismatch.

  N  neighbour link (xr2:4:18:16:0): dst in X11Y10 reads source slot 4 of X10Y10 over the direct
     link; patched to read slot 18 instead: dst select code, dst LUT input, slot 18's general-output
     select and its two link driver bits (li_neighbour.json), all values Quartus itself uses for
     slot 18 (xr2:...:1).  Predicted D5: base = ~sa ^ sb ^ A, patched = ~A.
  G  row clock select (gsel:5:7): counters on PLL c0 = 48 MHz (row 5) and c1 = 24 MHz (row 7); copy
     row 5's 4-bit row select (gclk.json) into row 7.  Predicted: row 7's counter at 48 MHz.
  M  M9K width code (rom2:9x512 at X13_Y10, random contents): x18 code -> x9 code (m9k_mode.json).
     Exploratory: hypotheses for how the 9-bit address maps to the x9 word are compared.

  pending_test.py [--offline]
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import m9kpatch  # noqa: E402
import mux1cmap  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "pending")
NL = json.load(open(os.path.join(HERE, "li_neighbour.json")))


def apply(base: bytes, want: dict) -> tuple[bytes, list]:
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    changed = []
    for (f, p, b), val in want.items():
        off = 32 + f * 255 + p
        if (buf[off] >> b & 1) != val:
            buf[off] ^= 1 << b
            v += lutpos.header_weight(f, p, b) * (1 if val else -1)
            changed.append((f, p, b))
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    return bytes(buf), changed


def neighbour():
    X, Y, NA, NB, ND = 10, 10, 4, 18, 16
    bn = f"c10_016__xr2-{NA}-{NB}-{ND}-0_X{X}Y{Y}__vidorlo"
    base = xdev.load(OUT, bn)
    c = lutpos._predict_phys(X + 1, Y, ND)
    f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
    fl = (ND // 2) % 2
    rc = lambda df, col: (f0 + df, lo + (col - 2 if fl else col), bit)
    old, new = set(map(tuple, NL["links"]["+1"][str(NA)])), set(map(tuple, NL["links"]["+1"][str(NB)]))
    assert frozenset(mux1cmap.region(base, X + 1, Y, ND)) == old
    want = {rc(*k): 0 for k in old - new}
    want.update({rc(*k): 1 for k in new - old})
    pin = NL["dst_input_plus1"][str(NB)]
    m = sum(1 << i for i in range(16) if not (i >> pin & 1))
    want.update({cc: m >> i & 1 for i, cc in enumerate(c)})
    s = lutpos._predict_phys(X, Y, NB)
    sf0, slo, sbit = min(v[0] for v in s), min(v[1] for v in s), s[0][2]
    F0 = min(v[0] for v in lutpos._predict_phys(X, Y, 0))
    want[(sf0 + 8, slo + NL["src_output_byte"]["+1"][str(NB)], sbit)] = 1
    for df, db in NL["src_driver_bits"]["+1"][str(NB)]:
        want[(F0 + df, slo + db, sbit)] = 1
    data, changed = apply(base, want)
    ref = xdev.load(OUT, f"c10_016__xr2-{NA}-{NB}-{ND}-1_X{X}Y{Y}__vidorlo")
    assert all((ref[32 + f * 255 + p] >> b & 1) == v for (f, p, b), v in want.items()), "differs from Quartus's slot-18 values"
    sa = lambda a, b, c_, d: (a ^ b ^ c_ ^ d) ^ 1            # 6996: index i = a + 2b + 4c + 8d -> xnor-ish parity
    m6996, m8E71 = 0x6996, 0x8E71
    f = lambda mask, a, b, c_, d: mask >> (a + 2 * b + 4 * c_ + 8 * d) & 1
    pred_base = {k: (1 - f(m6996, *k)) ^ (f(m8E71, *k) ^ k[0]) for k in hwtest.COMBOS4}
    pred_new = {k: 1 - k[0] for k in hwtest.COMBOS4}
    return [("N_base", os.path.join(OUT, bn + ".rbf"), pred_base, base, None),
            ("N_slot18", data, pred_new, base, changed)]


def clocksel():
    bn = "c10_016__gsel57_X0Y0N0__vidorlo"
    base = xdev.load(OUT, bn)

    def cells(y):
        lo, pl = lutpos.ROW[y]
        out = []
        for o in (0, 5, 6, 8):
            bb, pp = lo - 62 + o, pl
            if bb < 1:
                pp += 1
                bb += 251 if pp >= 5 else 252
            out.append((488, bb, pp))
        return out
    want = {c7: base[32 + c5[0] * 255 + c5[1]] >> c5[2] & 1 for c5, c7 in zip(cells(5), cells(7))}
    data, changed = apply(base, want)
    return [("G_base", os.path.join(OUT, bn + ".rbf"), {"c0": 48.0, "c1": 24.0}, base, None),
            ("G_row7_on_c0", data, {"c0": 48.0, "c1": 48.0}, base, changed)]


def m9k():
    site, bn = "X13_Y10", "c10_016__rom2-9x512-X13_Y10-zero__vidorlo"
    rnd = random.Random(99)
    words = [rnd.randrange(512) for _ in range(512)]
    data, rom_cells = m9kpatch.write(site, words, (9, 512), bn, 9)
    mode = json.load(open(os.path.join(HERE, "m9k_mode.json")))["width_code"]
    lo, pl = lutpos.ROW[10]
    F = m9kpatch.F[13]
    cc = lambda c: (F + c[0], lo + c[1], pl + c[2])
    patched, code_cells = apply(data, {cc(mode["x18 (18x512, 9x512)"]): 0, cc(mode["x9 (9x1024)"]): 1})

    def word9(buf, w):     # read the x9 word w back from the cells (layout 9x1024)
        return sum((buf[32 + f * 255 + p] >> b & 1) << k for k in range(9) for f, p, b in [m9kpatch.cell(site, w, k, (9, 1024))])
    hyps = {"w=2a": lambda a: 2 * a, "w=2a+1": lambda a: 2 * a + 1, "w=a": lambda a: a, "w=a+512": lambda a: a + 512}
    par = lambda v: bin(v).count("1") & 1
    pred_base = [par(words[a]) for a in range(64)]
    pred_new = {h: [par(word9(patched, fn(a))) for a in range(64)] for h, fn in hyps.items()}
    base = xdev.load(OUT, bn)
    return [("M_contents_x18", data, {"x18": pred_base}, base, rom_cells),
            ("M_x9_code", patched, pred_new, base, rom_cells + code_cells)]


def main() -> int:
    os.makedirs(DIR, exist_ok=True)
    runs = []
    for label, data, pred, base, cells in neighbour() + clocksel() + m9k():
        if isinstance(data, str):
            path = data
        else:
            errs = gate.check(base, data, [], extra_cells=cells)
            if errs:
                raise SystemExit(f"{label}: gate refused {errs}")
            path = os.path.join(DIR, f"lo_{label}.rbf")
            open(path, "wb").write(data)
        runs.append((label, path, pred))
    pp = os.path.join(OUT, time.strftime("pending_predictions_%Y%m%d_%H%M%S.json"))
    json.dump({label: {str(k): v for k, v in pred.items()} for label, _, pred in runs}, open(pp, "w"))
    print(f"{len(runs)} files (patched ones gate-checked); predictions written: {pp}")
    if "--offline" in sys.argv:
        return 0

    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc}) for {p}")
        bench.cmd("A")

    def read(A, B, C, D):
        got, seen = bench.read((A, B, C, D))
        if seen != f"{A}{B}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")

    def control_ok():
        load(os.path.join(OUT, "lo_quartus_0000.rbf"))
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    def measure(sel):
        read(0, 0, sel, 0)
        t0, prev, edges = time.time(), None, []
        while time.time() - t0 < 10.0:
            v = int(bench.cmd("R")[3])
            if prev is not None and v != prev:
                edges.append(time.time())
            prev = v
        return 2 ** 25 / ((edges[-1] - edges[0]) / (len(edges) - 1)) / 1e6 if len(edges) >= 3 else 0.0

    log, ok_all = [], True
    control_ok()
    for label, path, pred in runs:
        load(path)
        if label.startswith("N"):
            got = {k: read(*k) for k in hwtest.COMBOS4}
            wrong = sum(got[k] != pred[k] for k in got)
            ok = wrong == 0
            msg = f"16 input combinations, {wrong} wrong"
            res = dict(wrong=wrong)
        elif label.startswith("G"):
            f0, f1 = measure(0), measure(1)
            ok = abs(f0 - pred["c0"]) / pred["c0"] < 0.05 and abs(f1 - pred["c1"]) / pred["c1"] < 0.05
            msg = f"row 5 counter {f0:.2f} MHz (pred {pred['c0']}), row 7 counter {f1:.2f} MHz (pred {pred['c1']})"
            res = dict(row5_mhz=f0, row7_mhz=f1)
        else:
            seq = []
            read(0, 0, 0, 0)
            for _ in range(64):
                read(1, 0, 0, 0)
                read(1, 1, 0, 0)                   # edge: q = mem[a], a += 1
                seq.append(read(1, 1, 0, 0))
                read(1, 0, 0, 0)
            fits = [h for h, p in pred.items() if p == seq]
            ok = len(fits) == 1
            msg = f"64 words; fits {fits or 'no hypothesis'} (mismatches: " + \
                  ", ".join(f"{h} {sum(a != b for a, b in zip(p, seq))}" for h, p in pred.items()) + ")"
            res = dict(fits=fits, seq=seq)
        bench.cmd("I")
        ok_all &= ok
        log.append(dict(file=label, ok=ok, result=res))
        print(f"  {label:16s}: {msg} -> {'PASS' if ok else 'FAIL'}", flush=True)
        if not ok and not label.startswith("M_x9"):
            print("STOP: first wrong result")
            break
    control_ok()
    lp = os.path.join(OUT, time.strftime("pending_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"\n{sum(e['ok'] for e in log)}/{len(log)} files as predicted. Log: {lp}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
