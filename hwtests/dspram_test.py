#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Silicon tests of the offline mode-bit candidates (user-approved 2026-11-23): multiplier registers
and 9x9 mode (dsp.json mode_candidates), M9K RAM mode (m9k_mode.json ram_mode_candidates).

  D  macm:18:18 at X18Y10 (36-bit shift register from D1^D3^D4 on D2 -> 18x18 multiplier -> D5 = parity
     of the product).  Patched from the unregistered Quartus build: output-register bits, input-register
     bits, both (each with the clock-into-block bits): predicted 1, 1 and 2 clocks of delay.  The 9x9 bit
     is exploratory (several hypotheses for how the halves split).
  R  rr:X13_Y10:ram (single-port RAM, wren = D4, data = D3) with random initial contents; patched: the
     3 RAM-mode candidate bits set to their ROM values.  Predicted: writes take effect in the base and
     are ignored in the patched file.

Same rules as the other board tests: SRAM loads, vidorlo pins, gate.py with exactly the patched cells,
predictions written before loading, all-zero control before and after.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import gate  # noqa: E402
import hwtest  # noqa: E402
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import m9kpatch  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
DIR = os.path.join(OUT, "dspram")
par = lambda v: bin(v).count("1") & 1


def apply(base, want):
    buf = bytearray(base)
    v = lutpatch.header_sum(base)
    ch = []
    for (f, p, b), val in want.items():
        off = 32 + f * 255 + p
        if (buf[off] >> b & 1) != val:
            buf[off] ^= 1 << b
            v += lutpos.header_weight(f, p, b) * (1 if val else -1)
            ch.append((f, p, b))
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    return bytes(buf), ch


def dsp_sim(seq, inreg, outreg, mode="18x18"):
    sh, xr, yr, pr, out = 0, 0, 0, 0, []
    mask = (1 << 36) - 1

    def prod(x, y):
        if mode == "18x18":
            return x * y
        lo = (x & 511) * (y & 511)
        hi = (x >> 9) * (y >> 9)
        return {"split": lo | (hi << 18), "lo_only": lo, "hi_only": hi << 18, "split_swapped": hi | (lo << 18)}[mode]
    for bit in seq:
        x, y = (xr, yr) if inreg else (sh & 0x3FFFF, sh >> 18)
        p = prod(x, y)
        npr, nxr, nyr = p, sh & 0x3FFFF, sh >> 18
        sh = ((sh << 1) | bit) & mask
        if outreg:
            pr = npr
        if inreg:
            xr, yr = nxr, nyr
        x, y = (xr, yr) if inreg else (sh & 0x3FFFF, sh >> 18)
        out.append(par(pr if outreg else prod(x, y)))
    return out


