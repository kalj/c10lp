#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-device Quartus campaign: Cyclone IV E vs Cyclone 10 LP.

Run on the machine with Quartus Prime Lite.  Builds tiny designs for several
devices, caches the uncompressed .rbf files, and reports how the bitstreams
relate (same die? same LUT bits?).  Only Quartus output is analysed; Quartus
itself is never inspected.

Subcommands
  parts                       list installed Cyclone IV E / 10 LP part names
  plan    [build options]     print the compile list and a time estimate, build nothing
  build   [build options]     compile everything that is not cached yet
  sweep   --device D --loc X,Y,N
                              16 single-minterm LUTs + mask 0 at one LE (LUT calibration)
  report                      analyse everything in --out

Typical first session (about 14 compiles):
  python3 xdev.py parts
  python3 xdev.py plan
  python3 xdev.py build --jobs 2
  python3 xdev.py report

Environment: QUARTUS_BIN (default ~/intelFPGA_lite/21.1/quartus/bin).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rbfgeom  # noqa: E402

QUARTUS_BIN = os.environ.get("QUARTUS_BIN",
                             os.path.expanduser("~/intelFPGA_lite/21.1/quartus/bin"))
HERE = os.path.dirname(os.path.abspath(__file__))

# Determinism settings copied from Cyclone_CRAM_Mapper fuzz/config.py.
QSF_OPTIMIZATIONS_OFF = [
    ("AUTO_RAM_RECOGNITION", "OFF"),
    ("AUTO_DSP_RECOGNITION", "OFF"),
    ("AUTO_SHIFT_REGISTER_RECOGNITION", "OFF"),
    ("ALLOW_REGISTER_RETIMING", "OFF"),
    ("SYNTH_TIMING_DRIVEN_SYNTHESIS", "OFF"),
    ("PHYSICAL_SYNTHESIS_COMBO_LOGIC", "OFF"),
    ("PHYSICAL_SYNTHESIS_REGISTER_DUPLICATION", "OFF"),
    ("PHYSICAL_SYNTHESIS_REGISTER_RETIMING", "OFF"),
    ("FITTER_EFFORT", '"STANDARD FIT"'),
    ("OPTIMIZE_HOLD_TIMING", "OFF"),
    ("OPTIMIZE_MULTI_CORNER_TIMING", "OFF"),
    ("ROUTER_TIMING_OPTIMIZATION_LEVEL", "MINIMUM"),
]

# Device aliases.  Part names that your Quartus does not know are reported
# as build failures; run `parts` and add the right names with --device.
DEVICES = {
    "ce6":    ("Cyclone IV E",  "EP4CE6F17C8"),
    "c10_006": ("Cyclone 10 LP", "10CL006YU256C8G"),
    "ce15":   ("Cyclone IV E",  "EP4CE15F17C8"),
    "ce15u":  ("Cyclone IV E",  "EP4CE15U14I7"),      # same U256 package as the Vidor part
    "c10_016": ("Cyclone 10 LP", "10CL016YU256C8G"),  # Arduino MKR Vidor 4000
}
PRIM = {"Cyclone IV E": "cycloneive", "Cyclone 10 LP": "cyclone10lp"}

# Vidor MKR header pins (from vidor-libraries/VidorFPGA vidor_s_pins.qsf).
# These balls are also wired to SAMD21 GPIOs: see README before driving them.
VIDOR_PINS = {"A": "PIN_N3",   # bMKR_D[1]
              "B": "PIN_P3",   # bMKR_D[2]
              "C": "PIN_R3",   # bMKR_D[3]
              "D": "PIN_T3",   # bMKR_D[4]
              "Q": "PIN_T2"}   # bMKR_D[5]
# AX301 pins used by the repo's EP4CE6 corpus (fuzz/config.py FUZZ_PINS).
AX301_PINS = {"A": "PIN_E16", "B": "PIN_M16", "C": "PIN_M15",
              "D": "PIN_E15", "Q": "PIN_G15"}

DEFAULT_DEVICES = ["ce6", "c10_006", "ce15", "ce15u", "c10_016"]
DEFAULT_DESIGNS = ["wire", "lut:0000", "lut:FFFF", "lut:8888"]
DEFAULT_LOC = (10, 10, 0)
# Control: rebuild a pair that exists in the repo's results/golden_rbf_modeH/,
# using that script's exact Verilog/QSF (pins="repo", see repo_project()).
CONTROL = [("ce6", "lut:0000", (10, 2, 0), "repo"),
           ("ce6", "lut:DEAD", (10, 2, 0), "repo")]
# Cross-device pairs to diff in `report`.
PAIRS = [("ce6", "c10_006"), ("ce15", "c10_016"), ("ce15u", "c10_016"), ("ce6", "ce15")]


# User templates ("tpl:NAME:SPEC"): templates/NAME/top.v is any netlist of
# <family>_lcell_comb instances (+ registers) on ports A, B, C, D -> Q.  SPEC is
# "asis" (masks as written, unplaced) or one hex mask per LUT instance in file
# order, joined by "-"; then templates/NAME/locs.qsf (back-annotated placement)
# pins every cell.  See tpatch.py.
TEMPLATE_DIR = os.path.join(HERE, "templates")
_LUT_RE = re.compile(r"(_lcell_comb\s*#\(\s*\.lut_mask\(16'h)([0-9A-Fa-f]{4})(\).*?\)\s*)(\w+)(\s*\()",
                     re.S)


def tpl_luts(name: str) -> list[tuple[str, int]]:
    """(instance, mask as written) for each LUT of template NAME, in file order."""
    src = open(os.path.join(TEMPLATE_DIR, name, "top.v")).read()
    return [(m.group(4), int(m.group(2), 16)) for m in _LUT_RE.finditer(src)]


def tpl_verilog(name: str, spec: str) -> str:
    src = open(os.path.join(TEMPLATE_DIR, name, "top.v")).read()
    if spec == "asis":
        return src
    masks = iter(int(v, 16) for v in spec.split("-"))
    return _LUT_RE.sub(lambda m: f"{m.group(1)}{next(masks):04X}{m.group(3)}{m.group(4)}{m.group(5)}",
                       src)


# Multi-LUT template ("tree:M0-M1-M2-M3-MF"): four first-level LUTs on A..D, spread
# over the die, feeding one final LUT whose output drives Q.
TREE_LOCS = [(10, 10, 0), (30, 20, 12), (22, 8, 6), (36, 23, 30), (16, 21, 14)]


