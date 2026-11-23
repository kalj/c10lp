#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Combined patch demo: one Quartus-placed design, four kinds of change without Quartus, one file.

Design demo:X13_Y15 (xdev.py): a 9x512 ROM at M9K X13_Y15 (q[0] read, zero init) stepped by D2 with
enable D4; a PLL from the Vidor's 48 MHz clock (PIN_E2) driving a 26-bit counter; one pinned LUT
mx at X10Y10N0 = D3 ? cnt[25] : q[0] (D1 connected, unused).

The patched file changes, on top of the Quartus build:
  1. ROM contents: random bit-0 words (m9kpatch.py),
  2. LUT mx: D3 ? cnt[25] : q[0] ^ D1 (lutpos.py cells, input order read from the base),
  3. PLL C0: 12 -> 24, so the counter runs at 24 MHz instead of 48 (periph.py),
  4. D4 (PIN_T3): bus hold instead of pull-up (periph.py).
It is gate-checked with exactly those cells, then the Quartus base and the patched file are run
on the board with predictions written first.

  demo_patch.py [--offline]
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
import newclass_test  # noqa: E402
import periph  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
SITE = "X13_Y15"
LOC = (10, 10, 0)
BASE = xdev.Job("c10_016", f"demo:{SITE}", LOC, "vidorlo").name
SEL = sum(((i >> 1 & 1) if i >> 2 & 1 else (i & 1)) << i for i in range(16))                  # c ? b : a
NEW = sum(((i >> 1 & 1) if i >> 2 & 1 else ((i & 1) ^ (i >> 3 & 1))) << i for i in range(16))  # c ? b : a ^ d
STEPS = 64


def build() -> tuple[bytes, bytes, list[int]]:
    base = xdev.load(OUT, BASE)
    if base is None:
        raise SystemExit(f"build {BASE} first")
    rnd = random.Random(2026)
    words = [rnd.randrange(2) for _ in range(512)]
    # 1. ROM contents
    data, rom_cells = m9kpatch.write(SITE, words, (9, 512), BASE, 1)
    # 2. LUT: find the physical input order from the base mask (d = the input SEL ignores)
    cells = lutpos._predict_phys(*LOC)
    stored = sum((base[32 + f * 255 + p] >> b & 1) << i for i, (f, p, b) in enumerate(cells))
    perms = [pm for pm in lutpos.PERMS if sum((SEL >> i & 1) << lutpos.permute(i, pm) for i in range(16)) == stored]
    if not perms:
        raise SystemExit("base LUT does not hold the expected mask")
    want = {sum((NEW >> i & 1) << lutpos.permute(i, pm) for i in range(16)) for pm in perms}
    if len(want) != 1:
        raise SystemExit(f"input order ambiguous for the new mask ({len(perms)} orders)")
    want = want.pop()
    buf = bytearray(data)
    v = lutpatch.header_sum(data)
    for i, (f, p, b) in enumerate(cells):
        off = 32 + f * 255 + p
        if (buf[off] >> b & 1) != (want >> i & 1):
            buf[off] ^= 1 << b
            v += lutpos.header_weight(f, p, b) * (1 if buf[off] >> b & 1 else -1)
    lutpatch.patch_crc(buf, rbfgeom.infer(base))
    lutpatch.set_header_sum(buf, v % (1 << 32))
    # 3 + 4. periphery: PLL C0 and bus hold on D4
    pch = newclass_test.pll_changes(bytes(buf), {"C0": 24}) + periph.setting("PIN_T3", "bushold", 1)
    data = periph.apply(bytes(buf), pch)
    errs = gate.check(base, data, [LOC], extra_cells=rom_cells, periph_bits=[c[:3] for c in pch])
    if errs:
        raise SystemExit(f"gate refused: {errs}")
    print(f"patched file: {len(rom_cells)} ROM cells, LUT {SEL:04X} -> {NEW:04X} ({len(perms)} input orders agree), "
          f"{len(pch)} periphery bits (PLL C0 = 24, D4 bus hold); gate PASS")
    return base, data, words


def predictions(words, patched):
    seq = []
    for k in range(STEPS):
        q = words[k] if patched else 0
        seq.append({"A0": q, "A1": q ^ 1 if patched else q})
    return dict(rom=seq, pll_mhz=24.0 if patched else 48.0, d4_released_low=0 if patched else 1)


def main() -> int:
    base, data, words = build()
    path = os.path.join(OUT, "demo", "lo_demo_patched.rbf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    runs = [("quartus base", os.path.join(OUT, BASE + ".rbf"), predictions(words, False)),
            ("patched", path, predictions(words, True))]
    pp = os.path.join(OUT, time.strftime("demo_predictions_%Y%m%d_%H%M%S.json"))
    json.dump({name: pred for name, _, pred in runs}, open(pp, "w"))
    print("predictions written:", pp)
    if "--offline" in sys.argv:
        return 0

    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")

    def load(p):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", p], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
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

    results, ok_all = {}, True
    control_ok()
    for name, p, pred in runs:
        load(p)
        rom_wrong = 0
        read(0, 0, 0, 1)
        for k in range(STEPS):
            read(0, 1, 0, 1)                       # rising edge: q = mem[a], a += 1
            rom_wrong += read(0, 1, 0, 1) != pred["rom"][k]["A0"]
            rom_wrong += read(1, 1, 0, 1) != pred["rom"][k]["A1"]
            read(0, 0, 0, 1)
        read(0, 0, 1, 1)                           # D3 = 1: D5 = cnt[25]
        t0, prev, edges = time.time(), None, []
        while time.time() - t0 < 12.0:
            v = int(bench.cmd("R")[3])
            if prev is not None and v != prev:
                edges.append(time.time())
            prev = v
        mhz = 2 ** 25 / ((edges[-1] - edges[0]) / (len(edges) - 1)) / 1e6 if len(edges) >= 3 else None
        bench.read((1, 0, 0, 0))                   # D4 driven low, then released
        bench.cmd("I")
        time.sleep(0.01)
        d4 = int(bench.cmd("R").split("=")[2][3])
        ok = (rom_wrong == 0 and mhz is not None and abs(mhz - pred["pll_mhz"]) / pred["pll_mhz"] < 0.05
              and d4 == pred["d4_released_low"])
        ok_all &= ok
        results[name] = dict(rom_wrong=rom_wrong, rom_readings=2 * STEPS, pll_mhz=mhz, d4_released_low=d4, ok=ok)
        print(f"  {name:13s}: ROM/LUT {2 * STEPS - rom_wrong}/{2 * STEPS} readings as predicted; PLL "
              f"{('%.2f' % mhz) if mhz else 'n/a'} MHz (predicted {pred['pll_mhz']}); D4 released low reads {d4} "
              f"(predicted {pred['d4_released_low']}) -> {'PASS' if ok else 'FAIL'}", flush=True)
        if not ok:
            print("STOP: first wrong result")
            break
    control_ok()
    lp = os.path.join(OUT, time.strftime("demo_%Y%m%d_%H%M%S.json"))
    json.dump(results, open(lp, "w"), indent=1)
    print(f"\n{'both runs as predicted' if ok_all else 'FAILED'}. Log: {lp}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
