#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode intra-LAB LUT input muxes from xdev design "mux4" (data only).

Each build: four sources at known slots drive dst's four inputs; dst's mask
3CEC reveals which physical input p each source landed on.  We read dst's mux
region directly (absolute bits, frames f0-18..f0-2, bytes 0..3 of dst) and fit
stage 1 (frames -12..-4): one select bit per (physical input, source slot).
The table from one LAB is then used to predict the other LABs' builds.

  mux4map.py [--repo ../Cyclone_CRAM_Mapper]
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402

GEO = {"ce6": 210, "c10_016": 255}
MASK = 0x3CEC


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    ap.add_argument("--show", action="store_true", help="print the decoded tables")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "fuzz"))
    import bitstream
    bitstream._sigma_inv_lookup = lambda *x, **k: (0, 1, 2, 3)
    import mux4_plan

    def phys(dev, x, y, n):
        if dev == "c10_016":
            return lutpos._predict_phys(x, y, n)
        fb = GEO["ce6"]
        pats = bitstream.LutCodec.from_cram_model(x, y, n).patterns
        return [next((((o - 32) // fb, (o - 32) % fb, b) for o, b in pats[i])) for i in range(16)]

    per_lab = {}
    for dev, (x, y), pins in mux4_plan.LABS:
        fb = GEO[dev]
        rows = collections.defaultdict(list)          # d -> [(src slot per physical input, region)]
        bad = 0
        for j in mux4_plan.jobs():
            if j.dev != dev or j.loc[:2] != (x, y):
                continue
            _, sd, srcs = j.design.split(":")
            d, srcs = int(sd), [int(v) for v in srcs.split("-")]
            with open(os.path.join(HERE, "out", j.name + ".rbf"), "rb") as f:
                buf = f.read()
            cells = phys(dev, x, y, d)
            on = {c for c in cells if buf[32 + c[0] * fb + c[1]] >> c[2] & 1}
            hits = [p for p in lutpos.PERMS
                    if {cells[lutpos.permute(i, p)] for i in range(16) if MASK >> i & 1} == on]
            if len(hits) != 1:
                bad += 1
                continue
            perm = hits[0]
            src_of_phys = {perm[i]: srcs[i] for i in range(4)}
            f0, lo, bit = min(c[0] for c in cells), min(c[1] for c in cells), cells[0][2]
            odd = (d // 2) % 2
            region = collections.defaultdict(set)
            for df in range(-18, -1):
                for db in range(-2, 6):
                    p = lo + ((1 - db) if odd else db)
                    if 0 <= p < fb - 2 and buf[32 + (f0 + df) * fb + p] >> bit & 1:
                        region[db].add(df)
            rows[d].append((src_of_phys, {k: frozenset(v) for k, v in region.items()}))
        per_lab[(dev, (x, y))] = rows
        print(f"{dev} X{x}Y{y}: {sum(len(v) for v in rows.values())} builds decoded, {bad} without a unique order")

    # Stage 1 (frames -12..-4 of dst bytes 0..3): one select bit per (physical input, source slot),
    # in dst coordinates where odd LEs map byte column c -> 3 - c.  The EP4CE6 cell order labels
    # physical inputs 0 and 1 the other way round.
    def stage1(reg, d):
        flip = (d // 2) % 2
        return {(f, (3 - c) if flip else c) for c, fr in reg.items() if 0 <= c <= 3 for f in fr if f <= -4}

    labs = list(per_lab)
    tables = {}
    for lab in labs:
        swap = {0: 1, 1: 0, 2: 2, 3: 3} if lab[0] == "ce6" else {q: q for q in range(4)}
        seen = collections.defaultdict(list)
        for d, builds in per_lab[lab].items():
            for src, reg in builds:
                r = stage1(reg, d)
                for q in range(4):
                    seen[(swap[q], src[q])].append(r)
        tables[lab] = ({k: set.intersection(*v) for k, v in seen.items()}, swap)
        sizes = collections.Counter(len(v) for v in tables[lab][0].values())
        print(f"  {lab[0]} X{lab[1][0]}Y{lab[1][1]}: {len(tables[lab][0])} (input, source) entries, "
              f"bits per entry {dict(sorted(sizes.items()))}")
    ref = tables[labs[0]][0]
    for lab in labs[1:]:
        other, swap = tables[lab]
        com = set(ref) & set(other)
        ok = n = 0
        for d, builds in per_lab[lab].items():
            for src, reg in builds:
                ks = [(swap[q], src[q]) for q in range(4)]
                if all(k in ref for k in ks):
                    n += 1
                    ok += set().union(*(ref[k] for k in ks)) == stage1(reg, d)
        print(f"  table from {labs[0][0]} X{labs[0][1][0]}Y{labs[0][1][1]} vs {lab[0]} X{lab[1][0]}Y{lab[1][1]}: "
              f"{sum(ref[k] == other[k] for k in com)}/{len(com)} entries identical; predicts {ok}/{n} builds' "
              f"stage-1 bits exactly")
    if a.show:
        for q in range(4):
            row = {s_: sorted(v) for (qq, s_), v in sorted(ref.items()) if qq == q}
            print(f"  input {q}: " + ", ".join(f"src {s_}: {v}" for s_, v in row.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