@dataclass(frozen=True)
class Job:
    dev: str
    design: str           # "wire" | "lut:XXXX" | "ff:base|hi|ena|sclr" (loc N odd) | "tree:M0-..-MF" | "reg:XXXX"
    loc: tuple[int, int, int]
    pins: str = "vidor"   # "vidor" | "ax301"

    @property
    def name(self) -> str:
        d = self.design.replace(":", "")
        if self.design.startswith(("xr:", "xr3:")):
            _, ns, dx, nd, *dy = self.design.split(":")
            dy = f"-y{dy[0]}" if dy else ""
            head = self.design.split(":")[0]
            return f"{self.dev}__{head}-{ns}-{dx}-{nd}{dy}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("oreg:"):
            _, sl, vv, *dd = self.design.split(":")
            vv += "".join(f"-{v}" for v in dd)
            return f"{self.dev}__oreg-{sl}-{vv}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("ffc:"):
            _, kind, sl = self.design.split(":")
            return f"{self.dev}__ffc-{kind}-{sl}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("ffe2:"):
            _, kind, k, *b = self.design.split(":")
            k += f"-b{b[0]}" if b else ""
            return f"{self.dev}__ffe2-{kind}-{k}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("ffe:"):
            _, kind, k = self.design.split(":")
            return f"{self.dev}__ffe-{kind}-{k}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("chain:"):
            _, mode, spec = self.design.split(":")
            return f"{self.dev}__chain-{mode}-{spec}_X{self.loc[0]}Y{self.loc[1]}N{self.loc[2]}__{self.pins}"
        if self.design.startswith("ram:"):
            _, site, spec = self.design.split(":")
            return f"{self.dev}__ram-{site}-{spec}__{self.pins}"
        if self.design.startswith("rom2:"):
            _, wd, site, spec = self.design.split(":")
            return f"{self.dev}__rom2-{wd}-{site}-{spec}__{self.pins}"
        if self.design.startswith("rom:"):
            _, site, spec = self.design.split(":")
            return f"{self.dev}__rom-{site}-{spec}__{self.pins}"
        if self.design.startswith("tpl:"):
            _, tname, spec = self.design.split(":")
            return f"{self.dev}__tpl-{tname}-{spec}__{self.pins}"
        if self.design.startswith(("mux1p:", "mux1c:")):
            kind, d, a, k = self.design.split(":")
            return f"{self.dev}__{kind}-{d}-{a}-{k}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith(("mux4:", "mux4x:", "mux4d:")):
            kind, d, srcs = self.design.split(":")
            return f"{self.dev}__{kind}-{d}-{srcs}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith(("mux:", "mux1:")):
            kind, a, d, sel = self.design.split(":")
            return f"{self.dev}__{kind}-{a}-{d}-{sel}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        if self.design.startswith("lab2:"):
            _, ns, nd = self.design.split(":")
            dy = f"dy{self.loc[2]}" if self.loc[2] else ""
            return f"{self.dev}__lab2-{ns}-{nd}{dy}_X{self.loc[0]}Y{self.loc[1]}__{self.pins}"
        loc = ("" if self.design == "wire" or self.design.startswith("tree:")
               else f"_X{self.loc[0]}Y{self.loc[1]}N{self.loc[2]}")
        return f"{self.dev}__{d}{loc}__{self.pins}"


def repo_project(job: Job) -> tuple[str, str, str]:
    """(project name, Verilog, QSF) copied from the repo's
    scripts/handoff_modeh/build_d1_golden.py, so the control can be compared
    byte for byte with results/golden_rbf_modeH/."""
    x, y, n = job.loc
    mask = int(job.design.split(":")[1], 16)
    name = f"X{x}_Y{y}_N{n}_mask{mask:04X}_q211"
    v = f"""\
module {name} (input KEY1, input KEY2, input KEY3, input KEY4, output LED0);
    wire combout;
    cycloneive_lcell_comb #(
        .lut_mask(16'h{mask:04X}),
        .sum_lutc_input("datac"),
        .lpm_type("cycloneive_lcell_comb")
    ) le_inst (
        .dataa(KEY1),
        .datab(KEY2),
        .datac(KEY3),
        .datad(KEY4),
        .cin(1'b0),
        .combout(combout),
        .cout()
    );
    assign LED0 = combout;
endmodule
"""
    q = f"""\
set_global_assignment -name FAMILY "Cyclone IV E"
set_global_assignment -name DEVICE EP4CE6F17C8
set_global_assignment -name TOP_LEVEL_ENTITY {name}
set_global_assignment -name VERILOG_FILE {name}.v
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name SEED 1
set_global_assignment -name STRATIX_DEVICE_IO_STANDARD "3.3-V LVTTL"
set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED WITH WEAK PULL-UP"
set_global_assignment -name CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION "USE AS REGULAR IO"
set_location_assignment PIN_E15 -to KEY1
set_location_assignment PIN_E16 -to KEY2
set_location_assignment PIN_M16 -to KEY3
set_location_assignment PIN_M15 -to KEY4
set_location_assignment PIN_G15 -to LED0
set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to "le_inst"
"""
    return name, v, q


def verilog(job: Job) -> str:
    fam = DEVICES[job.dev][0]
    if job.design.startswith("iopin:"):
        return verilog(Job(job.dev, "lut:6996", job.loc, job.pins))
    if job.design.startswith("io:"):
        # io:VARIANT: lut:6996 at job.loc with one I/O setting changed (IO_VARIANTS)
        return verilog(Job(job.dev, "lut:6996", job.loc, job.pins))
    if job.design == "wire":
        return ("module fuzz_top(input wire A, B, C, D, output wire Q);\n"
                "  assign Q = A;\nendmodule\n")
    if job.design.startswith("tree:"):
        m = [int(v, 16) for v in job.design[5:].split("-")]
        cells = []
        for i in range(4):
            cells.append(f"""  {PRIM[fam]}_lcell_comb #(.lut_mask(16'h{m[i]:04X}), .sum_lutc_input("datac"),
    .dont_touch("on")) l{i} (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t[{i}]));""")
        cells.append(f"""  {PRIM[fam]}_lcell_comb #(.lut_mask(16'h{m[4]:04X}), .sum_lutc_input("datac"),
    .dont_touch("on")) lf (.dataa(t[0]), .datab(t[1]), .datac(t[2]), .datad(t[3]), .combout(Q));""")
        return ("module fuzz_top(input wire A, B, C, D, output wire Q);\n  wire [3:0] t;\n"
                + "\n".join(cells) + "\nendmodule\n")
    if job.design.startswith(("xr:", "xr3:")):
        # xr:NS:DX:ND[:DY]: source LE (slot NS, pins A..D) in LAB (x, y); dst LE (slot ND) in LAB (x+DX, y)
        # reads only the source (dataa), other inputs unconnected; dst -> Q.  One net crosses LABs.
        # xr3: the same, but dst = t & (A | B), so the source must take another physical input.
        p = PRIM[fam]
        three = job.design.startswith("xr3:")
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire t;
  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  {p}_lcell_comb #(.lut_mask(16'h{"A8A8" if three else "5555"}), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa(t), {".datab(A), .datac(B), " if three else ""}.combout(Q));
