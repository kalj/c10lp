#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""10CL016 (EP4CE15 die) LUT position model: (X, Y, N, minterm) -> (frame, byte, bit).

Fitted from `xdev.py` mask-0000/FFFF builds along Y=10 (all LAB columns),
X=10 (all rows) and X10Y10 (all N), plus the 16-minterm sweep at X10Y10N0.
Coordinates are RBF-relative: frame index after the 32-byte preamble, byte
within the 255-byte frame, bit 0..7.

When the N offset pushes the pair below byte 0 it wraps into the next higher
bit, whose "plane" is 251 bytes long for bits 5..7 and 252 for bits 1..4
(measured on 6 wrapping LEs).  A pair straddling byte 0 has not been seen.

The minterm order is relative to the LE's *physical* inputs.  Quartus may route
the design's A..D to the four LUT inputs in any order (the input permutation),
and it chooses per placement.  The 16 positions don't depend on it.  The order
does, so writing an asymmetric mask at a new LE needs that LE's permutation:
compile mask 0x008A (minterms a, a&b, a&b&c) there once and use perm_from_probe().
Symmetric masks (0000, FFFF, 6996, 9669, ...) are unaffected.

  python3 lutpos.py X Y N            print the 16 cells
  python3 lutpos.py --check          compare against every build in out/
"""
from __future__ import annotations

import itertools
import os
import sys

LAB_X = [x for x in range(1, 41) if x not in (13, 18, 25, 34)]
HOLE = {(x, y) for x in range(1, 10) for y in range(15, 20)}

# First LUT frame of each LAB column (measured at Y=10, N=0).
FRAME_BASE = {1: 86, 14: 803, 19: 968, 26: 1471, 30: 1615, 35: 1780}
for x in LAB_X:
    if x not in FRAME_BASE:
        FRAME_BASE[x] = FRAME_BASE[x - 1] + 35

# Row -> (low byte of the pair at N=0, bit).
ROW = {1: (94, 7), 2: (164, 7), 3: (234, 7), 4: (53, 6), 5: (123, 6), 6: (193, 6),
       7: (12, 5), 8: (82, 5), 9: (152, 5), 10: (222, 5), 11: (41, 4), 12: (111, 4),
       13: (181, 4), 14: (251, 4), 15: (69, 3), 16: (139, 3), 17: (209, 3), 18: (27, 2),
       19: (97, 2), 20: (167, 2), 21: (237, 2), 22: (55, 1), 23: (125, 1), 24: (195, 1),
       25: (13, 0), 26: (83, 0), 27: (153, 0), 28: (223, 0)}

# Minterm -> (frame offset 0..7, upper byte?) at an even LE (N/2 even).
TT = [(7, 1), (5, 1), (3, 1), (1, 1), (6, 0), (4, 0), (2, 0), (0, 0),
      (7, 0), (5, 0), (3, 0), (1, 0), (6, 1), (4, 1), (2, 1), (0, 1)]


def n_offset(n: int) -> int:
    k = n // 2
    return -(8 * (k // 2) + 2 * (k % 2) + (6 if k >= 8 else 0))


# Header checksum (see lutpatch.py): each set CRAM data bit (frames 37..2002,
# not the CRC bytes) adds 2**((2*L - frame) % 8) to V, where L is the bit's
# row-space index: byte + PLANE_START[bit].  Fits 105 single-bit builds and
# every whole-file pair tested; V = 133509 + sum over a file (Vidor projects).
PLANE_START = {7: 0, 6: 251, 5: 502, 4: 753, 3: 1005, 2: 1257, 1: 1509, 0: 1761}


def header_weight(frame: int, byte: int, bit: int) -> int:
    return 1 << ((2 * (byte + PLANE_START[bit]) - frame) % 8)


PROBE_MASK = 0x008A   # minterms 1 (a), 3 (a&b), 7 (a&b&c)
PERMS = list(itertools.permutations(range(4)))
IDENT = (0, 1, 2, 3)


def permute(i: int, perm) -> int:
    """Logical minterm i -> physical minterm when logical input k drives physical input perm[k]."""
    return sum((i >> k & 1) << perm[k] for k in range(4))


def predict(x: int, y: int, n: int, perm=IDENT) -> list[tuple[int, int, int]]:
    """16 (frame, byte, bit) cells, indexed by logical minterm."""
    phys = _predict_phys(x, y, n)
    return [phys[permute(i, perm)] for i in range(16)]


def perm_from_probe(cells: set, x: int, y: int, n: int):
    """The permutation consistent with a mask-0x008A build's LUT cells, or None."""
    hits = [p for p in PERMS
            if {predict(x, y, n, p)[i] for i in (1, 3, 7)} == set(cells)]
    return hits[0] if len(hits) == 1 else None


