#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Die-agnostic geometry, CRC and diff tool for uncompressed Cyclone III/IV/10 LP .rbf files.

The Cyclone_CRAM_Mapper repo hard-codes the EP4CE6/EP4CE10 die
(368,011 B = 32 B preamble + 1752 frames x 210 B + 59 B postamble,
CRC-16 poly 0x8005 reflected, init 0xFE54, CRC on frames 25..1751).
This tool infers those parameters from any uncompressed RBF instead of
assuming them, so the same code can be pointed at a 10CL016 bitstream.

Commands:
  info  FILE.rbf              infer frame size, CRC init, CRC-covered frames
  diff  A.rbf B.rbf           region-aware diff (works across devices)
  selftest                    synthetic-bitstream test of the inference code

The CRC init is solved, not guessed: a reflected CRC with no final XOR is
linear over GF(2), so crc(init, data) = M*init XOR crc(0, data), where M
depends only on the frame length.  One frame is enough to solve for init.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from dataclasses import dataclass, field

# Per-die geometry reported by awtoau/pluribus issue #173 (secondary source;
# confirm against real Quartus output).  key = uncompressed RBF size in bytes.
KNOWN_DIES = {
    368_011: dict(name="EP3C5/EP3C10/EP4CE6/EP4CE10 (expected: 10CL006/10CL010)",
                  frame=210, periphery=25, cram=1727),
    510_856: dict(name="EP3C16/EP4CE15 (expected: 10CL016)",
                  frame=255, periphery=37, cram=1966),
    718_569: dict(name="EP3C25/EP4CE22 (expected: 10CL025)",
                  frame=298, periphery=25, cram=2386),
    1_191_788: dict(name="EP3C40/EP4CE30/EP4CE40 (expected: 10CL040)",
                    frame=377, periphery=37, cram=3124),
    1_861_195: dict(name="EP3C55/EP4CE55 (expected: 10CL055)",
                    frame=464, periphery=21, cram=3990),
}

POLY_REFLECTED = 0xA001          # bit-reversed 0x8005 (CRC-16/IBM family)
PREAMBLE = 32
POSTAMBLE = 59


def _make_table(poly: int) -> list[int]:
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        t.append(c)
    return t


_TABLE = _make_table(POLY_REFLECTED)


def crc16(data: bytes, init: int, table: list[int] = _TABLE) -> int:
    c = init
    for b in data:
        c = (c >> 8) ^ table[(c ^ b) & 0xFF]
    return c


def solve_init(data: bytes, stored: int) -> int:
    """Return the unique init such that crc16(data, init) == stored."""
    n = len(data)
    zeros = bytes(n)
    cols = [crc16(zeros, 1 << k) for k in range(16)]   # M's columns
    target = stored ^ crc16(data, 0)
    # Gaussian elimination over GF(2): find x with sum(x_k * cols[k]) == target.
    rows = []                                           # (vector, combination)
    for k, v in enumerate(cols):
        comb = 1 << k
        for rv, rc in rows:
            if v ^ rv < v:
                v ^= rv
                comb ^= rc
        if v:
            rows.append((v, comb))
            rows.sort(reverse=True)
    x, t = 0, target
    for rv, rc in rows:
        if t ^ rv < t:
            t ^= rv
            x ^= rc
    if t:
        raise ValueError("no solution (singular system)")
    return x


@dataclass
class Geometry:
    size: int
    preamble: int
    postamble: int
    frame: int
    nframes: int
    init: int | None = None
    byteorder: str = "little"
    crc_frames: list[int] = field(default_factory=list)  # frames whose CRC checks

    @property
    def crc_range(self) -> str:
        if not self.crc_frames:
            return "none"
        runs, start, prev = [], self.crc_frames[0], self.crc_frames[0]
        for f in self.crc_frames[1:]:
            if f != prev + 1:
                runs.append((start, prev))
                start = f
            prev = f
        runs.append((start, prev))
        return ", ".join(f"{a}..{b}" if a != b else f"{a}" for a, b in runs)

    @property
    def first_crc_frame(self) -> int | None:
        return self.crc_frames[0] if self.crc_frames else None

    def frame_of(self, off: int) -> int | None:
        if off < self.preamble or off >= self.preamble + self.nframes * self.frame:
            return None
        return (off - self.preamble) // self.frame