endmodule
"""
    if job.design.startswith("oreg:"):
        # oreg:S:V: src LE at slot S (LUT of pins + its FF, clock B). dst1 (slot 20) and dst2 (slot 24) in the same LAB read
        # src's combinational and registered outputs on dataa: V=0 dst1 <- comb, dst2 <- reg; V=1 swapped.  Q = dst1 ^ dst2 (qo).
        _, sl, vv, *_dsts = job.design.split(":")
        p = PRIM[fam]
        a, b = {"0": ("c", "q"), "1": ("q", "c"), "2": ("q", "q")}[vv]     # V=2: both read the FF
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire c, q, o1, o2;
  {p}_lcell_comb #(.lut_mask(16'h9696), .sum_lutc_input("datac"), .dont_touch("on"))
    src (.dataa(A), .datab(C), .datac(D), .combout(c));
  dffeas fs (.d(c), .clk(B), .ena(1'b1), .sclr(1'b0), .clrn(1'b1), .prn(1'b1), .sload(1'b0), .asdata(1'b0), .q(q));
  {p}_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) d1 (.dataa({a}), .combout(o1));
  {p}_lcell_comb #(.lut_mask(16'h3333), .sum_lutc_input("datac"), .dont_touch("on")) d2 (.datab({b}), .combout(o2));
  {p}_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on")) qo (.dataa(o1), .datab(o2), .combout(Q));
endmodule
"""
    if job.design.startswith("ffc:"):
        # ffc:KIND:S: ffe2:KIND:F, but the control comes from an LE in the same LAB (slot S, t = C ^ D) instead of the pin C,
        # so the control-line mux has a known local source.
        _, kind, sl = job.design.split(":")
        v = verilog(Job(job.dev, f"ffe2:{kind}:F", job.loc, job.pins))
        v = v.replace("  wire [3:0] d, r;", "  wire [3:0] d, r;\n  wire t;\n"
                      f"  {PRIM[fam]}_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                      "    ctl (.dataa(C), .datab(D), .combout(t));")
        for port in ("ena", "sclr", "clrn", "clk"):
            v = v.replace(f".{port}(C)", f".{port}(t)")
        return v
    if job.design.startswith("ffe2:"):
        # ffe2:KIND:K[:BASE]: like ffe:, on LEs BASE..BASE+3 (default 0), but with dffeas primitives (so Quartus can't fold the control into the
        # LUT) and a pinned parity LUT that also reads C, so C is routed into the LAB in every variant.
        _, kind, kk = job.design.split(":")[:3]
        k = int(kk, 16)
        p = PRIM[fam]
        L = ["module fuzz_top(input wire A, B, C, D, output wire Q);", "  wire [3:0] d, r;"]
        masks = ["6666", "8888", "EEEE", "9999"]
        for i in range(4):
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h{masks[i]}), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     f"    l{i} (.dataa(A), .datab(D), .combout(d[{i}]));")
            use = k >> i & 1
            ena = "C" if use and kind == "ena" else "1'b1"
            sclr = "C" if use and kind == "sclr" else "1'b0"
            clrn = "C" if use and kind == "aclr" else "1'b1"
            sload, asdata = ("C", "A") if use and kind == "sload" else ("1'b0", "1'b0")
            clk = "C" if use and kind == "clk" else "B"
            L.append(f"  dffeas f{i} (.d(d[{i}]), .clk({clk}), .ena({ena}), .sclr({sclr}), .clrn({clrn}), .prn(1'b1),"
                     f" .sload({sload}), .asdata({asdata}), .q(r[{i}]));")
        if kind == "osel":                      # parity reads r[i] if bit i of K, else d[i]; all FFs kept
            L[1] = "  wire [3:0] d, r, s;"
            L.extend(f"  assign s[{i}] = {'r' if k >> i & 1 else 'd'}[{i}];" for i in range(4))
            L.append("  wire pa, an;")
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     "    par (.dataa(s[0]), .datab(s[1]), .datac(s[2]), .datad(s[3]), .combout(pa));")
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'hFFFE), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     "    anyr (.dataa(r[0]), .datab(r[1]), .datac(r[2]), .datad(r[3]), .combout(an));")
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     "    qo (.dataa(pa), .datab(an), .combout(Q));")
        else:
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     "    par (.dataa(r[0]), .datab(r[1]), .datac(r[2]), .datad(r[3] ^ C), .combout(Q));")
        L.append("endmodule")
        return "\n".join(L) + "\n"
    if job.design.startswith("ffe:"):
        # ffe:KIND:K: four registers r0..r3 (D = LUT of A, B in the same LE), clock B; register i uses the
        # control C (KIND "ena": clock enable, "sclr": synchronous clear) iff bit i of K is set.
        # Q = parity of r0..r3.
        _, kind, kk = job.design.split(":")
        k = int(kk, 16)
        p = PRIM[fam]
        L = ["module fuzz_top(input wire A, B, C, D, output wire Q);", "  reg [3:0] r = 4'd0;", "  wire [3:0] d;"]
        masks = ["6666", "8888", "EEEE", "9999"]
        for i in range(4):
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h{masks[i]}), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
                     f"    l{i} (.dataa(A), .datab(D), .combout(d[{i}]));")
            if k >> i & 1:
                body = f"if (C) r[{i}] <= d[{i}];" if kind == "ena" else f"if (C) r[{i}] <= 1'b0; else r[{i}] <= d[{i}];"
            else:
                body = f"r[{i}] <= d[{i}];"
            L.append(f"  always @(posedge B) {body}")
        L.append("  assign Q = ^r;")
        L.append("endmodule")
        return "\n".join(L) + "\n"
    if job.design.startswith("chain:"):
        # chain:MODE:M0-M1-M2-M3: four LEs in one LAB, dataa = A, datab = B (LE 0..3 also see C, D
        # on datad).  MODE "arith" links cout -> cin (arithmetic mode); "plain" leaves cin unused.
        _, mode, spec = job.design.split(":")
        ms = [int(v, 16) for v in spec.split("-")]
        p = PRIM[fam]
        L = ["module fuzz_top(input wire A, B, C, D, output wire Q);", "  wire [3:0] y; wire [4:0] c;",
             ]
        for i, m in enumerate(ms):
            cin = ((f", .cin(c[{i}])" if i else "") + f", .cout(c[{i + 1}])") if mode == "arith" else ""
            sumc = '"cin"' if mode == "arith" else '"datac"'
            datac = ""                       # same inputs (A, B, D) in both modes
            L.append(f"  {p}_lcell_comb #(.lut_mask(16'h{m:04X}), .sum_lutc_input({sumc}), .dont_touch(\"on\"))\n"
                     f"    e{i} (.dataa(A), .datab(B){datac}, .datad(D){cin}, .combout(y[{i}]));")
        L.append("  assign Q = ^y;")
        L.append("endmodule")
        return "\n".join(L) + "\n"
    if job.design.startswith("ram:"):
        # ram:SITE:SPEC: 9x512 single-port RAM, address = 9-bit counter (clock B, enable A), write enable =
        # D (D4), write data = {9{C}} (D3).  Q = q[0] (read-during-write: old data).
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  reg [8:0] a = 9'd0;
  always @(posedge B) if (A) a <= a + 9'd1;
  wire [8:0] q;
  altsyncram #(.operation_mode("SINGLE_PORT"), .width_a(9), .widthad_a(9), .numwords_a(512),
    .lpm_type("altsyncram"), .ram_block_type("M9K"), .outdata_reg_a("UNREGISTERED"),
    .read_during_write_mode_port_a("OLD_DATA"),
    .init_file("rom.mif"), .intended_device_family("{fam}")) u (
    .clock0(B), .address_a(a), .wren_a(D), .data_a({{9{{C}}}}), .q_a(q));
  assign Q = q[0];
