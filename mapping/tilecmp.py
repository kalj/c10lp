#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is the LAB tile bit-identical on the EP4CE6 and 10CL016 dies?  (intra-LAB routing)

Design lab2 (xdev.py): src LUT at slot ns (inputs from pins) drives all four
inputs of dst LUT at slot nd, in the same LAB.  Experiment A moves ns (nd = 16),
B moves nd (ns = 0), at 4 LABs per die.

Bits are put in LAB-relative coordinates: (frame - f0, byte - lo0) in the bit
plane of the LAB's slot-0 LUT, where f0/lo0 are that LUT's first frame and low
byte (repo's LutCodec cell addresses on the EP4CE6, lutpos.py on the 10CL016).
For each moved slot we keep the bits that (1) change with that slot and (2) are
the same at all 4 LABs of a die, then compare the two dies' sets.

  tilecmp.py [--repo ../Cyclone_CRAM_Mapper]
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402

GEO = {"ce6": (210, 1752, 25), "c10_016": (255, 2003, 37)}   # frame bytes, frames, first CRC frame


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    ap.add_argument("--vertical", action="store_true",
                    help="inter-LAB: src 1..4 rows above/below dst (design lab2 with dy)")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "fuzz"))
    import bitstream
    bitstream._sigma_inv_lookup = lambda *x, **k: (0, 1, 2, 3)
    import lab2_plan

    def lut_cells(dev, x, y, n):
        if dev == "c10_016":
            return lutpos._predict_phys(x, y, n)
        fb = GEO["ce6"][0]
        cells = bitstream.LutCodec.from_cram_model(x, y, n).patterns
        return [((off - 32) // fb, (off - 32) % fb, b) for c in cells.values() for off, b in c]

    def rel_bits(dev, buf, x, y):
        fb, nf, _ = GEO[dev]
        lc = lut_cells(dev, x, y, 0)
        f0 = min(f for f, _, _ in lc)
        lo0 = min(p for _, p, _ in lc)
        bit = lc[0][2]
        res = set()
        for f in range(max(0, f0 - 40), min(nf, f0 + 41)):
            base = 32 + f * fb
            for p in range(max(0, lo0 - 80), min(fb - 2, lo0 + 21)):
                if buf[base + p] >> bit & 1:
                    res.add((f - f0, p - lo0))
        return res

    if a.vertical:
        import lab2v_plan
        return vertical(lab2v_plan, rel_bits)

    data = {}
    for j in lab2_plan.jobs():
        p = os.path.join(HERE, "out", j.name + ".rbf")
        if not os.path.exists(p):
            continue
        _, ns, nd = j.design.split(":")
        with open(p, "rb") as f:
            data[(j.dev, j.loc[:2], int(ns), int(nd))] = rel_bits(j.dev, f.read(), *j.loc[:2])

    for exp, key, moved in (("A (dst 16, src moves)", lambda ns, nd: nd == 16, 2),
                            ("B (src 0, dst moves)", lambda ns, nd: ns == 0, 3)):
        print(f"\n== Experiment {exp}")
        per_die = {}
        for dev, labs in lab2_plan.LABS.items():
            per_slot = {}
            for x, y in labs:
                rows = {k[moved]: v for k, v in data.items()
                        if k[0] == dev and k[1] == (x, y) and key(k[2], k[3])}
                if not rows:
                    continue
                common = set.intersection(*rows.values())     # bits that don't move with the slot
                for s, v in rows.items():
                    per_slot.setdefault(s, []).append(v - common)
            per_die[dev] = {s: set.intersection(*vs) for s, vs in per_slot.items() if len(vs) == len(labs)}
        slots = sorted(set(per_die["ce6"]) & set(per_die["c10_016"]))
        same = 0
        for s in slots:
            A, B = per_die["ce6"][s], per_die["c10_016"][s]
            j = len(A & B) / max(1, len(A | B))
            same += A == B
            print(f"  slot {s:2d}: EP4CE6 {len(A):3d} bits, 10CL016 {len(B):3d}, shared {len(A & B):3d}, "
                  f"Jaccard {j:.2f}" + ("  IDENTICAL" if A == B else
                                         f"  only-CE6 {sorted(A - B)[:4]} only-C10 {sorted(B - A)[:4]}"))
        print(f"  {same}/{len(slots)} slots identical across the two dies")
    return 0


def vertical(plan, rel_bits) -> int:
    """Compare dst-region and src-region bits per row offset dy across the two dies."""
    regions = {}
    for j in plan.jobs():
        p = os.path.join(HERE, "out", j.name + ".rbf")
        if not os.path.exists(p):
            continue
        x, y, dy = j.loc
        with open(p, "rb") as f:
            buf = f.read()
        regions[(j.dev, (x, y), dy)] = (rel_bits(j.dev, buf, x, y), rel_bits(j.dev, buf, x, y + dy))
    for name, idx in (("dst LAB region (bits that change with dy)", 0),
                      ("src LAB region (all bits, consistent over the 4 LABs)", 1)):
        print(f"\n== Vertical, {name}")
        per_die = {}
        for dev, labs in plan.LABS.items():
            per = {}
            for lab in labs:
                rows = {dy: regions[(dev, lab, dy)][idx] for dy in plan.DYS if (dev, lab, dy) in regions}
                if len(rows) != len(plan.DYS):
                    continue
                common = set.intersection(*rows.values()) if idx == 0 else set()
                for dy, v in rows.items():
                    per.setdefault(dy, []).append(v - common)
            per_die[dev] = {dy: set.intersection(*v) for dy, v in per.items() if len(v) == len(labs)}
        same = 0
        for dy in plan.DYS:
            if dy not in per_die["ce6"] or dy not in per_die["c10_016"]:
                continue
            A, B = per_die["ce6"][dy], per_die["c10_016"][dy]
            same += A == B
            print(f"  dy {dy:+d}: EP4CE6 {len(A):3d}, 10CL016 {len(B):3d}, shared {len(A & B):3d}, Jaccard "
                  f"{len(A & B) / max(1, len(A | B)):.2f}" + ("  IDENTICAL" if A == B else
                  f"  only-CE6 {sorted(A - B)[:4]} only-C10 {sorted(B - A)[:4]}"))
        print(f"  {same}/{len(plan.DYS)} row offsets identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