def perms_for_mask(cells: set, x: int, y: int, n: int, mask: int) -> list:
    """Every permutation under which logical `mask` sets exactly `cells` (a build's
    set LUT cells at that LE).  One hit identifies the input order from that build
    alone; symmetric masks give several."""
    return [p for p in PERMS
            if {c for i, c in enumerate(predict(x, y, n, p)) if mask >> i & 1} == set(cells)]


def unique_perm_mask(mask: int) -> bool:
    """True if no two permutations turn `mask` into the same physical pattern."""
    pats = {sum((mask >> i & 1) << permute(i, p) for i in range(16)) for p in PERMS}
    return len(pats) == len(PERMS)


def _predict_phys(x: int, y: int, n: int) -> list[tuple[int, int, int]]:
    if x not in FRAME_BASE or y not in ROW or (x, y) in HOLE or n % 2 or not 0 <= n <= 30:
        raise ValueError(f"X{x}Y{y}N{n} is not a LE on the 10CL016")
    low, bit = ROW[y]
    low += n_offset(n)
    odd = (n // 2) % 2
    res = []
    for fo, up in TT:
        byte, b = low + (up ^ odd), bit
        if byte < 2:
            # Bytes 0 and 1 hold no LUT bits: the cell wraps to the top of the frame, one bit
            # plane up.  Per byte, so a pair can straddle (seen at X36Y11N18: bytes 1, 2).
            b += 1
            byte += 251 if b >= 5 else 252
        res.append((FRAME_BASE[x] + fo, byte, b))
    return res


def check(out: str) -> int:
    sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d) for d in ("lib", "flow", "mapping", "hwtests")]
    import rbfgeom
    import xdev
    per_le: dict[tuple, list] = {}
    for f in sorted(os.listdir(out)):
        if not (f.startswith("c10_016__lut") and f.endswith(("__vidor.rbf", "__vidorlo.rbf"))):
            continue
        pins = f[:-4].split("__")[2]
        mask = int(f[12:16], 16)
        loc = f[16:].split("__")[0]
        if mask == 0 or not loc.startswith("_X"):
            continue
        x, rest = loc[2:].split("Y")
        y, n = rest.split("N")
        x, y, n = int(x), int(y), int(n)
        z = xdev.load(out, f"c10_016__lut0000{loc}__{pins}")
        if z is None:
            continue
        actual = set(xdev.cells(z, xdev.load(out, f[:-4]), rbfgeom.infer(z)))
        per_le.setdefault((x, y, n, pins), []).append((f, mask, actual))
    ok = bad = 0
    perm_counts: dict[tuple, int] = {}
    for (x, y, n, _pins), builds in sorted(per_le.items()):
        # One permutation per LE must explain every build there.
        fits = [p for p in PERMS
                if all(a == {predict(x, y, n, p)[i] for i in range(16) if m >> i & 1}
                       for _, m, a in builds)]
        if fits:
            ok += len(builds)
            if len(fits) < len(PERMS):           # only informative LEs
                key = fits[0] if IDENT not in fits else IDENT
                perm_counts[key] = perm_counts.get(key, 0) + 1
        else:
            bad += len(builds)
            for f, m, a in builds:
                print(f"  MISMATCH {f}: got {sorted(a)}")
    print(f"{ok} builds match ({len(per_le)} LEs), {bad} mismatch; "
          f"input permutations seen: {len(perm_counts)}")
    return 1 if bad else 0


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if sys.argv[1:] == ["--check"]:
        sys.exit(check(os.path.join(here, "out")))
    x, y, n = (int(v) for v in sys.argv[1:4])
    for i, c in enumerate(predict(x, y, n)):
        print(f"TT[{i:2d}] frame {c[0]} byte {c[1]} bit {c[2]}")