endmodule
"""
    if job.design.startswith("rom2:"):
        # General M9K ROM layout W x D: an address counter (D2 clock, D1 enable) and
        # D5 = parity of all W output bits, so Quartus stores every bit.
        _, wd, _site, _spec = job.design.split(":")
        w, d = (int(v) for v in wd.split("x"))
        ab = (d - 1).bit_length()
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  reg [{ab - 1}:0] a = {ab}'d0;
  always @(posedge B) if (A) a <= a + {ab}'d1;
  wire [{w - 1}:0] q;
  altsyncram #(.operation_mode("ROM"), .width_a({w}), .widthad_a({ab}), .numwords_a({d}),
    .lpm_type("altsyncram"), .ram_block_type("M9K"), .outdata_reg_a("UNREGISTERED"),
    .init_file("rom.mif"), .intended_device_family("{fam}")) u (
    .clock0(B), .address_a(a), .q_a(q));
  assign Q = ^q;
endmodule
"""
    if job.design.startswith("rom:"):
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  reg [8:0] a = 9'd0;
  always @(posedge B) if (A) a <= a + 9'd1;
  wire [8:0] q;
  altsyncram #(.operation_mode("ROM"), .width_a(9), .widthad_a(9), .numwords_a(512),
    .lpm_type("altsyncram"), .ram_block_type("M9K"), .outdata_reg_a("UNREGISTERED"),
    .init_file("rom.mif"), .intended_device_family("{fam}")) u (
    .clock0(B), .address_a(a), .q_a(q));
  assign Q = C ? (D ? q[3] : q[2]) : (D ? q[1] : q[0]);
endmodule
"""
    if job.design.startswith("tpl:"):
        _, tname, spec = job.design.split(":")
        return tpl_verilog(tname, spec)
    if job.design.startswith("mux4d:"):
        # Three local sources; dst's ports = (t0, t0, t1, t2): two inputs share source 0.
        p = PRIM[fam]
        srcs = "\n".join(f"""  {p}_lcell_comb #(.lut_mask(16'h{m:04X}), .sum_lutc_input("datac"), .dont_touch("on"))
    s{i} (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t[{i}]));"""
                          for i, m in enumerate((0x6996, 0x96A5, 0x1E78)))
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire [2:0] t;
{srcs}
  {p}_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa(t[0]), .datab(t[0]), .datac(t[1]), .datad(t[2]), .combout(Q));
endmodule
"""
    if job.design.startswith("mux1c:"):
        # One local source (slot a) on dst logical port k; dst's other ports tied to 0 (dont_touch).
        _, sd, sa, k = job.design.split(":")
        p = PRIM[fam]
        ports = ["1'b0"] * 3
        ports.insert(int(k), "t")
        conn = ", ".join(f".data{c}({v})" for c, v in zip("abcd", ports))
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire t;
  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  {p}_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    dst ({conn}, .combout(Q));
endmodule
"""
    if job.design.startswith("mux1p:"):
        # One local source (slot a, pins A..D) on dst logical port k; dst's other ports = pins B, C, D.
        _, sd, sa, k = job.design.split(":")
        p = PRIM[fam]
        ports = ["B", "C", "D"]
        ports.insert(int(k), "t")
        conn = ", ".join(f".data{c}({v})" for c, v in zip("abcd", ports))
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire t;
  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  {p}_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    dst ({conn}, .combout(Q));
endmodule
"""
    if job.design.startswith(("mux4:", "mux4x:")):
        # Four sources at known slots drive dst's four inputs; dst's mask (3CEC) reveals which
        # physical input each source landed on.  Q = dst.
        p = PRIM[fam]
        srcs = "\n".join(f"""  {p}_lcell_comb #(.lut_mask(16'h{m:04X}), .sum_lutc_input("datac"), .dont_touch("on"))
    s{i} (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t[{i}]));"""
                          for i, m in enumerate((0x6996, 0x96A5, 0x1E78, 0x7BD2)))
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire [3:0] t;
{srcs}
  {p}_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa(t[0]), .datab(t[1]), .datac(t[2]), .datad(t[3]), .combout(Q));
endmodule
"""
    if job.design.startswith("mux1:"):
        # Like "mux", but only dst.dataa comes from the selected source; datab..d are pins B..D.
        # dst's mask is asymmetric (unique input order), so its LUT cells say which physical
        # input carries the selected source.
        sel = job.design.split(":")[3]
        t = "ta" if sel == "A" else "tb"
        p = PRIM[fam]
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire ta, tb, k, d;
  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    srca (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(ta));
  {p}_lcell_comb #(.lut_mask(16'h96A5), .sum_lutc_input("datac"), .dont_touch("on"))
    srcb (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(tb));
  {p}_lcell_comb #(.lut_mask(16'h1E78), .sum_lutc_input("datac"), .dont_touch("on"))
    keep (.dataa(ta), .datab(tb), .datac(A), .datad(B), .combout(k));
  {p}_lcell_comb #(.lut_mask(16'h3CEC), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa({t}), .datab(B), .datac(C), .datad(D), .combout(d));
  {p}_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    outl (.dataa(d), .datab(k), .datac(C), .datad(D), .combout(Q));
endmodule
"""
    if job.design.startswith("mux:"):
        # srcA (slot a) and srcB (slot 30) both feed a keeper (slot 28); dst (slot d) takes all
        # four inputs from one of them (sel A/B); Q = out(dst, keeper) at slot 26.  Two builds
        # differing in sel differ only in dst's input-mux selects.
        sel = job.design.split(":")[3]
        t = "ta" if sel == "A" else "tb"
        p = PRIM[fam]
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire ta, tb, k, d;
  {p}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    srca (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(ta));
  {p}_lcell_comb #(.lut_mask(16'h96A5), .sum_lutc_input("datac"), .dont_touch("on"))
    srcb (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(tb));
  {p}_lcell_comb #(.lut_mask(16'h1E78), .sum_lutc_input("datac"), .dont_touch("on"))
    keep (.dataa(ta), .datab(tb), .datac(A), .datad(B), .combout(k));
  {p}_lcell_comb #(.lut_mask(16'h8001), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa({t}), .datab({t}), .datac({t}), .datad({t}), .combout(d));
  {p}_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    outl (.dataa(d), .datab(k), .datac(C), .datad(D), .combout(Q));