def _stored(buf: bytes, s: int, F: int, order: str) -> int:
    return int.from_bytes(buf[s + F - 2:s + F], order)


def check_frames(buf: bytes, pre: int, F: int, n: int, init: int, order: str) -> list[int]:
    ok = []
    for k in range(n):
        s = pre + k * F
        if crc16(buf[s:s + F - 2], init) == _stored(buf, s, F, order):
            ok.append(k)
    return ok


def infer(buf: bytes, pre: int = PREAMBLE, post: int = POSTAMBLE,
          fmin: int = 64, fmax: int = 2048) -> Geometry:
    """Find the frame size whose frames share one CRC init.

    Frame size candidates are divisors of the body length.  For each, the
    init is solved from the last frame and checked against a sample of
    other frames; the candidate with the most agreeing frames wins.
    """
    body = len(buf) - pre - post
    best = None
    for F in range(fmin, fmax + 1):
        if body % F:
            continue
        n = body // F
        for order in ("little", "big"):
            s = pre + (n - 1) * F
            try:
                init = solve_init(buf[s:s + F - 2], _stored(buf, s, F, order))
            except ValueError:
                continue
            sample = range(max(0, n - 40), n)            # tail frames are CRAM
            hits = sum(1 for k in sample
                       if crc16(buf[pre + k * F:pre + k * F + F - 2], init)
                       == _stored(buf, pre + k * F, F, order))
            if best is None or hits > best[0]:
                best = (hits, F, n, init, order)
    if best is None or best[0] < 3:
        return Geometry(len(buf), pre, post, 0, 0)
    _, F, n, init, order = best
    g = Geometry(len(buf), pre, post, F, n, init, order)
    g.crc_frames = check_frames(buf, pre, F, n, init, order)
    return g


def lead_ff(buf: bytes) -> int:
    i = 0
    while i < len(buf) and buf[i] == 0xFF:
        i += 1
    return i


def trail_ff(buf: bytes) -> int:
    i = 0
    while i < len(buf) and buf[-1 - i] == 0xFF:
        i += 1
    return i


def cmd_info(path: str) -> int:
    buf = open(path, "rb").read()
    print(f"file      : {path}")
    print(f"size      : {len(buf):,} B   sha1 {hashlib.sha1(buf).hexdigest()[:16]}")
    print(f"0xFF run  : leading {lead_ff(buf)} B, trailing {trail_ff(buf)} B")
    k = KNOWN_DIES.get(len(buf))
    print(f"size table: {k['name'] if k else 'no match (compressed? different die?)'}")
    g = infer(buf)
    if not g.frame:
        print("geometry  : could not infer (is the file compressed?)")
        return 1
    print(f"frames    : {g.nframes} x {g.frame} B  (preamble {g.preamble}, postamble {g.postamble})")
    print(f"CRC       : poly 0x8005 reflected, init 0x{g.init:04X}, stored {g.byteorder}-endian")
    print(f"CRC frames: {g.crc_range}  ({len(g.crc_frames)} frames)")
    if g.first_crc_frame is not None:
        print(f"header    : frames 0..{g.first_crc_frame - 1} have no matching CRC "
              f"(bytes 0..{g.preamble + g.first_crc_frame * g.frame - 1})")
    if k:
        exp_frames = k["periphery"] + k["cram"]
        ok = (g.frame == k["frame"] and g.nframes == exp_frames
              and g.first_crc_frame == k["periphery"])
        print(f"vs table  : expected {k['frame']} B frames, {k['periphery']} periphery + "
              f"{k['cram']} CRAM -> {'consistent' if ok else 'MISMATCH'}")
    print("first header bytes:", buf[g.preamble:g.preamble + 48].hex(" "))
    return 0


