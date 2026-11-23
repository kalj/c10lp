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
import json
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
            # I/O settings other than the standard Vidor ones: add their plane-2 periphery weights (periph.py)
            import periph
            ref = xdev.load(OUT, "c10_016__iobase_X10Y10N0__vidor")
            if ref is not None and ref[32:32 + 37 * 255] != b[32:32 + 37 * 255]:
                v += sum(periph.header_weight(k, pp, bit) * (1 if val else -1) for k, pp, bit, val in periph.diff(ref, b))
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

    @check("regtest: LUT->register template rewritten byte-identical to Quartus")
    def _():
        import regtest
        regtest.OUT = OUT
        n = 0
        for loc in regtest.LOCS:
            c = regtest.codec(loc)
            for f in sorted(glob.glob(os.path.join(OUT, f"c10_016__reg*_X{loc[0]}Y{loc[1]}N{loc[2]}__vidorlo.rbf"))):
                m = int(os.path.basename(f)[12:16], 16)
                if m in (0, lutpos.PROBE_MASK):
                    continue
                with open(f, "rb") as fh:
                    assert c.write(m, fix_header=True) == fh.read(), os.path.basename(f)
                n += 1
        return f"{n} builds" if n else ("SKIP", "no reg builds")

    @check("tpatch: fsm3 input orders unique from the base; Quartus re-wired builds fit the model")
    def _():
        import tpatch
        tpatch.OUT = OUT
        t = tpatch.Template("fsm3")          # raises (-> SKIP/FAIL) unless each order is unique
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__tpl-fsm3-*__vidorlo.rbf"))):
            spec = os.path.basename(f).split("__")[1][len("tpl-fsm3-"):]
            if spec == "asis":
                continue
            masks = [int(v, 16) for v in spec.split("-")]
            with open(f, "rb") as fh:
                ref = fh.read()
            for inst, m in zip(t.luts, masks):
                on = {c for c in lutpos._predict_phys(*t.les[inst])
                      if ref[32 + c[0] * 255 + c[1]] >> c[2] & 1}
                assert lutpos.perms_for_mask(on, *t.les[inst], m), f"{inst} in {spec}"
            n += 1
        return f"{n} builds" if n else ("SKIP", "no fsm3 builds")

    @check("templates: every template's base build identifies each LUT's input order uniquely")
    def _():
        import tpatch
        tpatch.OUT = OUT
        names = sorted(d for d in os.listdir(xdev.TEMPLATE_DIR)
                       if os.path.exists(os.path.join(xdev.TEMPLATE_DIR, d, "locs.qsf")))
        luts = fixed = 0
        for nm in names:
            t = tpatch.Template(nm, partial=True)     # chain-start LEs in arithmetic mode stay fixed
            luts += len(t.luts)
            fixed += len(t.fixed)
            import re
            src = open(os.path.join(xdev.TEMPLATE_DIR, nm, "top.v")).read()
            # Only arithmetic-mode LEs may stay fixed: chain starts and carry-only LEs (sum unused)
            # store less than the full mask, so their input order can't be read from the base.
            arith = {i for i in t.fixed if re.search(rf'"cin"[^;]*\)\s*\n?\s*{re.escape(i)}\s*\(', src)}
            assert t.fixed <= arith, f"{nm}: {sorted(t.fixed - arith)} not identified"
        return (f"{len(names)} templates, {luts} LUTs ({fixed} fixed arithmetic chain starts)"
                if names else ("SKIP", "no templates"))

    @check("m9kpatch: M9K ROM contents (all layouts) written byte-identical to Quartus")
    def _():
        import m9kpatch
        m9kpatch.OUT = OUT
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__rom*-*__vidorlo.rbf"))):
            tag = os.path.basename(f).split("__")[1]
            if tag.endswith("-zero"):
                continue
            if tag.startswith("rom2-"):
                _, wd, site, spec = tag.split("-", 3)
                w, d = (int(v) for v in wd.split("x"))
                zero = os.path.basename(f).replace(f"-{spec}__", "-zero__")[:-4]
                data, _ = m9kpatch.write(site, xdev.rom_words(spec, w, d), (w, d), zero, w)
            else:
                site, spec = tag[4:].rsplit("-", 1)
                data, _ = m9kpatch.write(site, [x & 15 for x in xdev.rom_words(spec)])
            with open(f, "rb") as fh:
                assert data == fh.read(), tag
            n += 1
        return f"{n} builds" if n else ("SKIP", "no ROM builds")

    @check("arithmetic mode: carry-only encodings (chain start, middle LE) on Quartus builds")
    def _():
        import carrytest
        n = 0
        for tname, slot, enc_fn, key in (("arith2", 0, carrytest.enc, lambda ms: ms[0] & 0xF),
                                          ("arith3", 2, carrytest.enc3, lambda ms: ms[1] & 0xFF)):
            for f in sorted(glob.glob(os.path.join(OUT, f"c10_016__tpl-{tname}-*__vidorlo.rbf"))):
                spec = os.path.basename(f).split("__")[1][len(f"tpl-{tname}-"):]
                if spec == "asis":
                    continue
                ms = [int(v, 16) for v in spec.split("-")]
                if tname == "arith3" and ms[0] != 0x11CC:
                    continue
                with open(f, "rb") as fh:
                    buf = fh.read()
                cells = lutpos._predict_phys(3, 1, slot)
                ph = sum((buf[32 + fr * 255 + p] >> b & 1) << i for i, (fr, p, b) in enumerate(cells))
                assert ph == enc_fn(key(ms)), os.path.basename(f)
                n += 1
        return f"{n} builds" if n else ("SKIP", "no arithmetic builds")

    @check("M9K RAM: initial contents written byte-identical to Quartus (ram: builds)")
    def _():
        import m9kpatch
        m9kpatch.OUT = OUT
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__ram-*__vidorlo.rbf"))):
            tag = os.path.basename(f).split("__")[1]
            site, spec = tag[4:].rsplit("-", 1)
            if spec == "zero":
                continue
            zero = os.path.basename(f).replace(f"-{spec}__", "-zero__")[:-4]
            data, _ = m9kpatch.write(site, [w & 1 for w in xdev.rom_words(spec)], (9, 512), zero, 1)
            with open(f, "rb") as fh:
                assert data == fh.read(), tag
            n += 1
        return f"{n} builds" if n else ("SKIP", "no RAM builds")

    @check("neighbour-LAB links: li_neighbour.json codes on xr: builds (dx = +/-1)")
    def _():
        import mux1cmap
        import re
        tab = json.load(open(os.path.join(HERE, "li_neighbour.json")))["links"]
        n = ok = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__xr-*_X*__vidor.rbf"))):
            m = re.search(r"__xr-(\d+)-(-?\d+)-(\d+)_X(\d+)Y(\d+)__", os.path.basename(f))
            if not m or m.group(2) not in ("1", "-1"):
                continue
            ns, dx, nd, x, y = (int(v) for v in m.groups())
            with open(f, "rb") as fh:
                got = sorted(map(list, mux1cmap.region(fh.read(), x + dx, y, nd)))
            n += 1
            ok += got == tab["+1" if dx > 0 else "-1"][str(ns)]
        if not n:
            return ("SKIP", "no xr builds")
        assert ok >= n - 2, f"{ok}/{n}"
        return f"{ok}/{n} builds (2 known misses at X20Y21)"

    @check("FF controls: ff_control.json per-register bits on ffe2: builds (sclr, sload, aclr)")
    def _():
        import re
        tab = json.load(open(os.path.join(HERE, "ff_control.json")))
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__ffe2-*_X*__vidor.rbf"))):
            m = re.search(r"__ffe2-(sclr|sload|aclr)-([0-9A-F])(?:-b(\d+))?_X(\d+)Y(\d+)__", os.path.basename(f))
            if not m:
                continue
            kind, k, base, x, y = m.group(1), int(m.group(2), 16), int(m.group(3) or 0), int(m.group(4)), int(m.group(5))
            c0 = lutpos._predict_phys(x, y, 0)
            f0, lo, bit = min(c[0] for c in c0), min(c[1] for c in c0), c0[0][2]
            col, df = (tab["aclr_enable"], 10) if kind == "aclr" else (tab["sync_enable"], 11)
            with open(f, "rb") as fh:
                buf = fh.read()
            got = []
            for i in range(4):
                p, pl = lo + col[base + i], bit
                if p < 1:                                   # byte wrap (threshold 1 for these bits)
                    pl += 1
                    p += 251 if pl >= 5 else 252
                got.append(buf[32 + (f0 + df) * 255 + p] >> pl & 1)
            assert got == [k >> i & 1 for i in range(4)], os.path.basename(f)
            n += 1
        return f"{n} builds" if n else ("SKIP", "no ffe2 builds")

    @check("LE output selects: le_output_select.json direct-line bit on oreg: builds")
    def _():
        import re
        tab = json.load(open(os.path.join(HERE, "le_output_select.json")))["bytes"]
        n = ok = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__oreg-*-0_X*__vidor.rbf"))):
            m = re.search(r"__oreg-(\d+)-0_X(\d+)Y(\d+)__", os.path.basename(f))
            s, x, y = (int(v) for v in m.groups())
            other = f.replace(f"oreg-{s}-0_", f"oreg-{s}-1_")
            if str(s) not in tab or not os.path.exists(other):
                continue
            c = lutpos._predict_phys(x, y, s)
            f0, lo, bit = min(v[0] for v in c), min(v[1] for v in c), c[0][2]
            with open(f, "rb") as fa, open(other, "rb") as fb:
                a, b = fa.read(), fb.read()
            off = 32 + (f0 + 9) * 255 + lo + tab[str(s)][1]
            n += 1
            ok += (a[off] >> bit & 1, b[off] >> bit & 1) == (1, 0)      # V=0: direct line comb; V=1: registered
        if not n:
            return ("SKIP", "no oreg builds")
        assert ok == n, f"{ok}/{n}"
        return f"{n} build pairs"

    @check("neighbour-LAB links: source driver bits (li_neighbour.json) set in xr: builds")
    def _():
        import re
        tab = json.load(open(os.path.join(HERE, "li_neighbour.json")))["src_driver_bits"]
        n = ok = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__xr-*_X*__vidor.rbf"))):
            m = re.search(r"__xr-(\d+)-(-?1)-(\d+)_X(\d+)Y(\d+)__", os.path.basename(f))
            if not m:
                continue
            ns, dx, _nd, x, y = (int(v) for v in m.groups())
            bits = tab["+1" if dx > 0 else "-1"].get(str(ns))
            if not bits:
                continue
            c = lutpos._predict_phys(x, y, ns)
            F0 = min(v[0] for v in lutpos._predict_phys(x, y, 0))
            lo, bit = min(v[1] for v in c), c[0][2]
            with open(f, "rb") as fh:
                buf = fh.read()
            n += 1
            ok += all(buf[32 + (F0 + df) * 255 + lo + db] >> bit & 1 for df, db in bits)
        if not n:
            return ("SKIP", "no xr builds")
        assert ok >= n - 2, f"{ok}/{n}"
        return f"{ok}/{n} builds (known miss at X20Y21)"

    @check("periphery: I/O settings rebuilt byte-identical (periph.py: x4 copies, CRC, header weight)")
    def _():
        import periph
        n = 0
        pairs = [(f"c10_016__iobase_X10Y10N0__vidor", f"c10_016__io{v}_X10Y10N0__vidor") for v in xdev.IO_VARIANTS if v != "base"]
        pairs += [(os.path.basename(f)[:-4].replace("__vidorlo", "__vidor"), os.path.basename(f)[:-4])
                  for f in sorted(glob.glob(os.path.join(OUT, "c10_016__lut*_X*__vidorlo.rbf")))[:40]]
        for a_name, b_name in pairs:
            a, b = xdev.load(OUT, a_name), xdev.load(OUT, b_name)
            if a is None or b is None:
                continue
            core_same = a[32 + 37 * 255:] == b[32 + 37 * 255:]
            if not core_same:
                continue
            assert periph.apply(a, periph.diff(a, b)) == b, b_name
            n += 1
        return f"{n} file pairs" if n else ("SKIP", "no io builds")

    @check("I/O tile: pull-up per pin (io_pullup.json) and drive offsets (io_tile.json) on iopin:/iopinq: builds")
    def _():
        import periph
        pu = json.load(open(os.path.join(HERE, "io_pullup.json")))["pullup"]
        tile = json.load(open(os.path.join(HERE, "io_tile.json")))["drive_8mA_to_4mA"]["changes"]
        n = 0
        for pin, (k, by, bit) in sorted(pu.items()):
            a = xdev.load(OUT, f"c10_016__iopin{pin}1_X10Y10N0__vidor")
            b = xdev.load(OUT, f"c10_016__iopin{pin}0_X10Y10N0__vidor")
            if a is not None and b is not None:
                assert periph.diff(a, b) == [(k, by, bit, 0)], pin
                assert periph.apply(a, [(k, by, bit, 0)]) == b, pin
                n += 1
            a = xdev.load(OUT, f"c10_016__iopinq{pin}8_X10Y10N0__vidor")
            b = xdev.load(OUT, f"c10_016__iopinq{pin}4_X10Y10N0__vidor")
            if a is not None and b is not None:
                ch = []
                for off, v in tile:
                    b2, k2 = by + off, k
                    if b2 > 252:
                        b2, k2 = b2 - 252, k + 1
                    ch.append((k2, b2, bit, v))
                assert periph.apply(a, ch) == b, pin
                n += 1
        return f"{n} pin probes" if n else ("SKIP", "no iopin builds")

    @check("global clocks: regional select model (gclk.json) on gclk: builds, E1 vs T8")
    def _():
        import re
        glob_ = {tuple(json.loads(k)) for k in json.load(open(os.path.join(HERE, "gclk.json")))["global"]}
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__gclkPIN_T8_X*__vidor.rbf"))):
            m = re.search(r"_X(\d+)Y(\d+)N0", f)
            x, y = int(m.group(1)), int(m.group(2))
            a = xdev.load(OUT, xdev.Job("c10_016", "gclk:PIN_E1", (x, y, 0), "vidor").name)
            if a is None:
                continue
            with open(f, "rb") as fh:
                b = fh.read()
            got = sorted(c for c in xdev.cells(a, b, rbfgeom.infer(a)) if c not in glob_)
            q = 487 if x <= 20 else 1592
            pred = [(q, 66, 5), (q, 235, 6)] if y <= 14 else [(q, 39, 1), (q, 209, 2)]
            sp = 488 if x <= 12 else 489 if x <= 20 else 1593 if x <= 29 else 1594
            lo, pl = lutpos.ROW[y]
            if y == 14:                                     # observed exception (gclk.json)
                pred += [(sp, bb, 4) for bb in (221, 223, 228, 229)]
                assert got == sorted(pred), f"X{x}Y{y}"
                n += 1
                continue
            for off in (0, 5, 6, 8):
                bb, pp = lo - 62 + off, pl
                if bb < 1:
                    pp += 1
                    bb += 251 if pp >= 5 else 252
                pred.append((sp, bb, pp))
            assert got == sorted(pred), f"X{x}Y{y}"
            n += 1
        return f"{n} LABs" if n else ("SKIP", "no gclk builds")

    @check("periph.py set: pull-up, bus hold, drive, open drain written byte-identical to Quartus")
    def _():
        import re
        import periph
        n = 0
        base = xdev.load(OUT, "c10_016__iobase_X10Y10N0__vidor")
        if base is None:
            return ("SKIP", "no io builds")
        for v, pin, k, val in [("q_bushold", "PIN_T2", "bushold", 1), ("a_bushold", "PIN_N3", "bushold", 1),
                               ("b_bushold", "PIN_P3", "bushold", 1), ("q_cur_4", "PIN_T2", "drive", 4),
                               ("c_nopu", "PIN_R3", "pullup", 0), ("d_nopu", "PIN_T3", "pullup", 0)]:
            assert periph.apply(base, periph.setting(pin, k, val)) == xdev.load(OUT, f"c10_016__io{v}_X10Y10N0__vidor"), v
            n += 1
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__ioxPIN_*q_od_X10Y10N0__vidor.rbf"))):
            pin = re.search(r"iox(PIN_[A-Z]\d+)q_od", f).group(1)
            a = xdev.load(OUT, f"c10_016__iox{pin}q_plain_X10Y10N0__vidor")
            with open(f, "rb") as fh:
                assert periph.apply(a, periph.setting(pin, "opendrain", 1)) == fh.read(), pin
            n += 1
        return f"{n} settings"

    @check("PLL: f = 48 MHz * M / (N * C0) from the counter fields (pll.json) on pll: builds")
    def _():
        import periph
        from fractions import Fraction
        n = 0
        for f in sorted(glob.glob(os.path.join(OUT, "c10_016__pll*__vidor.json"))):
            meta = json.load(open(f))
            buf = xdev.load(OUT, meta["job"])
            if not meta.get("ok") or buf is None or not meta["design"].startswith("pll:"):
                continue
            L = periph.logical(buf, rbfgeom.infer(buf))
            bits = lambda start, k: sum((L[0][start + i] >> 1 & 1) << i for i in range(k))
            count = lambda b: 1 if bits(b + 17, 1) else bits(b, 8) + bits(b + 9, 8)   # 18-byte counter block
            m, nn, c = count(175), count(193), count(157)
            mm, dd = (int(v) for v in meta["design"].split(":")[1:3])
            assert Fraction(48 * m, nn * c) == Fraction(48 * mm, dd), meta["design"]
            n += 1
        return f"{n} builds" if n else ("SKIP", "no pll builds")

    w = max(len(n) for _, n, _ in results)
    for status, n, info in results:
        print(f"[{status}] {n:{w}s}  {info}")
    return 1 if any(s == "FAIL" for s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