endmodule
"""
    if job.design.startswith("lab2:"):
        # src LUT (pins A..D) -> all four inputs of dst LUT, both in LAB (x, y): local routing.
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire t;
  {PRIM[fam]}_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  {PRIM[fam]}_lcell_comb #(.lut_mask(16'h8001), .sum_lutc_input("datac"), .dont_touch("on"))
    dst (.dataa(t), .datab(t), .datac(t), .datad(t), .combout(Q));
endmodule
"""
    if job.design.startswith("reg:"):
        # LUT -> register in one LE, with the register fed back into the LUT:
        # next = mask(a=A, b=C, c=D, d=state), clocked by B, state on Q.
        mask = int(job.design[4:], 16)
        return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  reg r;
  wire l;
  {PRIM[fam]}_lcell_comb #(
    .lut_mask(16'h{mask:04X}),
    .sum_lutc_input("datac"),
    .dont_touch("on")
  ) lut_inst (
    .dataa(A), .datab(C), .datac(D), .datad(r),
    .combout(l)
  );
  always @(posedge B) r <= l;
  assign Q = r;
endmodule
"""
    if job.design.startswith("ff:"):
        # One register at a pinned FF site: D = A, clock = B, C = enable or sync clear.
        body = {"base": "r <= A;", "hi": "r <= A;", "ena": "if (C) r <= A;",
                "sclr": "if (C) r <= 1'b0; else r <= A;"}[job.design[3:]]
        return ("module fuzz_top(input wire A, B, C, D, output wire Q);\n"
                "  reg r;\n"
                f"  always @(posedge B) {body}\n"
                "  assign Q = r;\nendmodule\n")
    mask = int(job.design.split(":")[1], 16)
    return f"""module fuzz_top(input wire A, B, C, D, output wire Q);
  wire lut_out;
  {PRIM[fam]}_lcell_comb #(
    .lut_mask(16'h{mask:04X}),
    .sum_lutc_input("datac"),
    .dont_touch("on")
  ) lut_inst (
    .dataa(A), .datab(B), .datac(C), .datad(D),
    .combout(lut_out)
  );
  assign Q = lut_out;
