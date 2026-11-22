#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""EP4CE6: does the dont_touch design + one 0x008A probe replace the repo's canon tables?

Uses the repo's own CE6 cell addresses (fuzz/bitstream.py LutCodec.from_cram_model,
with sigma set to the physical order) and our ce6 builds at the repo's 14 D1++
positions (pins ax301, dont_touch on).  For each position: bits outside the LUT
vs mask 0000, whether one input order explains every mask, and whether the
probe's order predicts 4444/DEAD/6996 exactly (data bits; then byte for byte
with the CE6 header rule and frame CRCs).

  ce6probe.py [--repo ../Cyclone_CRAM_Mapper]
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpatch  # noqa: E402
import rbfgeom  # noqa: E402

POS = [(10, 14, 0), (10, 2, 0), (10, 8, 0), (16, 14, 0), (16, 21, 0), (16, 2, 0), (16, 8, 0),
       (22, 14, 0), (22, 21, 0), (22, 2, 0), (22, 8, 0), (28, 14, 0), (28, 17, 0), (28, 8, 0)]
PERMS = list(itertools.permutations(range(4)))
S = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 0}      # CE6 header-sum rule (README)


def permute(i, p):
    return sum((i >> k & 1) << p[k] for k in range(4))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "fuzz"))
    import bitstream
    bitstream._sigma_inv_lookup = lambda *x, **k: (0, 1, 2, 3)

    def ok(o):
        return not (5282 <= o < 367952 and (o - 32) % 210 >= 208) and o >= 0x4B

    def diff(A, B):
        return {(i, b) for i in range(len(A)) if A[i] != B[i] and ok(i)
                for b in range(8) if (A[i] ^ B[i]) >> b & 1}

    def load(m, p):
        with open(os.path.join(HERE, "out", f"ce6__lut{m}_X{p[0]}Y{p[1]}N{p[2]}__ax301.rbf"), "rb") as f:
            return f.read()

    totals = dict(outside=0, oneorder=0, data=0, byte=0, n=0)
    for p in POS:
        phys = bitstream.LutCodec.from_cram_model(*p).patterns     # physical minterm -> {(off, bit)}
        cell = {i: next(iter(c)) for i, c in phys.items()}
        lut = set(cell.values())
        Z = load("0000", p)
        on = lambda B: diff(Z, B) & lut
        probe = on(load("008A", p))
        po = [q for q in PERMS if {cell[permute(i, q)] for i in (1, 3, 7)} == probe]
        outside = 0
        common = set(PERMS)
        data_ok = byte_ok = 0
        for m in ("008A", "4444", "DEAD", "6996"):
            B = load(m, p)
            d = diff(Z, B)
            outside += len(d - lut)
            mm = int(m, 16)
            common &= {q for q in PERMS if {cell[permute(i, q)] for i in range(16) if mm >> i & 1} == d & lut}
            if m == "008A" or len(po) != 1:
                continue
            # Write mask m from the 0000 build using the probe's order, then compare.
            buf = bytearray(Z)
            v = lutpatch.header_sum(Z)
            for i in range(16):
                if mm >> i & 1:
                    off, b = cell[permute(i, po[0])]
                    buf[off] ^= 1 << b
                    f, pos = divmod(off - 32, 210)
                    v += 1 << ((pos + S[b] - f) % 8)
            g = rbfgeom.infer(Z)
            lutpatch.patch_crc(buf, g)
            data_ok += diff(bytes(buf), B) == set()
            lutpatch.set_header_sum(buf, v % (1 << 32))
            byte_ok += bytes(buf) == B
        totals["outside"] += outside == 0
        totals["oneorder"] += bool(common)
        totals["data"] += data_ok == 3
        totals["byte"] += byte_ok == 3
        totals["n"] += 1
        print(f"  X{p[0]}Y{p[1]}N{p[2]}: bits outside the LUT {outside}, one order for all masks "
              f"{bool(common)}, probe order {po[0] if len(po) == 1 else po}, "
              f"4444/DEAD/6996 data-identical {data_ok}/3, byte-identical {byte_ok}/3")
    n = totals["n"]
    print(f"\n{totals['outside']}/{n} positions: 0 bits outside the LUT; {totals['oneorder']}/{n}: one "
          f"input order for all masks; {totals['data']}/{n}: probe predicts all 3 masks' data bits; "
          f"{totals['byte']}/{n}: byte-identical incl. header")
    return 0


if __name__ == "__main__":
    sys.exit(main())
