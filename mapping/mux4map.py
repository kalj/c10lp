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
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402

GEO = {"ce6": 210, "c10_016": 255}
LO = -12          # lowest frame (relative to dst LUT) in the owner model
MASK = 0x3CEC


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    ap.add_argument("--show", action="store_true", help="print the decoded tables")
    ap.add_argument("--full", action="store_true",
                    help="all 16 dst slots (10CL016): owner model over frames -12..-2, slot invariance")
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
        for j in mux4_plan.jobs(full=a.full):
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

    if a.full:
        return owner_model(per_lab)

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


def owner_model(per_lab) -> int:
    """Each bit of dst bytes 0..3, frames -12..-2 (odd LEs: column c -> 3 - c), is owned by the one
    physical input whose source slot decides it.  Entry (input q, source s) = the q-owned bits that
    are on when q's source is s.  Fit per (LAB, dst slot); then test whether one table fits all."""
    def bits(reg, d):
        flip = (d // 2) % 2
        return {(f, (3 - c) if flip else c) for c, fr in reg.items() if 0 <= c <= 3 for f in fr if LO <= f <= -2}

    fits = {}
    for lab, rows in per_lab.items():
        if lab[0] != "c10_016":
            continue
        for d, builds in rows.items():
            B = [(src, bits(reg, d)) for src, reg in builds]
            allb = set().union(*(b for _, b in B))
            table, unowned = collections.defaultdict(set), []
            for bit in sorted(allb):
                owner = None
                for q in range(4):
                    by = collections.defaultdict(set)
                    for src, b in B:
                        by[src[q]].add(bit in b)
                    if all(len(v) == 1 for v in by.values()):
                        owner = (q, {s_ for s_, v in by.items() if True in v})
                        break
                if owner is None:
                    unowned.append(bit)
                    continue
                for s_ in owner[1]:
                    table[(owner[0], s_)].add(bit)
            ok = sum(set().union(*(table.get((q, src[q]), set()) for q in range(4))) == b for src, b in B)
            fits[(lab, d)] = dict(table)
            print(f"  X{lab[1][0]}Y{lab[1][1]} dst {d:2d}: {len(allb)} bits, {len(unowned)} not owned by one input"
                  f"{' ' + str(unowned[:3]) if unowned else ''}; owner model reproduces {ok}/{len(B)} builds")
    # Slot invariance: merge all fits, count conflicts per (input, source) entry.
    merged = collections.defaultdict(collections.Counter)
    for t in fits.values():
        for k, v in t.items():
            merged[k][frozenset(v)] += 1
    clean = sum(len(c) == 1 for c in merged.values())
    print(f"\n  (input, source) entries over all dst slots and both LABs: {len(merged)}; the same in every "
          f"fit that has them: {clean}")
    big = [(k, c) for k, c in merged.items() if len(c) > 1][:6]
    for k, c in big:
        print(f"    {k}: " + "; ".join(f"{sorted(v)} x{n}" for v, n in c.most_common(3)))
    # Leave-one-out: the merged majority table predicts each (LAB, dst) set's builds.
    major = {k: set(c.most_common(1)[0][0]) for k, c in merged.items()}
    tot = hit = 0
    for (lab, d), _t in fits.items():
        for src, reg in per_lab[lab][d]:
            if all((q, src[q]) in major for q in range(4)):
                tot += 1
                hit += set().union(*(major[(q, src[q])] for q in range(4))) == bits(reg, d)
    print(f"  one slot-independent table predicts {hit}/{tot} builds exactly (all dst slots, both LABs)")
    # Honest version: leave one (LAB, dst slot) out of the table, predict its builds.
    tot = hit = 0
    for held in fits:
        m2 = collections.defaultdict(collections.Counter)
        for key, t in fits.items():
            if key != held:
                for k, v in t.items():
                    m2[k][frozenset(v)] += 1
        maj = {k: set(c.most_common(1)[0][0]) for k, c in m2.items()}
        lab, d = held
        for src, reg in per_lab[lab][d]:
            if all((q, src[q]) in maj for q in range(4)):
                tot += 1
                hit += set().union(*(maj[(q, src[q])] for q in range(4))) == bits(reg, d)
    print(f"  leave-one-(LAB, dst slot)-out: {hit}/{tot} held-out builds predicted exactly")
    # The same table on the EP4CE6 builds (physical inputs 0/1 labelled the other way round there).
    swap = {0: 1, 1: 0, 2: 2, 3: 3}
    tot = hit = 0
    for lab, rows in per_lab.items():
        if lab[0] != "ce6":
            continue
        for d, builds in rows.items():
            for src, reg in builds:
                ks = [(swap[q], src[q]) for q in range(4)]
                if all(k in major for k in ks):
                    tot += 1
                    hit += set().union(*(major[k] for k in ks)) == bits(reg, d)
    print(f"  the 10CL016 table on the EP4CE6 builds: {hit}/{tot} predicted exactly")
    out = os.path.join(HERE, "data", "li_local_table.json")
    with open(out, "w") as f:
        json.dump({"about": "10CL016 intra-LAB LUT-input mux selects for LE-output (local line) sources. "
                            "Key 'input,source_slot' -> [[frame offset, byte column], ...] relative to the dst "
                            "LE: frame offset from dst's first LUT frame, byte column from dst's low LUT byte "
                            "(odd LEs: column c -> 3 - c), in dst's bit plane. Physical input numbering as in "
                            "lutpos.permute. Set the union of the entries for dst's four (input, source) pairs.",
                   "frames": [LO, -2], "entries": {f"{q},{s_}": sorted(v) for (q, s_), v in sorted(major.items())}},
                  f, indent=1)
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
