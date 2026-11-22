#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-check every established c10lp result against the cached builds in out/.

No Quartus needed. Each check prints PASS/FAIL/SKIP; a check is skipped when
the builds it needs are missing.  Exit status 1 if anything fails.

  python3 selftest.py [--repo ../Cyclone_CRAM_Mapper] [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpatch  # noqa: E402
import lutpos  # noqa: E402
import rbfgeom  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
results: list[tuple[str, str, str]] = []


def check(name: str):
    def deco(fn):
        try:
            r = fn()
            status, info = ("PASS", r) if r is not False else ("FAIL", "")
            if isinstance(r, tuple):
                status, info = r
        except FileNotFoundError as e:
            status, info = "SKIP", f"missing {os.path.basename(str(e.filename or e))}"
        except SystemExit as e:                   # a codec refusing for lack of builds
            status, info = "SKIP", str(e)[:70]
        except AssertionError as e:
            status, info = "FAIL", str(e)
        results.append((status, name, info or ""))
        return fn
    return deco


def rbf(n: str) -> bytes:
    p = os.path.join(OUT, n + ".rbf")
    with open(p, "rb") as f:
        return f.read()


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    ap.add_argument("--out", default=OUT, help="build directory (default out/)")
    a = ap.parse_args()
    OUT = a.out

    @check("control: repo design rebuilds byte-identical to golden_rbf_modeH")
    def _():
        g = os.path.join(a.repo, "results", "golden_rbf_modeH")
        for m in ("0000", "DEAD"):
            mine = rbf(f"ce6__lut{m}_X10Y2N0__repo")
            with open(os.path.join(g, f"X10_Y2_N0_mask{m}_q211.rbf"), "rb") as f:
                assert mine == f.read(), f"mask {m} differs from golden"
        return "0000, DEAD"

    @check("geometry: 10CL016 = 2003 x 255 B, CRC init 0xFE54, CRC frames 37..2002")
    def _():
        b = rbf("c10_016__wire__vidor")
        g = rbfgeom.infer(b)
        assert len(b) == 510_856 and g.frame == 255 and g.nframes == 2003, "size/frames"
        assert g.init == 0xFE54 and g.first_crc_frame == 37, f"init/CRC {g.init:#x} {g.crc_range}"
        return "510,856 B"

    @check("same die: LUT pair-diffs identical for ce6/c10_006 and ce15/c10_016/ce15u")
    def _():
        for a_, b_ in (("ce6", "c10_006"), ("ce15", "c10_016"), ("ce15u", "c10_016")):
            for m in ("FFFF", "8888"):
                cs = []
                for d in (a_, b_):
                    z = rbf(f"{d}__lut0000_X10Y10N0__vidor")
                    cs.append(sorted(xdev.cells(z, rbf(f"{d}__lut{m}_X10Y10N0__vidor"),
                                                rbfgeom.infer(z))))
                assert cs[0] == cs[1], f"{a_} vs {b_} mask {m}"
        return "3 pairs x 2 masks"

    @check("header: bytes 0x49..0x4A = CRC-16 init 0xFFFF over bytes 33..0x48, every RBF")
    def _():
        files = glob.glob(os.path.join(OUT, "*.rbf"))
        files += glob.glob(os.path.join(a.repo, "results", "golden_rbf_modeH", "*.rbf"))
        bad = []
        for f in files:
            with open(f, "rb") as fh:
                b = fh.read()
            if rbfgeom.crc16(b[33:0x49], 0xFFFF).to_bytes(2, "little") != b[0x49:0x4B]:
                bad.append(os.path.basename(f))
        assert not bad, f"{len(bad)} fail, e.g. {bad[:3]}"
        return f"{len(files)} files"

    @check("lutpos: model predicts the LUT cells of every single/FFFF/hold-out build")
    def _():
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = lutpos.check(OUT)
        assert rc == 0, buf.getvalue().strip().splitlines()[-1]
        last = buf.getvalue().strip().splitlines()[-1]
        return ("SKIP", "no LUT builds") if last.startswith("0 builds") else last

    @check("lutpatch sweep codec at X10Y10N0: --fix-header is byte-identical to Quartus")
    def _():
        c = lutpatch.Codec(OUT, "c10_016", (10, 10, 0))
        done = []
        for m in (0x4444, 0x6996, 0x8888, 0xDEAD, 0xFFFF):
            ref = rbf(f"c10_016__lut{m:04X}_X10Y10N0__vidor")
            assert c.write(m, fix_header=True) == ref, f"mask {m:04X}"
            done.append(f"{m:04X}")
        return " ".join(done)

    @check("lutpatch --model: 0 data-bit diffs vs Quartus at random hold-out LEs (6996)")
    def _():
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__lut6996_X*__vidor.rbf"))):
            loc = os.path.basename(f)[16:].split("__")[0]
            x, rest = loc[2:].split("Y")
            y, nn = rest.split("N")
            loc_t = (int(x), int(y), int(nn))
            if loc_t == (10, 10, 0):
                continue
            c = lutpatch.Codec(OUT, "c10_016", loc_t, model=True)
            new = c.write(0x6996)
            with open(f, "rb") as fh:
                ref = fh.read()
            assert not lutpatch.data_cells(new, ref, c.g), f"data bits differ at {loc}"
            n += 1
        return (("PASS", f"{n} LEs") if n else ("SKIP", "no hold-out builds"))

    @check("header sum: V = 133509 + lutpos.header_weight over set CRAM bits (Vidor builds)")
    def _():
        files = sorted(glob.glob(os.path.join(OUT, "c10_016__*__vidor.rbf")))[::10]
        if not files:
            return "SKIP", "no c10_016 builds"
        tab = {(f % 8, p, x): sum(lutpos.header_weight(f, p, b) for b in range(8) if x >> b & 1)
               for f in range(8) for p in range(253) for x in range(256)}
        for fn in files:
            with open(fn, "rb") as fh:
                b = fh.read()
            v = 133509
            for f in range(37, 2003):
                base = 32 + f * 255
                for p in range(253):
                    if b[base + p]:
                        v += tab[(f % 8, p, b[base + p])]
            assert v % (1 << 32) == lutpatch.header_sum(b), os.path.basename(fn)
        return f"{len(files)} files"

    @check("lutpatch --model --fix-header: byte-identical to Quartus (probe for asymmetric)")
    def _():
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__lut*_X*__vidor.rbf"))):
            base = os.path.basename(f)
            mask, loc = int(base[12:16], 16), base[16:].split("__")[0]
            if mask in (0, lutpos.PROBE_MASK) or (mask & (mask - 1)) == 0 or loc == "_X10Y10N0":
                continue
            x, rest = loc[2:].split("Y")
            y, nn = rest.split("N")
            c = lutpatch.Codec(OUT, "c10_016", (int(x), int(y), int(nn)), model=True)
            if c.perm is None and mask not in (0xFFFF, 0x6996, 0x9669):
                continue
            with open(f, "rb") as fh:
                assert c.write(mask, fix_header=True) == fh.read(), base
            n += 1
        return f"{n} builds" if n else ("SKIP", "no model-checkable builds")

    @check("header sum on the EP4CE6 die: one constant per project setup (incl. repo goldens)")
    def _():
        s = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 0}
        tab = {(f, p, x): sum(1 << ((p + s[b] - f) % 8) for b in range(8) if x >> b & 1)
               for f in range(8) for p in range(208) for x in range(256)}
        groups = {"repo goldens": glob.glob(os.path.join(a.repo, "results", "golden_rbf_modeH",
                                                         "*.rbf"))[::6],
                  "ce6 vidor": glob.glob(os.path.join(OUT, "ce6__*__vidor.rbf"))[::6]}
        groups = {g: f for g, f in groups.items() if f}
        if len(groups) < 2:
            return "SKIP", "needs both the repo goldens and ce6 vidor builds"
        for g, files in groups.items():
            consts = set()
            for fn in files:
                with open(fn, "rb") as fh:
                    b = fh.read()
                v = 0
                for f in range(25, 1752):
                    base = 32 + f * 210
                    for p in range(208):
                        if b[base + p]:
                            v += tab[(f % 8, p, b[base + p])]
                consts.add((lutpatch.header_sum(b) - v) % (1 << 32))
            assert files and len(consts) == 1, f"{g}: {len(files)} files, constants {consts}"
        return ", ".join(f"{g} {len(f)}" for g, f in groups.items())

    @check("multipatch: 5-LUT template rewritten byte-identical to Quartus (random masks)")
    def _():
        import multipatch
        mp = multipatch.Multi(OUT, xdev.TREE_LOCS, "vidorlo")
        assert not mp.stray, f"template/probe routing differs in {len(mp.stray)} bits"
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__tree*__vidorlo.rbf"))):
            masks = multipatch.parse_masks(os.path.basename(f)[13:].split("__")[0])
            if set(masks) <= {0, lutpos.PROBE_MASK}:
                continue
            with open(f, "rb") as fh:
                assert mp.write(masks, True) == fh.read(), os.path.basename(f)
            n += 1
        return (("PASS", f"{n} builds") if n else ("SKIP", "no tree builds"))

    w = max(len(n) for _, n, _ in results)
    for status, n, info in results:
        print(f"[{status}] {n:{w}s}  {info}")
    return 1 if any(s == "FAIL" for s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