def build():
    files = []
    d = json.load(open(os.path.join(HERE, "data", "dsp.json")))["mode_candidates"]
    lo, pl = lutpos.ROW[10]
    cell = lambda c: (940 + c[0], lo + c[1], pl + c[2])
    bn = "c10_016__macm181800nonenone_X18Y10N2__vidorlo"
    base = xdev.load(OUT, bn)
    rnd = random.Random(55)
    seq = [rnd.randrange(2) for _ in range(80)]
    clk = d["any_register_clocked (clock into the block)"]
    files.append(("D_base", os.path.join(OUT, bn + ".rbf"), base, [], dict(kind="D", seq=seq, pred={"none": dsp_sim(seq, 0, 0)})))
    for label, cand, ir, orr in (("D_outreg", d["output_registers"], 0, 1), ("D_inreg", d["input_registers"], 1, 0),
                                 ("D_both", d["input_registers"] + d["output_registers"], 1, 1)):
        data, ch = apply(base, {cell(c): c[3] for c in clk + cand})
        files.append((label, data, base, ch, dict(kind="D", seq=seq, pred={f"in{ir}out{orr}": dsp_sim(seq, ir, orr)})))
    data, ch = apply(base, {cell(c): c[3] for c in d["mode_9x9"]})
    files.append(("D_9x9", data, base, ch, dict(kind="D", seq=seq, pred={m: dsp_sim(seq, 0, 0, m) for m in
                                                                         ("18x18", "split", "lo_only", "hi_only", "split_swapped")})))
    # M9K: RAM base with random initial contents, then the 3 mode bits set to their ROM values
    site = "X13_Y10"
    bn = xdev.Job("c10_016", f"rr:{site}:ram", (0, 0, 0), "vidorlo").name
    init = [w & 1 for w in xdev.rom_words("r23")]
    ram, rom_cells = m9kpatch.write(site, init, (9, 512), bn, 1)
    m = json.load(open(os.path.join(HERE, "data", "m9k_mode.json")))["ram_mode_candidates"]["bits"]
    lo, pl = lutpos.ROW[10]
    F = m9kpatch.F[13]
    data, ch = apply(ram, {(F + c[0], lo + c[1], pl + c[2]): 1 - c[3] for c in m})
    rawbase = xdev.load(OUT, bn)
    newbits = [w >> 3 & 1 for w in xdev.rom_words("r24")]
    files.append(("R_ram", ram, rawbase, rom_cells, dict(kind="R", init=init, new=newbits, writes=True)))
    files.append(("R_mode_bits_rom", data, rawbase, rom_cells + ch, dict(kind="R", init=init, new=newbits, writes=False)))
    return files


def main() -> int:
    os.makedirs(DIR, exist_ok=True)
    runs = []
    for label, data, base, cells, info in build():
        if isinstance(data, str):
            path = data
        else:
            errs = gate.check(base, data, [], extra_cells=cells)
            if errs:
                raise SystemExit(f"{label}: gate refused {errs}")
            path = os.path.join(DIR, f"lo_{label}.rbf")
            open(path, "wb").write(data)
        runs.append((label, path, info))
    pp = os.path.join(OUT, time.strftime("dspram_predictions_%Y%m%d_%H%M%S.json"))
    json.dump({l: i for l, _, i in runs}, open(pp, "w"))
    print(f"{len(runs)} files gate-checked; predictions: {pp}")
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

    log = []
    control_ok()
    for label, path, info in runs:
        load(path)
        if info["kind"] == "D":
            got = []
            for bit in info["seq"]:
                read(bit, 0, 0, 0)
                got.append(read(bit, 1, 0, 0))
                read(bit, 0, 0, 0)
            fits = [h for h, p in info["pred"].items() if p == got]
            mism = {h: sum(a != b for a, b in zip(p, got)) for h, p in info["pred"].items()}
            ok = len(fits) == 1
            msg = f"{len(got)} clocks; fits {fits or 'none'}; mismatches {mism}"
            res = dict(fits=fits, mismatches=mism)
        else:
            mem, a, wrongs = list(info["init"]), 0, {}
            read(1, 0, 0, 0)
            for name, we in (("read", 0), ("write", 1), ("readback", 0)):
                wrong = 0
                for _ in range(512):
                    c = info["new"][a] if we else 0
                    read(1, 0, c, we)
                    want = mem[a]
                    if we and info["writes"]:
                        mem[a] = c
                    a = (a + 1) % 512
                    wrong += read(1, 1, c, we) != want
                    read(1, 0, c, we)
                wrongs[name] = wrong
            ok = all(v == 0 for v in wrongs.values())
            msg = f"3 passes x 512 words, wrong {wrongs} (writes {'expected' if info['writes'] else 'expected to be ignored'})"
            res = dict(wrong=wrongs)
        bench.cmd("I")
        log.append(dict(file=label, ok=ok, result=res))
        print(f"  {label:16s}: {msg} -> {'PASS' if ok else 'FAIL'}", flush=True)
    control_ok()
    lp = os.path.join(OUT, time.strftime("dspram_%Y%m%d_%H%M%S.json"))
    json.dump(log, open(lp, "w"), indent=1)
    print(f"\n{sum(e['ok'] for e in log)}/{len(log)} files as predicted. Log: {lp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
