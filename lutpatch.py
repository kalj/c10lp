#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-agnostic LUT truth-table codec, calibrated from an `xdev.py sweep`.

Method (same as Cyclone_CRAM_Mapper Phase 2.1): compile mask 0x0000 and the
16 single-minterm masks 1<<i at one LE.  delta_i = cells(0000 -> 1<<i).  If
the encoding is XOR-linear, cells(0000 -> M) = XOR of delta_i over the set
bits of M.  CRC bytes are excluded from the deltas and recomputed afterwards
with the CRC init inferred from the file, so this works on any die.

  calibrate --out DIR --device D --loc X,Y,N   build/check the codec, print layout
  write     --out DIR --device D --loc X,Y,N --mask 8888 -o new.rbf [--fix-header]
  verify    --out DIR --device D --loc X,Y,N   predict every other built mask at
                                               that LE and compare to Quartus

Header checksum (found on all 103 RBFs we have, both dies): bit 0 of bytes
0x29..0x48 holds a 32-bit value V, LSB first, and bytes 0x49..0x4A hold
CRC-16/0x8005 (init 0xFFFF, little-endian) over bytes 33..0x48.  V is
*additive* in the minterms: V(M) = V(0) + sum of per-minterm weights mod 2^32.
The general bit -> weight rule is not known yet, so --fix-header uses the
weights measured by the sweep and only works for masks at a calibrated LE.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rbfgeom  # noqa: E402
import xdev  # noqa: E402


def name(dev: str, mask: int, loc, pins: str = "vidor") -> str:
    return xdev.Job(dev, f"lut:{mask:04X}", loc, pins).name


def data_cells(a: bytes, b: bytes, g: rbfgeom.Geometry) -> set[tuple[int, int]]:
    """Differing (byte offset, bit) outside header and CRC bytes."""
    res = set()
    for f, pos, bit in xdev.cells(a, b, g):
        res.add((g.preamble + f * g.frame + pos, bit))
    return res


def patch_crc(buf: bytearray, g: rbfgeom.Geometry) -> int:
    changed = 0
    for f in g.crc_frames:
        s = g.preamble + f * g.frame
        c = rbfgeom.crc16(bytes(buf[s:s + g.frame - 2]), g.init).to_bytes(2, g.byteorder)
        if buf[s + g.frame - 2:s + g.frame] != c:
            buf[s + g.frame - 2:s + g.frame] = c
            changed += 1
    return changed


HDR_SUM, HDR_CRC = 0x29, 0x49     # 32 one-bit bytes, then 2 CRC bytes


def header_sum(buf: bytes) -> int:
    return sum((buf[HDR_SUM + i] & 1) << i for i in range(32))


def set_header_sum(buf: bytearray, v: int) -> None:
    for i in range(32):
        buf[HDR_SUM + i] = (buf[HDR_SUM + i] & 0xFE) | (v >> i & 1)
    buf[HDR_CRC:HDR_CRC + 2] = rbfgeom.crc16(bytes(buf[33:HDR_CRC]), 0xFFFF).to_bytes(2, "little")