endmodule
"""


# I/O-cell probes (design io:VARIANT): extra assignments on top of the "vidor" pin set.
IO_VARIANTS = {
    "base": [],
    "q_cur_min": ['set_instance_assignment -name CURRENT_STRENGTH_NEW "MINIMUM CURRENT" -to Q'],
    "q_cur_4": ['set_instance_assignment -name CURRENT_STRENGTH_NEW 4MA -to Q'],
    "q_cur_8": ['set_instance_assignment -name CURRENT_STRENGTH_NEW 8MA -to Q'],
    "q_cur_16": ['set_instance_assignment -name CURRENT_STRENGTH_NEW 16MA -to Q'],
    "q_slew_0": ["set_instance_assignment -name SLEW_RATE 0 -to Q"],
    "q_slew_1": ["set_instance_assignment -name SLEW_RATE 1 -to Q"],
    "q_lvcmos": ['set_instance_assignment -name IO_STANDARD "3.3-V LVCMOS" -to Q'],
    "q_2v5": ['set_instance_assignment -name IO_STANDARD "2.5 V" -to Q'],
    "q_pu": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to Q"],
    "q_bushold": ["set_instance_assignment -name ENABLE_BUS_HOLD_CIRCUITRY ON -to Q"],
    "a_nopu": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to A"],
    "a_bushold": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to A",
                  "set_instance_assignment -name ENABLE_BUS_HOLD_CIRCUITRY ON -to A"],
    "b_nopu": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to B"],
    "c_nopu": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to C"],
    "d_nopu": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to D"],
    "b_bushold": ["set_instance_assignment -name WEAK_PULL_UP_RESISTOR OFF -to B",
                  "set_instance_assignment -name ENABLE_BUS_HOLD_CIRCUITRY ON -to B"],
    "a_lvcmos": ['set_instance_assignment -name IO_STANDARD "3.3-V LVCMOS" -to A'],
    "a_2v5": ['set_instance_assignment -name IO_STANDARD "2.5 V" -to A'],
}


def qsf(job: Job) -> str:
    fam, part = DEVICES[job.dev]
    vidor = job.pins in ("vidor", "vidorlo")
    pins = VIDOR_PINS if vidor else AX301_PINS
    if job.design.startswith("iopin:"):            # iopin:PIN:PU: input A moved to PIN, pull-up PU (0/1)
        pins = dict(pins, A=job.design.split(":")[1])
    L = [f'set_global_assignment -name FAMILY "{fam}"',
         f"set_global_assignment -name DEVICE {part}",
         "set_global_assignment -name TOP_LEVEL_ENTITY fuzz_top",
         "set_global_assignment -name VERILOG_FILE fuzz_top.v",
         "set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files",
         "set_global_assignment -name MIN_CORE_JUNCTION_TEMP 0",
         "set_global_assignment -name MAX_CORE_JUNCTION_TEMP 85",
         "set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 1",
         'set_global_assignment -name STRATIX_DEVICE_IO_STANDARD "3.3-V LVTTL"',
         "set_global_assignment -name SEED 1"]
    L += [f"set_global_assignment -name {k} {v}" for k, v in QSF_OPTIMIZATIONS_OFF]
    for sig, pin in pins.items():
        L.append(f"set_location_assignment {pin} -to {sig}")
    if vidor:
        # Inputs float on the MKR header; pull-ups let a jumper to GND drive them.
        for sig in "ABCD":
            L.append(f"set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to {sig}")
    if job.pins == "vidorlo":
        # Hardware-test variant: the header pins are shared with SAMD21 GPIOs, so
        # drive Q as weakly as the I/O standard allows to limit any contention.
        L.append('set_instance_assignment -name CURRENT_STRENGTH_NEW "MINIMUM CURRENT" -to Q')
    if job.design.startswith("iopin:"):
        x, y, nn = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{nn} -to "lut_inst"')
        L.append(f'set_instance_assignment -name WEAK_PULL_UP_RESISTOR {"ON" if job.design.split(":")[2] == "1" else "OFF"} -to A')
    elif job.design.startswith("io:"):
        x, y, nn = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{nn} -to "lut_inst"')
        L += IO_VARIANTS[job.design.split(":")[1]]
    elif job.design.startswith(("xr:", "xr3:")):
        _, ns, dx, nd, *dy = job.design.split(":")
        x, y, _n = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{ns} -to "src"')
        L.append(f'set_location_assignment LCCOMB_X{x + int(dx)}_Y{y + int(dy[0]) if dy else y}_N{nd} -to "dst"')
    elif job.design.startswith("oreg:"):
        x, y, _n = job.loc
        f = job.design.split(":")
        sl = int(f[1])
        n1, n2, nq = (int(v) for v in f[3:6]) if len(f) > 3 else (20, 24, 28)
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{sl} -to "src"')
        L.append(f'set_location_assignment FF_X{x}_Y{y}_N{sl + 1} -to "fs"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n1} -to "d1"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n2} -to "d2"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{nq} -to "qo"')
    elif job.design.startswith("ffc:"):
        x, y, _n = job.loc
        for i in range(4):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * i} -to "l{i}"')
            L.append(f'set_location_assignment FF_X{x}_Y{y}_N{2 * i + 1} -to "f{i}"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N16 -to "par"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{job.design.split(":")[2]} -to "ctl"')
    elif job.design.startswith("ffe2:"):
        x, y, _n = job.loc
        base = int((job.design.split(":") + ["0"])[3])
        for i in range(4):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * (base + i)} -to "l{i}"')
            L.append(f'set_location_assignment FF_X{x}_Y{y}_N{2 * (base + i) + 1} -to "f{i}"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{16 if base < 8 else 0} -to "par"')
        if job.design.split(":")[1] == "osel":
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N18 -to "anyr"')
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N20 -to "qo"')
    elif job.design.startswith("ffe:"):
        x, y, _n = job.loc
        for i in range(4):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * i} -to "l{i}"')
            L.append(f'set_location_assignment FF_X{x}_Y{y}_N{2 * i + 1} -to "r[{i}]"')
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
    elif job.design.startswith("chain:"):
        x, y, n0 = job.loc
        for i in range(4):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n0 + 2 * i} -to "e{i}"')
    elif job.design.startswith("ram:"):
        _, site, _spec = job.design.split(":")
        L.append(f'set_location_assignment M9K_{site}_N0 -to "u"')
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
    elif job.design.startswith("rom2:"):
        _, _wd, site, _spec = job.design.split(":")
        L.append(f'set_location_assignment M9K_{site}_N0 -to "u"')
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
    elif job.design.startswith("rom:"):
        _, site, _spec = job.design.split(":")
        L.append(f'set_location_assignment M9K_{site}_N0 -to "u"')
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
    elif job.design.startswith(("mux1p:", "mux1c:")):
        _, sd, sa, _k = job.design.split(":")
        x, y, _n = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{sa} -to "src"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{sd} -to "dst"')
    elif job.design.startswith(("mux4:", "mux4x:", "mux4d:")):
        _, sd, srcs = job.design.split(":")
        x, y, _n = job.loc
        for i, sp in enumerate(srcs.split("-")):
            if job.design.startswith("mux4x:"):            # dx_dy_slot (source in another LAB)
                dx, dy, slot = (int(v) for v in sp.replace("m", "-").split("_"))
                L.append(f'set_location_assignment LCCOMB_X{x + dx}_Y{y + dy}_N{slot} -to "s{i}"')
            else:
                L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{sp} -to "s{i}"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{sd} -to "dst"')
    elif job.design.startswith(("mux:", "mux1:")):
        _, sa, sd, _sel = job.design.split(":")
        x, y, _n = job.loc
        for inst, slot in (("srca", sa), ("srcb", 30), ("keep", 28), ("dst", sd), ("outl", 26)):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{slot} -to "{inst}"')
    elif job.design.startswith("lab2:"):
        _, ns, nd = job.design.split(":")
        x, y, _n = job.loc
        sy = y + int(job.loc[2])          # loc[2] = row offset of src (0: same LAB)
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{sy}_N{ns} -to "src"')
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{nd} -to "dst"')
    elif job.design.startswith("tpl:"):
        _, tname, spec = job.design.split(":")
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
        extra = os.path.join(TEMPLATE_DIR, tname, "extra.qsf")   # template's own pins etc.
        if os.path.exists(extra):
            with open(extra) as f:
                L += [ln.rstrip("\n") for ln in f if ln.strip() and not ln.startswith("#")]
        if spec != "asis":
            with open(os.path.join(TEMPLATE_DIR, tname, "locs.qsf")) as f:
                L += [ln.rstrip("\n") for ln in f if ln.strip()]
    elif job.design.startswith("reg:"):
        x, y, n = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to "lut_inst"')
        L.append(f'set_location_assignment FF_X{x}_Y{y}_N{n + 1} -to "r"')
        # Power up low, with no NOT-gate push-back that would invert the stored state.
        L.append("set_global_assignment -name ALLOW_POWER_UP_DONT_CARE OFF")
        L.append("set_instance_assignment -name POWER_UP_LEVEL LOW -to r")
    elif job.design.startswith("tree:"):
        for name, (x, y, n) in zip(["l0", "l1", "l2", "l3", "lf"], TREE_LOCS):
            L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to "{name}"')
    elif job.design.startswith("ff:"):
        x, y, n = job.loc
        L.append(f'set_location_assignment FF_X{x}_Y{y}_N{n} -to "r"')
        if job.design == "ff:hi":
            L.append("set_instance_assignment -name POWER_UP_LEVEL HIGH -to r")
    elif job.design != "wire":
        x, y, n = job.loc
        L.append(f'set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to "lut_inst"')
    return "\n".join(L) + "\n"


def rom_words(spec: str, width: int = 9, depth: int = 512) -> list[int]:
    """ROM contents for design spec: "zero", "w<word>b<bit>" (one bit set) or "r<seed>"."""
    words = [0] * depth
    if spec.startswith("w"):
        w, b = spec[1:].split("b")
        words[int(w)] = 1 << int(b)
    elif spec.startswith("r"):
        import random
        r = random.Random(int(spec[1:]))
        words = [r.randrange(1 << width) for _ in range(depth)]
    return words


def rom_mif(words: list[int], width: int = 9) -> str:
    hw, ha = (width + 3) // 4, (len(words) - 1).bit_length() // 4 + 1
    lines = [f"WIDTH = {width};", f"DEPTH = {len(words)};", "ADDRESS_RADIX = HEX;", "DATA_RADIX = HEX;",
             "CONTENT BEGIN"]
    lines += [f"  {w:0{ha}X} : {v:0{hw}X};" for w, v in enumerate(words)]
    return "\n".join(lines + ["END;"]) + "\n"


def extra_files(job) -> dict[str, str]:
    if job.design.startswith("tpl:"):
        tdir = os.path.join(TEMPLATE_DIR, job.design.split(":")[1])
        return {f: open(os.path.join(tdir, f)).read() for f in sorted(os.listdir(tdir)) if f.endswith(".mif")}
    if job.design.startswith("rom:"):
        return {"rom.mif": rom_mif(rom_words(job.design.split(":")[2]))}
    if job.design.startswith("rom2:"):
        _, wd, _site, spec = job.design.split(":")
        w, d = (int(v) for v in wd.split("x"))
        return {"rom.mif": rom_mif(rom_words(spec, w, d), w)}
    if job.design.startswith("ram:"):
        return {"rom.mif": rom_mif(rom_words(job.design.split(":")[2]))}
    return {}


def tool(name: str) -> str:
    return os.path.join(QUARTUS_BIN, name)


def build_one(job: Job, out: str, keep: bool) -> dict:
    rbf = os.path.join(out, job.name + ".rbf")
    meta_path = os.path.join(out, job.name + ".json")
    if os.path.exists(rbf) and os.path.exists(meta_path):
        return dict(json.load(open(meta_path)), cached=True)
    work = os.path.join(out, "work", job.name)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    if job.pins == "repo":
        proj, v, q = repo_project(job)
        vfile = proj + ".v"
    else:
        proj, v, q, vfile = "fuzz", verilog(job), qsf(job), "fuzz_top.v"
    open(os.path.join(work, vfile), "w").write(v)
    for fname, content in extra_files(job).items():
        open(os.path.join(work, fname), "w").write(content)
    open(os.path.join(work, proj + ".qsf"), "w").write(q)
    open(os.path.join(work, proj + ".qpf"), "w").write(f'PROJECT_REVISION = "{proj}"\n')
    meta = dict(job=job.name, dev=job.dev, part=DEVICES[job.dev][1], design=job.design,
                loc=list(job.loc), pins=job.pins, ok=False, times={})
    steps = [["quartus_map", proj], ["quartus_fit", proj], ["quartus_asm", proj],
             ["quartus_cpf", "-c", "-o", "bitstream_compression=off",
              f"output_files/{proj}.sof", os.path.abspath(rbf)]]
    for cmd in steps:
        t0 = time.time()
        r = subprocess.run([tool(cmd[0])] + cmd[1:], cwd=work, capture_output=True,
                           text=True, timeout=900)
        meta["times"][cmd[0]] = round(time.time() - t0, 2)
        if r.returncode:
            lines = (r.stdout + r.stderr).splitlines()
            errs = [l for l in lines if "Error" in l] or lines[-3:] or [f"exit {r.returncode}"]
            meta["error"] = f"{cmd[0]}: " + " | ".join(errs[:4])
            open(os.path.join(work, "failed.log"), "w").write(r.stdout + r.stderr)
            break
    else:
        meta["ok"] = os.path.exists(rbf)
    meta["total_s"] = round(sum(meta["times"].values()), 2)
    if meta["ok"]:
        json.dump(meta, open(meta_path, "w"), indent=1)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return meta


def parse_loc(s: str) -> tuple[int, int, int]:
    x, y, n = (int(v) for v in s.split(","))
    return x, y, n


def make_jobs(a) -> list[Job]:
    jobs = []
    if not a.no_control:
        jobs += [Job(d, des, loc, pins) for d, des, loc, pins in CONTROL]
    for dev in a.device or DEFAULT_DEVICES:
        for des in a.design or DEFAULT_DESIGNS:
            jobs.append(Job(dev, des, a.loc))
    return list(dict.fromkeys(jobs))


def sweep_jobs(a) -> list[Job]:
    masks = ["lut:0000"] + [f"lut:{1 << i:04X}" for i in range(16)]
    return [Job(a.device_one, m, a.loc) for m in masks]


def history(out: str) -> list[float]:
    t = []
    for f in os.listdir(out) if os.path.isdir(out) else []:
        if f.endswith(".json"):
            m = json.load(open(os.path.join(out, f)))
            if m.get("ok"):
                t.append(m["total_s"])
    return t


def estimate(jobs: list[Job], out: str, nj: int) -> str:
    todo = [j for j in jobs if not os.path.exists(os.path.join(out, j.name + ".rbf"))]
    h = history(out)
    if h:
        per = sorted(h)[len(h) // 2]
        basis = f"median of {len(h)} earlier compiles = {per:.0f} s"
    else:
        per = 20.0
        basis = ("no measurements yet; assuming ~20 s (the repo measured 9-10 s on the "
                 "EP4CE6 die, the 10CL016 die is ~40% larger)")
    total = len(todo) * per / max(1, nj)
    return (f"{len(todo)} of {len(jobs)} compiles to run, {nj} parallel, "
            f"~{total / 60:.1f} min ({basis})")


def run_jobs(jobs: list[Job], out: str, nj: int, keep: bool) -> int:
    os.makedirs(out, exist_ok=True)
    if not os.path.exists(tool("quartus_map")):
        print(f"quartus_map not found in {QUARTUS_BIN}; set QUARTUS_BIN")
        return 1
    print(estimate(jobs, out, nj))
    fails = 0
    with cf.ThreadPoolExecutor(nj) as ex:
        futs = {ex.submit(build_one, j, out, keep): j for j in jobs}
        for f in cf.as_completed(futs):
            m = f.result()
            tag = "cached" if m.get("cached") else ("ok" if m["ok"] else "FAIL")
            print(f"  [{tag:6s}] {m['job']:45s} {m.get('total_s', 0):6.1f} s "
                  f"{m.get('error', '')}")
            fails += not m["ok"]
    return 1 if fails else 0


# ---------------------------------------------------------------- analysis

def load(out: str, name: str) -> bytes | None:
    p = os.path.join(out, name + ".rbf")
    return open(p, "rb").read() if os.path.exists(p) else None


def cells(a: bytes, b: bytes, g: rbfgeom.Geometry, include_crc: bool = False):
    """Differing bits outside the header, as (frame, byte_in_frame, bit)."""
    first = g.first_crc_frame or 0
    res = []
    start = g.preamble + first * g.frame
    for i in range(start, g.preamble + g.nframes * g.frame):
        x = a[i] ^ b[i]
        if not x:
            continue
        f, pos = divmod(i - g.preamble, g.frame)
        if pos >= g.frame - 2 and not include_crc:
            continue
        for bit in range(8):
            if x >> bit & 1:
                res.append((f, pos, bit))
    return res


def describe_cells(cs) -> str:
    if not cs:
        return "none"
    fr = sorted({c[0] for c in cs})
    pos = sorted({c[1] for c in cs})
    return (f"{len(cs)} bits in {len(fr)} frames {fr[0]}..{fr[-1]}, "
            f"byte-in-frame {pos[0]}..{pos[-1]} ({len(pos)} distinct)")


def shape(cs):
    """Translation-invariant fingerprint: cells relative to the first one."""
    if not cs:
        return ()
    f0 = min(c[0] for c in cs)
    p0 = min(c[1] for c in cs)
    return tuple(sorted((f - f0, p - p0, b) for f, p, b in cs))


def report(out: str, repo: str | None) -> int:
    names = sorted(f[:-4] for f in os.listdir(out) if f.endswith(".rbf"))
    if not names:
        print("nothing built yet")
        return 1
    geo = {}
    print("== Geometry per build ==")
    for n in names:
        buf = load(out, n)
        g = rbfgeom.infer(buf)
        geo[n] = g
        print(f"  {n:45s} {len(buf):9,d} B  {g.nframes}x{g.frame}  init 0x{(g.init or 0):04X}"
              f"  CRC {g.crc_range}")

    print("\n== Cross-device diffs (same design, same pins) ==")
    designs = sorted({n.split("__", 1)[1] for n in names if "__" in n})
    for a, b in PAIRS:
        for d in designs:
            na, nb = f"{a}__{d}", f"{b}__{d}"
            if na in geo and nb in geo:
                A, B = load(out, na), load(out, nb)
                if len(A) != len(B):
                    print(f"  {d:28s} {a} vs {b}: different size ({len(A):,} vs {len(B):,}) "
                          "-> different die")
                    continue
                if A == B:
                    print(f"  {d:28s} {a} vs {b}: BYTE-IDENTICAL")
                    continue
                g = geo[na]
                regs: dict[str, int] = {}
                for i in range(len(A)):
                    if A[i] != B[i]:
                        r = rbfgeom.region_of(g, i)
                        regs[r] = regs.get(r, 0) + 1
                print(f"  {d:28s} {a} vs {b}: differ in "
                      + ", ".join(f"{k} {v} B" for k, v in regs.items()))

    print("\n== LUT pair-diffs (mask 0000 vs others, CRC bytes excluded) ==")
    fingerprints = {}
    for n in names:
        parts = n.split("__")
        if len(parts) != 3 or not parts[1].startswith("lut0000"):
            continue                      # hand-made files (lo_*, x8888*), FF builds
        dev, d, pins = parts
        if not d.startswith("lut0000"):
            continue
        loc = d[len("lut0000"):]
        z = load(out, n)
        for m in ("FFFF", "8888", "DEAD"):
            other = f"{dev}__lut{m}{loc}__{pins}"
            if other in geo:
                cs = cells(z, load(out, other), geo[n])
                fingerprints[(dev, m, loc, pins)] = cs
                print(f"  {dev:8s} {loc:10s} 0000->{m}: {describe_cells(cs)}")
    for a, b in PAIRS:
        for (dev, m, loc, pins), cs in sorted(fingerprints.items()):
            other = fingerprints.get((b, m, loc, pins))
            if dev != a or other is None:
                continue
            print(f"  mask {m} {loc}: {a} vs {b}: absolute "
                  f"{'SAME' if sorted(cs) == sorted(other) else 'different'}, relative shape "
                  f"{'SAME' if shape(cs) == shape(other) else 'different'}")

    if repo:
        print("\n== Control: your EP4CE6 build vs the repo's golden_rbf_modeH ==")
        gdir = os.path.join(repo, "results", "golden_rbf_modeH")
        g0 = os.path.join(gdir, "X10_Y2_N0_mask0000_q211.rbf")
        g1 = os.path.join(gdir, "X10_Y2_N0_maskDEAD_q211.rbf")
        m0 = load(out, "ce6__lut0000_X10Y2N0__repo")
        m1 = load(out, "ce6__lutDEAD_X10Y2N0__repo")
        if os.path.exists(g0) and os.path.exists(g1) and m0 and m1:
            G0, G1 = open(g0, "rb").read(), open(g1, "rb").read()
            gg = rbfgeom.infer(G0)
            gold = cells(G0, G1, gg)
            mine = cells(m0, m1, gg)
            print(f"  repo  pair-diff: {describe_cells(gold)}")
            print(f"  yours pair-diff: {describe_cells(mine)}")
            print(f"  LUT cells {'MATCH' if sorted(gold) == sorted(mine) else 'DIFFER'}")
            # The repo documents [0x29,0x35) and [0x49,0x4B) as per-build variable.
            var = set(range(0x29, 0x35)) | set(range(0x49, 0x4B))
            for tag, mine_f, gold_f in (("0000", m0, G0), ("DEAD", m1, G1)):
                d = [i for i in range(len(gold_f)) if mine_f[i] != gold_f[i]]
                rest = [i for i in d if i not in var]
                print(f"  mask {tag}: byte-identical {mine_f == gold_f}; {len(d)} B differ, "
                      f"{len(rest)} outside the variable header bytes"
                      + (f" (first {', '.join(hex(i) for i in rest[:8])})" if rest else ""))
        else:
            print("  control builds or golden files missing")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parts")
    for name in ("plan", "build"):
        p = sub.add_parser(name)
        p.add_argument("--device", action="append", choices=sorted(DEVICES))
        p.add_argument("--design", action="append",
                       help="wire | lut:XXXX (hex mask); repeatable")
        p.add_argument("--loc", type=parse_loc, default=DEFAULT_LOC, help="X,Y,N")
        p.add_argument("--no-control", action="store_true")
        p.add_argument("--jobs", type=int, default=2)
        p.add_argument("--keep", action="store_true", help="keep Quartus work dirs")
    p = sub.add_parser("sweep")
    p.add_argument("--device", dest="device_one", required=True, choices=sorted(DEVICES))
    p.add_argument("--loc", type=parse_loc, required=True)
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("report")
    p.add_argument("--repo", help="path to a Cyclone_CRAM_Mapper checkout (for the control)")
    a = ap.parse_args()

    if a.cmd == "parts":
        tcl = os.path.join(a.out, "parts.tcl")
        os.makedirs(a.out, exist_ok=True)
        open(tcl, "w").write(
            'load_package device\n'
            'foreach fam {"Cyclone IV E" "Cyclone 10 LP"} {\n'
            '  foreach p [get_part_list -family $fam] { puts "$fam|$p" }\n}\n')
        r = subprocess.run([tool("quartus_sh"), "-t", tcl], capture_output=True, text=True)
        keep = ("EP4CE6", "EP4CE10", "EP4CE15", "10CL006", "10CL010", "10CL016")
        for line in r.stdout.splitlines():
            if "|" in line and any(k in line for k in keep):
                print(line)
        return r.returncode
    if a.cmd in ("plan", "build"):
        jobs = make_jobs(a)
        if a.cmd == "plan":
            for j in jobs:
                print(f"  {j.name}  ({DEVICES[j.dev][1]})")
            print(estimate(jobs, a.out, a.jobs))
            return 0
        return run_jobs(jobs, a.out, a.jobs, a.keep)
    if a.cmd == "sweep":
        jobs = sweep_jobs(a)
        if a.dry_run:
            for j in jobs:
                print(" ", j.name)
            print(estimate(jobs, a.out, a.jobs))
            return 0
        return run_jobs(jobs, a.out, a.jobs, a.keep)
    return report(a.out, a.repo)


if __name__ == "__main__":
    sys.exit(main())
