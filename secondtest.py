#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Careful silicon tests of the second path (an LE output reaching a non-direct LUT input).

Part A (no new drivers): in a Quartus mux4 base where source s is already used through its
second path (s's driver is on), rewire another non-direct input p to s by rewriting only dst's
select bits (table code for (p, s)).  Prediction: works.

Part B (source-side enable): in a base where s is used only directly, set s's second-path
signature bits (li_second_path.json) and dst's (p, s) code.  Only when all signature bits are
clear in the base and no LE in the LAB has its frame +8 output-select bit set.  One file at a
time; stops at the first wrong reading.

  secondtest.py plan A|B      list candidates and predictions (writes second_predictions_<part>.json)
  secondtest.py board A|B     run them
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
import rewire as R  # noqa: E402
import xdev  # noqa: E402

DIRECT = {int(k): set(v) for k, v in json.load(open(os.path.join(HERE, "li_direct.json"))).items()}
SIG = {int(k): [tuple(v) for v in vs]
       for k, vs in json.load(open(os.path.join(HERE, "li_second_path.json")))["entries"].items()}
# Per (reading input, source) signatures: the line depends on which input reads it.
PSIG = {tuple(map(int, k.split(","))): [tuple(v) for v in vs]
        for k, vs in json.load(open(os.path.join(HERE, "li_second_path_pairs.json")))["entries"].items()}


def sig_cells(s: int, rel=None) -> list[tuple[int, int, int]]:
    """Absolute (frame, byte, bit) cells of a second-path signature of source slot s."""
    rel = SIG[s] if rel is None else rel
    x, y = R.LOC[:2]
    f0 = min(f for f, _, _ in lutpos._predict_phys(x, y, 0))
    cells = lutpos._predict_phys(x, y, s)
    lo, b, fl = min(p for _, p, _ in cells), cells[0][2], (s // 2) % 2
    return [(f0 + df, lo + (col - 2 if fl else col), b) for df, col in rel]


def any_output_select(base: bytes) -> list[int]:
    """LE slots with any known frame +8 second-path output-select bit set (any slot, any pair)."""
    on = set()
    for (q, s), rel in PSIG.items():
        for (f, p, b), (df, col) in zip(sig_cells(s, rel), rel):
            if df == 8 and base[32 + f * 255 + p] >> b & 1:
                on.add(s)
    return sorted(on)


def candidates(part: str, st: str):
    R.SRCS = [int(v) for v in st.split("-")]
    base = xdev.load(R.OUT, R.base_name())
    dst = R.Dst(base)
    cur = {dst.perm[i]: R.SRCS[i] for i in range(4)}
    if dst.region(base) != R.predict(cur):
        return base, dst, []
    res = []
    for i in range(4):
        p = dst.perm[i]
        for s in R.SRCS:
            if s == cur[p] or p in DIRECT[s] or (p, s) not in R.ENTRIES or (p, cur[p]) not in R.ENTRIES:
                continue
            via2 = any(q not in DIRECT[s] for q, v in cur.items() if v == s)   # s already on 2nd path
            if part == "A" and via2:
                res.append((i, p, s, []))
            if part == "B" and not via2 and (p, s) in PSIG:
                sc = sig_cells(s, PSIG[(p, s)])
                if any(base[32 + f * 255 + pp] >> b & 1 for f, pp, b in sc) or any_output_select(base):
                    continue
                res.append((i, p, s, sc))
    return base, dst, res


def build(base, dst, i, p, s, sc):
    pass_i = sum(((m >> i) & 1) << m for m in range(16))
    new, extra = R.make(base, dst, pass_i, {p: s})
    if sc:
        buf = bytearray(new)
        v = [lutpatch.header_sum(new)]
        for c in sc:
            R.flip_bit(buf, c, v)
            extra.add(c)
        lutpatch.patch_crc(buf, rbfgeom.infer(base))
        lutpatch.set_header_sum(buf, v[0] % (1 << 32))
        new = bytes(buf)
    les = [(R.LOC[0], R.LOC[1], R.D)]
    errs = gate.check(base, new, les, extra_cells=extra)
    if errs:
        raise SystemExit(f"gate refused: {errs}")
    return new, extra, pass_i


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "board"])
    ap.add_argument("part", choices=["A", "B"])
    a = ap.parse_args()
    bases = json.load(open(os.path.join(R.OUT, "second_bases.json")))
    if a.part == "B":
        bases = ["0-4-8-12", "2-10-18-24", "0-6-20-28", "2-6-18-30", "12-14-20-28", "0-10-18-24",
                 "14-20-22-26", "2-4-18-30", "12-18-26-28", "0-4-22-24", "2-12-22-30", "2-8-22-24"]
    pred_path = os.path.join(HERE, f"second_predictions_{a.part}.json")
    if a.cmd == "plan":
        preds = {}
        for st in bases:
            base, dst, cs = candidates(a.part, st)
            for i, p, s, sc in cs:
                preds[f"{st}:in{p}_to_src{s}"] = True
                print(f"  {st}: input {p} -> source {s}" + (f"  + {len(sc)} source-side bits" if sc else ""))
        json.dump(preds, open(pred_path, "w"), indent=1)
        print(f"{len(preds)} candidates, all predicted to work -> {pred_path}")
        return 0

    preds = json.load(open(pred_path))
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    control = os.path.join(R.OUT, "lo_quartus_0000.rbf")
    log_path = os.path.join(R.OUT, time.strftime(f"second_{a.part}_%Y%m%d_%H%M%S.jsonl"))
    os.makedirs(os.path.join(R.OUT, "second"), exist_ok=True)

    def load(path):
        bench.cmd("I")
        rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", path], False)
        if rc:
            raise SystemExit(f"STOP: load failed (exit {rc})")
        bench.cmd("A")

    def control_ok():
        load(control)
        if any(bench.read(ds)[0] == "h" for ds in hwtest.COMBOS4):
            raise SystemExit("STOP: all-zero control did not hold D5 low")
        bench.cmd("I")
        print("  control: D5 low, ok", flush=True)

    hit = n = 0
    with open(log_path, "w") as log:
        for key in preds:
            st, rest = key.split(":")
            p, s = (int(v) for v in rest[2:].replace("_to_src", " ").split())
            base, dst, cs = candidates(a.part, st)
            match = [c for c in cs if c[1] == p and c[2] == s]
            if not match:
                print(f"STOP: {key} no longer a candidate")
                return 1
            i, p, s, sc = match[0]
            new, extra, mask = build(base, dst, i, p, s, sc)
            path = os.path.join(R.OUT, "second", f"lo_{a.part}_{st}_in{p}_src{s}.rbf")
            open(path, "wb").write(new)
            control_ok()
            load(path)
            wrong = []
            for ds in hwtest.COMBOS4:
                got, seen = bench.read(ds)
                if seen != "".join(map(str, ds)):
                    bench.cmd("I")
                    raise SystemExit(f"STOP: D1..D4 read back {seen}, drove {ds}")
                if (got == "h") != bool(R.expected(mask, dst, {p: s}, ds)):
                    wrong.append("".join(map(str, ds)))
            bench.cmd("I")
            n += 1
            hit += not wrong
            log.write(json.dumps(dict(key=key, wrong=wrong, src_bits=len(sc))) + "\n")
            log.flush()
            print(f"  {key}: " + ("PASS" if not wrong else f"FAIL {wrong}"), flush=True)
            if wrong and a.part == "B":
                print("STOP: first wrong reading in part B")
                break
        control_ok()
    print(f"\npart {a.part}: {hit}/{n} as predicted. Log: {log_path}")
    return 0 if hit == n else 1


if __name__ == "__main__":
    sys.exit(main())
