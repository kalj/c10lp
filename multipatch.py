#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite every LUT of a multi-LUT Quartus template (10CL016), routing untouched.

Needs two Quartus builds of the same netlist: the template with all LUT masks
0000 and a probe with all masks 0x008A.  The probe fixes each LE's input
permutation; lutpos.py gives the cells.  Then any combination of masks is
written without compiling:

  multipatch.py write --masks 8888-F000-6666-0FF0-FEEE -o new.rbf [--fix-header]
  multipatch.py check            # template/probe consistency, compare with every
                                 # other Quartus build of the same netlist

Default netlist: xdev.py's "tree:" design (xdev.TREE_LOCS), pins vidorlo.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402


def tree_name(masks, pins: str) -> str:
    return xdev.Job("c10_016", "tree:" + "-".join(f"{m:04X}" for m in masks), (0, 0, 0), pins).name


class Multi:
    def __init__(self, out: str, locs, pins: str):
        self.out, self.locs, self.pins = out, locs, pins
        k = len(locs)
        self.zero = xdev.load(out, tree_name([0] * k, pins))
        probe = xdev.load(out, tree_name([lutpos.PROBE_MASK] * k, pins))
        if self.zero is None or probe is None:
            raise SystemExit("build the all-0000 template and the all-008A probe first")
        self.g = rbfgeom.infer(self.zero)
        diff = set(xdev.cells(self.zero, probe, self.g))
        self.perms, used = [], set()
        for x, y, n in locs:
            mine = diff & set(lutpos._predict_phys(x, y, n))
            p = lutpos.perm_from_probe(mine, x, y, n)
            if p is None:
                raise SystemExit(f"probe does not identify the permutation at X{x}Y{y}N{n}")
            self.perms.append(p)
            used |= mine
        # Anything else that changed means Quartus re-routed between the two builds.
        self.stray = diff - used

    def cells(self, masks) -> list[tuple[int, int, int]]:
        res = []
        for (x, y, n), p, m in zip(self.locs, self.perms, masks):
            res += [c for i, c in enumerate(lutpos.predict(x, y, n, p)) if m >> i & 1]
        return res

    def write(self, masks, fix_header: bool) -> bytes:
        buf = bytearray(self.zero)
        v = lutpatch.header_sum(self.zero)
        for f, p, b in self.cells(masks):
            buf[self.g.preamble + f * self.g.frame + p] ^= 1 << b
            v += lutpos.header_weight(f, p, b)
        lutpatch.patch_crc(buf, self.g)
        if fix_header:
            lutpatch.set_header_sum(buf, v % (1 << 32))
        return bytes(buf)


def parse_masks(s: str) -> list[int]:
    return [int(v, 16) for v in s.split("-")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["write", "check"])
    ap.add_argument("--out", default=os.path.join(xdev.HERE, "out"))
    ap.add_argument("--pins", default="vidorlo")
    ap.add_argument("--masks", type=parse_masks)
    ap.add_argument("-o", "--output")
    ap.add_argument("--fix-header", action="store_true")
    a = ap.parse_args()
    mp = Multi(a.out, xdev.TREE_LOCS, a.pins)
    print("permutations: " + ", ".join(f"X{x}Y{y}N{n}={p}" for (x, y, n), p
                                        in zip(mp.locs, mp.perms)))
    print(f"template vs probe outside the LUT cells: {len(mp.stray)} bits"
          + (" (routing identical)" if not mp.stray else " -- Quartus re-routed!"))

    if a.cmd == "write":
        if a.masks is None or len(a.masks) != len(mp.locs) or not a.output:
            raise SystemExit(f"write needs --masks with {len(mp.locs)} values and -o")
        new = mp.write(a.masks, a.fix_header)
        open(a.output, "wb").write(new)
        g2 = rbfgeom.infer(new)
        print(f"wrote {a.output}: {len(mp.cells(a.masks))} LUT bits set, CRC frames valid "
              f"{len(g2.crc_frames)}/{len(mp.g.crc_frames)}, header "
              f"{'rewritten' if a.fix_header else 'left as in the template'}")
        ref = xdev.load(a.out, tree_name(a.masks, a.pins))
        if ref is not None:
            print("vs Quartus build of the same masks: "
                  + ("BYTE-IDENTICAL" if ref == new else
                     f"{sum(x != y for x, y in zip(new, ref))} bytes differ"))
        return 0

    bad = n = 0
    pre = f"c10_016__tree"
    for f in sorted(os.listdir(a.out)):
        if not (f.startswith(pre) and f.endswith(f"__{a.pins}.rbf")):
            continue
        masks = parse_masks(f[len(pre):].split("__")[0])
        if set(masks) <= {0, lutpos.PROBE_MASK}:
            continue
        ok = mp.write(masks, True) == xdev.load(a.out, f[:-4])
        n += 1
        bad += not ok
        print(f"  {'-'.join(f'{m:04X}' for m in masks)}: {'BYTE-IDENTICAL' if ok else 'DIFFERS'}")
    print(f"{n - bad}/{n} Quartus builds reproduced byte for byte")
    return 1 if bad or mp.stray else 0


if __name__ == "__main__":
    sys.exit(main())