class Codec:
    def __init__(self, out: str, dev: str, loc, model: bool = False, pins: str = "vidor"):
        self.pins = pins
        self.zero_name = name(dev, 0, loc, pins)
        z = xdev.load(out, self.zero_name)
        if z is None:
            raise SystemExit(f"missing {self.zero_name}.rbf; build mask 0000 at this LE first")
        self.zero = z
        self.g = rbfgeom.infer(z)
        self.delta = []
        self.hweight = []
        if model:
            # Cell positions from the lutpos.py model instead of a 16-compile sweep.
            import lutpos
            if dev != "c10_016":
                raise SystemExit("--model is only fitted for c10_016")
            # Input permutation from a mask-0x008A probe build at this LE, if any.
            self.perm = None
            probe = xdev.load(out, name(dev, lutpos.PROBE_MASK, loc, pins))
            if probe is not None:
                cs = set(xdev.cells(z, probe, self.g))
                self.perm = lutpos.perm_from_probe(cs, *loc)
                if self.perm is None:
                    raise SystemExit("probe build does not match any input permutation")
            for f, p, b in lutpos.predict(*loc, self.perm or lutpos.IDENT):
                self.delta.append({(self.g.preamble + f * self.g.frame + p, b)})
                w = lutpos.header_weight(f, p, b) if hasattr(lutpos, "header_weight") else None
                self.hweight.append(w)
            return
        for i in range(16):
            m = xdev.load(out, name(dev, 1 << i, loc, pins))
            if m is None:
                raise SystemExit(f"missing minterm {i}; run xdev.py sweep first")
            self.delta.append(data_cells(z, m, self.g))
            self.hweight.append((header_sum(m) - header_sum(z)) % (1 << 32))

    def predict(self, mask: int) -> set[tuple[int, int]]:
        acc: set[tuple[int, int]] = set()
        for i in range(16):
            if mask >> i & 1:
                acc ^= self.delta[i]
        return acc

    def write(self, mask: int, fix_header: bool = False) -> bytes:
        if getattr(self, "perm", 0) is None:
            import lutpos
            if any(sum((mask >> lutpos.permute(i, p) & 1) << i for i in range(16)) != mask
                   for p in lutpos.PERMS):
                raise SystemExit(f"mask {mask:04X} depends on input order; build mask "
                                 f"{lutpos.PROBE_MASK:04X} at this LE first (one compile)")
        buf = bytearray(self.zero)
        for off, bit in self.predict(mask):
            buf[off] ^= 1 << bit
        patch_crc(buf, self.g)
        if fix_header:
            if None in self.hweight:
                raise SystemExit("--fix-header needs measured header weights (run a sweep at this LE)")
            v = header_sum(self.zero) + sum(self.hweight[i] for i in range(16) if mask >> i & 1)
            set_header_sum(buf, v % (1 << 32))
        return bytes(buf)

    def layout(self) -> str:
        allc = set().union(*self.delta)
        shared = set.intersection(*self.delta)
        lines = [f"geometry: {self.g.nframes}x{self.g.frame} B, CRC init 0x{self.g.init:04X}",
                 f"minterm deltas: {[len(d) for d in self.delta]}",
                 f"cells touched by any minterm: {len(allc)}; shared by all 16: {len(shared)}"]
        frames = sorted({(o - self.g.preamble) // self.g.frame for o, _ in allc})
        lines.append(f"frames: {frames}")
        lines.append("minterm -> (frame, byte_in_frame, bit) cells unique to it:")
        for i, d in enumerate(self.delta):
            u = sorted(d - shared)
            fmt = [((o - self.g.preamble) // self.g.frame, (o - self.g.preamble) % self.g.frame, b)
                   for o, b in u]
            lines.append(f"  TT[{i:2d}]: {fmt}")
        return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["calibrate", "write", "verify"])
    ap.add_argument("--out", default=os.path.join(xdev.HERE, "out"))
    ap.add_argument("--device", required=True, choices=sorted(xdev.DEVICES))
    ap.add_argument("--loc", type=xdev.parse_loc, required=True)
    ap.add_argument("--mask", type=lambda s: int(s, 16))
    ap.add_argument("-o", "--output")
    ap.add_argument("--fix-header", action="store_true",
                    help="also rewrite the header checksum (calibrated LE only)")
    ap.add_argument("--pins", default="vidor", help="pin variant of the builds (vidor, vidorlo)")
    ap.add_argument("--model", action="store_true",
                    help="take LUT cells from lutpos.py (needs only mask 0000 at the LE)")
    a = ap.parse_args()
    c = Codec(a.out, a.device, a.loc, a.model, a.pins)

    if a.cmd == "calibrate":
        print(c.layout())
        path = os.path.join(a.out, f"codec_{a.device}_X{a.loc[0]}Y{a.loc[1]}N{a.loc[2]}.json")
        json.dump({"zero": c.zero_name, "frame": c.g.frame, "init": c.g.init,
                   "delta": [sorted(d) for d in c.delta]}, open(path, "w"))
        print(f"saved {path}")
        return 0

    if a.cmd == "write":
        if a.mask is None or not a.output:
            raise SystemExit("write needs --mask and -o")
        new = c.write(a.mask, a.fix_header)
        open(a.output, "wb").write(new)
        g2 = rbfgeom.infer(new)
        print(f"wrote {a.output}: mask 0x{a.mask:04X}, {len(c.predict(a.mask))} cells flipped, "
              f"CRC frames valid {len(g2.crc_frames)}/{len(c.g.crc_frames)}, "
              f"header checksum {'rewritten' if a.fix_header else 'left as in mask 0000'}")
        ref = xdev.load(a.out, name(a.device, a.mask, a.loc, a.pins))
        if ref is not None:
            same = data_cells(new, ref, c.g)
            nb = sum(x != y for x, y in zip(new, ref))
            print(f"vs Quartus build of the same mask: {len(same)} data-bit differences, "
                  f"{nb} bytes differ in the whole file"
                  + (" (BYTE-IDENTICAL)" if new == ref else ""))
        return 0

    # verify: every other mask built at this LE
    prefix = f"{a.device}__lut"
    suffix = f"_X{a.loc[0]}Y{a.loc[1]}N{a.loc[2]}__vidor.rbf"
    bad = 0
    for f in sorted(os.listdir(a.out)):
        if f.startswith(prefix) and f.endswith(suffix):
            m = int(f[len(prefix):len(prefix) + 4], 16)
            if m == 0 or m & (m - 1) == 0:
                continue                                  # calibration inputs
            ref = xdev.load(a.out, f[:-4])
            actual = data_cells(c.zero, ref, c.g)
            pred = c.predict(m)
            ok = actual == pred
            bad += not ok
            print(f"  mask {m:04X}: predicted {len(pred)}, Quartus {len(actual)}, "
                  f"{'MATCH' if ok else f'MISMATCH ({len(actual ^ pred)} bits)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
