#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""One command from a Verilog file to a checked bitstream for the Vidor (make design V=FILE TOP=MODULE).

Ports by name: K = the 48 MHz clock (iCLK), A..D = inputs D1..D4, Q = output D5 (any subset of A..D).  Steps:
  1. Yosys: synth_intel -family cyclone10lp -nodsp -nobram -> out/TOP.json
  2. c10lp_netlist.py --io --out-le auto (nextpnr places the output LE too)
  3. npnr_io.py: nextpnr place / route (timing target 100 MHz, fallback regions, on-demand probing) -> asm.py
     -> out/ypnr_TOP.rbf
  4. ycheck.py --timing --fresh: Quartus with our placement and routing forced; must be equal except the RCF-mode bit,
     every branch honoured, timing positive at every corner
  5. gate.py against Quartus's normal build of the same netlist and placement, periphery identical to the
     board-tested files
Steps 4-5 use Quartus (the cross-check); without them the file is untested.  --no-check stops after step 3.
Exit 0 only if every step passed; the last line says whether the file is safe to load (SRAM:
openFPGALoader -c usb-blaster out/ypnr_TOP.rbf).

  design.py FILE.v TOP [--no-check]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
OUT = os.path.join(HERE, "out")
REGIONS = "4,5,8,8;5,6,7,7;3,4,9,9;2,3,10,10"


def run(cmd, what):
    print(f"== {what}", flush=True)
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    out = r.stdout + r.stderr
    if r.returncode:
        print(out[-1500:])
        raise SystemExit(f"FAILED: {what}")
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        raise SystemExit(__doc__)
    src, top = args
    run(["yosys", "-q", "-p", f"read_verilog {src}; synth_intel -family cyclone10lp -nodsp -nobram -top {top}; "
         f"write_json out/{top}.json"], "Yosys")
    print(run([sys.executable, "nextpnr/c10lp_netlist.py", f"out/{top}.json", top, f"out/npnr_{top}.json", "--io",
               "--out-le", "auto"], "netlist").strip().splitlines()[-1])
    out = run([sys.executable, "nextpnr/npnr_io.py", f"out/npnr_{top}.json", f"out/npnr_{top}_side.json", top,
               "--region", REGIONS, "--seeds", "20", "--rounds", "12"], "nextpnr place / route, assemble")
    print("\n".join(ln for ln in out.splitlines() if ln.startswith(("round", "  bundle")) or "LEs from" in ln))
    rbf = os.path.join(OUT, f"ypnr_{top}.rbf")
    if "--no-check" in sys.argv:
        print(f"-> {rbf} (NOT CHECKED: run without --no-check before loading it)")
        return 0
    out = run([sys.executable, "flow/ycheck.py", f"out/{top}.json", top, "--timing", "--fresh"],
              "Quartus cross-check (ycheck)")
    m = re.search(r"RCF errors (\d+).*branches honoured (\d+) / (\d+)", out)
    d = re.search(r"core bits differing (\d+)", out)
    t = "timing: PASS" in out
    print("\n".join(ln for ln in out.splitlines() if "timing:" in ln or "honoured" in ln or "core bits" in ln))
    exact = bool(m and d and m[1] == "0" and m[2] == m[3] and d[1] == "1")
    sys.path[:0] = [os.path.join(HERE, x) for x in ("lib", "flow", "mapping", "hwtests")]
    import explain as E
    import gate
    import rcfforce as F
    import tpatch
    import xdev
    import ycheck
    tpl, _x = ycheck.fresh_template(top)
    ref = F.Project(tpatch.job(tpl, [mm for _, mm in xdev.tpl_luts(tpl)]), E.ROOT).base_rbf
    ours = open(rbf, "rb").read()
    errs = gate.check(ref, ours, [], extra_cells=sorted(E.core_diff(ref, ours)))
    board = open(os.path.join(OUT, "ypnr_blink_quartusbit.rbf"), "rb").read()
    peri = sum(ours[i] != board[i] for i in range(32 + 255, 32 + 37 * 255))
    print(f"gate: {'PASS' if not errs else errs}; periphery bytes differing from the board-tested files: {peri}")
    ok = exact and t and not errs and peri == 0
    print(f"-> {rbf}: {'all checks PASS, safe to load (SRAM)' if ok else 'checks FAILED: do not load'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