def region_of(g: Geometry, off: int) -> str:
    f = g.frame_of(off)
    if f is None:
        return "preamble" if off < g.preamble else "postamble"
    first = g.first_crc_frame or 0
    if f < first:
        return "header"
    pos = (off - g.preamble) % g.frame
    return "cram-crc" if pos >= g.frame - 2 else "cram-data"


def cmd_diff(a_path: str, b_path: str, top: int = 12) -> int:
    a, b = open(a_path, "rb").read(), open(b_path, "rb").read()
    ga, gb = infer(a), infer(b)
    for tag, p, buf, g in (("A", a_path, a, ga), ("B", b_path, b, gb)):
        print(f"{tag}: {os.path.basename(p)}  {len(buf):,} B  "
              f"{g.nframes}x{g.frame} B frames  init 0x{(g.init or 0):04X}  CRC {g.crc_range}")
    if len(a) != len(b) or ga.frame != gb.frame:
        print("\nDifferent geometry: these are different dies (or one file is compressed).")
        print("A header:", a[32:80].hex(" "))
        print("B header:", b[32:80].hex(" "))
        return 2
    if a == b:
        print("\n>>> BYTE-IDENTICAL <<<")
        return 0
    regions: dict[str, list[int]] = {}
    frames: dict[int, int] = {}
    nbits = 0
    for i in range(len(a)):
        x = a[i] ^ b[i]
        if x:
            regions.setdefault(region_of(ga, i), []).append(i)
            f = ga.frame_of(i)
            if f is not None:
                frames[f] = frames.get(f, 0) + 1
            nbits += bin(x).count("1")
    print(f"\n{sum(map(len, regions.values()))} bytes / {nbits} bits differ")
    for r in ("preamble", "header", "cram-data", "cram-crc", "postamble"):
        if r in regions:
            offs = regions[r]
            print(f"  {r:10s}: {len(offs):6d} bytes  first 0x{offs[0]:06X}  last 0x{offs[-1]:06X}")
    if "header" in regions:
        print("  header byte diffs (off: A -> B):")
        for i in regions["header"][:24]:
            print(f"    0x{i:06X}: {a[i]:02X} -> {b[i]:02X}")
    data_frames = {f: c for f, c in frames.items()
                   if ga.first_crc_frame is None or f >= ga.first_crc_frame}
    if data_frames:
        print(f"  CRAM frames touched: {len(data_frames)} "
              f"(range {min(data_frames)}..{max(data_frames)}); top {top}:")
        for f, c in sorted(data_frames.items(), key=lambda kv: -kv[1])[:top]:
            print(f"    frame {f:5d}: {c} bytes")
    return 1


def selftest() -> int:
    rnd = random.Random(1)
    cases = [(210, 25, 1727, 0xFE54), (255, 37, 1966, rnd.randrange(65536)),
             (298, 25, 2386, rnd.randrange(65536))]
    for F, P, C, init in cases:
        n = P + C
        buf = bytearray(b"\xff" * PREAMBLE)
        for k in range(n):
            d = bytes(rnd.randrange(256) for _ in range(F - 2))
            crc = crc16(d, init) if k >= P else rnd.randrange(65536)
            buf += d + crc.to_bytes(2, "little")
        buf += b"\xff" * POSTAMBLE
        g = infer(bytes(buf))
        ok = (g.frame == F and g.nframes == n and g.init == init
              and g.first_crc_frame == P and len(g.crc_frames) == C)
        print(f"F={F} P={P} C={C} init=0x{init:04X} -> inferred F={g.frame} "
              f"n={g.nframes} init=0x{(g.init or 0):04X} crc={g.crc_range}  "
              f"{'PASS' if ok else 'FAIL'}")
        if not ok:
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("rbf")
    p = sub.add_parser("diff"); p.add_argument("a"); p.add_argument("b")
    p.add_argument("--top", type=int, default=12)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "info":
        return cmd_info(a.rbf)
    if a.cmd == "diff":
        return cmd_diff(a.a, a.b, a.top)
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
